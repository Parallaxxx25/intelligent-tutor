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
import csv
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

import math
import re

_schema_path = (
    Path(__file__).resolve().parents[2]
    / "SQL-Server-Sample-Database"
    / "BikeStores Sample Database - create objects.sql"
)
_schema_sql = _schema_path.read_text(encoding="utf-8")
_schema_sql = _schema_sql.replace("INT IDENTITY (1, 1)", "SERIAL")
_schema_sql = _schema_sql.replace("CREATE SCHEMA ", "CREATE SCHEMA IF NOT EXISTS ")
_schema_sql = re.sub(r"(?i)\bgo\b", "", _schema_sql)
_schema_sql = _schema_sql.replace("tinyint", "SMALLINT")
TARGET_DB_SCHEMA = _schema_sql

# ---------------------------------------------------------------------------
# Reference data inserts
# ---------------------------------------------------------------------------

_data_path = (
    Path(__file__).resolve().parents[2]
    / "SQL-Server-Sample-Database"
    / "BikeStores Sample Database - load data.sql"
)
_data_sql = _data_path.read_text(encoding="utf-8")
_data_sql = re.sub(r"(?i)use BikeStores;", "", _data_sql)
_data_sql = re.sub(r"(?i)SET\s+IDENTITY_INSERT\s+[^\s]+\s+(?:ON|OFF);?", "", _data_sql)
_data_sql = re.sub(r"(?m)^INSERT INTO", ";\nINSERT INTO", _data_sql)
TARGET_DB_DATA = _data_sql


# ---------------------------------------------------------------------------
# SQL problems
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------


def split_sql_statements(sql: str) -> list[str]:
    """Safely split SQL by semicolon, ignoring those inside quotes or comments."""
    statements = []
    in_string = False
    in_single_line_comment = False
    in_multi_line_comment = False
    current_statement = []

    i = 0
    length = len(sql)
    while i < length:
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < length else ""

        if in_single_line_comment:
            if char == "\n":
                in_single_line_comment = False
            current_statement.append(char)
        elif in_multi_line_comment:
            if char == "*" and next_char == "/":
                in_multi_line_comment = False
                current_statement.append("*/")
                i += 1
            else:
                current_statement.append(char)
        elif in_string:
            if char == "'":
                if next_char == "'":
                    current_statement.append("''")
                    i += 1
                else:
                    in_string = False
                    current_statement.append(char)
            else:
                current_statement.append(char)
        else:
            if char == "-" and next_char == "-":
                in_single_line_comment = True
                current_statement.append("--")
                i += 1
            elif char == "/" and next_char == "*":
                in_multi_line_comment = True
                current_statement.append("/*")
                i += 1
            elif char == "'":
                in_string = True
                current_statement.append(char)
            elif char == ";":
                statements.append("".join(current_statement).strip())
                current_statement = []
            else:
                current_statement.append(char)
        i += 1

    last_stmt = "".join(current_statement).strip()
    if last_stmt:
        statements.append(last_stmt)

    return [s for s in statements if s]


async def create_target_tables(session: AsyncSession) -> None:
    """Create reference tables (departments, employees, etc.) in the target DB."""
    logger.info("Creating target reference tables...")
    statements = split_sql_statements(TARGET_DB_SCHEMA)
    total = len(statements)
    for i, statement in enumerate(statements, 1):
        if statement:
            try:
                async with session.begin_nested():
                    await session.execute(text(statement))
            except Exception as e:
                pass
            sys.stdout.write(f"\r  Progress: {i}/{total} [{int(i/total*100)}%]   ")
            sys.stdout.flush()
    sys.stdout.write("\n")
    await session.commit()
    logger.info("Reference tables created.")


async def insert_reference_data(session: AsyncSession) -> None:
    """Insert sample data into reference tables."""
    logger.info("Inserting reference data...")
    statements = split_sql_statements(TARGET_DB_DATA)
    total = len(statements)
    for i, statement in enumerate(statements, 1):
        if statement:
            try:
                async with session.begin_nested():
                    await session.execute(text(statement))
            except Exception as e:
                if (
                    "unique constraint" not in str(e).lower()
                    and "duplicate" not in str(e).lower()
                ):
                    sys.stdout.write(f"\nError on statement {i}: {e}\n")
            sys.stdout.write(f"\r  Progress: {i}/{total} [{int(i/total*100)}%]   ")
            sys.stdout.flush()
    sys.stdout.write("\n")
    await session.commit()
    logger.info("Reference data inserted.")


async def seed_problems(session: AsyncSession) -> None:
    """Seed SQL problems, test cases, and gold standards."""
    csv_path = (
        Path(__file__).resolve().parents[2]
        / "sql-problem"
        / "Practice-Assignment-Bike shop-2025.csv"
    )

    if not csv_path.exists():
        logger.warning(f"CSV file not found: {csv_path}")
        return

    problems_to_create = []

    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            seq = str(row.get("ลำดับ", "")).strip()
            topic = str(row.get("Topic Evaluated", "SQL")).strip()
            if not seq or str(topic).lower() in ["nan", "none", ""]:
                continue

            # --- Practice Problem ---
            prac_en = str(row.get("Practice Question (English)", "")).strip()
            prac_th = str(row.get("Practice Question (Thai)", "")).strip()
            prac_ans = str(row.get("Practice Answer", "")).strip()

            if prac_th and prac_ans and prac_ans.lower() not in ["nan", "none", ""]:
                problems_to_create.append(
                    {
                        "title": f"Practice {seq} - {topic.split( chr(10) )[0].strip()}",
                        "description": f"{prac_en}\n\n{prac_th}",
                        "topic": topic,
                        "difficulty": Difficulty.EASY,
                        "language": Language.SQL,
                        "starter_code": "-- Write your query here\n",
                        "test_cases": [
                            {
                                "expected_query": prac_ans,
                                "check_order": "ORDER BY" in prac_ans.upper(),
                                "description": "Practice expected output",
                            }
                        ],
                        "gold_standard": {
                            "solution_code": prac_ans,
                            "explanation": "Practice solution.",
                        },
                    }
                )

            # --- Assignment Problem ---
            assign_en = str(row.get("Assignment Question (English)", "")).strip()
            assign_th = str(row.get("Assignment Question (Thai)", "")).strip()
            assign_ans = str(row.get("Assignment Answer", "")).strip()

            if (
                assign_th
                and assign_ans
                and assign_ans.lower() not in ["nan", "none", ""]
            ):
                problems_to_create.append(
                    {
                        "title": f"Assignment {seq} - {topic.split( chr(10) )[0].strip()}",
                        "description": f"{assign_en}\n\n{assign_th}",
                        "topic": topic,
                        "difficulty": Difficulty.EASY,  # Force EASY as requested
                        "language": Language.SQL,
                        "starter_code": "-- Write your query here\n",
                        "test_cases": [
                            {
                                "expected_query": assign_ans,
                                "check_order": "ORDER BY" in assign_ans.upper(),
                                "description": "Assignment expected output",
                            }
                        ],
                        "gold_standard": {
                            "solution_code": assign_ans,
                            "explanation": "Assignment solution.",
                        },
                    }
                )

    for pdata in problems_to_create:
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
                    input_data=tc["expected_query"],  # gold-standard query
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
    result = await session.execute(select(User).where(User.email == "student@demo.com"))
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
    logging.getLogger("sqlalchemy.engine").disabled = True
    logging.getLogger("sqlalchemy.engine.Engine").disabled = True
    asyncio.run(seed_database())
