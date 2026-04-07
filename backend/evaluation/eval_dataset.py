"""
RAGAS Evaluation Dataset — Ground-truth samples for RAG pipeline evaluation.

Each sample maps to one of the 11 SQL error taxonomy categories, with
expected hints at various scaffolding levels (1–4).

The dataset provides the data needed for RAGAS metrics:
  - user_input     : The student question/error context
  - response       : Expected hint text (ground truth)
  - retrieved_contexts : Expected RAG documents
  - reference      : Ideal reference answer

Version: 2026-03-27
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalSample:
    """One evaluation sample for RAGAS scoring."""

    sample_id: str
    error_type: str
    student_query: str
    error_message: str
    problem_description: str
    hint_level: int
    attempt_count: int
    expected_hint_keywords: list[str] = field(default_factory=list)
    expected_rag_topics: list[str] = field(default_factory=list)
    ground_truth_hint: str = ""
    reference_answer: str = ""
    problematic_clause: str | None = None


# ---------------------------------------------------------------------------
# Evaluation dataset: 15 samples covering all 11 error taxonomy categories
# ---------------------------------------------------------------------------

EVAL_DATASET: list[EvalSample] = [
    # 1. syntax_error — Level 1 (Attention)
    EvalSample(
        sample_id="syntax_01",
        error_type="syntax_error",
        student_query="SELECT first_name last_name FROM sales.customers;",
        error_message="syntax error at or near 'last_name'",
        problem_description="List all customer first and last names.",
        hint_level=1,
        attempt_count=1,
        expected_hint_keywords=["SELECT", "comma", "clause"],
        expected_rag_topics=["select_basics"],
        ground_truth_hint=(
            "Take a closer look at your SELECT clause. "
            "Are all your column names separated correctly?"
        ),
        reference_answer=(
            "You're missing a comma between first_name and last_name in your "
            "SELECT clause. Add a comma: SELECT first_name, last_name FROM sales.customers;"
        ),
        problematic_clause="SELECT",
    ),

    # 2. column_error — Level 2 (Category)
    EvalSample(
        sample_id="column_01",
        error_type="column_error",
        student_query="SELECT full_name FROM sales.customers;",
        error_message="column 'full_name' does not exist",
        problem_description="List all customer names.",
        hint_level=2,
        attempt_count=2,
        expected_hint_keywords=["column", "does not exist", "name"],
        expected_rag_topics=["select_basics", "database_schema"],
        ground_truth_hint=(
            "You're referencing a column that doesn't exist in the table. "
            "The customers table uses first_name and last_name, not full_name."
        ),
        reference_answer=(
            "The column 'full_name' does not exist in sales.customers. "
            "Use first_name and last_name instead."
        ),
        problematic_clause="SELECT",
    ),

    # 3. relation_error — Level 1 (Attention)
    EvalSample(
        sample_id="relation_01",
        error_type="relation_error",
        student_query="SELECT * FROM sales.customer;",
        error_message="relation 'sales.customer' does not exist",
        problem_description="Show all customer data.",
        hint_level=1,
        attempt_count=1,
        expected_hint_keywords=["table", "name", "FROM"],
        expected_rag_topics=["database_schema"],
        ground_truth_hint=(
            "Look at your FROM clause carefully. "
            "Is the table name spelled correctly?"
        ),
        reference_answer=(
            "The table name is 'sales.customers' (plural), "
            "not 'sales.customer'."
        ),
        problematic_clause="FROM",
    ),

    # 4. join_error — Level 3 (Concept)
    EvalSample(
        sample_id="join_01",
        error_type="join_error",
        student_query=(
            "SELECT o.order_id, c.first_name "
            "FROM sales.orders o, sales.customers c;"
        ),
        error_message="missing FROM-clause entry for table",
        problem_description="List orders with customer first names.",
        hint_level=3,
        attempt_count=3,
        expected_hint_keywords=["JOIN", "ON", "condition"],
        expected_rag_topics=["joins"],
        ground_truth_hint=(
            "When combining tables, use an explicit JOIN with an ON condition. "
            "Here's a similar example:\n"
            "SELECT e.name, d.name FROM employees e "
            "JOIN departments d ON e.department_id = d.id;"
        ),
        reference_answer=(
            "Use JOIN with ON: SELECT o.order_id, c.first_name "
            "FROM sales.orders o "
            "JOIN sales.customers c ON o.customer_id = c.customer_id;"
        ),
        problematic_clause="JOIN",
    ),

    # 5. aggregation_error — Level 2 (Category)
    EvalSample(
        sample_id="agg_01",
        error_type="aggregation_error",
        student_query=(
            "SELECT store_id, product_name, COUNT(*) "
            "FROM production.products GROUP BY store_id;"
        ),
        error_message="column 'product_name' must appear in GROUP BY clause or aggregate",
        problem_description="Count products per store.",
        hint_level=2,
        attempt_count=2,
        expected_hint_keywords=["GROUP BY", "aggregate", "column"],
        expected_rag_topics=["group_by", "aggregate_functions"],
        ground_truth_hint=(
            "You have a GROUP BY error. Every column in SELECT must either "
            "appear in GROUP BY or be wrapped in an aggregate function."
        ),
        reference_answer=(
            "Remove product_name from SELECT or add it to GROUP BY. "
            "Since you want a count per store, just SELECT store_id, COUNT(*)."
        ),
        problematic_clause="GROUP BY",
    ),

    # 6. subquery_error — Level 3 (Concept)
    EvalSample(
        sample_id="subquery_01",
        error_type="subquery_error",
        student_query=(
            "SELECT * FROM sales.orders "
            "WHERE customer_id = (SELECT customer_id FROM sales.customers WHERE state = 'NY');"
        ),
        error_message="more than one row returned by a subquery used as an expression",
        problem_description="Find orders from New York customers.",
        hint_level=3,
        attempt_count=3,
        expected_hint_keywords=["subquery", "IN", "multiple rows"],
        expected_rag_topics=["subqueries"],
        ground_truth_hint=(
            "When a subquery can return multiple rows, use IN instead of =. "
            "Example: WHERE id IN (SELECT id FROM table WHERE condition);"
        ),
        reference_answer=(
            "Use IN instead of =: WHERE customer_id IN "
            "(SELECT customer_id FROM sales.customers WHERE state = 'NY');"
        ),
        problematic_clause="subquery",
    ),

    # 7. type_error — Level 1 (Attention)
    EvalSample(
        sample_id="type_01",
        error_type="type_error",
        student_query="SELECT * FROM production.products WHERE list_price = 'expensive';",
        error_message="invalid input syntax for type numeric: 'expensive'",
        problem_description="Find expensive products.",
        hint_level=1,
        attempt_count=1,
        expected_hint_keywords=["type", "numeric", "WHERE"],
        expected_rag_topics=["data_types", "where_clause"],
        ground_truth_hint=(
            "Look at your WHERE clause. The comparison value doesn't match "
            "the column's data type."
        ),
        reference_answer=(
            "list_price is a numeric column. Use a number instead of a string: "
            "WHERE list_price > 1000;"
        ),
        problematic_clause="WHERE",
    ),

    # 8. logic_error — Level 4 (Solution scaffold)
    EvalSample(
        sample_id="logic_01",
        error_type="logic_error",
        student_query=(
            "SELECT c.first_name, c.last_name "
            "FROM sales.customers c "
            "WHERE c.city = 'New York';"
        ),
        error_message="Query runs but returns wrong results. Expected customers who placed orders.",
        problem_description="List customers from New York who have placed at least one order.",
        hint_level=4,
        attempt_count=4,
        expected_hint_keywords=["JOIN", "orders", "template", "___"],
        expected_rag_topics=["joins", "where_clause"],
        ground_truth_hint=(
            "Here's a template to help:\n"
            "SELECT ___\n"
            "FROM sales.customers c\n"
            "JOIN ___ ON ___\n"
            "WHERE c.city = '___';"
        ),
        reference_answer=(
            "You need to JOIN with sales.orders to filter for customers who "
            "have placed orders: JOIN sales.orders o ON c.customer_id = o.customer_id"
        ),
        problematic_clause="FROM",
    ),

    # 9. ambiguity_error — Level 2 (Category)
    EvalSample(
        sample_id="ambiguity_01",
        error_type="ambiguity_error",
        student_query=(
            "SELECT order_id, first_name "
            "FROM sales.orders "
            "JOIN sales.customers ON orders.customer_id = customers.customer_id;"
        ),
        error_message="column reference 'order_id' is ambiguous",
        problem_description="List orders with customer names.",
        hint_level=2,
        attempt_count=2,
        expected_hint_keywords=["ambiguous", "alias", "qualify"],
        expected_rag_topics=["joins"],
        ground_truth_hint=(
            "You have an ambiguous column reference. When joining tables that share "
            "column names, prefix each column with the table name or alias."
        ),
        reference_answer=(
            "Use table aliases: SELECT o.order_id, c.first_name "
            "FROM sales.orders o JOIN sales.customers c ON o.customer_id = c.customer_id;"
        ),
        problematic_clause="SELECT",
    ),

    # 10. timeout_error — Level 1 (Attention)
    EvalSample(
        sample_id="timeout_01",
        error_type="timeout_error",
        student_query=(
            "SELECT * FROM sales.orders, production.products;"
        ),
        error_message="statement timeout — query exceeded time limit",
        problem_description="List orders with product details.",
        hint_level=1,
        attempt_count=1,
        expected_hint_keywords=["timeout", "Cartesian", "JOIN"],
        expected_rag_topics=["joins"],
        ground_truth_hint=(
            "Your query is taking too long because you're creating a "
            "Cartesian product. Check your FROM clause for missing JOIN conditions."
        ),
        reference_answer=(
            "Add proper JOINs: FROM sales.orders o "
            "JOIN sales.order_items oi ON o.order_id = oi.order_id "
            "JOIN production.products p ON oi.product_id = p.product_id;"
        ),
        problematic_clause="FROM",
    ),

    # 11. no_error — Correct query
    EvalSample(
        sample_id="no_error_01",
        error_type="no_error",
        student_query="SELECT first_name, last_name FROM sales.customers;",
        error_message="",
        problem_description="List all customer first and last names.",
        hint_level=0,
        attempt_count=1,
        expected_hint_keywords=["correct", "Great job", "Well done"],
        expected_rag_topics=[],
        ground_truth_hint=(
            "Great job! Your SQL query is correct and returns the expected results."
        ),
        reference_answer="The query is correct. No changes needed.",
    ),

    # 12. syntax_error — Level 4 (high attempts)
    EvalSample(
        sample_id="syntax_02",
        error_type="syntax_error",
        student_query="SELECT * sales.customers;",
        error_message="syntax error at or near 'sales'",
        problem_description="Show all customers.",
        hint_level=4,
        attempt_count=5,
        expected_hint_keywords=["FROM", "template", "SELECT"],
        expected_rag_topics=["select_basics", "execution_order"],
        ground_truth_hint=(
            "Here's a template:\n"
            "SELECT ___ FROM ___;\n"
            "What keyword is missing between SELECT and the table name?"
        ),
        reference_answer="Missing FROM keyword: SELECT * FROM sales.customers;",
        problematic_clause="SELECT",
    ),

    # 13. join_error — Level 2
    EvalSample(
        sample_id="join_02",
        error_type="join_error",
        student_query=(
            "SELECT p.product_name, b.brand_name "
            "FROM production.products p "
            "JOIN production.brands b ON p.product_id = b.brand_id;"
        ),
        error_message="Wrong results — join key mismatch",
        problem_description="List products with their brand names.",
        hint_level=2,
        attempt_count=2,
        expected_hint_keywords=["JOIN", "ON", "column", "foreign key"],
        expected_rag_topics=["joins", "database_schema"],
        ground_truth_hint=(
            "Your JOIN condition uses the wrong columns. The ON clause must use "
            "the foreign key that actually connects the two tables."
        ),
        reference_answer=(
            "Use the correct FK: JOIN production.brands b ON p.brand_id = b.brand_id;"
        ),
        problematic_clause="JOIN",
    ),

    # 14. aggregation_error — Level 3
    EvalSample(
        sample_id="agg_02",
        error_type="aggregation_error",
        student_query=(
            "SELECT category_id, AVG(list_price) "
            "FROM production.products "
            "WHERE AVG(list_price) > 500 "
            "GROUP BY category_id;"
        ),
        error_message="aggregate functions are not allowed in WHERE",
        problem_description="Find categories with average price above $500.",
        hint_level=3,
        attempt_count=3,
        expected_hint_keywords=["HAVING", "WHERE", "aggregate"],
        expected_rag_topics=["having", "group_by", "aggregate_functions"],
        ground_truth_hint=(
            "Aggregate functions like AVG() cannot be used in WHERE. "
            "Example:\n"
            "SELECT dept, AVG(salary) FROM employees "
            "GROUP BY dept HAVING AVG(salary) > 50000;"
        ),
        reference_answer=(
            "Use HAVING instead of WHERE for aggregate conditions: "
            "HAVING AVG(list_price) > 500;"
        ),
        problematic_clause="GROUP BY",
    ),

    # 15. logic_error — Level 1
    EvalSample(
        sample_id="logic_02",
        error_type="logic_error",
        student_query=(
            "SELECT product_name, list_price "
            "FROM production.products "
            "WHERE list_price > 0;"
        ),
        error_message=(
            "Query runs but returns too many rows. "
            "Expected only products with orders."
        ),
        problem_description="List products that have been ordered at least once.",
        hint_level=1,
        attempt_count=1,
        expected_hint_keywords=["WHERE", "condition", "orders"],
        expected_rag_topics=["joins", "subqueries", "where_clause"],
        ground_truth_hint=(
            "Your query returns all products, but the problem asks only for "
            "products that have been ordered. Think about which table tracks orders."
        ),
        reference_answer=(
            "Add a subquery or JOIN to filter for ordered products: "
            "WHERE product_id IN (SELECT product_id FROM sales.order_items);"
        ),
        problematic_clause="WHERE",
    ),
]


def get_error_type_coverage() -> dict[str, int]:
    """Return a dict mapping each error_type to its count in the dataset."""
    coverage: dict[str, int] = {}
    for s in EVAL_DATASET:
        coverage[s.error_type] = coverage.get(s.error_type, 0) + 1
    return coverage


def get_hint_level_distribution() -> dict[int, int]:
    """Return a dict mapping each hint_level to its count in the dataset."""
    dist: dict[int, int] = {}
    for s in EVAL_DATASET:
        dist[s.hint_level] = dist.get(s.hint_level, 0) + 1
    return dist


def _safe_int(value: str, default: int, field_name: str, sample_id: str) -> int:
    """Coerce *value* to int, falling back to *default* with a clear warning."""
    try:
        return int(value)
    except (ValueError, TypeError):
        print(
            f"Warning: invalid {field_name!r} value {value!r} for sample {sample_id!r}; "
            f"defaulting to {default}."
        )
        return default


def load_eval_dataset_from_csv(csv_path: str) -> list[EvalSample]:
    """Load evaluation dataset from a CSV file."""
    dataset = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):  # row 1 is the header
            sample_id = row.get("sample_id", f"row_{row_num}")
            dataset.append(EvalSample(
                sample_id=sample_id,
                error_type=row.get("error_type", ""),
                student_query=row.get("student_query", ""),
                error_message=row.get("error_message", ""),
                problem_description=row.get("problem_description", ""),
                hint_level=_safe_int(row.get("hint_level", ""), 1, "hint_level", sample_id),
                attempt_count=_safe_int(row.get("attempt_count", ""), 1, "attempt_count", sample_id),
                expected_hint_keywords=[k.strip() for k in row.get("expected_hint_keywords", "").split(",") if k.strip()],
                expected_rag_topics=[k.strip() for k in row.get("expected_rag_topics", "").split(",") if k.strip()],
                ground_truth_hint=row.get("ground_truth_hint", ""),
                reference_answer=row.get("reference_answer", ""),
                problematic_clause=row.get("problematic_clause", None)
            ))
    return dataset
