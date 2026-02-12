"""
SQL Hint Generator Tool — Multi-level pedagogical scaffolding for SQL.

Generates hints at four scaffolding levels based on SQL error type,
student attempt count, and the problematic SQL clause.

Levels:
  1 (Attention)  : "Which clause seems suspicious?"
  2 (Category)   : Explain the SQL concept / error principle
  3 (Concept)    : Show a similar SQL example demonstrating the principle
  4 (Solution)   : Provide an incomplete SQL query with blanks

Version: 2026-02-12  (SQL-focused rewrite)
"""

from __future__ import annotations

import logging
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

class SQLHintGeneratorInput(BaseModel):
    """Input schema for the SQLHintGeneratorTool."""

    error_type: str = Field(
        ..., description="SQL error category (e.g. syntax_error, join_error, logic_error)"
    )
    error_message: str = Field(
        ..., description="Human-readable error description"
    )
    student_query: str = Field(
        ..., description="The student's submitted SQL query"
    )
    attempt_count: int = Field(
        default=1, ge=1, description="How many times the student has attempted this problem"
    )
    problem_description: str = Field(
        default="", description="The problem statement for context"
    )
    problematic_clause: str | None = Field(
        None, description="The SQL clause most likely causing the issue"
    )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class SQLHintGeneratorTool(BaseTool):
    """Generate a scaffolded pedagogical hint for SQL queries."""

    name: str = "sql_hint_generator"
    description: str = (
        "Generates a multi-level pedagogical hint for a SQL student based on "
        "their error type, query, and number of attempts. "
        "Level 1 = attention nudge, Level 2 = SQL concept explanation, "
        "Level 3 = similar SQL example, Level 4 = guided SQL template."
    )
    args_schema: Type[BaseModel] = SQLHintGeneratorInput

    def _run(
        self,
        error_type: str,
        error_message: str,
        student_query: str,
        attempt_count: int = 1,
        problem_description: str = "",
        problematic_clause: str | None = None,
    ) -> str:
        result = generate_sql_hint(
            error_type=error_type,
            error_message=error_message,
            student_query=student_query,
            attempt_count=attempt_count,
            problem_description=problem_description,
            problematic_clause=problematic_clause,
        )
        return (
            f"HINT_LEVEL: {result['hint_level']}\n"
            f"HINT_TYPE: {result['hint_type']}\n"
            f"HINT_TEXT: {result['hint_text']}\n"
            f"RATIONALE: {result['pedagogical_rationale']}\n"
            f"FOLLOW_UP: {result.get('follow_up_question', '')}"
        )


# ---------------------------------------------------------------------------
# Standalone helper
# ---------------------------------------------------------------------------

def generate_sql_hint(
    error_type: str,
    error_message: str,
    student_query: str,
    attempt_count: int = 1,
    problem_description: str = "",
    problematic_clause: str | None = None,
) -> dict[str, str | int]:
    """
    Determine hint level from attempt count and produce a SQL-specific hint.

    Hint-level escalation policy:
      - Attempt 1       → Level 1 (Attention)
      - Attempt 2       → Level 2 (Category)
      - Attempt 3       → Level 3 (Concept)
      - Attempt 4+      → Level 4 (Solution scaffold)
    """
    if attempt_count <= 1:
        level = 1
    elif attempt_count == 2:
        level = 2
    elif attempt_count == 3:
        level = 3
    else:
        level = 4

    # Correct answer — congratulate
    if error_type == "no_error":
        return {
            "hint_level": 0,
            "hint_type": "text",
            "hint_text": (
                "🎉 Great job! Your SQL query is correct and returns the expected results. "
                "Well done!"
            ),
            "pedagogical_rationale": "Positive reinforcement for correct SQL query.",
            "follow_up_question": (
                "Can you think of a way to write this query differently? "
                "For example, could you use a JOIN instead of a subquery, or vice versa?"
            ),
        }

    generators = {
        1: _level_1_attention,
        2: _level_2_category,
        3: _level_3_concept,
        4: _level_4_solution,
    }

    return generators[level](
        error_type=error_type,
        error_message=error_message,
        student_query=student_query,
        problem_description=problem_description,
        problematic_clause=problematic_clause,
    )


