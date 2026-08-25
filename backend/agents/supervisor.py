"""
Supervisor / Graph Coordinator — Orchestrates the SQL tutoring pipeline.

Manages the sequential flow:
    Grader → Diagnostician → Tutor

The Supervisor builds a LangGraph StateGraph with sequential edges and
provides the ``run_pipeline`` entry points used by the API layer.

Version: 2026-03-20 (LangGraph migration)
"""

from __future__ import annotations

import dataclasses
import json
from langsmith import traceable
import logging
import time
from datetime import datetime, timezone
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from backend import metrics
from backend.agents.diagnostician import diagnose_errors
from backend.agents.escalation_policy import EscalationSignals, decide_hint_level
from backend.agents.few_shot_examples import DIAGNOSIS_FEW_SHOT, HINT_FEW_SHOT
from backend.agents.tutor import generate_hint
from backend.config import get_settings
from backend.db.schemas import (
    CodeSubmission,
    DiagnosisResult,
    ErrorTypeEnum,
    GradingResult,
    HintResponse,
    SubmissionResponse,
    TestCaseResult,
)
from backend.tools.error_classifier import classify_sql_error
from backend.tools.hint_generator import generate_sql_hint
from backend.tools.test_runner import run_sql_tests

logger = logging.getLogger(__name__)


def _prepend_dialect_note(hint_text: str, dialect_note: str | None) -> str:
    """Prefix a hint with the MySQL-vs-Postgres dialect note when set.
    Never changes the verdict — this only affects hint wording."""
    if not dialect_note:
        return hint_text
    return f"{dialect_note}\n\n{hint_text}"


# ---------------------------------------------------------------------------
# Pipeline (deterministic, no LLM required)
# ---------------------------------------------------------------------------


