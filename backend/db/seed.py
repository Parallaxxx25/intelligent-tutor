"""
Seed data — SQL learning problems.

Populates the TargetDB with:
  1. Reference tables (employees, departments, orders, etc.)
  2. SQL query problems with gold-standard queries & test cases

Idempotent — safe to run multiple times.

Version: 2026-02-12  (SQL-focused rewrite)
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Allow `python -m backend.db.seed` from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.db.database import async_session_factory, init_db
from backend.db.models import (
    Base,
    Difficulty,
    GoldStandard,
    Language,
    Problem,
    TestCase,
    User,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reference-table DDL (run on the TargetDB)
# ---------------------------------------------------------------------------

TARGET_DB_SCHEMA = """\
-- Departments table
CREATE TABLE IF NOT EXISTS departments (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    budget      NUMERIC(12, 2),
    location    VARCHAR(100)
);

-- Employees table
CREATE TABLE IF NOT EXISTS employees (
    id              SERIAL PRIMARY KEY,
    first_name      VARCHAR(50) NOT NULL,
    last_name       VARCHAR(50) NOT NULL,
    email           VARCHAR(100) UNIQUE,
    salary          NUMERIC(10, 2),
    hire_date       DATE,
    department_id   INT REFERENCES departments(id),
    manager_id      INT REFERENCES employees(id)
);

-- Products table
CREATE TABLE IF NOT EXISTS products (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    category    VARCHAR(50),
    price       NUMERIC(10, 2),
    stock       INT DEFAULT 0
);

-- Customers table
CREATE TABLE IF NOT EXISTS customers (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    email       VARCHAR(100),
    city        VARCHAR(50),
    country     VARCHAR(50) DEFAULT 'USA'
);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    customer_id     INT REFERENCES customers(id),
    product_id      INT REFERENCES products(id),
    quantity        INT DEFAULT 1,
    total_amount    NUMERIC(10, 2),
    order_date      DATE,
    status          VARCHAR(20) DEFAULT 'pending'
);
"""

# ---------------------------------------------------------------------------
# Reference data inserts
# ---------------------------------------------------------------------------

TARGET_DB_DATA = """\
-- Departments
INSERT INTO departments (id, name, budget, location) VALUES
    (1, 'Engineering',  500000, 'Building A'),
    (2, 'Marketing',    200000, 'Building B'),
    (3, 'Sales',        300000, 'Building C'),
    (4, 'HR',           150000, 'Building A'),
    (5, 'Finance',      250000, 'Building D')
ON CONFLICT DO NOTHING;

-- Employees
INSERT INTO employees (id, first_name, last_name, email, salary, hire_date, department_id, manager_id) VALUES
    (1,  'Alice',   'Johnson',  'alice@company.com',    95000,  '2020-01-15', 1, NULL),
    (2,  'Bob',     'Smith',    'bob@company.com',      85000,  '2020-03-20', 1, 1),
    (3,  'Charlie', 'Brown',    'charlie@company.com',  72000,  '2021-06-10', 2, NULL),
    (4,  'Diana',   'Lee',      'diana@company.com',    68000,  '2021-08-25', 2, 3),
    (5,  'Eve',     'Davis',    'eve@company.com',      91000,  '2019-11-01', 3, NULL),
    (6,  'Frank',   'Wilson',   'frank@company.com',    78000,  '2022-02-14', 3, 5),
    (7,  'Grace',   'Taylor',   'grace@company.com',    62000,  '2023-01-09', 4, NULL),
    (8,  'Henry',   'Anderson', 'henry@company.com',    55000,  '2023-05-15', 4, 7),
    (9,  'Ivy',     'Thomas',   'ivy@company.com',      98000,  '2018-07-01', 5, NULL),
    (10, 'Jack',    'Martinez', 'jack@company.com',     73000,  '2022-09-30', 1, 1)
ON CONFLICT DO NOTHING;

-- Products
INSERT INTO products (id, name, category, price, stock) VALUES
    (1, 'Laptop Pro',    'Electronics', 1299.99, 50),
    (2, 'Wireless Mouse','Electronics',   29.99, 200),
    (3, 'Desk Lamp',     'Office',        45.00, 150),
    (4, 'Notebook',      'Stationery',     5.99, 500),
    (5, 'Monitor 27"',   'Electronics',  399.99,  75),
    (6, 'Keyboard',      'Electronics',   69.99, 120),
    (7, 'Standing Desk', 'Office',       549.00,  30),
    (8, 'Pen Set',       'Stationery',    12.50, 300)
