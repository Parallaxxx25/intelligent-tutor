"""
Pydantic v2 schemas for request/response validation.

These schemas define the data contracts between the API layer,
the agent pipeline, and the frontend.

Version: 2026-02-12 (SQL-focused)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums (mirror db/models.py for API layer)
# ---------------------------------------------------------------------------

class DifficultyEnum(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class LanguageEnum(str, Enum):
    PYTHON = "python"
    SQL = "sql"


class ErrorTypeEnum(str, Enum):
    """SQL-specific error taxonomy."""
    SYNTAX_ERROR = "syntax_error"
    COLUMN_ERROR = "column_error"
    RELATION_ERROR = "relation_error"
    JOIN_ERROR = "join_error"
    AGGREGATION_ERROR = "aggregation_error"
    SUBQUERY_ERROR = "subquery_error"
    TYPE_ERROR = "type_error"
    AMBIGUITY_ERROR = "ambiguity_error"
    LOGIC_ERROR = "logic_error"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT_ERROR = "timeout_error"
    NO_ERROR = "no_error"


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CodeSubmission(BaseModel):
    """Request body for submitting a SQL query to the grading pipeline."""

    user_id: int = Field(..., description="ID of the submitting student")
    problem_id: int = Field(..., description="ID of the problem being attempted")
    code: str = Field(..., min_length=1, description="Student's submitted SQL query")
    language: LanguageEnum = Field(
        default=LanguageEnum.SQL, description="Query language (SQL)"
    )


# ---------------------------------------------------------------------------
# Internal pipeline schemas (passed between agents)
# ---------------------------------------------------------------------------

class TestCaseResult(BaseModel):
    """Result of running a single SQL test case."""

    test_case_id: int
    passed: bool
    error_message: Optional[str] = None
    expected_columns: Optional[list[str]] = None
    actual_columns: Optional[list[str]] = None
    expected_row_count: Optional[int] = None
    actual_row_count: Optional[int] = None


class GradingResult(BaseModel):
    """Structured output from the Grader Agent."""

    passed: bool = Field(..., description="Whether all test cases passed")
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Score from 0.0 to 1.0"
    )
    total_tests: int = Field(..., description="Total number of test cases")
    passed_tests: int = Field(..., description="Number of passing tests")
    test_results: list[TestCaseResult] = Field(
        default_factory=list, description="Per-test-case results"
    )
    student_error: Optional[str] = Field(
        None, description="SQL error message if query failed"
    )
    student_error_type: Optional[str] = Field(
        None, description="SQL error type if query failed"
    )
    execution_time_ms: Optional[int] = None


class DiagnosisResult(BaseModel):
    """Structured output from the Diagnostician Agent."""

    error_type: ErrorTypeEnum = Field(
        ..., description="Classification of the SQL error"
    )
    error_message: str = Field(..., description="Human-readable error description")
    problematic_clause: Optional[str] = Field(
        None, description="SQL clause causing the issue (SELECT, WHERE, JOIN, etc.)"
    )
    severity: str = Field(
        default="medium", description="low / medium / high"
    )
    recommended_hint_level: int = Field(
        ..., ge=1, le=4,
        description="Recommended hint level (1=attention, 2=category, 3=concept, 4=solution)"
    )
    pedagogical_rationale: str = Field(
        ..., description="Why this hint level was chosen"
    )


class HintResponse(BaseModel):
    """Structured output from the Tutor Agent."""

    hint_level: int = Field(
        ..., ge=0, le=4,
        description="The scaffolding level of the hint (0=correct, 1-4=escalating)"
    )
    hint_text: str = Field(..., description="The actual hint text")
    hint_type: str = Field(
        default="text",
        description="Format of the hint: text, code_template, example"
    )
    pedagogical_rationale: Optional[str] = Field(
        None, description="Why this hint was chosen"
    )
    follow_up_question: Optional[str] = Field(
        None, description="Optional question to prompt student reflection"
    )


# ---------------------------------------------------------------------------
# API response schemas
# ---------------------------------------------------------------------------

class TestCaseResponse(BaseModel):
    """Test case data returned to the frontend (hidden cases excluded)."""

    id: int
    input_data: str
    expected_output: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class ProblemResponse(BaseModel):
    """Problem details returned to the frontend."""

    id: int
    title: str
    description: str
    difficulty: DifficultyEnum
    language: LanguageEnum
    topic: str
    starter_code: Optional[str] = None
    test_cases: list[TestCaseResponse] = Field(
        default_factory=list, description="Visible test cases only"
    )
    created_at: datetime

    model_config = {"from_attributes": True}


class ProblemListItem(BaseModel):
    """Abbreviated problem info for listing."""

    id: int
    title: str
    difficulty: DifficultyEnum
    language: LanguageEnum
    topic: str

    model_config = {"from_attributes": True}


class SubmissionResponse(BaseModel):
    """Full response from the agent pipeline after SQL submission."""

    submission_id: int = Field(..., description="ID of the interaction record")
    grading: GradingResult
    diagnosis: Optional[DiagnosisResult] = None
    hint: Optional[HintResponse] = None
    overall_passed: bool = Field(
        ..., description="True if all tests passed"
    )
    timestamp: datetime


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    version: str = "0.1.0"
    timestamp: datetime