@traceable(name="Deterministic Pipeline")
def run_pipeline_deterministic(
    submission: CodeSubmission,
    problem_description: str,
    problem_topic: str,
    test_cases: list[dict[str, Any]],
    attempt_count: int = 1,
    signals: EscalationSignals | None = None,
) -> SubmissionResponse:
    """
    Run the full SQL tutoring pipeline **without** calling the LLM.

    This is the fast, deterministic path used in Phase 1. The pipeline
    executes the student SQL query, classifies errors, and generates
    hints using only the rule-based tools.

    Args:
        submission: The student's SQL submission.
        problem_description: Text description of the problem.
        problem_topic: Topic tag (e.g. "JOINs", "Aggregation").
        test_cases: List of test case dicts with ``expected_query`` keys.
        attempt_count: Number of times the student has attempted this problem.
        signals: Attempt/error history, topic mastery, dwell time — built
            by the caller from Postgres (see backend/db/queries.py). None
            degrades to the v1 attempt-count-only fallback. error_type and
            current_query are always overridden below from this attempt's
            own classification, regardless of what the caller supplied.

    Returns:
        A fully-populated ``SubmissionResponse``.
    """
    start_time = time.perf_counter()

    # --- Step 1: Grade --------------------------------------------------
    logger.info(
        "Pipeline step 1/3: Grading SQL submission for problem %d",
        submission.problem_id,
    )

    # Convert test cases to the format expected by run_sql_tests
    sql_test_cases = [
        {
            "test_case_id": tc.get("test_case_id", idx),
            "expected_query": tc[
                "input_data"
            ],  # gold-standard query stored in input_data
            "check_order": tc.get("check_order", False),
        }
        for idx, tc in enumerate(test_cases)
    ]

    grading_raw = run_sql_tests(submission.code, sql_test_cases)

    grading = GradingResult(
        passed=grading_raw["passed"],
        score=grading_raw["score"],
        total_tests=grading_raw["total_tests"],
        passed_tests=grading_raw["passed_tests"],
        test_results=[
            TestCaseResult(
                **{
                    "test_case_id": tr["test_case_id"],
                    "passed": tr["passed"],
                    "error_message": tr.get("error_message"),
                    "label_mismatch": tr.get("label_mismatch", False),
                    "diff_summary": tr.get("diff_summary"),
                    "actual_columns": tr.get("actual_columns"),
                    "actual_row_count": tr.get("actual_row_count"),
                }
            )
            for tr in grading_raw["test_results"]
        ],
        student_error=grading_raw.get("student_error"),
        student_error_type=grading_raw.get("student_error_type"),
    )

    # --- Step 2: Diagnose -----------------------------------------------
    logger.info("Pipeline step 2/3: Diagnosing SQL errors")

    # Prepare failed test details for classifier
    failed_details = json.dumps(
        [tr for tr in grading_raw["test_results"] if not tr["passed"]],
        indent=2,
        default=str,
    )

    classification = classify_sql_error(
        error_message=grading_raw.get("student_error") or "",
        error_type_hint=grading_raw.get("student_error_type") or "",
        all_tests_passed=grading.passed,
        failed_test_details=failed_details,
        student_query=submission.code,
    )

    # Determine hint level via the v2 escalation policy (see
    # backend/agents/escalation_policy.py + docs/hint-escalation-policy-v2.md).
    resolved_signals = dataclasses.replace(
        signals or EscalationSignals(attempt_count=attempt_count),
        error_type=classification.error_type,
        current_query=submission.code,
    )
    decision = decide_hint_level(resolved_signals)
    recommended_level = decision.level

    diagnosis = DiagnosisResult(
        error_type=ErrorTypeEnum(classification.error_type),
        error_message=classification.error_message,
        problematic_clause=classification.problematic_clause,
        severity=classification.severity,
        recommended_hint_level=recommended_level,
        pedagogical_rationale=(
            f"Attempt {attempt_count}. Error type {classification.error_type} "
            f"(clause: {classification.problematic_clause}), "
            f"{classification.severity} severity. {decision.rationale()}"
        ),
        dialect_note=classification.dialect_note,
        escalation_trace=decision.as_dict(),
    )

    # --- Step 3: Generate hint (skip if all passed) ---------------------
    hint: HintResponse | None = None
    if not grading.passed:
        logger.info("Pipeline step 3/3: Generating hint at level %d", recommended_level)
        hint_raw = generate_sql_hint(
            error_type=classification.error_type,
            error_message=classification.error_message,
            student_query=submission.code,
            attempt_count=attempt_count,
            problem_description=problem_description,
            problematic_clause=classification.problematic_clause,
            hint_level=recommended_level,
        )
        hint = HintResponse(
            hint_level=hint_raw["hint_level"],
            hint_text=_prepend_dialect_note(hint_raw["hint_text"], classification.dialect_note),
            hint_type=hint_raw.get("hint_type", "text"),
            pedagogical_rationale=hint_raw.get("pedagogical_rationale"),
            follow_up_question=hint_raw.get("follow_up_question"),
        )
    else:
        logger.info("Pipeline step 3/3: All tests passed — no hint needed")

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)

    return SubmissionResponse(
        submission_id=0,  # Filled by the API layer after DB insert
        grading=grading,
        diagnosis=diagnosis if not grading.passed else None,
        hint=hint,
        overall_passed=grading.passed,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# LangGraph pipeline
# ---------------------------------------------------------------------------


class PipelineState(TypedDict, total=False):
    """Shared state passed through the LangGraph tutoring pipeline."""

    student_code: str
    grading_raw: dict
    grading_results_str: str
    attempt_count: int
    problem_description: str
    problem_topic: str
    escalation_signals: Any  # EscalationSignals | None, built by the caller
    # Set by diagnostician node
    classification: Any
    diagnosis_error_type: str
    diagnosis_error_message: str
    diagnosis_problematic_clause: str | None
    diagnosis_severity: str
    diagnosis_dialect_note: str | None
    recommended_hint_level: int
    pedagogical_rationale: str
    escalation_trace: dict
    # Set by tutor node
    hint_raw: dict
    hint_text: str


def build_tutoring_graph() -> Any:
    """
    Build and compile the LangGraph tutoring pipeline.

    Graph:  diagnose → tutor → END
    """
    graph = StateGraph(PipelineState)

    graph.add_node("diagnose", diagnose_errors)
    graph.add_node("tutor", generate_hint)

    graph.set_entry_point("diagnose")
    graph.add_edge("diagnose", "tutor")
    graph.add_edge("tutor", END)

    return graph.compile()


@traceable(name="LangGraph Pipeline")
def run_pipeline_langgraph(
    submission: CodeSubmission,
    problem_description: str,
    problem_topic: str,
    test_cases: list[dict[str, Any]],
    attempt_count: int = 1,
    signals: EscalationSignals | None = None,
) -> SubmissionResponse:
    """
    Run the SQL tutoring pipeline using LangGraph.

    ``signals``: attempt/error history, topic mastery, dwell time — built
    by the caller from Postgres. None degrades to the v1 fallback rule
    inside the diagnostician node (see backend/agents/diagnostician.py).
    """
    start_time = time.perf_counter()

    logger.info("LangGraph Pipeline step 1: Grading SQL submission")

    sql_test_cases = [
        {
            "test_case_id": tc.get("test_case_id", idx),
            "expected_query": tc["input_data"],
            "check_order": tc.get("check_order", False),
        }
        for idx, tc in enumerate(test_cases)
    ]

    grading_raw = run_sql_tests(submission.code, sql_test_cases)

    grading = GradingResult(
        passed=grading_raw["passed"],
        score=grading_raw["score"],
        total_tests=grading_raw["total_tests"],
        passed_tests=grading_raw["passed_tests"],
        test_results=[
            TestCaseResult(
                **{
                    "test_case_id": tr["test_case_id"],
                    "passed": tr["passed"],
                    "error_message": tr.get("error_message"),
                    "label_mismatch": tr.get("label_mismatch", False),
                    "diff_summary": tr.get("diff_summary"),
                    "actual_columns": tr.get("actual_columns"),
                    "actual_row_count": tr.get("actual_row_count"),
                }
            )
            for tr in grading_raw["test_results"]
        ],
        student_error=grading_raw.get("student_error"),
        student_error_type=grading_raw.get("student_error_type"),
    )

    if grading.passed:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return SubmissionResponse(
            submission_id=0,
            grading=grading,
            diagnosis=None,
            hint=HintResponse(
                hint_level=0,
                hint_text=(
                    "Great job! Your SQL query is correct and returns the expected "
                    "results. Well done!"
                ),
                hint_type="text",
                pedagogical_rationale="Positive reinforcement for correct SQL query.",
                follow_up_question=(
                    "Can you think of a way to write this query differently?"
                ),
            ),
            overall_passed=True,
            timestamp=datetime.now(timezone.utc),
        )

    logger.info("LangGraph Pipeline step 2: Diagnosing and Tutoring with LangGraph")

    # Build and invoke the graph
    compiled_graph = build_tutoring_graph()
    graph_output = compiled_graph.invoke(
        {
            "student_code": submission.code,
            "grading_raw": grading_raw,
            "grading_results_str": json.dumps(grading_raw, indent=2),
            "attempt_count": attempt_count,
            "problem_description": problem_description,
            "problem_topic": problem_topic,
            "escalation_signals": signals,
        }
    )

    # Build structured response from graph output
    dialect_note = graph_output.get("diagnosis_dialect_note")
    diagnosis = DiagnosisResult(
        error_type=ErrorTypeEnum(graph_output["diagnosis_error_type"]),
        error_message=graph_output["diagnosis_error_message"],
        problematic_clause=graph_output.get("diagnosis_problematic_clause"),
        severity=graph_output.get("diagnosis_severity", "medium"),
        recommended_hint_level=graph_output.get("recommended_hint_level", 1),
        pedagogical_rationale=graph_output.get(
            "pedagogical_rationale", "Generated by LangGraph pipeline."
        ),
        dialect_note=dialect_note,
        escalation_trace=graph_output.get("escalation_trace"),
    )

    hint_raw = graph_output.get("hint_raw", {})
    hint = HintResponse(
        hint_level=hint_raw.get(
            "hint_level", graph_output.get("recommended_hint_level", 1)
        ),
        hint_text=_prepend_dialect_note(
            graph_output.get("hint_text", str(graph_output)), dialect_note
        ),
        hint_type=hint_raw.get("hint_type", "text"),
        pedagogical_rationale=hint_raw.get(
            "pedagogical_rationale", "Generated by LangGraph pipeline."
        ),
        follow_up_question=hint_raw.get("follow_up_question"),
    )

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
    logger.info("LangGraph Pipeline complete in %dms", elapsed_ms)

    return SubmissionResponse(
        submission_id=0,
        grading=grading,
        diagnosis=diagnosis,
        hint=hint,
        overall_passed=grading.passed,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# LLM-powered pipeline (Phase 2)
# ---------------------------------------------------------------------------


@traceable(name="Diagnose and Hint")
def diagnose_and_hint(
    student_code: str,
    grading_raw: dict[str, Any],
    problem_description: str,
    problem_topic: str,
    attempt_count: int = 1,
    gold_standard_query: str = "",
    schema_info: dict[str, Any] | None = None,
    past_struggles: str = "",
    signals: EscalationSignals | None = None,
) -> tuple[DiagnosisResult, HintResponse]:
    """
    Gemini diagnosis + hint generation for an already-graded, already-failed
    submission — the part of the LLM pipeline that actually needs Gemini.

    Pulled out of ``run_pipeline_llm`` so ``/api/v1/hint`` can call this
    without holding a DB session across the Gemini call: the caller reads
    what it needs (this student's grading_raw, problem text, attempt count),
    releases its session, calls this function, then reacquires a session
    only to persist the result. This function itself touches no DB session.

    ``signals``: attempt/error history, topic mastery, dwell time — built
    by the caller from Postgres. None degrades to the v1 attempt-count-only
    fallback. The v2 policy (backend/agents/escalation_policy.py) is
    authoritative for the level actually served; Gemini's own proposed
    level is still requested and recorded in the trace as
    ``llm_proposed_level`` (a reportable agreement-rate datum), never used
    to raise or lower what's served — see ADR-0005.

    Never call this for a passing submission — callers own the
    "all tests passed" short-circuit, same as run_pipeline_llm did.
    """
    from backend.guardrails import validate_input, validate_output
    from backend.llm import generate_response, generate_structured_response
    from backend.rag.retriever import retrieve_relevant_context

    # Run rule-based classifier first for baseline
    failed_details = json.dumps(
        [tr for tr in grading_raw["test_results"] if not tr["passed"]],
        indent=2,
        default=str,
    )

    classification = classify_sql_error(
        error_message=grading_raw.get("student_error") or "",
        error_type_hint=grading_raw.get("student_error_type") or "",
        all_tests_passed=False,
        failed_test_details=failed_details,
        student_query=student_code,
    )

    resolved_signals = dataclasses.replace(
        signals or EscalationSignals(attempt_count=attempt_count),
        error_type=classification.error_type,
        current_query=student_code,
    )
    decision = decide_hint_level(resolved_signals)
    base_rec_level = decision.level

    # student_code is about to be embedded verbatim into a Gemini prompt —
    # gate that here rather than at the caller, since this is the only
    # place in the codebase that actually builds that prompt. run_pipeline_llm
    # also checks input guardrails earlier (before grading even runs) and
    # short-circuits to the deterministic pipeline first, so this is a
    # no-op there; for /api/v1/hint (which never sees the raw submission
    # before this point) it's the only gate.
    input_check = validate_input(student_code)
    if not input_check.passed:
        logger.warning("Input guardrails failed on hint request: %s", input_check.violations)
        metrics.record_hint_fallback("guardrail")
        diagnosis = DiagnosisResult(
            error_type=ErrorTypeEnum(classification.error_type),
            error_message=classification.error_message,
            problematic_clause=classification.problematic_clause,
            severity=classification.severity,
            recommended_hint_level=base_rec_level,
            pedagogical_rationale=(
                "Rule-based diagnosis (input guardrail rejected the request). "
                f"{decision.rationale()}"
            ),
            dialect_note=classification.dialect_note,
            escalation_trace=decision.as_dict(),
        )
        hint_raw = generate_sql_hint(
            error_type=classification.error_type,
            error_message=classification.error_message,
            student_query=student_code,
            attempt_count=attempt_count,
            problem_description=problem_description,
            problematic_clause=classification.problematic_clause,
            hint_level=base_rec_level,
        )
        hint = HintResponse(
            hint_level=hint_raw["hint_level"],
            hint_text=_prepend_dialect_note(hint_raw["hint_text"], classification.dialect_note),
            hint_type=hint_raw.get("hint_type", "text"),
            pedagogical_rationale=hint_raw.get("pedagogical_rationale"),
            follow_up_question=hint_raw.get("follow_up_question"),
            source="rule_based",
            fallback_reason="guardrail",
        )
        return diagnosis, hint

    # Retrieve relevant SQL concept context
    rag_query = (
        f"SQL error: {classification.error_type}. "
        f"Student query: {student_code}. "
        f"Error: {classification.error_message}"
    )
    rag_context = retrieve_relevant_context(
        query=rag_query,
        error_type=classification.error_type,
        n_results=3,
    )

    # Course-grounded slide context (DB66 lab decks) — additive to the curated
    # KB above, not a replacement. Never allowed to fail the pipeline: any
    # error here just means the hint loses slide citations, same fallback
    # contract as the curated RAG call.
    settings = get_settings()
    slide_context: list[dict[str, Any]] = []
    if settings.SLIDE_RAG_ENABLED:
        try:
            from backend.rag.slide_retriever import search_slides

            slide_context = search_slides(
                query=rag_query,
                error_type=classification.error_type,
                n_results=settings.SLIDE_RAG_N_RESULTS,
            )
        except Exception as e:
            logger.warning("Slide RAG retrieval failed (non-fatal): %s", e)

    combined_context = rag_context + slide_context
    rag_text = (
        "\n\n".join(f"### {doc['title']}\n{doc['content']}" for doc in combined_context)
        if combined_context
        else "No additional SQL reference available."
    )

    # This student's own recent failed attempts, for personalization (e.g.
    # "keeps missing GROUP BY"). Read from interaction_history by the caller
    # and passed in, because this function is sync and has no DB session.
    past_struggles_text = past_struggles

    if slide_context:
        rag_text += (
            "\n\nNote: excerpts citing 'DB66 LAB' come from the student's own course "
            "slides, which teach Oracle SQL against a different practice schema "
            "(employees/departments/locations). Use them only to explain the underlying "
            "concept and cite the slide — never name those tables/columns; the student's "
            "database is PostgreSQL with the BikeStores schema."
        )

    # Use Gemini to produce a richer diagnosis
    try:
        diagnosis_schema = {
            "error_type": "string (one of: syntax_error, column_error, relation_error, join_error, aggregation_error, subquery_error, type_error, ambiguity_error, logic_error, runtime_error, timeout_error)",
            "error_message": "string — clear explanation of the error",
            "problematic_clause": "string — SQL clause causing the issue (SELECT, FROM, WHERE, JOIN, GROUP BY, HAVING, ORDER BY)",
            "severity": "string — low, medium, or high",
            "recommended_hint_level": "integer 1-4",
            "pedagogical_rationale": "string — why this hint level",
        }

        rec_level = base_rec_level

        diagnosis_prompt = (
            f"You are an expert SQL diagnostician. Analyse this student's SQL error.\n\n"
            f"{DIAGNOSIS_FEW_SHOT}\n"
            f"NOW ANALYSE THIS CASE:\n\n"
            f"STUDENT QUERY:\n```sql\n{student_code}\n```\n\n"
            f"ERROR MESSAGE: {classification.error_message}\n"
            f"RULE-BASED CLASSIFICATION: {classification.error_type}\n"
            f"PROBLEMATIC CLAUSE: {classification.problematic_clause or 'unknown'}\n"
            f"FAILED TESTS:\n{failed_details}\n\n"
            f"PROBLEM: {problem_description}\n"
            f"TOPIC: {problem_topic}\n"
            f"ATTEMPT NUMBER: {attempt_count}\n"
            f"RECOMMENDED HINT LEVEL: {rec_level}\n\n"
            f"RELEVANT SQL CONCEPTS:\n{rag_text}\n\n"
            f"Provide a detailed but concise diagnosis. Be specific about what's wrong."
        )

        llm_diagnosis = generate_structured_response(
            prompt=diagnosis_prompt,
            response_schema=diagnosis_schema,
            system_instruction=(
                "You are an SQL education diagnostician. Classify errors precisely "
                "and recommend appropriate hint levels based on the student's attempt count."
            ),
            temperature=0.3,
        )

        # recommended_hint_level is the v2 policy's decision (rec_level ==
        # base_rec_level == decision.level), not Gemini's — the policy is
        # authoritative (ADR-0005). Gemini's own proposal is recorded in
        # the trace as llm_proposed_level: a reportable agreement-rate
        # datum, never used to raise or lower what's actually served.
        llm_proposed_level = int(llm_diagnosis.get("recommended_hint_level", rec_level))
        diagnosis = DiagnosisResult(
            error_type=ErrorTypeEnum(
                llm_diagnosis.get("error_type", classification.error_type)
            ),
            error_message=llm_diagnosis.get(
                "error_message", classification.error_message
            ),
            problematic_clause=llm_diagnosis.get(
                "problematic_clause", classification.problematic_clause
            ),
            severity=llm_diagnosis.get("severity", classification.severity),
            recommended_hint_level=rec_level,
            pedagogical_rationale=llm_diagnosis.get(
                "pedagogical_rationale",
                f"LLM diagnosis for attempt {attempt_count}.",
            ),
            dialect_note=classification.dialect_note,
            escalation_trace={**decision.as_dict(), "llm_proposed_level": llm_proposed_level},
        )
    except Exception as e:
        logger.warning("LLM diagnosis failed (%s) — using rule-based fallback.", e)
        rec_level = base_rec_level

        diagnosis = DiagnosisResult(
            error_type=ErrorTypeEnum(classification.error_type),
            error_message=classification.error_message,
            problematic_clause=classification.problematic_clause,
            severity=classification.severity,
            recommended_hint_level=rec_level,
            pedagogical_rationale=(
                f"Rule-based diagnosis (LLM fallback). Student attempt {attempt_count}. "
                f"{decision.rationale()}"
            ),
            dialect_note=classification.dialect_note,
            escalation_trace=decision.as_dict(),
        )

    # --- Generate hint with LLM + RAG ------------------------------------
    try:
        hint_level = diagnosis.recommended_hint_level
        level_descriptions = {
            1: "Attention: Direct their attention to the problematic clause WITHOUT explaining the error.",
            2: "Category: Explain what TYPE of SQL error they made and the general principle.",
            3: "Concept: Show a SIMILAR but DIFFERENT SQL example demonstrating the correct pattern.",
            4: "Solution Scaffold: Provide an incomplete SQL template with blanks (___) for them to fill in.",
        }

        hint_prompt = (
            f"You are a warm, encouraging SQL tutor. Generate a hint for this student.\n\n"
            f"STUDENT QUERY:\n```sql\n{student_code}\n```\n\n"
            f"DIAGNOSIS:\n"
            f"- Error type: {diagnosis.error_type}\n"
            f"- Error message: {diagnosis.error_message}\n"
            f"- Problematic clause: {diagnosis.problematic_clause or 'unknown'}\n\n"
            f"PROBLEM: {problem_description}\n"
            f"ATTEMPT: {attempt_count}\n"
            f"REQUIRED HINT LEVEL: {hint_level} — {level_descriptions.get(hint_level, '')}\n\n"
            f"RELEVANT SQL CONCEPTS:\n{rag_text}\n\n"
            + (
                f"THIS STUDENT'S PAST STRUGGLES (use only if a pattern is relevant — "
                f"e.g. call out a recurring mistake — never just repeat this list):\n"
                f"{past_struggles_text}\n\n"
                if past_struggles_text
                else ""
            )
            + f"RULES:\n"
            f"- NEVER reveal the complete SQL solution\n"
            f"- Be encouraging — use positive framing\n"
            f"- Keep the hint concise (2-4 sentences for levels 1-2, up to a paragraph for 3-4)\n"
            f"- Use SQL code blocks for any query snippets\n"
            f"- End with a follow-up question to promote reflection\n\n"
            f"{HINT_FEW_SHOT}\n"
            f"NOW WRITE THE LEVEL {hint_level} HINT FOR THE STUDENT ABOVE:\n"
        )

        llm_hint_text = generate_response(
            prompt=hint_prompt,
            system_instruction=(
                "You are an encouraging SQL tutor. Never give away the full answer. "
                "Match hint specificity to the required level."
            ),
            temperature=0.7,
        )

        output_check = validate_output(
            llm_response=llm_hint_text,
            gold_standard_query=gold_standard_query,
            schema_info=schema_info,
        )

        hint_source = "llm"
        hint_fallback_reason = None
        if not output_check.passed:
            logger.warning("Output guardrails flagged: %s", output_check.violations)
            # Use sanitized content if available, otherwise fall back
            if output_check.sanitized_content:
                llm_hint_text = output_check.sanitized_content
            else:
                # Fall back to rule-based hint
                hint_raw = generate_sql_hint(
                    error_type=classification.error_type,
                    error_message=classification.error_message,
                    student_query=student_code,
                    attempt_count=attempt_count,
                    problem_description=problem_description,
                    problematic_clause=classification.problematic_clause,
                    hint_level=hint_level,
                )
                llm_hint_text = hint_raw["hint_text"]
                hint_source = "rule_based"
                hint_fallback_reason = "guardrail"

        hint = HintResponse(
            hint_level=hint_level,
            hint_text=_prepend_dialect_note(llm_hint_text, diagnosis.dialect_note),
            hint_type="text",
            pedagogical_rationale=diagnosis.pedagogical_rationale,
            follow_up_question=None,  # Embedded in the LLM response itself
            source=hint_source,
            fallback_reason=hint_fallback_reason,
        )
        if hint_fallback_reason:
            metrics.record_hint_fallback(hint_fallback_reason)

    except Exception as e:
        logger.warning(
            "LLM hint generation failed (%s) — using rule-based fallback.", e
        )
        metrics.record_hint_fallback("hint_error")
        hint_raw = generate_sql_hint(
            error_type=classification.error_type,
            error_message=classification.error_message,
            student_query=student_code,
            attempt_count=attempt_count,
            problem_description=problem_description,
            problematic_clause=classification.problematic_clause,
            hint_level=hint_level,
        )
        hint = HintResponse(
            hint_level=hint_raw["hint_level"],
            hint_text=_prepend_dialect_note(hint_raw["hint_text"], classification.dialect_note),
            hint_type=hint_raw.get("hint_type", "text"),
            pedagogical_rationale=hint_raw.get("pedagogical_rationale"),
            follow_up_question=hint_raw.get("follow_up_question"),
            source="rule_based",
            fallback_reason="hint_error",
        )

    return diagnosis, hint


@traceable(name="LLM Pipeline")
def run_pipeline_llm(
    submission: CodeSubmission,
    problem_description: str,
    problem_topic: str,
    test_cases: list[dict[str, Any]],
    attempt_count: int = 1,
    gold_standard_query: str = "",
    schema_info: dict[str, Any] | None = None,
    past_struggles: str = "",
    signals: EscalationSignals | None = None,
) -> SubmissionResponse:
    """
    Run the SQL tutoring pipeline with Gemini LLM reasoning + RAG.

    Flow:
      1. Input guardrails → validate student query
      2. Grader → deterministic SQL testing (same as Phase 1)
      3. Diagnostician → Gemini reasons about the error + RAG context
      4. Tutor → Gemini generates personalized hint + RAG context
      5. Output guardrails → validate/sanitize response

    Falls back to deterministic pipeline if LLM or guardrails fail.

    Args:
        submission: The student's SQL submission.
        problem_description: Text description of the problem.
        problem_topic: Topic tag (e.g. "JOINs", "Aggregation").
        test_cases: List of test case dicts.
        attempt_count: Number of attempts on this problem.
        gold_standard_query: The gold-standard SQL for leakage detection.
        schema_info: Dict with 'tables' and 'columns' for hallucination check.
        signals: Attempt/error history, topic mastery, dwell time — built
            by the caller from Postgres. None degrades to the v1 fallback.

    Returns:
        A fully-populated ``SubmissionResponse``.
    """

    if not get_settings().LLM_ENABLED:
        logger.info("LLM_ENABLED=false — routing to the deterministic pipeline.")
        return run_pipeline_deterministic(
            submission=submission,
            problem_description=problem_description,
            problem_topic=problem_topic,
            test_cases=test_cases,
            attempt_count=attempt_count,
            signals=signals,
        )

    from backend.guardrails import validate_input

    start_time = time.perf_counter()

    # --- Step 0: Input guardrails ----------------------------------------
    logger.info("LLM Pipeline step 0: Input guardrails")
    input_check = validate_input(submission.code)
    if not input_check.passed:
        logger.warning("Input guardrails failed: %s", input_check.violations)
        # Fall back to deterministic pipeline for safety
        return run_pipeline_deterministic(
            submission=submission,
            problem_description=problem_description,
            problem_topic=problem_topic,
            test_cases=test_cases,
            attempt_count=attempt_count,
            signals=signals,
        )

    # --- Step 1: Grade (deterministic — same as Phase 1) -----------------
    logger.info("LLM Pipeline step 1/4: Grading SQL submission")

    sql_test_cases = [
        {
            "test_case_id": tc.get("test_case_id", idx),
            "expected_query": tc["input_data"],
            "check_order": tc.get("check_order", False),
        }
        for idx, tc in enumerate(test_cases)
    ]

    grading_raw = run_sql_tests(submission.code, sql_test_cases)

    grading = GradingResult(
        passed=grading_raw["passed"],
        score=grading_raw["score"],
        total_tests=grading_raw["total_tests"],
        passed_tests=grading_raw["passed_tests"],
        test_results=[
            TestCaseResult(
                **{
                    "test_case_id": tr["test_case_id"],
                    "passed": tr["passed"],
                    "error_message": tr.get("error_message"),
                    "label_mismatch": tr.get("label_mismatch", False),
                    "diff_summary": tr.get("diff_summary"),
                    "actual_columns": tr.get("actual_columns"),
                    "actual_row_count": tr.get("actual_row_count"),
                }
            )
            for tr in grading_raw["test_results"]
        ],
        student_error=grading_raw.get("student_error"),
        student_error_type=grading_raw.get("student_error_type"),
    )

    # If all tests pass, skip diagnosis + tutoring
    if grading.passed:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        return SubmissionResponse(
            submission_id=0,
            grading=grading,
            diagnosis=None,
            hint=HintResponse(
                hint_level=0,
                hint_text=(
                    "Great job! Your SQL query is correct and returns the expected "
                    "results. Well done!"
                ),
                hint_type="text",
                pedagogical_rationale="Positive reinforcement for correct SQL query.",
                follow_up_question=(
                    "Can you think of a way to write this query differently? "
                    "For example, could you use a JOIN instead of a subquery, or vice versa?"
                ),
            ),
            overall_passed=True,
            timestamp=datetime.now(timezone.utc),
        )

    diagnosis, hint = diagnose_and_hint(
        student_code=submission.code,
        grading_raw=grading_raw,
        problem_description=problem_description,
        problem_topic=problem_topic,
        attempt_count=attempt_count,
        gold_standard_query=gold_standard_query,
        schema_info=schema_info,
        signals=signals,
        past_struggles=past_struggles,
    )

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
    logger.info("LLM Pipeline complete in %dms", elapsed_ms)

    return SubmissionResponse(
        submission_id=0,
        grading=grading,
        diagnosis=diagnosis,
        hint=hint,
        overall_passed=grading.passed,
        timestamp=datetime.now(timezone.utc),
    )