ON CONFLICT DO NOTHING;

-- Customers
INSERT INTO customers (id, name, email, city, country) VALUES
    (1, 'Acme Corp',       'orders@acme.com',     'New York',     'USA'),
    (2, 'Globex Inc',      'buy@globex.com',      'Los Angeles',  'USA'),
    (3, 'Initech',         'purchasing@initech.com','Austin',      'USA'),
    (4, 'Umbrella Corp',   'orders@umbrella.com', 'London',       'UK'),
    (5, 'Wayne Enterprises','supply@wayne.com',   'Gotham',       'USA')
ON CONFLICT DO NOTHING;

-- Orders
INSERT INTO orders (id, customer_id, product_id, quantity, total_amount, order_date, status) VALUES
    (1,  1, 1, 2,  2599.98, '2024-01-10', 'completed'),
    (2,  1, 2, 5,   149.95, '2024-01-15', 'completed'),
    (3,  2, 5, 3,  1199.97, '2024-02-01', 'completed'),
    (4,  2, 3, 10,  450.00, '2024-02-10', 'shipped'),
    (5,  3, 1, 1,  1299.99, '2024-02-15', 'completed'),
    (6,  3, 6, 5,   349.95, '2024-03-01', 'pending'),
    (7,  4, 7, 2,  1098.00, '2024-03-10', 'shipped'),
    (8,  4, 4, 50,  299.50, '2024-03-15', 'completed'),
    (9,  5, 1, 3,  3899.97, '2024-04-01', 'pending'),
    (10, 5, 5, 1,   399.99, '2024-04-05', 'completed')