# ---------------------------------------------------------------------------
# Level 1 — Attention
# ---------------------------------------------------------------------------

def _level_1_attention(
    error_type: str,
    error_message: str,
    student_query: str,
    problem_description: str,
    problematic_clause: str | None,
) -> dict[str, str | int]:
    """Point the student to the right clause or area."""

    if problematic_clause:
        hint_text = (
            f"Take a closer look at your **{problematic_clause}** clause. "
            "Something there doesn't seem quite right. "
            "Can you spot what might be causing the issue?"
        )
    elif error_type == "logic_error":
        hint_text = (
            "Your query runs without errors, but the results don't match "
            "what's expected. Re-read the problem carefully — is there a "
            "condition you might have missed in your WHERE clause? "
            "Or perhaps the wrong columns in your SELECT?"
        )
    elif error_type == "timeout_error":
        hint_text = (
            "Your query is taking too long to execute. This often happens "
            "when there's a missing JOIN condition, creating a Cartesian product. "
            "Check your FROM and JOIN clauses carefully."
        )
    else:
        hint_text = (
            "There's an issue with your SQL query. Read the error message "
            "carefully — it usually tells you which part of the query has "
            "the problem."
        )

    return {
        "hint_level": 1,
        "hint_type": "text",
        "hint_text": hint_text,
        "pedagogical_rationale": (
            "Level 1 (Attention): Directing the student's attention to the "
            "problematic SQL clause without revealing the fix."
        ),
        "follow_up_question": (
            f"What does your {problematic_clause or 'query'} clause do exactly?"
        ),
    }


# ---------------------------------------------------------------------------
# Level 2 — Category
# ---------------------------------------------------------------------------

def _level_2_category(
    error_type: str,
    error_message: str,
    student_query: str,
    problem_description: str,
    problematic_clause: str | None,
) -> dict[str, str | int]:
    """Explain the SQL error category and the underlying principle."""

    explanations = {
        "syntax_error": (
            "You have a **SQL syntax error** — the database can't parse your query. "
            "Common causes: missing commas between columns, unmatched parentheses, "
            "misspelled keywords (e.g. `SELCT` instead of `SELECT`), or a missing "
            "`FROM` clause."
        ),
        "column_error": (
            "You're referencing a **column that doesn't exist** in the table. "
            "Check: Is the column name spelled correctly? Are you using the right "
            "table alias? Does this column actually belong to the table you're querying?"
        ),
        "relation_error": (
            "You're referencing a **table that doesn't exist** in the database. "
            "Check: Is the table name spelled correctly? Are you using the right "
            "schema? Remember that SQL identifiers may be case-sensitive."
        ),
        "join_error": (
            "There's a problem with your **JOIN**. Common issues: referencing a "
            "table in SELECT that isn't in FROM/JOIN, using the wrong column in "
            "the ON clause, or forgetting to specify a JOIN type."
        ),
        "aggregation_error": (
            "You have a **GROUP BY / aggregation error**. The rule: every column "
            "in your SELECT must either be in the GROUP BY clause or wrapped in "
            "an aggregate function (COUNT, SUM, AVG, MAX, MIN)."
        ),
        "subquery_error": (
            "There's a problem with your **subquery**. If you use a subquery with "
            "`=`, it must return exactly one value. If it could return multiple rows, "
            "use `IN` instead of `=`."
        ),
        "type_error": (
            "You have a **data type mismatch**. You might be comparing a string "
            "to a number, or using a function with the wrong data type. "
            "Check: Are you quoting string literals? Is the column type what you expect?"
        ),
        "logic_error": (
            "Your query runs but returns **incorrect results**. This is a logic error. "
            "Common causes: wrong WHERE condition, missing or incorrect JOIN, "
            "wrong aggregate function, or selecting the wrong columns."
        ),
        "ambiguity_error": (
            "You have an **ambiguous column reference**. When querying multiple tables "
            "that share the same column name, you must prefix the column with the table "
            "name or alias (e.g. `orders.id` instead of just `id`)."
        ),
        "timeout_error": (
            "Your query **timed out** — it's too slow. Common causes: missing WHERE "
            "clause on a large table, Cartesian product from missing JOIN conditions, "
            "or an expensive correlated subquery. Simplify and test step by step."
        ),
    }

    explanation = explanations.get(
        error_type,
        f"You're encountering a `{error_type}` error. "
        "Review the error message for clues about what went wrong.",
    )

    hint_text = f"{explanation}\n\nError detail: `{error_message}`"

    return {
        "hint_level": 2,
        "hint_type": "text",
        "hint_text": hint_text,
        "pedagogical_rationale": (
            "Level 2 (Category): Explaining the SQL error category so the "
            "student understands WHAT type of mistake they made."
        ),
        "follow_up_question": (
            "Based on this explanation, which part of your query do you think "
            "needs to change?"
        ),
    }


