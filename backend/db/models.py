"""
SQLAlchemy ORM models for the Intelligent SQL Tutoring System.

Tables:
  - problems         : SQL query problems with descriptions and metadata
  - test_cases        : Gold-standard queries linked to problems
  - gold_standards    : Reference SQL solutions for problems
  - users             : Registered students
  - student_progress  : Per-problem mastery tracking
  - interaction_history : Full log of every submission + agent response

Version: 2026-02-12 (SQL-focused)
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Declarative base for all models."""
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Difficulty(str, enum.Enum):
    """Problem difficulty levels."""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Language(str, enum.Enum):
    """Supported programming languages."""
    PYTHON = "python"
    SQL = "sql"


class ErrorType(str, enum.Enum):
    """SQL-specific error classification taxonomy."""
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
    SECURITY_VIOLATION = "security_violation"
    NO_ERROR = "no_error"


class MasteryLevel(str, enum.Enum):
    """Student mastery levels per topic."""
    NOVICE = "novice"
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Problem(Base):
    """A coding problem that students can attempt."""

    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[Difficulty] = mapped_column(
        Enum(Difficulty), nullable=False, default=Difficulty.EASY
    )
    language: Mapped[Language] = mapped_column(
        Enum(Language), nullable=False, default=Language.SQL
    )
    topic: Mapped[str] = mapped_column(String(128), nullable=False, default="general")
    starter_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    test_cases: Mapped[list["TestCase"]] = relationship(
        back_populates="problem", cascade="all, delete-orphan", order_by="TestCase.order"
    )
    gold_standards: Mapped[list["GoldStandard"]] = relationship(
        back_populates="problem", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Problem(id={self.id}, title={self.title!r})>"


class TestCase(Base):
    """An input/output test case for a problem."""

    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    input_data: Mapped[str] = mapped_column(Text, nullable=False)
    expected_output: Mapped[str] = mapped_column(Text, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    problem: Mapped["Problem"] = relationship(back_populates="test_cases")

    def __repr__(self) -> str:
        return f"<TestCase(id={self.id}, problem_id={self.problem_id})>"


class GoldStandard(Base):
    """Reference solution for a problem (used by agents, never shown to students)."""

    __tablename__ = "gold_standards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    solution_code: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    problem: Mapped["Problem"] = relationship(back_populates="gold_standards")

    def __repr__(self) -> str:
        return f"<GoldStandard(id={self.id}, problem_id={self.problem_id})>"


class User(Base):
    """A registered student."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    progress: Mapped[list["StudentProgress"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    interactions: Mapped[list["InteractionHistory"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username!r})>"


class StudentProgress(Base):
    """Tracks a student's mastery progress on a specific problem."""

    __tablename__ = "student_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "problem_id", name="uq_user_problem"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    best_score: Mapped[float] = mapped_column(Float, default=0.0)
    mastery_level: Mapped[MasteryLevel] = mapped_column(
        Enum(MasteryLevel), default=MasteryLevel.NOVICE
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="progress")
    problem: Mapped["Problem"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<StudentProgress(user_id={self.user_id}, "
            f"problem_id={self.problem_id}, score={self.best_score})>"
        )


class InteractionHistory(Base):
    """Full audit log of every student submission and agent response."""

    __tablename__ = "interaction_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("problems.id", ondelete="CASCADE"), nullable=False
    )
    submitted_code: Mapped[str] = mapped_column(Text, nullable=False)

    # Grading results
    grading_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    grading_score: Mapped[float] = mapped_column(Float, default=0.0)
    grading_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Diagnosis
    error_type: Mapped[Optional[ErrorType]] = mapped_column(
        Enum(ErrorType), nullable=True
    )
    diagnosis_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Hint
    hint_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hint_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    execution_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="interactions")
    problem: Mapped["Problem"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<InteractionHistory(id={self.id}, user_id={self.user_id}, "
            f"problem_id={self.problem_id})>"
        )
