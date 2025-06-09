import pytest
from flask import Flask
from pymongo import MongoClient
from testcontainers.mongodb import MongoDbContainer
from datetime import datetime, timezone, timedelta
from pymongo.errors import ConnectionFailure
import json

# Import the app and other necessary components from your server.py
# Assuming server.py is in the same directory or accessible via PYTHONPATH
from server import app as flask_app, schema, expenses_collection as main_expenses_collection, db as main_db

@pytest.fixture(scope="session")
def mongo_container():
    """Starts and stops a MongoDB container for the test session."""
    with MongoDbContainer("mongo:latest") as mongo:
        yield mongo

@pytest.fixture(scope="session")
def test_db_client(mongo_container):
    """Provides a PyMongo client connected to the test MongoDB container."""
    client = mongo_container.get_connection_client()
    yield client
    client.close()

@pytest.fixture(scope="function") # Changed to function scope for app context
def app(test_db_client, mongo_container):
    """Configures the Flask app to use the test MongoDB instance."""
    # Point the app's MongoDB client to the test container
    # This is a bit tricky as your server.py directly initializes MongoClient
    # We'll re-assign the global variables in server.py for the test session
    # This is not ideal for larger apps, consider dependency injection or app factories

    original_client = main_db.client
    original_db_name = main_db.name
    original_collection = main_expenses_collection

    # Create a new client and database for testing within the app's context
    test_db_name = "test_expenses_app"
    flask_app.config['TESTING'] = True
    flask_app.config['MONGO_URI'] = mongo_container.get_connection_url() # For potential direct use

    # Override the global db and collection objects in your server module for tests
    # This is a common pattern for testing when globals are used.
    # A more robust solution would be to use an app factory pattern.
    # global expenses_collection, db # 'global' not needed here for module attribute modification
    import server # Use the direct import
    server.client = test_db_client
    server.db = test_db_client[test_db_name]
    server.expenses_collection = server.db['expenses']

    # Ensure the app context is available
    with flask_app.app_context():
        yield flask_app

    # Restore original globals (important if tests are run in the same process as other things)
    server.client = original_client
    server.db = original_client[original_db_name]
    server.expenses_collection = original_collection


@pytest.fixture
def client(app):
    """Provides a test client for the Flask app."""
    return app.test_client()

@pytest.fixture(autouse=True) # autouse to run before each test
def clear_db(app):
    """Clears the test database before each test."""
    # Need to access the collection via the modified server module
    import server # Use the direct import
    if server.expenses_collection is not None:
        server.expenses_collection.delete_many({})


def graphql_query(client, query, variables=None):
    """Helper function to make GraphQL requests."""
    response = client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        content_type="application/json",
    )
    return response

# --- Test Cases ---

def test_create_expense(client):
    mutation = """
        mutation CreateExpense($description: String!, $category: ExpenseCategory!, $cost: Float!) {
            createExpense(description: $description, category: $category, cost: $cost) {
                id
                description
                category
                cost
                createdAt
            }
        }
    """
    variables = {"description": "Test Coffee", "category": "FOOD", "cost": 4.50}
    response = graphql_query(client, mutation, variables)
    json_data = response.get_json()

    assert response.status_code == 200
    assert "errors" not in json_data
    data = json_data["data"]["createExpense"]
    assert data["description"] == "Test Coffee"
    assert data["category"] == "FOOD"
    assert data["cost"] == 4.50
    assert "id" in data
    assert "createdAt" in data

    # Verify in DB (using the test-specific collection)
    import server # Use the direct import
    created_doc = server.expenses_collection.find_one({"description": "Test Coffee"})
    assert created_doc is not None
    assert created_doc["cost"] == 4.50


def test_get_expenses_empty(client):
    query = """
        query {
            getExpenses {
                items {
                    id
                    description
                }
                totalCost
            }
        }
    """
    response = graphql_query(client, query)
    json_data = response.get_json()

    assert response.status_code == 200
    assert "errors" not in json_data
    data = json_data["data"]["getExpenses"]
    assert data["items"] == []
    assert data["totalCost"] == 0


