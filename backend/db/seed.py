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

import re
_schema_path = Path(__file__).resolve().parents[2] / "SQL-Server-Sample-Database" / "BikeStores Sample Database - create objects.sql"
_schema_sql = _schema_path.read_text(encoding="utf-8")
_schema_sql = _schema_sql.replace("INT IDENTITY (1, 1)", "SERIAL")
_schema_sql = re.sub(r"(?i)\bgo\b", "", _schema_sql)
_schema_sql = _schema_sql.replace("tinyint", "SMALLINT")
TARGET_DB_SCHEMA = _schema_sql

# ---------------------------------------------------------------------------
# Reference data inserts
# ---------------------------------------------------------------------------

_data_path = Path(__file__).resolve().parents[2] / "SQL-Server-Sample-Database" / "BikeStores Sample Database - load data.sql"
_data_sql = _data_path.read_text(encoding="utf-8")
_data_sql = re.sub(r"(?i)use BikeStores;", "", _data_sql)
_data_sql = re.sub(r"(?i)SET\s+IDENTITY_INSERT\s+[^\s]+\s+(?:ON|OFF);?", "", _data_sql)
TARGET_DB_DATA = _data_sql


# ---------------------------------------------------------------------------
# SQL problems
# ---------------------------------------------------------------------------

