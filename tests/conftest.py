"""
conftest.py — Shared fixtures for the test suite.

Version: 2026-02-12
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_sql_code() -> str:
    """Simple valid SQL code."""
    return "SELECT * FROM sales.customers;"


@pytest.fixture
def syntax_error_code() -> str:
    """SQL code with a syntax error."""
    return "SELECT * FROMMMM sales.customers;"


@pytest.fixture
def logic_error_code() -> str:
    """SQL code with a logic error."""
    return "SELECT first_name FROM sales.customers;"


@pytest.fixture
def sample_test_cases() -> list[dict]:
    """Test cases for the SQL problem."""
    return [
        {
            "test_case_id": 1,
            "input_data": "SELECT first_name, last_name FROM sales.customers",
            "expected_output": "All customers",
        }
    ]


@pytest.fixture
def blocked_sql_code() -> str:
    """Code using a blocked SQL command."""
    return "DROP TABLE sales.customers;"
