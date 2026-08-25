"""
Tests for backend/db/queries.py — the Postgres reads that feed the
escalation policy's signals (attempt history, topic mastery).

Requires PostgreSQL (see tests/test_api.py's note on ENV=test / a
'_test' database name — same safety fixture, same requirement).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from backend.config import get_settings
from backend.db.database import async_session_factory, engine
from backend.db.models import (
    Base,
    Difficulty,
    ErrorType,
    Language,
    MasteryLevel,
    Problem,
    StudentProgress,
    InteractionHistory,
    User,
)
from backend.db.queries import (
    get_attempt_history,
    get_topic_mastery,
    seconds_since_last_attempt,
)


def _assert_safe_to_wipe() -> None:
    url = get_settings().POSTGRES_URL
    if os.environ.get("ENV") != "test" or "_test" not in url:
        pytest.exit(
            "Refusing to run: tests/test_escalation_data.py drops all tables "
            "against POSTGRES_URL. Set ENV=test and point POSTGRES_URL at a "
            "database whose name contains '_test' before running this file.",
            returncode=1,
        )


@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    _assert_safe_to_wipe()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db():
    async with async_session_factory() as session:
        yield session


async def _make_user(db, username="student1") -> User:
    user = User(username=username, email=f"{username}@example.com", display_name=username)
    db.add(user)
    await db.flush()
    return user


async def _make_problem(db, topic="general", title="P") -> Problem:
    problem = Problem(
        title=title,
        description="desc",
        difficulty=Difficulty.EASY,
        language=Language.SQL,
        topic=topic,
        starter_code="-- Write your query here\n",
    )
    db.add(problem)
    await db.flush()
    return problem


async def _make_interaction(
    db,
    user_id: int,
    problem_id: int,
    *,
    error_type: ErrorType | None,
    hint_level: int | None,
    code: str = "SELECT 1",
    timestamp: datetime | None = None,
) -> InteractionHistory:
    row = InteractionHistory(
        user_id=user_id,
        problem_id=problem_id,
        submitted_code=code,
        grading_passed=False,
        grading_score=0.0,
        error_type=error_type,
        hint_level=hint_level,
        attempt_number=1,
    )
    db.add(row)
    await db.flush()
    if timestamp is not None:
        # timestamp has a server_default; override it directly for tests
        # that need to control dwell-time math.
        row.timestamp = timestamp
        await db.flush()
    return row


class TestGetAttemptHistory:
    @pytest.mark.asyncio
    async def test_empty_for_new_student(self, db) -> None:
        user = await _make_user(db)
        problem = await _make_problem(db)
        await db.commit()

        history = await get_attempt_history(db, user.id, problem.id)
        assert history == []

    @pytest.mark.asyncio
    async def test_returns_oldest_first(self, db) -> None:
        user = await _make_user(db)
        problem = await _make_problem(db)
        await _make_interaction(
            db, user.id, problem.id, error_type=ErrorType.SYNTAX_ERROR, hint_level=1, code="A"
        )
        await _make_interaction(
            db, user.id, problem.id, error_type=ErrorType.JOIN_ERROR, hint_level=2, code="B"
        )
        await db.commit()

        history = await get_attempt_history(db, user.id, problem.id)
        assert [h["submitted_code"] for h in history] == ["A", "B"]
        assert [h["error_type"] for h in history] == ["syntax_error", "join_error"]
        assert [h["hint_level"] for h in history] == [1, 2]

    @pytest.mark.asyncio
    async def test_respects_limit(self, db) -> None:
        user = await _make_user(db)
        problem = await _make_problem(db)
        for i in range(7):
            await _make_interaction(
                db, user.id, problem.id, error_type=None, hint_level=1, code=f"Q{i}"
            )
        await db.commit()

        history = await get_attempt_history(db, user.id, problem.id, limit=3)
        assert len(history) == 3
        # Most recent 3, still oldest-first within that window.
        assert [h["submitted_code"] for h in history] == ["Q4", "Q5", "Q6"]

    @pytest.mark.asyncio
    async def test_excludes_current_interaction_row(self, db) -> None:
        """/api/v1/hint's own not-yet-hinted row already exists in
        interaction_history by the time it reads history -- it must not
        appear as its own prior attempt."""
        user = await _make_user(db)
        problem = await _make_problem(db)
        await _make_interaction(
            db, user.id, problem.id, error_type=ErrorType.SYNTAX_ERROR, hint_level=1, code="A"
        )
        current = await _make_interaction(
            db, user.id, problem.id, error_type=None, hint_level=None, code="B"
        )
        await db.commit()

        history = await get_attempt_history(
            db, user.id, problem.id, exclude_interaction_id=current.id
        )
        assert [h["submitted_code"] for h in history] == ["A"]

    @pytest.mark.asyncio
    async def test_scoped_to_user_and_problem(self, db) -> None:
        user_a = await _make_user(db, "alice")
        user_b = await _make_user(db, "bob")
        problem = await _make_problem(db)
        await _make_interaction(
            db, user_a.id, problem.id, error_type=None, hint_level=1, code="A"
        )
        await _make_interaction(
            db, user_b.id, problem.id, error_type=None, hint_level=1, code="B"
        )
        await db.commit()

        history = await get_attempt_history(db, user_a.id, problem.id)
        assert [h["submitted_code"] for h in history] == ["A"]


class TestSecondsSinceLastAttempt:
    def test_none_when_no_history(self) -> None:
        assert seconds_since_last_attempt([]) is None

    def test_measures_gap_from_most_recent(self) -> None:
        five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        history = [
            {
                "error_type": None,
                "submitted_code": "X",
                "hint_level": 1,
                "timestamp": five_minutes_ago,
            }
        ]
        gap = seconds_since_last_attempt(history)
        assert gap is not None
        assert 290 <= gap <= 310  # ~300s, tolerant of test runtime


class TestGetTopicMastery:
    @pytest.mark.asyncio
    async def test_none_for_unseen_topic(self, db) -> None:
        user = await _make_user(db)
        problem = await _make_problem(db, topic="topic-a")
        await db.commit()

        assert await get_topic_mastery(db, user.id, problem.id) is None

    @pytest.mark.asyncio
    async def test_reads_mastery_from_sibling_problem_same_topic(self, db) -> None:
        user = await _make_user(db)
        practice = await _make_problem(db, topic="shared-topic", title="Practice 1")
        assignment = await _make_problem(db, topic="shared-topic", title="Assignment 1")
        db.add(
            StudentProgress(
                user_id=user.id,
                problem_id=practice.id,
                attempts=2,
                best_score=1.0,
                mastery_level=MasteryLevel.EXPERT,
            )
        )
        await db.commit()

        mastery = await get_topic_mastery(db, user.id, assignment.id)
        assert mastery == MasteryLevel.EXPERT

    @pytest.mark.asyncio
    async def test_excludes_current_problem(self, db) -> None:
        user = await _make_user(db)
        problem = await _make_problem(db, topic="topic-b")
        db.add(
            StudentProgress(
                user_id=user.id,
                problem_id=problem.id,
                attempts=1,
                best_score=1.0,
                mastery_level=MasteryLevel.EXPERT,
            )
        )
        await db.commit()

        # Only progress row is on the current problem itself — must not count.
        assert await get_topic_mastery(db, user.id, problem.id) is None

    @pytest.mark.asyncio
    async def test_different_topics_do_not_mix(self, db) -> None:
        user = await _make_user(db)
        problem_a = await _make_problem(db, topic="topic-a")
        problem_b = await _make_problem(db, topic="topic-b")
        db.add(
            StudentProgress(
                user_id=user.id,
                problem_id=problem_a.id,
                attempts=2,
                best_score=1.0,
                mastery_level=MasteryLevel.EXPERT,
            )
        )
        await db.commit()

        assert await get_topic_mastery(db, user.id, problem_b.id) is None

    @pytest.mark.asyncio
    async def test_returns_max_across_multiple_siblings(self, db) -> None:
        user = await _make_user(db)
        p1 = await _make_problem(db, topic="topic-c", title="P1")
        p2 = await _make_problem(db, topic="topic-c", title="P2")
        current = await _make_problem(db, topic="topic-c", title="Current")
        db.add(
            StudentProgress(
                user_id=user.id, problem_id=p1.id, attempts=3,
                best_score=0.5, mastery_level=MasteryLevel.BEGINNER,
            )
        )
        db.add(
            StudentProgress(
                user_id=user.id, problem_id=p2.id, attempts=2,
                best_score=1.0, mastery_level=MasteryLevel.ADVANCED,
            )
        )
        await db.commit()

        assert await get_topic_mastery(db, user.id, current.id) == MasteryLevel.ADVANCED