def test_get_expenses_with_data(client):
    # First, create some expenses
    import server # Use the direct import
    now = datetime.now(timezone.utc)
    server.expenses_collection.insert_many([
        {"description": "Lunch", "category": "FOOD", "cost": 15.00, "createdAt": now},
        {"description": "Groceries", "category": "HOUSEHOLD", "cost": 60.00, "createdAt": now - timedelta(days=1)},
        {"description": "Movie", "category": "ENTERTAINMENT", "cost": 20.00, "createdAt": now.replace(year=now.year -1)} # last year
    ])

    query = """
        query GetExpenses($year: Int, $month: Int, $day: Int) {
            getExpenses(year: $year, month: $month, day: $day) {
                items {
                    id
                    description
                    cost
                    category
                    createdAt
                }
                totalCost
            }
        }
    """
    # Test fetching all (no filters)
    response_all = graphql_query(client, query)
    json_data_all = response_all.get_json()
    assert response_all.status_code == 200
    data_all = json_data_all["data"]["getExpenses"]
    assert len(data_all["items"]) == 3
    assert data_all["totalCost"] == 15.00 + 60.00 + 20.00

    # Test fetching by current year
    variables_year = {"year": now.year}
    response_year = graphql_query(client, query, variables_year)
    json_data_year = response_year.get_json()
    assert response_year.status_code == 200
    data_year = json_data_year["data"]["getExpenses"]
    # This will depend on the "year so far" logic vs "full year" logic
    # Based on your server.py: current year without month/day means "year so far"
    # So it should include "Lunch" and "Groceries" if they are in the current year
    # The "Movie" from last year should be excluded.
    # If "Groceries" was yesterday, it's still in "year so far"
    assert len(data_year["items"]) == 2
    assert data_year["totalCost"] == 15.00 + 60.00
    assert all(item['description'] != "Movie" for item in data_year["items"])


    # Test fetching by specific date (today for "Lunch")
    variables_day = {"year": now.year, "month": now.month, "day": now.day}
    response_day = graphql_query(client, query, variables_day)
    json_data_day = response_day.get_json()
    assert response_day.status_code == 200
    data_day = json_data_day["data"]["getExpenses"]
    assert len(data_day["items"]) == 1
    assert data_day["items"][0]["description"] == "Lunch"
    assert data_day["totalCost"] == 15.00

    # Test fetching by specific month
    variables_month = {"year": now.year, "month": now.month}
    response_month = graphql_query(client, query, variables_month)
    json_data_month = response_month.get_json()
    assert response_month.status_code == 200
    data_month = json_data_month["data"]["getExpenses"]
    # Should include "Lunch" and "Groceries" if they are in the current month
    assert len(data_month["items"]) == 2
    assert any(item['description'] == "Lunch" for item in data_month["items"])
    assert any(item['description'] == "Groceries" for item in data_month["items"])
    assert data_month["totalCost"] == 15.00 + 60.00


def test_edit_expense(client):
    # 1. Create an expense
    import server # Use the direct import
    initial_expense = {"description": "Initial Item", "category": "FOOD", "cost": 10.00, "createdAt": datetime.now(timezone.utc)}
    result = server.expenses_collection.insert_one(initial_expense)
    expense_id = str(result.inserted_id)

    # 2. Edit the expense
    mutation = """
        mutation EditExpense($id: ID!, $description: String, $category: ExpenseCategory, $cost: Float) {
            editExpense(id: $id, description: $description, category: $category, cost: $cost) {
                id
                description
                category
                cost
            }
        }
    """
    variables = {"id": expense_id, "description": "Updated Item", "cost": 12.50}
    response = graphql_query(client, mutation, variables)
    json_data = response.get_json()

    assert response.status_code == 200
    assert "errors" not in json_data
    data = json_data["data"]["editExpense"]
    assert data["id"] == expense_id
    assert data["description"] == "Updated Item"
    assert data["category"] == "FOOD" # Unchanged
    assert data["cost"] == 12.50

    # Verify in DB
    edited_doc = server.expenses_collection.find_one({"_id": result.inserted_id})
    assert edited_doc["description"] == "Updated Item"
    assert edited_doc["cost"] == 12.50


def test_edit_expense_not_found(client):
    mutation = """
        mutation EditExpense($id: ID!, $description: String) {
            editExpense(id: $id, description: $description) {
                id
            }
        }
    """
    # A valid ObjectId format, but non-existent
    non_existent_id = "60c72b9f9b1e8b3b0f6a1b2c"
    variables = {"id": non_existent_id, "description": "Wont Matter"}
    response = graphql_query(client, mutation, variables)
    json_data = response.get_json()

    assert response.status_code == 200
    assert "errors" not in json_data # GraphQL might return null for the field
    assert json_data["data"]["editExpense"] is None


def test_edit_expense_invalid_id_format(client):
    mutation = """
        mutation EditExpense($id: ID!, $description: String) {
            editExpense(id: $id, description: $description) {
                id
            }
        }
    """
    variables = {"id": "invalid-id-format", "description": "Wont Matter"}
    response = graphql_query(client, mutation, variables)
    json_data = response.get_json()

    assert response.status_code == 200
    # Your resolver returns None for invalid ID, which GraphQL represents as null
    assert json_data["data"]["editExpense"] is None
    # If you were raising a GraphQLError, you'd check for "errors" here.


