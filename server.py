from flask import Flask, request, jsonify
from ariadne import QueryType, MutationType, ScalarType, make_executable_schema, graphql_sync
from ariadne.explorer import ExplorerPlayground
import uuid
from datetime import datetime, timezone

# --- In-memory data store ---
expenses_db = []

# --- GraphQL Schema Definition ---
type_defs = """
    scalar DateTime

    type Expense {
        id: ID!
        description: String!
        category: String!
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
        createExpense(description: String!, category: String!, cost: Float!): Expense
        editExpense(id: ID!, description: String, category: String, cost: Float): Expense
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
    filtered_items = list(expenses_db) # Start with a copy

    current_time = datetime.now(timezone.utc)

    if year is not None:
        if month is None and day is None and year == current_time.year:
            # "Year so far" logic for current year
            filtered_items = [
                e for e in filtered_items if e['createdAt'].year == year and e['createdAt'] <= current_time
            ]
        else:
            filtered_items = [e for e in filtered_items if e['createdAt'].year == year]

    if month is not None:
        filtered_items = [e for e in filtered_items if e['createdAt'].month == month]

    if day is not None:
        filtered_items = [e for e in filtered_items if e['createdAt'].day == day]

    total_cost = sum(item['cost'] for item in filtered_items)

    return {"items": filtered_items, "totalCost": total_cost}


# --- Mutation Resolvers ---
mutation = MutationType()

@mutation.field("createExpense")
def resolve_create_expense(_, info, description, category, cost):
    new_expense = {
        "id": str(uuid.uuid4()),
        "description": description,
        "category": category,
        "cost": cost,
        "createdAt": datetime.now(timezone.utc)
    }
    expenses_db.append(new_expense)
    return new_expense

@mutation.field("editExpense")
def resolve_edit_expense(_, info, id, description=None, category=None, cost=None):
    expense_to_edit = None
    for expense in expenses_db:
        if expense["id"] == id:
            expense_to_edit = expense
            break

    if not expense_to_edit:
        return None # Or raise an error: raise Exception(f"Expense with id {id} not found")

    if description is not None:
        expense_to_edit["description"] = description
    if category is not None:
        expense_to_edit["category"] = category
    if cost is not None:
        expense_to_edit["cost"] = cost
    # createdAt is not editable

    return expense_to_edit


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
    # Initialize with some dummy data for testing
    expenses_db.append({
        "id": str(uuid.uuid4()), "description": "Coffee", "category": "Food", "cost": 3.50,
        "createdAt": datetime(2023, 10, 25, 9, 0, 0, tzinfo=timezone.utc)
    })
    expenses_db.append({
        "id": str(uuid.uuid4()), "description": "Lunch", "category": "Food", "cost": 12.00,
        "createdAt": datetime(2023, 10, 26, 12, 30, 0, tzinfo=timezone.utc)
    })
    expenses_db.append({
        "id": str(uuid.uuid4()), "description": "Groceries", "category": "Household", "cost": 55.20,
        "createdAt": datetime(2023, 10, 26, 18, 0, 0, tzinfo=timezone.utc)
    })
    expenses_db.append({
        "id": str(uuid.uuid4()), "description": "Movie Ticket", "category": "Entertainment", "cost": 15.00,
        "createdAt": datetime(2023, 11, 1, 20, 0, 0, tzinfo=timezone.utc)
    })
    expenses_db.append({
        "id": str(uuid.uuid4()), "description": "Book", "category": "Education", "cost": 22.99,
        "createdAt": datetime(datetime.now(timezone.utc).year, 1, 15, 10, 0, 0, tzinfo=timezone.utc) # Expense in current year
    })

    app.run(debug=True, host='0.0.0.0', port=5000)