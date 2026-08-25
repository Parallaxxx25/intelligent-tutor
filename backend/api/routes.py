"""
FastAPI API routes for the Intelligent Tutoring System.

Endpoints:
  GET    /api/health              — Health check (Postgres/Redis/Chroma)
  GET    /api/problems            — List all problems
  GET    /api/problems/{id}       — Get problem details with visible test cases
  POST   /api/submit              — Submit code for grading + hints (requires X-API-Key if configured)
  DELETE /api/users/{id}/data     — Erase a student's data (requires X-API-Key if configured)

Version: 2026-02-12
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.agents.escalation_policy import EscalationSignals
from backend.agents.supervisor import (
    run_pipeline_langgraph,
    run_pipeline_deterministic,
    run_pipeline_llm,
)
from backend.api.auth import require_api_key
from backend.config import get_settings
from backend.db.database import get_db
from backend.api.websocket import manager as ws_manager
from backend.db.models import (
    InteractionHistory,
    Problem,
    StudentProgress,
    TestCase,
    User,
)
from backend.db.queries import get_attempt_history, get_topic_mastery, seconds_since_last_attempt
from backend.db.schemas import (
    CodeSubmission,
    ComponentHealth,
    HealthResponse,
    ProblemListItem,
    ProblemResponse,
    SubmissionResponse,
    TestCaseResponse,
)
from backend.memory.redis_session import get_session_manager
from backend.memory.mastery import update_mastery
from backend import metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Tutoring API"])


class PipelineMode(str, Enum):
    """Pipeline execution mode."""

    DETERMINISTIC = "deterministic"
    LLM = "llm"
    LANGGRAPH = "langgraph"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Report Postgres/Redis/Chroma liveness and the embedding fallback rate."""
    from sqlalchemy import text

    # --- Postgres ---------------------------------------------------------
    try:
        await db.execute(text("SELECT 1"))
        postgres = ComponentHealth(status="up")
    except Exception as e:
        postgres = ComponentHealth(status="down", detail=str(e))

    # --- Redis --------------------------------------------------------------
    session_manager = get_session_manager()
    redis_ok = await session_manager.ping()
    redis = ComponentHealth(status="up" if redis_ok else "down")

    # --- Chroma (RAG knowledge base) ----------------------------------------
    from backend.rag.retriever import get_collection

    try:
        collection = get_collection()
        if collection is None:
            chroma = ComponentHealth(status="down", detail="collection not initialized")
        else:
            await run_in_threadpool(collection.count)
            chroma = ComponentHealth(status="up")
    except Exception as e:
        chroma = ComponentHealth(status="down", detail=str(e))

    from backend.rag.retriever import GoogleEmbeddingFunction

    embedding_fallback_rate = GoogleEmbeddingFunction.get_stats()["fallback_rate"]

    overall = "unhealthy" if postgres.status != "up" else (
        "degraded" if redis.status != "up" or chroma.status != "up" else "healthy"
    )

    return HealthResponse(
        status=overall,
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
        postgres=postgres,
        redis=redis,
        chroma=chroma,
        embedding_fallback_rate=embedding_fallback_rate,
    )


@router.get("/metrics")
async def get_metrics() -> dict[str, Any]:
    """In-process latency/fallback counters for this worker process — see
    backend/metrics.py. Not an aggregate across containers; with two
    instances behind the proxy, check both during the lab."""
    return metrics.snapshot()


# ---------------------------------------------------------------------------
# Problems
# ---------------------------------------------------------------------------


@router.get("/problems", response_model=list[ProblemListItem])
async def list_problems(db: AsyncSession = Depends(get_db)) -> Any:
    """Return a list of all available problems."""
    result = await db.execute(select(Problem).order_by(Problem.id))
    problems = result.scalars().all()
    return [ProblemListItem.model_validate(p) for p in problems]