def test_datetime_scalar_serialization_deserialization(client):
    # This tests the scalar indirectly through create and get
    now_utc_iso = datetime.now(timezone.utc).isoformat()
    # To make it perfectly round-trip without microsecond issues with fromisoformat
    # it's often easier to create a datetime object, then format it, then parse it.
    dt_obj = datetime.now(timezone.utc).replace(microsecond=0) # Remove microseconds for easier comparison
    dt_iso = dt_obj.isoformat()

    # Create an expense (server will use datetime.now(timezone.utc))
    create_mutation = """
        mutation CreateExpense($description: String!, $category: ExpenseCategory!, $cost: Float!) {
            createExpense(description: $description, category: $category, cost: $cost) {
                id
                createdAt
            }
        }
    """
    create_vars = {"description": "Datetime Test", "category": "FOOD", "cost": 1.0}
    create_response = graphql_query(client, create_mutation, create_vars)
    create_json = create_response.get_json()
    created_at_str = create_json["data"]["createExpense"]["createdAt"]

    # Test serialization: The returned 'createdAt' should be a valid ISO string
    try:
        parsed_dt = datetime.fromisoformat(created_at_str)
        assert parsed_dt is not None
    except ValueError:
        pytest.fail(f"createdAt '{created_at_str}' is not a valid ISO 8601 string.")

    # Test value_parser (implicitly tested by Ariadne when it processes input,
    # but your schema doesn't take DateTime as an input argument directly in mutations/queries)
    # If you had a mutation like `createExpenseWithDate(..., createdAt: DateTime!)`,
    # Ariadne would use your `parse_datetime_value`.
    # For now, we've confirmed the serializer.
    # To directly test parser, you could call it:
    from server import parse_datetime_value # Use the direct import
    assert parse_datetime_value(dt_iso) == dt_obj
    assert parse_datetime_value("invalid-date") is None


# --- Delete Expense Tests ---

def test_delete_expense(client):
    # 1. Create an expense
    import server # Use the direct import
    initial_expense = {"description": "Item to Delete", "category": "FOOD", "cost": 5.00, "createdAt": datetime.now(timezone.utc)}
    insert_result = server.expenses_collection.insert_one(initial_expense)
    expense_id = str(insert_result.inserted_id)

    # 2. Delete the expense
    mutation = """
        mutation DeleteExpense($id: ID!) {
            deleteExpense(id: $id)
        }
    """
    variables = {"id": expense_id}
    response = graphql_query(client, mutation, variables)
    json_data = response.get_json()

    assert response.status_code == 200
    assert "errors" not in json_data
    assert json_data["data"]["deleteExpense"] is True

    # 3. Verify in DB
    deleted_doc = server.expenses_collection.find_one({"_id": insert_result.inserted_id})
    assert deleted_doc is None


def test_delete_expense_not_found(client):
    mutation = """
        mutation DeleteExpense($id: ID!) {
            deleteExpense(id: $id)
        }
    """
    # A valid ObjectId format, but non-existent
    non_existent_id = "60c72b9f9b1e8b3b0f6a1b2d" # Different from edit test
    variables = {"id": non_existent_id}
    response = graphql_query(client, mutation, variables)
    json_data = response.get_json()

    assert response.status_code == 200
    assert "errors" not in json_data
    assert json_data["data"]["deleteExpense"] is False


def test_delete_expense_invalid_id_format(client):
    mutation = """
        mutation DeleteExpense($id: ID!) {
            deleteExpense(id: $id)
        }
    """
    variables = {"id": "invalid-id-for-delete"}
    response = graphql_query(client, mutation, variables)
    json_data = response.get_json()

    assert response.status_code == 200
    # The resolver returns False for invalid ID format
    assert "errors" not in json_data # If it were a GraphQLError, this would be different
    assert json_data["data"]["deleteExpense"] is False


# --- Health Check Tests ---

def test_health_check_all_up(client, mocker):
    # Mock the MongoDB ping command to simulate a healthy connection
    # The 'db' object is part of the 'server' module, which is modified by the 'app' fixture
    import server
    mocker.patch.object(server.db, 'command', return_value={'ok': 1.0})

    response = client.get("/health")
    json_data = response.get_json()

    assert response.status_code == 200
    assert json_data["status"] == "UP"
    assert json_data["components"]["mongodb"]["status"] == "UP"
    assert json_data["components"]["mongodb"]["details"] == "MongoDB is responsive"

def test_health_check_mongo_down(client, mocker):
    # Mock the MongoDB ping command to simulate a connection failure
    import server
    error_message = "Simulated MongoDB connection error"
    mocker.patch.object(server.db, 'command', side_effect=ConnectionFailure(error_message))

    response = client.get("/health")
    json_data = response.get_json()

    assert response.status_code == 503
    assert json_data["status"] == "DOWN"
    assert json_data["components"]["mongodb"]["status"] == "DOWN"
    assert json_data["components"]["mongodb"]["details"] == f"MongoDB connection failed: {error_message}"

    # Test with a generic exception as well
    generic_error_message = "Generic DB error"
    mocker.patch.object(server.db, 'command', side_effect=Exception(generic_error_message))
    response_generic_fail = client.get("/health")
    assert response_generic_fail.status_code == 503
    assert "Generic DB error" in response_generic_fail.get_json()["components"]["mongodb"]["details"]