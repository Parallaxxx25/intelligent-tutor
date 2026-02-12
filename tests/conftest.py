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
def valid_python_code() -> str:
    """Simple valid Python code that prints a result."""
    return 'print("hello world")'


@pytest.fixture
def syntax_error_code() -> str:
    """Python code with a syntax error."""
    return "def broken(\n    print('oops')"


@pytest.fixture
def infinite_loop_code() -> str:
    """Python code with an infinite loop."""
    return "while True:\n    pass"


@pytest.fixture
def two_sum_correct() -> str:
    """Correct solution to the Two Sum problem."""
    return (
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, num in enumerate(nums):\n"
        "        complement = target - num\n"
        "        if complement in seen:\n"
        "            return [seen[complement], i]\n"
        "        seen[num] = i\n"
        "    return []\n"
    )


@pytest.fixture
def two_sum_wrong() -> str:
    """Incorrect solution to the Two Sum problem (logic error)."""
    return (
        "def two_sum(nums, target):\n"
        "    # Off-by-one: returns wrong indices\n"
        "    for i in range(len(nums)):\n"
        "        for j in range(len(nums)):\n"
        "            if nums[i] + nums[j] == target:\n"
        "                return [i, j]\n"
        "    return []\n"
    )


@pytest.fixture
def two_sum_test_cases() -> list[dict]:
    """Test cases for the Two Sum problem."""
    return [
        {
            "test_case_id": 1,
            "input_data": "two_sum([2, 7, 11, 15], 9)",
            "expected_output": "[0, 1]",
        },
        {
            "test_case_id": 2,
            "input_data": "two_sum([3, 2, 4], 6)",
            "expected_output": "[1, 2]",
        },
    ]


@pytest.fixture
def blocked_import_code() -> str:
    """Code using a blocked import."""
    return "import os\nprint(os.listdir('.'))"
