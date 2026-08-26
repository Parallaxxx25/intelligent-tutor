"""
Import the partner platform's problem catalog into our Postgres.

Reads Problem rows directly from the partner's SQLite database file (their
`app/models/problem.py`: id, lesson_id, title, description, difficulty,
solution_query, starter_code — schema_sql/table_name/datasets are their own
per-problem sandbox and are NOT imported, since their 81 problems all share
one schema seeded from the same bikestore_mysql.sql this system's BikeStores
data comes from; see docs/adr/0006-partner-primary-dual-grade.md).

Idempotent — upserts on `Problem.external_problem_id`, so a partner-side
edit to a solution_query is picked up by re-running this, and running it
twice never duplicates rows.

Usage:
    python -m scripts.import_partner_problems --sqlite /path/to/its_sql.db
    python -m scripts.import_partner_problems --sqlite /path/to/its_sql.db --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import async_session_factory, init_db
from backend.db.models import Difficulty, GoldStandard, Language, Problem, TestCase

logger = logging.getLogger(__name__)

# Their Difficulty enum (beginner/intermediate/advanced) -> ours (easy/medium/hard).
_DIFFICULTY_MAP = {
    "beginner": Difficulty.EASY,
    "intermediate": Difficulty.MEDIUM,
    "advanced": Difficulty.HARD,
}

_SELECT_PROBLEMS = """
    SELECT p.id, p.title, p.description, p.difficulty, p.solution_query,
           p.starter_code, l.title AS lesson_title
    FROM problems p
    LEFT JOIN lessons l ON l.id = p.lesson_id
    ORDER BY p.id
"""


def read_partner_problems(sqlite_path: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(_SELECT_PROBLEMS).fetchall()
    finally:
        conn.close()


async def upsert_problem(session: AsyncSession, row: sqlite3.Row) -> str:
    """Returns 'created', 'updated', or 'skipped' (no solution_query)."""
    solution_query = (row["solution_query"] or "").strip()
    if not solution_query:
        logger.warning("Skipping partner problem #%d (%s) — no solution_query.",
                        row["id"], row["title"])
        return "skipped"

    result = await session.execute(
        select(Problem).where(Problem.external_problem_id == row["id"])
    )
    problem = result.scalars().first()

    difficulty = _DIFFICULTY_MAP.get((row["difficulty"] or "").lower(), Difficulty.EASY)
    topic = row["lesson_title"] or "general"
    check_order = "ORDER BY" in solution_query.upper()
    action = "updated"

    if problem is None:
        problem = Problem(
            external_problem_id=row["id"],
            title=row["title"],
            description=row["description"] or "",
            difficulty=difficulty,
            language=Language.SQL,
            topic=topic,
            starter_code=row["starter_code"],
        )
        session.add(problem)
        await session.flush()  # assign problem.id for the TestCase/GoldStandard FKs
        action = "created"
    else:
        problem.title = row["title"]
        problem.description = row["description"] or ""
        problem.difficulty = difficulty
        problem.topic = topic
        problem.starter_code = row["starter_code"]

    tc_result = await session.execute(
        select(TestCase).where(TestCase.problem_id == problem.id)
    )
    test_case = tc_result.scalars().first()
    if test_case is None:
        session.add(
            TestCase(
                problem_id=problem.id,
                input_data=solution_query,
                expected_output=f"Partner gold answer (problem #{row['id']})",
                is_hidden=False,
                order=0,
                check_order=check_order,
            )
        )
    else:
        test_case.input_data = solution_query
        test_case.check_order = check_order

    gs_result = await session.execute(
        select(GoldStandard).where(GoldStandard.problem_id == problem.id)
    )
    gold = gs_result.scalars().first()
    if gold is None:
        session.add(
            GoldStandard(
                problem_id=problem.id,
                solution_code=solution_query,
                explanation=f"Imported from partner platform, problem #{row['id']}.",
            )
        )
    else:
        gold.solution_code = solution_query

    return action


async def import_all(sqlite_path: Path, dry_run: bool) -> None:
    await init_db()
    rows = read_partner_problems(sqlite_path)
    logger.info("Read %d problems from %s", len(rows), sqlite_path)

    counts = {"created": 0, "updated": 0, "skipped": 0}
    async with async_session_factory() as session:
        for row in rows:
            action = await upsert_problem(session, row)
            counts[action] += 1
        if dry_run:
            await session.rollback()
            logger.info("Dry run — rolled back, nothing written.")
        else:
            await session.commit()

    logger.info(
        "Done: %d created, %d updated, %d skipped (of %d read).",
        counts["created"], counts["updated"], counts["skipped"], len(rows),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, type=Path,
                         help="Path to the partner platform's SQLite DB file (its_sql.db).")
    parser.add_argument("--dry-run", action="store_true",
                         help="Read and report counts without writing to Postgres.")
    args = parser.parse_args()

    if not args.sqlite.exists():
        parser.error(f"SQLite file not found: {args.sqlite}")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
    logging.getLogger("sqlalchemy.engine").disabled = True
    asyncio.run(import_all(args.sqlite, args.dry_run))


if __name__ == "__main__":
    main()
