from flask import Flask, request, jsonify
from ariadne import QueryType, MutationType, ScalarType, make_executable_schema, graphql_sync
from ariadne.explorer import ExplorerPlayground
from pymongo import MongoClient
from bson import ObjectId  # For handling MongoDB's _id
import uuid
from datetime import datetime, timezone, timedelta
import logging

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- MongoDB Setup ---
client = MongoClient('mongodb://mongo:27017/')  # Connect to the 'mongo' service in Docker Compose
db = client['expenses_app']  # Database name
expenses_collection = db['expenses']  # Collection name


# --- GraphQL Schema Definition ---
type_defs = """
    scalar DateTime

    enum ExpenseCategory {
        MANDATORY
        ENTERTAINMENT
        FOOD
        HOUSEHOLD
    }

    type Expense {
        id: ID!
        description: String!
        category: ExpenseCategory!
        cost: Float!
        createdAt: DateTime!
    }

    type ExpenseReport {
        items: [Expense!]!
        totalCost: Float!
    }

    type Query {
        getExpenses(year: Int, month: Int, day: Int): ExpenseReport
    }

    type Mutation {
        createExpense(description: String!, category: ExpenseCategory!, cost: Float!): Expense
        editExpense(id: ID!, description: String, category: ExpenseCategory, cost: Float): Expense
        deleteExpense(id: ID!): Boolean
    }
"""

# --- Scalar Types ---
datetime_scalar = ScalarType("DateTime")

@datetime_scalar.serializer
def serialize_datetime(value):
    return value.isoformat()

@datetime_scalar.value_parser
def parse_datetime_value(value):
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        logger.warning(f"Failed to parse datetime value: {value}.")
        return None  # Or raise GraphQLError for bad input


# --- Query Resolvers ---
query = QueryType()

@query.field("getExpenses")
def resolve_get_expenses(_, info, year=None, month=None, day=None):
    logger.info(f"Resolving getExpenses with filters: year={year}, month={month}, day={day}")
    mongo_query = {}
    current_time = datetime.now(timezone.utc)

    # Build the date range for the query
    if year is not None:
        start_date_year = datetime(year, 1, 1, tzinfo=timezone.utc)
        end_date_year = datetime(year + 1, 1, 1, tzinfo=timezone.utc)

        if month is None and day is None and year == current_time.year:
            logger.debug(f"Applying 'year so far' filter for current year: {year}")
            # "Year so far" logic for current year
            mongo_query['createdAt'] = {'$gte': start_date_year, '$lte': current_time}
        elif month is not None:
            start_date_month = datetime(year, month, 1, tzinfo=timezone.utc)
            if month == 12:
                end_date_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
                logger.debug(f"Applying month filter for December: {year}-{month}")
            else:
                end_date_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
                logger.debug(f"Applying month filter for: {year}-{month}")

            if day is not None:
                logger.debug(f"Applying day filter for: {year}-{month}-{day}")
                start_date_day = datetime(year, month, day, tzinfo=timezone.utc) # up to, but not including, the next day
                end_date_day = start_date_day + timedelta(days=1)
                mongo_query['createdAt'] = {'$gte': start_date_day, '$lt': end_date_day}
            else:
                mongo_query['createdAt'] = {'$gte': start_date_month, '$lt': end_date_month}
        else:
            logger.debug(f"Applying full year filter for: {year}")
            mongo_query['createdAt'] = {'$gte': start_date_year, '$lt': end_date_year}

    cursor = expenses_collection.find(mongo_query)
    resolved_items = []
    total_cost = 0
    for doc in cursor:
        doc['id'] = str(doc['_id'])  # Convert ObjectId to string for GraphQL ID
        # del doc['_id'] # Optionally remove the original _id
        resolved_items.append(doc)
        total_cost += doc.get('cost', 0)

    logger.info(f"Found {len(resolved_items)} expenses with total cost {total_cost}.")
    return {"items": resolved_items, "totalCost": total_cost}


# --- Mutation Resolvers ---
mutation = MutationType()

