import csv
import re
import random
import os

RANDOM_SEED = 42

input_file = "sql-problem/Practice-Assignment-Bike shop-2025.csv"
output_file = "sql-problem/Evaluation-Dataset-Bike-shop-2025.csv"


def _strip_semicolons(q: str) -> str:
    """Strip trailing whitespace and semicolons from a SQL query."""
    return q.rstrip("; \t\n\r")


error_scenarios = [
    {
        "type": "syntax_error",
        "mod": lambda q: re.sub(
            r"\bSELECT\b",
            "SELCT",
            _strip_semicolons(q),
            count=1,
            flags=re.IGNORECASE,
        ),
        "msg": 'syntax error at or near "SELCT"',
        "clause": "SELECT",
        "keywords": ["syntax", "keyword", "SELECT"],
        "topics": ["SQL Syntax", "Basic Queries"],
        "hint": "Check the spelling of your SQL keywords, particularly SELECT.",
    },
    {
        "type": "column_error",
        "mod": lambda q: re.sub(
            r"\bFROM\b",
            ", non_existent_col FROM",
            _strip_semicolons(q),
            count=1,
            flags=re.IGNORECASE,
        ),
        "msg": 'column "non_existent_col" does not exist',
        "clause": "SELECT",
        "keywords": ["column", "exist", "schema"],
        "topics": ["Schema", "Columns", "Tables"],
        "hint": "Ensure all columns in your SELECT clause actually exist in the table schema.",
    },
    {
        "type": "relation_error",
        "mod": lambda q: re.sub(
            r"\bFROM\s+(\w)",
            r"FROM fake_schema.\1",
            _strip_semicolons(q),
            count=1,
            flags=re.IGNORECASE,
        ),
        "msg": "relation does not exist",
        "clause": "FROM",
        "keywords": ["table", "relation", "FROM"],
        "topics": ["Tables", "FROM clause"],
        "hint": "Check the table name and schema in your FROM clause.",
    },
    {
        "type": "aggregation_error",
        "mod": lambda q: re.sub(
            r"\bSELECT\s+(?:DISTINCT\s+)?",
            "SELECT COUNT(*), ",
            _strip_semicolons(q),
            count=1,
            flags=re.IGNORECASE,
        ),
        "msg": "column must appear in the GROUP BY clause or be used in an aggregate function",
        "clause": "GROUP BY",
        "keywords": ["group by", "aggregate", "function"],
        "topics": ["Aggregation", "GROUP BY"],
        "hint": "Make sure all non-aggregated columns are included in your GROUP BY clause.",
    },
]


def main():
    random.seed(RANDOM_SEED)

    if not os.path.exists(input_file):
        print(f"Input file not found: {input_file}")
        return

    with open(input_file, "r", encoding="utf-8-sig") as f_in, open(
        output_file, "w", encoding="utf-8", newline=""
    ) as f_out:

        reader = csv.DictReader(f_in)
        headers = reader.fieldnames

        # Try to identify the correct columns based on the file contents
        q_col = next((h for h in headers if h and "question" in h.lower()), headers[0])
        a_col = next(
            (h for h in headers if h and "answer" in h.lower()),
            headers[1] if len(headers) > 1 else headers[0],
        )

        out_fieldnames = [
            "sample_id",
            "error_type",
            "student_query",
            "error_message",
            "problem_description",
            "hint_level",
            "attempt_count",
            "expected_hint_keywords",
            "expected_rag_topics",
            "ground_truth_hint",
            "reference_answer",
            "problematic_clause",
        ]
        writer = csv.DictWriter(f_out, fieldnames=out_fieldnames)
        writer.writeheader()

        count = 0
        for idx, row in enumerate(reader, start=1):
            q_text = row.get(q_col, "").strip()
            a_text = row.get(a_col, "").strip()

            if not q_text and not a_text:
                continue

            # 25% distribution across the four error types (syntax, column, relation, aggregation).
            scenario = random.choice(error_scenarios)
            student_query = scenario["mod"](a_text)

            # If the modifier didn't change anything, corrupt the SELECT keyword as a safe fallback
            if student_query == _strip_semicolons(a_text):
                student_query = _strip_semicolons(a_text) + " INVALID_SYNTAX"

            writer.writerow(
                {
                    "sample_id": f"eval_csv_{idx:02d}",
                    "error_type": scenario["type"],
                    "student_query": student_query,
                    "error_message": scenario["msg"],
                    "problem_description": q_text,
                    "hint_level": random.randint(1, 4),
                    "attempt_count": 1,
                    "expected_hint_keywords": ",".join(scenario["keywords"]),
                    "expected_rag_topics": ",".join(scenario["topics"]),
                    "ground_truth_hint": scenario["hint"],
                    "reference_answer": a_text,
                    "problematic_clause": scenario["clause"],
                }
            )
            count += 1

    print(f"Successfully generated {output_file} with {count} records.")


if __name__ == "__main__":
    main()