@router.get("/problems/{problem_id}", response_model=ProblemResponse)
async def get_problem(
    problem_id: int,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Return full problem details with visible (non-hidden) test cases."""
    result = await db.execute(
        select(Problem)
        .options(selectinload(Problem.test_cases))
        .where(Problem.id == problem_id)
    )
    problem = result.scalars().first()

    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Problem with id {problem_id} not found.",
        )

    # Filter to visible test cases only
    visible_cases = [
        TestCaseResponse.model_validate(tc)
        for tc in problem.test_cases
        if not tc.is_hidden
    ]

    resp = ProblemResponse.model_validate(problem)
    resp.test_cases = visible_cases
    return resp


# ---------------------------------------------------------------------------
# Submit code
# ---------------------------------------------------------------------------


async def _recent_struggles(db: AsyncSession, user_id: int, limit: int = 3) -> str:
    """
    This student's most recent failed attempts, formatted for the hint prompt.

    Recency beats semantic similarity here: a student has tens of rows, not
    thousands, so "what did they just get wrong" is the signal worth having.
    """
    result = await db.execute(
        select(InteractionHistory.error_type, InteractionHistory.hint_text)
        .where(
            InteractionHistory.user_id == user_id,
            InteractionHistory.grading_passed.is_(False),
        )
        .order_by(InteractionHistory.id.desc())
        .limit(limit)
    )
    return "\n".join(
        f"- {error_type.value if error_type else 'unknown'} error (past attempt): "
        f"{(hint_text or '')[:300]}"
        for error_type, hint_text in result.all()
    )


@router.post(
    "/submit",
    response_model=SubmissionResponse,
    dependencies=[Depends(require_api_key)],
)
async def submit_code(
    body: CodeSubmission,
    db: AsyncSession = Depends(get_db),
    mode: PipelineMode = Query(
        default=None,
        description="Pipeline mode: 'deterministic' (rule-based) or 'llm' (Gemini-powered).",
    ),
) -> Any:
    """
    Submit student code to the tutoring pipeline.

    1. Validate user and problem exist
    2. Fetch test cases
    3. Run the deterministic pipeline (Grader → Diagnostician → Tutor)
    4. Log the interaction
    5. Update student progress
    6. Return the full result
    """
    # --- Validate user --------------------------------------------------
    user_result = await db.execute(select(User).where(User.id == body.user_id))
    user = user_result.scalars().first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {body.user_id} not found.",
        )

    # --- Validate problem -----------------------------------------------
    prob_result = await db.execute(
        select(Problem)
        .options(selectinload(Problem.test_cases))
        .where(Problem.id == body.problem_id)
    )
    problem = prob_result.scalars().first()
    if problem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Problem with id {body.problem_id} not found.",
        )

    # --- Get attempt count ----------------------------------------------
    progress_result = await db.execute(
        select(StudentProgress).where(
            StudentProgress.user_id == body.user_id,
            StudentProgress.problem_id == body.problem_id,
        )
    )
    progress = progress_result.scalars().first()

    # --- Load Redis session (Phase 3) ------------------------------------
    session_manager = get_session_manager()
    session = await session_manager.get_session(body.user_id, body.problem_id)

    # Use the session's attempt count if it's more up-to-date (Redis hash
    # values are strings).
    session_attempts = int(session.get("attempts") or 0)
    db_attempts = progress.attempts if progress else 0
    attempt_count = max(db_attempts, session_attempts) + 1

    # --- Build test case list -------------------------------------------
    test_cases_for_runner = [
        {
            "test_case_id": tc.id,
            "input_data": tc.input_data,
            "expected_output": tc.expected_output,
            "check_order": tc.check_order,
        }
        for tc in problem.test_cases
    ]

    # --- Build escalation signals (see docs/hint-escalation-policy-v2.md) ---
    # error_type/current_query for *this* attempt aren't known yet (the
    # classifier hasn't run) — the pipeline fills those in from its own
    # classification via dataclasses.replace before deciding the level.
    history = await get_attempt_history(db, body.user_id, body.problem_id)
    topic_mastery = await get_topic_mastery(db, body.user_id, body.problem_id)
    signals = EscalationSignals(
        attempt_count=attempt_count,
        error_type_history=tuple(h["error_type"] for h in history),
        query_history=tuple(h["submitted_code"] for h in history),
        hint_level_history=tuple(
            h["hint_level"] for h in history if h["hint_level"] is not None
        ),
        seconds_since_prev=seconds_since_last_attempt(history),
        topic_mastery=topic_mastery.value if topic_mastery else None,
        starter_code=problem.starter_code,
    )

    # --- Resolve pipeline mode -----------------------------------------
    settings = get_settings()
    effective_mode = mode or PipelineMode(settings.DEFAULT_PIPELINE_MODE)

    logger.info(
        "Running pipeline (%s): user=%d, problem=%d, attempt=%d",
        effective_mode.value,
        body.user_id,
        body.problem_id,
        attempt_count,
    )

    # --- Run pipeline ---------------------------------------------------
    session_id_str = f"{body.user_id}:{body.problem_id}"
    await ws_manager.send_event(session_id_str, {"event": "grading_started"})

    _pipeline_start = time.perf_counter()

    if effective_mode == PipelineMode.LLM:
        # Extract gold-standard query for output guardrails
        gold_standard = ""
        if problem.test_cases:
            gold_standard = problem.test_cases[0].input_data or ""

        pipeline_result = await run_in_threadpool(
            run_pipeline_llm,
            submission=body,
            problem_description=problem.description,
            problem_topic=problem.topic,
            test_cases=test_cases_for_runner,
            attempt_count=attempt_count,
            gold_standard_query=gold_standard,
            schema_info=None,  # TODO: extract from problem metadata
            past_struggles=await _recent_struggles(db, body.user_id),
            signals=signals,
        )
    elif effective_mode == PipelineMode.LANGGRAPH:
        pipeline_result = await run_in_threadpool(
            run_pipeline_langgraph,
            submission=body,
            problem_description=problem.description,
            problem_topic=problem.topic,
            test_cases=test_cases_for_runner,
            attempt_count=attempt_count,
            signals=signals,
        )
    else:
        pipeline_result = await run_in_threadpool(
            run_pipeline_deterministic,
            submission=body,
            problem_description=problem.description,
            problem_topic=problem.topic,
            test_cases=test_cases_for_runner,
            attempt_count=attempt_count,
            signals=signals,
        )

    _pipeline_elapsed = time.perf_counter() - _pipeline_start
    # This endpoint runs grade+diagnose+hint as one call — until the
    # /grade + /hint split lands, grade_latency_seconds is the whole
    # pipeline's time, not grading alone. Real once split.
    metrics.record_grade_latency(_pipeline_elapsed)
    if pipeline_result.hint:
        metrics.record_hint_latency(_pipeline_elapsed, pipeline_result.hint.source)

    await ws_manager.send_event(
        session_id_str,
        {
            "event": "grading_complete",
            "score": pipeline_result.grading.score,
            "passed": pipeline_result.grading.passed,
        },
    )

    if pipeline_result.diagnosis:
        await ws_manager.send_event(
            session_id_str,
            {
                "event": "diagnosis_complete",
                "error_type": pipeline_result.diagnosis.error_type,
            },
        )

    if pipeline_result.hint:
        await ws_manager.send_event(
            session_id_str,
            {"event": "hint_ready", "hint_level": pipeline_result.hint.hint_level},
        )

    # --- Log interaction ------------------------------------------------
    interaction = InteractionHistory(
        user_id=body.user_id,
        problem_id=body.problem_id,
        submitted_code=body.code,
        grading_passed=pipeline_result.overall_passed,
        grading_score=pipeline_result.grading.score,
        grading_details=pipeline_result.grading.model_dump_json(),
        error_type=(
            pipeline_result.diagnosis.error_type if pipeline_result.diagnosis else None
        ),
        diagnosis_details=(
            pipeline_result.diagnosis.model_dump_json()
            if pipeline_result.diagnosis
            else None
        ),
        hint_level=(pipeline_result.hint.hint_level if pipeline_result.hint else None),
        hint_text=(pipeline_result.hint.hint_text if pipeline_result.hint else None),
    )
    db.add(interaction)
    await db.flush()

    pipeline_result.submission_id = interaction.id

    # --- Update student progress & mastery ------------------------------
    if progress is None:
        progress = StudentProgress(
            user_id=body.user_id,
            problem_id=body.problem_id,
            attempts=1,
            best_score=pipeline_result.grading.score,
            last_attempt_at=datetime.now(timezone.utc),
        )
        db.add(progress)
    else:
        progress.attempts = attempt_count
        progress.best_score = max(progress.best_score, pipeline_result.grading.score)
        progress.last_attempt_at = datetime.now(timezone.utc)

    # Apply mastery logic (Phase 3)
    update_mastery(progress, pipeline_result.grading.score, attempt_count)

    # --- Update Redis session -------------------------------------------
    if pipeline_result.overall_passed:
        # Clear short-term memory upon success
        await session_manager.clear_session(body.user_id, body.problem_id)
    else:
        # Save state for the next escalation
        await session_manager.update_session(
            body.user_id,
            body.problem_id,
            {
                "attempts": attempt_count,
                "last_error_type": (
                    pipeline_result.diagnosis.error_type
                    if pipeline_result.diagnosis
                    else None
                ),
                "last_hint_level": (
                    pipeline_result.hint.hint_level if pipeline_result.hint else None
                ),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
        )

    # Long-term memory needs no separate write — the interaction_history row
    # added above is the record `_recent_struggles` reads back.

    logger.info(
        "Pipeline complete: passed=%s, score=%.2f, hint_level=%s",
        pipeline_result.overall_passed,
        pipeline_result.grading.score,
        pipeline_result.hint.hint_level if pipeline_result.hint else "N/A",
    )

    return pipeline_result


# ---------------------------------------------------------------------------
# Delete-my-data
# ---------------------------------------------------------------------------


@router.delete("/users/{user_id}/data", dependencies=[Depends(require_api_key)])
async def delete_user_data(user_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """
    Erase a student's data everywhere it's stored: Postgres (account +
    interaction/progress history, cascade-deleted with the user row) and Redis
    (any live session hashes).
    """
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalars().first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {user_id} not found.",
        )

    await db.delete(user)  # ON DELETE CASCADE clears student_progress + interaction_history

    session_manager = get_session_manager()
    redis_deleted = await session_manager.clear_user_sessions(user_id)

    logger.info(
        "Deleted all data for user %d (redis_sessions=%d)", user_id, redis_deleted
    )

    return {
        "status": "deleted",
        "user_id": user_id,
        "redis_sessions_deleted": redis_deleted,
    }


# ---------------------------------------------------------------------------
# Debug endpoints for Streamlit Playground
# ---------------------------------------------------------------------------
# Dev-only: 404 unless DEBUG is set, and still gated by the API key when one
# is configured. These expose raw session/vector-store contents and an
# unrestricted SQL execution hole — never enable DEBUG in a reachable deploy.


async def _require_debug_mode() -> None:
    if not get_settings().DEBUG:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


_debug_dependencies = [Depends(_require_debug_mode), Depends(require_api_key)]


@router.get(
    "/debug/memory/redis/{user_id}/{problem_id}",
    dependencies=_debug_dependencies,
)
async def get_redis_memory(user_id: int, problem_id: int):
    session_manager = get_session_manager()
    session = await session_manager.get_session(user_id, problem_id)
    return session


@router.get("/debug/memory/history/{user_id}", dependencies=_debug_dependencies)
async def get_history_memory(
    user_id: int, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Long-term memory viewer: this student's recent interaction_history rows."""
    result = await db.execute(
        select(InteractionHistory)
        .where(InteractionHistory.user_id == user_id)
        .order_by(InteractionHistory.id.desc())
        .limit(20)
    )
    return {
        "status": "success",
        "records": [
            {
                "id": r.id,
                "problem_id": r.problem_id,
                "submitted_code": r.submitted_code,
                "passed": r.grading_passed,
                "error_type": r.error_type.value if r.error_type else None,
                "hint_level": r.hint_level,
                "hint_text": r.hint_text,
            }
            for r in result.scalars().all()
        ],
    }


@router.post("/debug/execute_sql", dependencies=_debug_dependencies)
def debug_execute_sql(query: str = Query(...)):
    from backend.tools.code_executor import execute_sql

    try:
        res = execute_sql(query=query)
        return res
    except Exception as e:
        return {"error_message": str(e)}