# ---------------------------------------------------------------------------
# Level 3 — Concept (similar example)
# ---------------------------------------------------------------------------

def _level_3_concept(
    error_type: str,
    error_message: str,
    student_query: str,
    problem_description: str,
    problematic_clause: str | None,
) -> dict[str, str | int]:
    """Show a similar SQL example demonstrating the correct principle."""

    examples = {
        "syntax_error": (
            "Here's a common SQL syntax error and fix:\n\n"
            "```sql\n"
            "-- ❌ Missing comma between columns\n"
            "SELECT name age FROM employees;\n\n"
            "-- ✅ Correct\n"
            "SELECT name, age FROM employees;\n"
            "```\n\n"
            "Check your query for missing commas, semicolons, or keywords."
        ),
        "column_error": (
            "Here's a common column error:\n\n"
            "```sql\n"
            "-- ❌ Wrong column name\n"
            "SELECT employee_name FROM employees;\n"
            "-- Error: column 'employee_name' does not exist\n\n"
            "-- ✅ Correct — use the actual column name\n"
            "SELECT name FROM employees;\n"
            "```\n\n"
            "Tip: Use `SELECT * FROM table_name LIMIT 5;` to see the actual column names."
        ),
        "join_error": (
            "Here's a correct JOIN example:\n\n"
            "```sql\n"
            "-- ❌ Missing JOIN condition → Cartesian product\n"
            "SELECT orders.id, customers.name\n"
            "FROM orders, customers;\n\n"
            "-- ✅ Correct — explicit JOIN with ON\n"
            "SELECT o.id, c.name\n"
            "FROM orders o\n"
            "JOIN customers c ON o.customer_id = c.id;\n"
            "```\n\n"
            "Make sure every table in your FROM has a JOIN condition."
        ),
        "aggregation_error": (
            "Here's a GROUP BY example:\n\n"
            "```sql\n"
            "-- ❌ 'name' is not in GROUP BY or aggregate\n"
            "SELECT department, name, COUNT(*)\n"
            "FROM employees\n"
            "GROUP BY department;\n\n"
            "-- ✅ Option A: Add 'name' to GROUP BY\n"
            "SELECT department, name, COUNT(*)\n"
            "FROM employees\n"
            "GROUP BY department, name;\n\n"
            "-- ✅ Option B: Use aggregate on 'name'\n"
            "SELECT department, COUNT(*) AS emp_count\n"
            "FROM employees\n"
            "GROUP BY department;\n"
            "```\n\n"
            "Rule: every non-aggregated column must appear in GROUP BY."
        ),
        "subquery_error": (
            "Here's a subquery example:\n\n"
            "```sql\n"
            "-- ❌ Subquery returns multiple rows with =\n"
            "SELECT * FROM orders\n"
            "WHERE customer_id = (SELECT id FROM customers WHERE city = 'NYC');\n\n"
            "-- ✅ Use IN for multiple rows\n"
            "SELECT * FROM orders\n"
            "WHERE customer_id IN (SELECT id FROM customers WHERE city = 'NYC');\n"
            "```\n\n"
            "Use `=` only when you're sure the subquery returns exactly one value."
        ),
        "logic_error": (
            "Here's a common logic mistake in SQL:\n\n"
            "```sql\n"
            "-- ❌ Wrong: finds customers with ANY order > 100\n"
            "SELECT c.name\n"
            "FROM customers c JOIN orders o ON c.id = o.customer_id\n"
            "WHERE o.amount > 100;\n\n"
            "-- ✅ Correct: finds customers whose TOTAL orders > 100\n"
            "SELECT c.name\n"
            "FROM customers c JOIN orders o ON c.id = o.customer_id\n"
            "GROUP BY c.name\n"
            "HAVING SUM(o.amount) > 100;\n"
            "```\n\n"
            "Re-read the problem: does it ask for individual rows or aggregates?"
        ),
        "ambiguity_error": (
            "Here's how to fix ambiguous columns:\n\n"
            "```sql\n"
            "-- ❌ Ambiguous: both tables have 'id'\n"
            "SELECT id, name FROM orders JOIN customers ON orders.cust_id = customers.id;\n\n"
            "-- ✅ Qualify with table alias\n"
            "SELECT o.id, c.name\n"
            "FROM orders o\n"
            "JOIN customers c ON o.cust_id = c.id;\n"
            "```"
        ),
        "timeout_error": (
            "Here's how a Cartesian product causes timeouts:\n\n"
            "```sql\n"
            "-- ❌ Cartesian product — O(n²) rows!\n"
            "SELECT * FROM orders, products;\n\n"
            "-- ✅ Use a proper JOIN condition\n"
            "SELECT * FROM orders o\n"
            "JOIN products p ON o.product_id = p.id;\n"
            "```\n\n"
            "Always check that you have a matching ON condition for every JOIN."
        ),
    }

    hint_text = examples.get(
        error_type,
        (
            "Try debugging your query step by step:\n\n"
            "1. Run just the SELECT + FROM to check the base data\n"
            "2. Add WHERE conditions one at a time\n"
            "3. Add JOINs one table at a time\n"
            "4. Add GROUP BY / aggregation last"
        ),
    )

    return {
        "hint_level": 3,
        "hint_type": "example",
        "hint_text": hint_text,
        "pedagogical_rationale": (
            "Level 3 (Concept): Providing a similar SQL example that "
            "demonstrates the correct pattern without revealing the specific solution."
        ),
        "follow_up_question": (
            "Can you see how the pattern in this example relates to your query?"
        ),
    }


