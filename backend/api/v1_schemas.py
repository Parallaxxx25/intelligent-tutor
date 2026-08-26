"""
Pydantic schemas for the /api/v1/grade + /api/v1/hint contract — the
service surface an integrating platform calls server-to-server.

Deliberately separate from backend/db/schemas.py's SubmissionResponse: that
shape is internal (used by /api/submit and the Streamlit playground) and
carries fields — full test_results, pedagogical_rationale — that are fine
for our own UI but are more than a third-party integration needs. This is
the student-safe, integration-stable contract: no expected values, no gold
query, ever.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from backend.db.schemas import DiffSummary


class GradeRequestV1(BaseModel):
    """POST /api/v1/grade body."""

    external_user_id: str = Field(
        ..., min_length=1, max_length=100,
        description="Opaque student identifier from the calling platform — never an email.",
    )
    problem_id: int = Field(..., description="Our problem id (from GET /api/v1/problems)")
    query: str = Field(..., min_length=1, description="The student's submitted SQL")
    attempt_number: Optional[int] = Field(
        None,
        description="Caller's claimed attempt number — accepted but clamped "
        "server-side against student_progress.attempts; never trusted outright.",
    )
    client_submission_id: str = Field(
        ..., min_length=1, max_length=128,
        description="Caller-generated idempotency key — a retry with the same "
        "id returns the original result instead of re-grading or double-counting.",
    )
    partner_verdict: Optional[Literal["pass", "fail", "ungradable"]] = Field(
        None,
        description="The calling platform's own grading verdict for this same "
        "submission, if it grades independently (see "
        "docs/adr/0006-partner-primary-dual-grade.md). Used only to decide "
        "whether a hint_token is minted when the two graders disagree — never "
        "overrides our own verdict or score.",
    )


class StudentResultV1(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


class GradeResponseV1(BaseModel):
    """POST /api/v1/grade response — no expected values, ever."""

    hint_token: Optional[str] = Field(
        None, description="Pass to /api/v1/hint. Absent when verdict='pass'."
    )
    verdict: Literal["pass", "fail", "ungradable"]
    score: float
    execution_time_ms: int
    error_message: Optional[str] = Field(
        None, description="Raw Postgres error only — never a gold value."
    )
    student_result: StudentResultV1
    diff_summary: Optional[DiffSummary] = None
    hint_available: bool


class HintRequestV1(BaseModel):
    """POST /api/v1/hint body — nothing but the token is trusted."""

    hint_token: str = Field(..., min_length=1)


class HintResponseV1(BaseModel):
    hint_level: int
    hint_text: str
    error_type: Optional[str] = None
    source: str = Field(..., description="'llm' | 'rule_based'")
    latency_ms: int


class ProblemV1(BaseModel):
    """GET /api/v1/problems item — what an integrator imports and maps to
    its own problem rows (tutor_problem_id)."""

    id: int
    external_problem_id: Optional[int] = Field(
        None,
        description="This problem's id in the caller's own catalog, when "
        "imported via scripts/import_partner_problems.py — match on this "
        "instead of title text to build your tutor_problem_id mapping.",
    )
    title: str
    description: str
    topic: str
    difficulty: str
    starter_code: Optional[str] = None

    model_config = {"from_attributes": True}