SEED_PROBLEMS: list[dict] = [
    {
        "title": "Basic SELECT — Customer Names",
        "description": (
            "Write a SQL query that returns the **first name** and **last name** "
            "of all customers, ordered alphabetically by last name.\n\n"
            "Expected columns: `first_name`, `last_name`"
        ),
        "difficulty": Difficulty.EASY,
        "language": Language.SQL,
        "topic": "SELECT basics",
        "starter_code": "SELECT -- your columns here\nFROM sales.customers\nORDER BY -- ?;",
        "test_cases": [
            {
                "expected_query": "SELECT first_name, last_name FROM sales.customers ORDER BY last_name",
                "check_order": True,
                "description": "All customers ordered by last name",
            },
        ],
        "gold_standard": {
            "solution_code": "SELECT first_name, last_name FROM sales.customers ORDER BY last_name;",
            "explanation": (
                "Use SELECT to choose the columns, FROM to specify the table, "
                "and ORDER BY to sort the results alphabetically."
            ),
        },
    },
    {
        "title": "WHERE Clause — Expensive Products",
        "description": (
            "Write a SQL query that returns the **product name** and **list price** "
            "of products that cost more than $1,000. "
            "Order the results by list price in descending order.\n\n"
            "Expected columns: `product_name`, `list_price`"
        ),
        "difficulty": Difficulty.EASY,
        "language": Language.SQL,
        "topic": "WHERE filtering",
        "starter_code": "SELECT -- columns\nFROM production.products\nWHERE -- condition\nORDER BY -- ?;",
        "test_cases": [
            {
                "expected_query": (
                    "SELECT product_name, list_price FROM production.products "
                    "WHERE list_price > 1000 ORDER BY list_price DESC"
                ),
                "check_order": True,
                "description": "Products with list_price > 1000, descending",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT product_name, list_price\n"
                "FROM production.products\n"
                "WHERE list_price > 1000\n"
                "ORDER BY list_price DESC;"
            ),
            "explanation": (
                "Use WHERE list_price > 1000 to filter rows, and "
                "ORDER BY list_price DESC to sort from highest to lowest."
            ),
        },
    },
    {
        "title": "INNER JOIN — Products & Brands",
        "description": (
            "Write a SQL query that returns each **product name** and its "
            "**brand name**. Order by brand name, then by product name.\n\n"
            "Expected columns: `product_name`, `brand_name`"
        ),
        "difficulty": Difficulty.MEDIUM,
        "language": Language.SQL,
        "topic": "JOINs",
        "starter_code": (
            "SELECT -- columns\n"
            "FROM production.products p\n"
            "-- JOIN ?\n"
            "ORDER BY -- ?;"
        ),
        "test_cases": [
            {
                "expected_query": (
                    "SELECT p.product_name, b.brand_name "
                    "FROM production.products p "
                    "JOIN production.brands b ON p.brand_id = b.brand_id "
                    "ORDER BY b.brand_name, p.product_name"
                ),
                "check_order": True,
                "description": "All products with brand names, sorted",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT p.product_name, b.brand_name\n"
                "FROM production.products p\n"
                "JOIN production.brands b ON p.brand_id = b.brand_id\n"
                "ORDER BY b.brand_name, p.product_name;"
            ),
            "explanation": (
                "Use INNER JOIN to combine products and brands on the "
                "foreign key brand_id."
            ),
        },
    },
    {
        "title": "GROUP BY — Brand Average Price",
        "description": (
            "Write a SQL query that returns each **brand name** and the "
            "**average list price** of products in that brand. "
            "Round the average to 2 decimal places. "
            "Order by average price descending.\n\n"
            "Expected columns: `brand_name`, `avg_price`"
        ),
        "difficulty": Difficulty.MEDIUM,
        "language": Language.SQL,
        "topic": "Aggregation",
        "starter_code": (
            "SELECT -- brand, aggregate\n"
            "FROM production.products p\n"
            "JOIN production.brands b ON p.brand_id = b.brand_id\n"
            "GROUP BY -- ?\n"
            "ORDER BY -- ?;"
        ),
        "test_cases": [
            {
                "expected_query": (
                    "SELECT b.brand_name, ROUND(AVG(p.list_price), 2) AS avg_price "
                    "FROM production.products p "
                    "JOIN production.brands b ON p.brand_id = b.brand_id "
                    "GROUP BY b.brand_name "
                    "ORDER BY avg_price DESC"
                ),
                "check_order": True,
                "description": "Average price per brand, descending",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT b.brand_name, ROUND(AVG(p.list_price), 2) AS avg_price\n"
                "FROM production.products p\n"
                "JOIN production.brands b ON p.brand_id = b.brand_id\n"
                "GROUP BY b.brand_name\n"
                "ORDER BY avg_price DESC;"
            ),
            "explanation": (
                "Use GROUP BY b.brand_name to group products by brand, "
                "AVG(p.list_price) to compute the mean, and ROUND() for formatting."
            ),
        },
    },
    {
        "title": "Subquery — Above-Average Priced Products",
        "description": (
            "Write a SQL query that returns the **product name** and **list price** "
            "of products that cost more than the overall average list price. "
            "Order by list price descending.\n\n"
            "Expected columns: `product_name`, `list_price`"
        ),
        "difficulty": Difficulty.MEDIUM,
        "language": Language.SQL,
        "topic": "Subqueries",
        "starter_code": (
            "SELECT -- columns\n"
            "FROM production.products\n"
            "WHERE list_price > (\n"
            "    -- subquery here\n"
            ")\n"
            "ORDER BY list_price DESC;"
        ),
        "test_cases": [
            {
                "expected_query": (
                    "SELECT product_name, list_price "
                    "FROM production.products "
                    "WHERE list_price > (SELECT AVG(list_price) FROM production.products) "
                    "ORDER BY list_price DESC"
                ),
                "check_order": True,
                "description": "Products priced above average",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT product_name, list_price\n"
                "FROM production.products\n"
                "WHERE list_price > (SELECT AVG(list_price) FROM production.products)\n"
                "ORDER BY list_price DESC;"
            ),
            "explanation": (
                "Use a scalar subquery (SELECT AVG(list_price) FROM production.products) "
                "in the WHERE clause."
            ),
        },
    },
    {
        "title": "HAVING — Stores with Many Orders",
        "description": (
            "Write a SQL query that returns the **store name** and the **number of orders** "
            "placed at that store. Only include stores with more than 100 orders. "
            "Order by number of orders descending.\n\n"
            "Expected columns: `store_name`, `order_count`"
        ),
        "difficulty": Difficulty.HARD,
        "language": Language.SQL,
        "topic": "HAVING clause",
        "starter_code": (
            "SELECT -- store name, aggregate\n"
            "FROM sales.stores s\n"
            "JOIN sales.orders o ON s.store_id = o.store_id\n"
            "GROUP BY -- ?\n"
            "HAVING -- ?\n"
            "ORDER BY -- ?;"
        ),
        "test_cases": [
            {
                "expected_query": (
                    "SELECT s.store_name, COUNT(o.order_id) AS order_count "
                    "FROM sales.stores s "
                    "JOIN sales.orders o ON s.store_id = o.store_id "
                    "GROUP BY s.store_name "
                    "HAVING COUNT(o.order_id) > 100 "
                    "ORDER BY order_count DESC"
                ),
                "check_order": True,
                "description": "Stores with > 100 orders",
            },
        ],
        "gold_standard": {
            "solution_code": (
                "SELECT s.store_name, COUNT(o.order_id) AS order_count\n"
                "FROM sales.stores s\n"
                "JOIN sales.orders o ON s.store_id = o.store_id\n"
                "GROUP BY s.store_name\n"
                "HAVING COUNT(o.order_id) > 100\n"
                "ORDER BY order_count DESC;"
            ),
            "explanation": (
                "JOIN stores and orders, GROUP BY store name, "
                "use COUNT for the number of orders, and HAVING to filter groups "
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
    for statement in TARGET_DB_SCHEMA.split(";"):
        stmt = statement.strip()
        if stmt:
            await session.execute(text(stmt))
    await session.commit()
    logger.info("Reference tables created.")


async def insert_reference_data(session: AsyncSession) -> None:
    """Insert sample data into reference tables."""
    logger.info("Inserting reference data...")
    for statement in TARGET_DB_DATA.split(";"):
        stmt = statement.strip()
        if stmt:
            await session.execute(text(stmt))
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
