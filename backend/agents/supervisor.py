"""
Supervisor / Graph Coordinator — Orchestrates the SQL tutoring pipeline.

Manages the sequential flow:
    Grader → Diagnostician → Tutor

The Supervisor builds a LangGraph StateGraph with sequential edges and
provides the ``run_pipeline`` entry points used by the API layer.

Version: 2026-03-20 (LangGraph migration)
"""

from __future__ import annotations

import json
from langsmith import traceable
import logging
import time
from datetime import datetime, timezone
from typing import Any, TypedDict

import sqlglot

from langgraph.graph import END, StateGraph

from backend.agents.diagnostician import diagnose_errors
from backend.agents.tutor import generate_hint
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


def _format_sql_query(query: str) -> str:
    """Format the student's query using sqlglot if syntax is valid."""
    try:
        parsed = sqlglot.parse_one(query)
        return parsed.sql(pretty=True)
    except Exception:
        # Ignore syntax errors here; let Grader & Diagnostician handle it
        # so it gets properly recorded as a failed attempt.
        return query


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

    Returns:
        A fully-populated ``SubmissionResponse``.
    """
    start_time = time.perf_counter()
    submission.code = _format_sql_query(submission.code)

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
            "check_order": tc.get("check_order", True),
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
                    "expected_columns": tr.get("expected_columns"),
                    "actual_columns": tr.get("actual_columns"),
                    "expected_row_count": tr.get("expected_row_count"),
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

    # Determine hint level from attempt count
    if attempt_count <= 1:
        recommended_level = 1
    elif attempt_count == 2:
        recommended_level = 2
    elif attempt_count == 3:
        recommended_level = 3
    else:
        recommended_level = 4

    diagnosis = DiagnosisResult(
        error_type=ErrorTypeEnum(classification.error_type),
        error_message=classification.error_message,
        problematic_clause=classification.problematic_clause,
        severity=classification.severity,
        recommended_hint_level=recommended_level,
        pedagogical_rationale=(
            f"Student is on attempt {attempt_count}. "
            f"Error type is {classification.error_type} "
            f"(clause: {classification.problematic_clause}) with "
            f"{classification.severity} severity. "
            f"Escalating to hint level {recommended_level}."
        ),
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
        )
        hint = HintResponse(
            hint_level=hint_raw["hint_level"],
            hint_text=hint_raw["hint_text"],
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
    # Set by diagnostician node
    classification: Any
    diagnosis_error_type: str
    diagnosis_error_message: str
    diagnosis_problematic_clause: str | None
    diagnosis_severity: str
    recommended_hint_level: int
    pedagogical_rationale: str
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
) -> SubmissionResponse:
    """
    Run the SQL tutoring pipeline using LangGraph.
    """
    start_time = time.perf_counter()
    submission.code = _format_sql_query(submission.code)

    logger.info("LangGraph Pipeline step 1: Grading SQL submission")

    sql_test_cases = [
        {
            "test_case_id": tc.get("test_case_id", idx),
            "expected_query": tc["input_data"],
            "check_order": tc.get("check_order", True),
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
                    "expected_columns": tr.get("expected_columns"),
                    "actual_columns": tr.get("actual_columns"),
                    "expected_row_count": tr.get("expected_row_count"),
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
        }
    )

    # Build structured response from graph output
    diagnosis = DiagnosisResult(
        error_type=ErrorTypeEnum(graph_output["diagnosis_error_type"]),
        error_message=graph_output["diagnosis_error_message"],
        problematic_clause=graph_output.get("diagnosis_problematic_clause"),
        severity=graph_output.get("diagnosis_severity", "medium"),
        recommended_hint_level=graph_output.get("recommended_hint_level", 1),
        pedagogical_rationale=graph_output.get(
            "pedagogical_rationale", "Generated by LangGraph pipeline."
        ),
    )

    hint_raw = graph_output.get("hint_raw", {})
    hint = HintResponse(
        hint_level=hint_raw.get(
            "hint_level", graph_output.get("recommended_hint_level", 1)
        ),
        hint_text=graph_output.get("hint_text", str(graph_output)),
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


@traceable(name="LLM Pipeline")
def run_pipeline_llm(
    submission: CodeSubmission,
    problem_description: str,
    problem_topic: str,
    test_cases: list[dict[str, Any]],
    attempt_count: int = 1,
    gold_standard_query: str = "",
    schema_info: dict[str, Any] | None = None,
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

    Returns:
        A fully-populated ``SubmissionResponse``.
    """
    submission.code = _format_sql_query(submission.code)

    from backend.guardrails import validate_input, validate_output
    from backend.llm import generate_response, generate_structured_response
    from backend.rag.retriever import retrieve_relevant_context

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
        )

    # --- Step 1: Grade (deterministic — same as Phase 1) -----------------
    logger.info("LLM Pipeline step 1/4: Grading SQL submission")

    sql_test_cases = [
        {
            "test_case_id": tc.get("test_case_id", idx),
            "expected_query": tc["input_data"],
            "check_order": tc.get("check_order", True),
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
                    "expected_columns": tr.get("expected_columns"),
                    "actual_columns": tr.get("actual_columns"),
                    "expected_row_count": tr.get("expected_row_count"),
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

    # --- Step 2: Diagnose with LLM + RAG --------------------------------
    logger.info("LLM Pipeline step 2/4: Diagnosing with Gemini + RAG")

    # Run rule-based classifier first for baseline
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

    # Retrieve relevant SQL concept context
    rag_query = (
        f"SQL error: {classification.error_type}. "
        f"Student query: {submission.code}. "
        f"Error: {classification.error_message}"
    )
    rag_context = retrieve_relevant_context(
        query=rag_query,
        error_type=classification.error_type,
        n_results=3,
    )
    rag_text = (
        "\n\n".join(f"### {doc['title']}\n{doc['content']}" for doc in rag_context)
        if rag_context
        else "No additional SQL reference available."
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

        if attempt_count <= 1:
            rec_level = 1
        elif attempt_count == 2:
            rec_level = 2
        elif attempt_count == 3:
            rec_level = 3
        else:
            rec_level = 4

        diagnosis_prompt = (
            f"You are an expert SQL diagnostician. Analyse this student's SQL error.\n\n"
            f"STUDENT QUERY:\n```sql\n{submission.code}\n```\n\n"
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
            recommended_hint_level=int(
                llm_diagnosis.get("recommended_hint_level", rec_level)
            ),
            pedagogical_rationale=llm_diagnosis.get(
                "pedagogical_rationale",
                f"LLM diagnosis for attempt {attempt_count}.",
            ),
        )
    except Exception as e:
        logger.warning("LLM diagnosis failed (%s) — using rule-based fallback.", e)
        if attempt_count <= 1:
            rec_level = 1
        elif attempt_count == 2:
            rec_level = 2
        elif attempt_count == 3:
            rec_level = 3
        else:
            rec_level = 4

        diagnosis = DiagnosisResult(
            error_type=ErrorTypeEnum(classification.error_type),
            error_message=classification.error_message,
            problematic_clause=classification.problematic_clause,
            severity=classification.severity,
            recommended_hint_level=rec_level,
            pedagogical_rationale=(
                f"Rule-based diagnosis (LLM fallback). Student attempt {attempt_count}."
            ),
        )

    # --- Step 3: Generate hint with LLM + RAG ---------------------------
    logger.info("LLM Pipeline step 3/4: Generating hint with Gemini + RAG")

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
            f"STUDENT QUERY:\n```sql\n{submission.code}\n```\n\n"
            f"DIAGNOSIS:\n"
            f"- Error type: {diagnosis.error_type}\n"
            f"- Error message: {diagnosis.error_message}\n"
            f"- Problematic clause: {diagnosis.problematic_clause or 'unknown'}\n\n"
            f"PROBLEM: {problem_description}\n"
            f"ATTEMPT: {attempt_count}\n"
            f"REQUIRED HINT LEVEL: {hint_level} — {level_descriptions.get(hint_level, '')}\n\n"
            f"RELEVANT SQL CONCEPTS:\n{rag_text}\n\n"
            f"RULES:\n"
            f"- NEVER reveal the complete SQL solution\n"
            f"- Be encouraging — use positive framing\n"
            f"- Keep the hint concise (2-4 sentences for levels 1-2, up to a paragraph for 3-4)\n"
            f"- Use SQL code blocks for any query snippets\n"
            f"- End with a follow-up question to promote reflection\n"
        )

        llm_hint_text = generate_response(
            prompt=hint_prompt,
            system_instruction=(
                "You are an encouraging SQL tutor. Never give away the full answer. "
                "Match hint specificity to the required level."
            ),
            temperature=0.7,
        )

        # --- Step 4: Output guardrails -----------------------------------
        logger.info("LLM Pipeline step 4/4: Output guardrails")
        output_check = validate_output(
            llm_response=llm_hint_text,
            gold_standard_query=gold_standard_query,
            schema_info=schema_info,
        )

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
                    student_query=submission.code,
                    attempt_count=attempt_count,
                    problem_description=problem_description,
                    problematic_clause=classification.problematic_clause,
                )
                llm_hint_text = hint_raw["hint_text"]

        hint = HintResponse(
            hint_level=hint_level,
            hint_text=llm_hint_text,
            hint_type="text",
            pedagogical_rationale=diagnosis.pedagogical_rationale,
            follow_up_question=None,  # Embedded in the LLM response itself
        )

    except Exception as e:
        logger.warning(
            "LLM hint generation failed (%s) — using rule-based fallback.", e
        )
        hint_raw = generate_sql_hint(
            error_type=classification.error_type,
            error_message=classification.error_message,
            student_query=submission.code,
            attempt_count=attempt_count,
            problem_description=problem_description,
            problematic_clause=classification.problematic_clause,
        )
        hint = HintResponse(
            hint_level=hint_raw["hint_level"],
            hint_text=hint_raw["hint_text"],
            hint_type=hint_raw.get("hint_type", "text"),
            pedagogical_rationale=hint_raw.get("pedagogical_rationale"),
            follow_up_question=hint_raw.get("follow_up_question"),
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