# ---------------------------------------------------------------------------
# Level 4 — Solution scaffold (fill-in-the-blanks)
# ---------------------------------------------------------------------------

def _level_4_solution(
    error_type: str,
    error_message: str,
    student_query: str,
    problem_description: str,
    problematic_clause: str | None,
) -> dict[str, str | int]:
    """Provide an incomplete SQL template for the student to complete."""

    # Build a generic SQL scaffold — the Tutor Agent can refine with LLM
    hint_text = (
        "Here's a template to help you structure your SQL query. "
        "Fill in the blanks (`___`) to complete it:\n\n"
        "```sql\n"
        "SELECT ___          -- Which columns do you need?\n"
        "FROM ___             -- What is the main table?\n"
        "JOIN ___ ON ___      -- Do you need to join another table? On which key?\n"
        "WHERE ___            -- What condition filters the rows?\n"
        "GROUP BY ___         -- Are you aggregating? Group by which columns?\n"
        "HAVING ___           -- Any condition on the aggregated result?\n"
        "ORDER BY ___         -- How should results be sorted?\n"
        "```\n\n"
        "Think about:\n"
        "1. Which columns does the problem ask you to show?\n"
        "2. Which table(s) contain those columns?\n"
        "3. How are the tables related (foreign keys)?\n"
        "4. What filtering or aggregation does the problem require?"
    )

    return {
        "hint_level": 4,
        "hint_type": "code_template",
        "hint_text": hint_text,
        "pedagogical_rationale": (
            "Level 4 (Solution Scaffold): Providing a SQL template with blanks. "
            "The student must think about the correct tables, columns, conditions, "
            "and joins to fill in."
        ),
        "follow_up_question": (
            "Start with SELECT and FROM — which columns and tables do you need? "
            "Then decide whether a JOIN is necessary."
        ),
    }
