# Expenses API

[![Python CI](https://github.com/mseng10/expenses/actions/workflows/actions.yml/badge.svg)](https://github.com/<YOUR_USERNAME>/<YOUR_REPOSITORY_NAME>/actions/workflows/actions.yml)

A simple Flask-based GraphQL API for managing expenses, using MongoDB as a database.

## Features

*   Create, read, and update expenses.
*   Filter expenses by year, month, or day.
*   Calculates total cost for filtered expenses.
*   Uses a custom `DateTime` scalar for date handling.
*   GraphQL endpoint with Playground explorer.
*   Dockerized for easy setup and deployment.
*   Automated testing with Pytest and Testcontainers.

## Technologies Used

*   **Backend:** Python, Flask, Ariadne (for GraphQL)
*   **Database:** MongoDB
*   **Testing:** Pytest, Testcontainers
*   **Containerization:** Docker, Docker Compose
*   **CI/CD:** GitHub Actions

## Prerequisites

*   Docker
*   Docker Compose

## Getting Started

1.  **Clone the repository:**
    ```bash
    chmod +x setup.sh
    ./setup.sh
    ```
    This will create a `venv` directory, activate it for the current session, and install dependencies.

3.  **Activate the virtual environment (if not already active or in a new terminal session):**
    ```bash
    source venv/bin/activate
    ```

4.  **Run the Flask application:**
    ```bash
    python app.py
    ```
    The application will start, and the GraphQL endpoint will be available at `http://localhost:5000/graphql`. You can access GraphiQL (an in-browser IDE for GraphQL) at this URL.

5.  **Deactivate the virtual environment when done:**
    ```bash
    deactivate
    ```

## GraphQL Schema

**Types:**

```graphql
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
```

## Example Operations

You can send these to `http://localhost:5000/graphql` using a tool like Postman, Insomnia, or the GraphiQL interface.

**1. Create an Expense:**
```graphql
mutation {
  createExpense(description: "Dinner with client", category: "Business", cost: 75.50) {
    id
    description
    category
    cost
    createdAt
  }
}
```

**2. Edit an Expense (replace `<expense_id>` with an actual ID):**
```graphql
mutation {
  editExpense(id: "<expense_id>", description: "Client Dinner", cost: 72.00) {
    id
    description
    category
    cost
  }
}
```

**3. Query Expenses:**

*   **Get all expenses and total:**
    ```graphql
    query {
      getExpenses {
        items {
          id
          description
          cost
          createdAt
        }
        totalCost
      }
    }
    ```

*   **Get expenses for a specific month and year (e.g., October 2023) and its total:**
    ```graphql
    query {
      getExpenses(year: 2023, month: 10) {
        items {
          id
          description
        }
        totalCost
      }
    }
    ```

*   **Get expenses for a specific day (e.g., October 26, 2023) and its total:**
    ```graphql
    query {
      getExpenses(year: 2023, month: 10, day: 26) {
        items {
          id
          description
          category
          cost
        }
        totalCost
      }
    }
    ```

*   **Get expenses for a year (e.g., 2023) and its total (if current year, it's "year so far"):**
    ```graphql
    query {
      getExpenses(year: 2023) {
        items {
          id
          description
        }
        totalCost
      }
    }
    ```