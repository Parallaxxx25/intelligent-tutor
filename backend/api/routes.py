"""
FastAPI API routes for the Intelligent Tutoring System.

Endpoints:
  GET  /api/health          — Health check
  GET  /api/problems        — List all problems
  GET  /api/problems/{id}   — Get problem details with visible test cases
  POST /api/submit          — Submit code for grading + hints

Version: 2026-02-12
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.agents.supervisor import run_pipeline_langgraph, run_pipeline_deterministic, run_pipeline_llm
from backend.config import get_settings
from backend.db.database import get_db
from backend.db.models import (
    InteractionHistory,
    Problem,
    StudentProgress,
    TestCase,
    User,
)
from backend.db.schemas import (
    CodeSubmission,
    HealthResponse,
    ProblemListItem,
    ProblemResponse,
    SubmissionResponse,
    TestCaseResponse,
)
from backend.memory.redis_session import get_session_manager
from backend.memory.long_term import get_long_term_memory
from backend.memory.mastery import get_mastery_tracker

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
async def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(
        status="healthy",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc),
    )


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

@router.post("/submit", response_model=SubmissionResponse)
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
    
    # Use the session's attempt count if it's more up-to-date
    session_attempts = session.get("attempts", 0)
    db_attempts = progress.attempts if progress else 0
    attempt_count = max(db_attempts, session_attempts) + 1

    # --- Build test case list -------------------------------------------
    test_cases_for_runner = [
        {
            "test_case_id": tc.id,
            "input_data": tc.input_data,
            "expected_output": tc.expected_output,
        }
        for tc in problem.test_cases
    ]

    # --- Resolve pipeline mode -----------------------------------------
    settings = get_settings()
    effective_mode = mode or PipelineMode(settings.DEFAULT_PIPELINE_MODE)

    logger.info(
        "Running pipeline (%s): user=%d, problem=%d, attempt=%d",
        effective_mode.value, body.user_id, body.problem_id, attempt_count,
    )

    # --- Run pipeline ---------------------------------------------------
    if effective_mode == PipelineMode.LLM:
        # Extract gold-standard query for output guardrails
        gold_standard = ""
        if problem.test_cases:
            gold_standard = problem.test_cases[0].input_data or ""

        pipeline_result = run_pipeline_llm(
            submission=body,
            problem_description=problem.description,
            problem_topic=problem.topic,
            test_cases=test_cases_for_runner,
            attempt_count=attempt_count,
            gold_standard_query=gold_standard,
            schema_info=None,  # TODO: extract from problem metadata
        )
    elif effective_mode == PipelineMode.LANGGRAPH:
        pipeline_result = run_pipeline_langgraph(
            submission=body,
            problem_description=problem.description,
            problem_topic=problem.topic,
            test_cases=test_cases_for_runner,
            attempt_count=attempt_count,
        )
    else:
        pipeline_result = run_pipeline_deterministic(
            submission=body,
            problem_description=problem.description,
            problem_topic=problem.topic,
            test_cases=test_cases_for_runner,
            attempt_count=attempt_count,
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
            pipeline_result.diagnosis.error_type
            if pipeline_result.diagnosis
            else None
        ),
        diagnosis_details=(
            pipeline_result.diagnosis.model_dump_json()
            if pipeline_result.diagnosis
            else None
        ),
        hint_level=(
            pipeline_result.hint.hint_level
            if pipeline_result.hint
            else None
        ),
        hint_text=(
            pipeline_result.hint.hint_text
            if pipeline_result.hint
            else None
        ),
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
    mastery_tracker = get_mastery_tracker()
    await mastery_tracker.update_mastery(
        db, 
        body.user_id, 
        body.problem_id, 
        pipeline_result.grading.score, 
        attempt_count,
        topic=problem.topic
    )

    # --- Update Persistence & State (Phase 3) ---------------------------
    # 1. Update Redis session
    if pipeline_result.overall_passed:
        # Clear short-term memory upon success
        await session_manager.clear_session(body.user_id, body.problem_id)
    else:
        # Save state for the next escalation
        await session_manager.update_session(body.user_id, body.problem_id, {
            "attempts": attempt_count,
            "last_error_type": (
                pipeline_result.diagnosis.error_type if pipeline_result.diagnosis else None
            ),
            "last_hint_level": (
                pipeline_result.hint.hint_level if pipeline_result.hint else None
            ),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })

    # 2. Store in Long-term memory
    try:
        ltm = get_long_term_memory()
        ltm.store_interaction(
            user_id=body.user_id,
            problem_id=body.problem_id,
            code=body.code,
            error_type=(
                pipeline_result.diagnosis.error_type if pipeline_result.diagnosis else "none"
            ),
            hint_text=(
                pipeline_result.hint.hint_text if pipeline_result.hint else "none"
            ),
            interaction_id=interaction.id,
        )
    except Exception as e:
        logger.warning("Could not store interaction in LTM: %s", e)

    logger.info(
        "Pipeline complete: passed=%s, score=%.2f, hint_level=%s",
        pipeline_result.overall_passed,
        pipeline_result.grading.score,
        pipeline_result.hint.hint_level if pipeline_result.hint else "N/A",
    )

    return pipeline_result