@mutation.field("createExpense")
def resolve_create_expense(_, info, description, category, cost):
    logger.info(f"Resolving createExpense: description='{description}', category='{category}', cost={cost}")
    new_expense = {
        # MongoDB will generate _id automatically
        "description": description,
        "category": category,
        "cost": cost,
        "createdAt": datetime.now(timezone.utc)
    }
    result = expenses_collection.insert_one(new_expense)
    created_expense = expenses_collection.find_one({"_id": result.inserted_id})
    if created_expense:
        created_expense['id'] = str(created_expense['_id'])
        # del created_expense['_id']
        logger.info(f"Expense created with ID: {created_expense['id']}")
    else:
        logger.error(f"Failed to retrieve created expense from DB after insert. Insert ID: {result.inserted_id}")
    return created_expense

@mutation.field("editExpense")
def resolve_edit_expense(_, info, id, description=None, category=None, cost=None):
    logger.info(f"Resolving editExpense for ID: {id} with updates: description='{description}', category='{category}', cost={cost}")
    try:
        object_id = ObjectId(id)
    except Exception as e:
        # Handle invalid ID format, perhaps raise GraphQLError
        logger.warning(f"Invalid ObjectId format for ID: {id}. Error: {e}")
        return None  # Or raise GraphQLError("Invalid ID format")

    update_fields = {}
    if description is not None:
        update_fields["description"] = description
    if category is not None:
        update_fields["category"] = category
    if cost is not None:
        update_fields["cost"] = cost

    if not update_fields:
        logger.info(f"No fields to update for expense ID: {id}. Returning current document.")
        # No fields to update, return the original or an error
        expense_doc = expenses_collection.find_one({"_id": object_id})
        if expense_doc:
            expense_doc['id'] = str(expense_doc['_id'])
        else:
            logger.warning(f"Expense not found for ID: {id} when no update fields were provided.")
        return expense_doc

    result = expenses_collection.find_one_and_update(
        {"_id": object_id},
        {"$set": update_fields},
        return_document=True  # pymongo.ReturnDocument.AFTER
    )
    if result:
        result['id'] = str(result['_id'])
        # del result['_id']
        logger.info(f"Expense ID: {id} updated successfully.")
    else:
        logger.warning(f"Expense ID: {id} not found for update.")
    return result

@mutation.field("deleteExpense")
def resolve_delete_expense(_, info, id):
    logger.info(f"Resolving deleteExpense for ID: {id}")
    try:
        object_id = ObjectId(id)
    except Exception as e:
        logger.warning(f"Invalid ObjectId format for ID: {id} during delete. Error: {e}")
        return False # Or raise GraphQLError("Invalid ID format")

    result = expenses_collection.delete_one({"_id": object_id})

    if result.deleted_count > 0:
        logger.info(f"Expense ID: {id} deleted successfully.")
        return True
    else:
        logger.warning(f"Expense ID: {id} not found for deletion.")
        return False
# --- Schema and Flask App Setup ---
schema = make_executable_schema(type_defs, query, mutation, datetime_scalar)
app = Flask(__name__)

@app.route("/graphql", methods=["GET"])
def graphql_playground():
    return ExplorerPlayground().html(None), 200

@app.route("/graphql", methods=["POST"])
def graphql_server():
    logger.debug("GraphQL request received.")
    data = request.get_json()
    success, result = graphql_sync(
        schema,
        data,
        context_value=request,  # Optional: pass context to resolvers
        debug=app.debug
    )
    status_code = 200 if success else 400
    if not success:
        logger.error(f"GraphQL query failed: {result}")
    logger.debug(f"GraphQL response status: {status_code}")
    return jsonify(result), status_code

@app.route("/health", methods=["GET"])
def health_check():
    logger.info("Health check requested.")
    overall_status = "UP"
    components = {}
    http_status_code = 200

    # Check MongoDB health
    try:
        # The ping command is cheap and does not require auth.
        db.command('ping')
        components['mongodb'] = {"status": "UP", "details": "MongoDB is responsive"}
        logger.debug("MongoDB ping successful.")
    except Exception as e:
        overall_status = "DOWN"
        http_status_code = 503
        components['mongodb'] = {"status": "DOWN", "details": f"MongoDB connection failed: {str(e)}"}
        logger.error(f"MongoDB health check failed: {e}")

    response_body = {"status": overall_status, "components": components}
    logger.info(f"Health check response: status={overall_status}, http_code={http_status_code}")
    return jsonify(response_body), http_status_code

if __name__ == "__main__":

    app.run(debug=True, host='0.0.0.0', port=5000)