ON CONFLICT DO NOTHING;
"""


# ---------------------------------------------------------------------------
# SQL problems
# ---------------------------------------------------------------------------

SEED_PROBLEMS: list[dict] = [
    {
        "title": "Basic SELECT — Employee Names",
        "description": (
            "Write a SQL query that returns the **first name** and **last name** "
            "of all employees, ordered alphabetically by last name.\n\n"
            "Expected columns: `first_name`, `last_name`"
        ),
        "difficulty": Difficulty.EASY,
        "language": Language.SQL,
        "topic": "SELECT basics",
        "starter_code": "SELECT -- your columns here\nFROM employees\nORDER BY -- ?;",
        "test_cases": [
            {
                "expected_query": "SELECT first_name, last_name FROM employees ORDER BY last_name",
                "check_order": True,
                "description": "All employees ordered by last name",
            },
        ],
        "gold_standard": {
            "solution_code": "SELECT first_name, last_name FROM employees ORDER BY last_name;",
            "explanation": (
                "Use SELECT to choose the columns, FROM to specify the table, "
                "and ORDER BY to sort the results alphabetically."
            ),
        },
    },
    {
        "title": "WHERE Clause — High Salary",
        "description": (
            "Write a SQL query that returns the **first name**, **last name**, "
            "and **salary** of employees who earn more than $80,000. "
            "Order the results by salary in descending order.\n\n"
            "Expected columns: `first_name`, `last_name`, `salary`"
        ),
        "difficulty": Difficulty.EASY,
        "language": Language.SQL,
        "topic": "WHERE filtering",
        "starter_code": "SELECT -- columns\nFROM employees\nWHERE -- condition\nORDER BY -- ?;",
        "test_cases": [
            {
                "expected_query": (
                    "SELECT first_name, last_name, salary FROM employees "
                    "WHERE salary > 80000 ORDER BY salary DESC"
                ),
                "check_order": True,
                "description": "Employees with salary > 80000, descending",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT first_name, last_name, salary\n"
                "FROM employees\n"
                "WHERE salary > 80000\n"
                "ORDER BY salary DESC;"
            ),
            "explanation": (
                "Use WHERE salary > 80000 to filter rows, and "
                "ORDER BY salary DESC to sort from highest to lowest."
            ),
        },
    },
    {
        "title": "INNER JOIN — Employees & Departments",
        "description": (
            "Write a SQL query that returns each employee's **first name**, "
            "**last name**, and their **department name**. "
            "Order by department name, then by last name.\n\n"
            "Expected columns: `first_name`, `last_name`, `department_name`"
        ),
        "difficulty": Difficulty.MEDIUM,
        "language": Language.SQL,
        "topic": "JOINs",
        "starter_code": (
            "SELECT -- columns\n"
            "FROM employees e\n"
            "-- JOIN ?\n"
            "ORDER BY -- ?;"
        ),
        "test_cases": [
            {
                "expected_query": (
                    "SELECT e.first_name, e.last_name, d.name AS department_name "
                    "FROM employees e "
                    "JOIN departments d ON e.department_id = d.id "
                    "ORDER BY d.name, e.last_name"
                ),
                "check_order": True,
                "description": "All employees with department names, sorted",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT e.first_name, e.last_name, d.name AS department_name\n"
                "FROM employees e\n"
                "JOIN departments d ON e.department_id = d.id\n"
                "ORDER BY d.name, e.last_name;"
            ),
            "explanation": (
                "Use INNER JOIN to combine employees and departments on the "
                "foreign key department_id. Alias the department name column "
                "as department_name to match expected output."
            ),
        },
    },
    {
        "title": "GROUP BY — Department Average Salary",
        "description": (
            "Write a SQL query that returns each **department name** and the "
            "**average salary** of employees in that department. "
            "Round the average to 2 decimal places. "
            "Order by average salary descending.\n\n"
            "Expected columns: `department_name`, `avg_salary`"
        ),
        "difficulty": Difficulty.MEDIUM,
        "language": Language.SQL,
        "topic": "Aggregation",
        "starter_code": (
            "SELECT -- department, aggregate\n"
            "FROM employees e\n"
            "JOIN departments d ON e.department_id = d.id\n"
            "GROUP BY -- ?\n"
            "ORDER BY -- ?;"
        ),
        "test_cases": [
            {
                "expected_query": (
                    "SELECT d.name AS department_name, ROUND(AVG(e.salary), 2) AS avg_salary "
                    "FROM employees e "
                    "JOIN departments d ON e.department_id = d.id "
                    "GROUP BY d.name "
                    "ORDER BY avg_salary DESC"
                ),
                "check_order": True,
                "description": "Average salary per department, descending",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT d.name AS department_name, ROUND(AVG(e.salary), 2) AS avg_salary\n"
                "FROM employees e\n"
                "JOIN departments d ON e.department_id = d.id\n"
                "GROUP BY d.name\n"
                "ORDER BY avg_salary DESC;"
            ),
            "explanation": (
                "Use GROUP BY d.name to group employees by department, "
                "AVG(e.salary) to compute the mean, and ROUND() for formatting."
            ),
        },
    },
    {
        "title": "Subquery — Above-Average Earners",
        "description": (
            "Write a SQL query that returns the **first name**, **last name**, "
            "and **salary** of employees who earn more than the company-wide "
            "average salary. Order by salary descending.\n\n"
            "Expected columns: `first_name`, `last_name`, `salary`"
        ),
        "difficulty": Difficulty.MEDIUM,
        "language": Language.SQL,
        "topic": "Subqueries",
        "starter_code": (
            "SELECT -- columns\n"
            "FROM employees\n"
            "WHERE salary > (\n"
            "    -- subquery here\n"
            ")\n"
            "ORDER BY salary DESC;"
        ),
        "test_cases": [
            {
                "expected_query": (
                    "SELECT first_name, last_name, salary "
                    "FROM employees "
                    "WHERE salary > (SELECT AVG(salary) FROM employees) "
                    "ORDER BY salary DESC"
                ),
                "check_order": True,
                "description": "Employees earning above average",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT first_name, last_name, salary\n"
                "FROM employees\n"
                "WHERE salary > (SELECT AVG(salary) FROM employees)\n"
                "ORDER BY salary DESC;"
            ),
            "explanation": (
                "Use a scalar subquery (SELECT AVG(salary) FROM employees) "
                "in the WHERE clause. Since AVG returns a single value, "
                "you can use the > operator directly."
            ),
        },
    },
    {
        "title": "HAVING — Big Spender Customers",
        "description": (
            "Write a SQL query that returns the **customer name** and the "
            "**total amount** they have spent across all orders. "
            "Only include customers who have spent more than $1,000 total. "
            "Order by total amount descending.\n\n"
            "Expected columns: `customer_name`, `total_spent`"
        ),
        "difficulty": Difficulty.HARD,
        "language": Language.SQL,
        "topic": "HAVING clause",
        "starter_code": (
            "SELECT -- customer name, aggregate\n"
            "FROM customers c\n"
            "JOIN orders o ON c.id = o.customer_id\n"
            "GROUP BY -- ?\n"
            "HAVING -- ?\n"
            "ORDER BY -- ?;"
        ),
        "test_cases": [
            {
                "expected_query": (
                    "SELECT c.name AS customer_name, SUM(o.total_amount) AS total_spent "
                    "FROM customers c "
                    "JOIN orders o ON c.id = o.customer_id "
                    "GROUP BY c.name "
                    "HAVING SUM(o.total_amount) > 1000 "
                    "ORDER BY total_spent DESC"
                ),
                "check_order": True,
                "description": "Customers with total spending > 1000",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT c.name AS customer_name, SUM(o.total_amount) AS total_spent\n"
                "FROM customers c\n"
                "JOIN orders o ON c.id = o.customer_id\n"
                "GROUP BY c.name\n"
                "HAVING SUM(o.total_amount) > 1000\n"
                "ORDER BY total_spent DESC;"
            ),
            "explanation": (
                "JOIN customers and orders, GROUP BY customer name, "
                "use SUM for total spending, and HAVING to filter groups "
                "(WHERE filters rows BEFORE grouping, HAVING filters AFTER)."
            ),
        },
    },
]


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

async def create_target_tables(session: AsyncSession) -> None:
    """Create reference tables (departments, employees, etc.) in the target DB."""
    logger.info("Creating target reference tables...")
    await session.execute(text(TARGET_DB_SCHEMA))
    await session.commit()
    logger.info("Reference tables created.")


async def insert_reference_data(session: AsyncSession) -> None:
    """Insert sample data into reference tables."""
    logger.info("Inserting reference data...")
    await session.execute(text(TARGET_DB_DATA))
    await session.commit()
    logger.info("Reference data inserted.")


async def seed_problems(session: AsyncSession) -> None:
    """Seed SQL problems, test cases, and gold standards."""
    for pdata in SEED_PROBLEMS:
        # Check if already exists
        result = await session.execute(
            select(Problem).where(Problem.title == pdata["title"])
        )
        if result.scalars().first():
            logger.info("Problem '%s' already exists — skipping.", pdata["title"])
            continue

        problem = Problem(
            title=pdata["title"],
            description=pdata["description"],
            difficulty=pdata["difficulty"],
            language=pdata["language"],
            topic=pdata["topic"],
            starter_code=pdata.get("starter_code"),
        )
        session.add(problem)
        await session.flush()  # Get the auto-generated ID

        # Test cases
        for i, tc in enumerate(pdata["test_cases"]):
            session.add(
                TestCase(
                    problem_id=problem.id,
                    input_data=tc["expected_query"],          # gold-standard query
                    expected_output=tc.get("description", ""),
                    is_hidden=False,
                    order=i,
                    description=tc.get("description", ""),
                )
            )

        # Gold standard
        gs = pdata["gold_standard"]
        session.add(
            GoldStandard(
                problem_id=problem.id,
                solution_code=gs["solution_code"],
                explanation=gs.get("explanation", ""),
            )
        )

        logger.info("Seeded problem: %s", pdata["title"])

    await session.commit()


async def seed_user(session: AsyncSession) -> None:
    """Create a demo student user if not exists."""
    result = await session.execute(
        select(User).where(User.email == "student@demo.com")
    )
    if result.scalars().first():
        logger.info("Demo user already exists.")
        return

    session.add(
        User(
            username="demo_student",
            email="student@demo.com",
            display_name="Demo Student",
        )
    )
    await session.commit()
    logger.info("Demo user created.")


async def seed_database() -> None:
    """Full seed: tables → data → problems → user."""
    await init_db()

    async with async_session_factory() as session:
        await create_target_tables(session)
        await insert_reference_data(session)
        await seed_problems(session)
        await seed_user(session)

    logger.info("✅ Database seeding complete.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    asyncio.run(seed_database())
