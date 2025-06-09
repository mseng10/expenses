from flask import Flask, request, jsonify
from ariadne import QueryType, MutationType, ScalarType, make_executable_schema, graphql_sync
from ariadne.explorer import ExplorerPlayground
from pymongo import MongoClient
from bson import ObjectId # For handling MongoDB's _id
import uuid
from datetime import datetime, timezone

# --- MongoDB Setup ---
client = MongoClient('mongodb://mongo:27017/') # Connect to the 'mongo' service in Docker Compose
db = client['expenses_app'] # Database name
expenses_collection = db['expenses'] # Collection name


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
        return None # Or raise GraphQLError for bad input

# --- Query Resolvers ---
query = QueryType()

@query.field("getExpenses")
def resolve_get_expenses(_, info, year=None, month=None, day=None):
    mongo_query = {}
    current_time = datetime.now(timezone.utc)

    # Build the date range for the query
    if year is not None:
        start_date_year = datetime(year, 1, 1, tzinfo=timezone.utc)
        end_date_year = datetime(year + 1, 1, 1, tzinfo=timezone.utc)

        if month is None and day is None and year == current_time.year:
            # "Year so far" logic for current year
            mongo_query['createdAt'] = {'$gte': start_date_year, '$lte': current_time}
        elif month is not None:
            start_date_month = datetime(year, month, 1, tzinfo=timezone.utc)
            if month == 12:
                end_date_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            else:
                end_date_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)

            if day is not None:
                start_date_day = datetime(year, month, day, tzinfo=timezone.utc)
                end_date_day = datetime(year, month, day + 1, tzinfo=timezone.utc) # up to, but not including, the next day
                mongo_query['createdAt'] = {'$gte': start_date_day, '$lt': end_date_day}
            else:
                mongo_query['createdAt'] = {'$gte': start_date_month, '$lt': end_date_month}
        else:
            mongo_query['createdAt'] = {'$gte': start_date_year, '$lt': end_date_year}

    cursor = expenses_collection.find(mongo_query)
    resolved_items = []
    total_cost = 0
    for doc in cursor:
        doc['id'] = str(doc['_id']) # Convert ObjectId to string for GraphQL ID
        # del doc['_id'] # Optionally remove the original _id
        resolved_items.append(doc)
        total_cost += doc.get('cost', 0)

    return {"items": resolved_items, "totalCost": total_cost}


# --- Mutation Resolvers ---
mutation = MutationType()

@mutation.field("createExpense")
def resolve_create_expense(_, info, description, category, cost):
    new_expense = {
        # MongoDB will generate _id automatically
        "description": description,
        "category": category,
        "cost": cost,
        "createdAt": datetime.now(timezone.utc)
    }
    result = expenses_collection.insert_one(new_expense_doc)
    created_expense = expenses_collection.find_one({"_id": result.inserted_id})
    if created_expense:
        created_expense['id'] = str(created_expense['_id'])
        # del created_expense['_id']
    return created_expense

@mutation.field("editExpense")
def resolve_edit_expense(_, info, id, description=None, category=None, cost=None):
    try:
        object_id = ObjectId(id)
    except Exception:
        # Handle invalid ID format, perhaps raise GraphQLError
        return None

    update_fields = {}
    if description is not None:
        update_fields["description"] = description
    if category is not None:
        update_fields["category"] = category
    if cost is not None:
        update_fields["cost"] = cost

    if not update_fields:
        # No fields to update, return the original or an error
        expense_doc = expenses_collection.find_one({"_id": object_id})
        if expense_doc:
            expense_doc['id'] = str(expense_doc['_id'])
        return expense_doc

    result = expenses_collection.find_one_and_update(
        {"_id": object_id},
        {"$set": update_fields},
        return_document=True # pymongo.ReturnDocument.AFTER
    )
    if result:
        result['id'] = str(result['_id'])
        # del result['_id']
    return result

# --- Schema and Flask App Setup ---
schema = make_executable_schema(type_defs, query, mutation, datetime_scalar)
app = Flask(__name__)

@app.route("/graphql", methods=["GET"])
def graphql_playground():
    return ExplorerPlayground().html(None), 200

@app.route("/graphql", methods=["POST"])
def graphql_server():
    data = request.get_json()
    success, result = graphql_sync(
        schema,
        data,
        context_value=request, # Optional: pass context to resolvers
        debug=app.debug
    )
    status_code = 200 if success else 400
    return jsonify(result), status_code

if __name__ == "__main__":
    # Optional: Initialize with some dummy data if the collection is empty
    if expenses_collection.count_documents({}) == 0:
        print("Populating MongoDB with initial data...")
        initial_expenses = [
            {"description": "Coffee", "category": "FOOD", "cost": 3.50, "createdAt": datetime(2023, 10, 25, 9, 0, 0, tzinfo=timezone.utc)},
            {"description": "Lunch", "category": "FOOD", "cost": 12.00, "createdAt": datetime(2023, 10, 26, 12, 30, 0, tzinfo=timezone.utc)},
            {"description": "Groceries", "category": "HOUSEHOLD", "cost": 55.20, "createdAt": datetime(2023, 10, 26, 18, 0, 0, tzinfo=timezone.utc)},
            {"description": "Movie Ticket", "category": "ENTERTAINMENT", "cost": 15.00, "createdAt": datetime(2023, 11, 1, 20, 0, 0, tzinfo=timezone.utc)},
            {"description": "Rent", "category": "MANDATORY", "cost": 800.00, "createdAt": datetime(datetime.now(timezone.utc).year, datetime.now(timezone.utc).month, 1, 8, 0, 0, tzinfo=timezone.utc)}
        ]
        expenses_collection.insert_many(initial_expenses)
        print(f"{len(initial_expenses)} documents inserted.")

    app.run(debug=True, host='0.0.0.0', port=5000)