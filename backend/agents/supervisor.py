"""
Supervisor / Crew Coordinator — Orchestrates the SQL tutoring pipeline.

Manages the sequential flow:
    Grader → Diagnostician → Tutor

The Supervisor creates a CrewAI Crew with Process.sequential and
provides the ``run_pipeline`` entry point used by the API layer.

Version: 2026-02-12 (SQL-focused)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from crewai import Crew, Process, Task

from backend.agents.diagnostician import create_diagnostician_agent
from backend.agents.grader import create_grader_agent
from backend.agents.tutor import create_tutor_agent
from backend.db.schemas import (
    CodeSubmission,
    DiagnosisResult,
    ErrorTypeEnum,
    GradingResult,
    HintResponse,
    SubmissionResponse,
    TestCaseResult,
)
from backend.prompts.diagnostician_prompts import DIAGNOSTICIAN_TASK_TEMPLATE
from backend.prompts.grader_prompts import GRADER_TASK_TEMPLATE
from backend.prompts.tutor_prompts import TUTOR_TASK_TEMPLATE
from backend.tools.error_classifier import classify_sql_error
from backend.tools.hint_generator import generate_sql_hint
from backend.tools.test_runner import run_sql_tests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline (deterministic, no LLM required)
# ---------------------------------------------------------------------------

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

    # --- Step 1: Grade --------------------------------------------------
    logger.info("Pipeline step 1/3: Grading SQL submission for problem %d", submission.problem_id)

    # Convert test cases to the format expected by run_sql_tests
    sql_test_cases = [
        {
            "test_case_id": tc.get("test_case_id", idx),
            "expected_query": tc["input_data"],  # gold-standard query stored in input_data
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
            TestCaseResult(**{
                "test_case_id": tr["test_case_id"],
                "passed": tr["passed"],
                "error_message": tr.get("error_message"),
                "expected_columns": tr.get("expected_columns"),
                "actual_columns": tr.get("actual_columns"),
                "expected_row_count": tr.get("expected_row_count"),
                "actual_row_count": tr.get("actual_row_count"),
            })
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
# CrewAI pipeline (LLM-powered, for Phase 2+)
# ---------------------------------------------------------------------------

class TutoringCrew:
    """
    CrewAI-based SQL tutoring pipeline.

    Orchestrates Grader → Diagnostician → Tutor in sequential process.
    This is the LLM-powered path — each agent reasons about the SQL
    inputs before using its tools.

    Usage:
        crew = TutoringCrew()
        result = crew.kickoff(submission, problem_description, test_cases, attempt_count)
    """

    def __init__(self) -> None:
        self.grader = create_grader_agent()
        self.diagnostician = create_diagnostician_agent()
        self.tutor = create_tutor_agent()

    def kickoff(
        self,
        submission: CodeSubmission,
        problem_description: str,
        problem_topic: str,
        test_cases_json: str,
        attempt_count: int = 1,
    ) -> str:
        """
        Run the full CrewAI pipeline.

        Returns:
            Raw crew output string (parsed by the API layer).
        """
        # --- Define tasks ------------------------------------------------
        grading_task = Task(
            description=GRADER_TASK_TEMPLATE.format(
                problem_description=problem_description,
                student_code=submission.code,
                test_cases_json=test_cases_json,
            ),
            expected_output=(
                "A structured grading report with pass/fail for each test, "
                "column/row comparison, overall score, and any error messages."
            ),
            agent=self.grader,
        )

        diagnosis_task = Task(
            description=DIAGNOSTICIAN_TASK_TEMPLATE.format(
                student_code=submission.code,
                grading_results="{grading_task_output}",
                attempt_count=attempt_count,
                problem_topic=problem_topic,
            ),
            expected_output=(
                "An error classification with: error_type, error_message, "
                "problematic_clause, severity, recommended_hint_level, and "
                "pedagogical_rationale."
            ),
            agent=self.diagnostician,
            context=[grading_task],
        )

        tutoring_task = Task(
            description=TUTOR_TASK_TEMPLATE.format(
                student_code=submission.code,
                error_type="{diagnosis_error_type}",
                error_message="{diagnosis_error_message}",
                hint_level="{recommended_hint_level}",
                problematic_clause="{problematic_clause}",
                problem_description=problem_description,
                attempt_count=attempt_count,
            ),
            expected_output=(
                "A pedagogical SQL hint with: hint_level, hint_text, hint_type, "
                "pedagogical_rationale, and follow_up_question."
            ),
            agent=self.tutor,
            context=[diagnosis_task],
        )

        # --- Create & run crew ------------------------------------------
        crew = Crew(
            agents=[self.grader, self.diagnostician, self.tutor],
            tasks=[grading_task, diagnosis_task, tutoring_task],
            process=Process.sequential,
            verbose=True,
        )

        logger.info("Kicking off TutoringCrew for problem %d", submission.problem_id)
        result = crew.kickoff()
        return str(result)
