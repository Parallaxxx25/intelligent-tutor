import csv
import random
import os

input_file = "sql-problem/Practice-Assignment-Bike shop-2025.csv"
output_file = "sql-problem/Evaluation-Dataset-Bike-shop-2025.csv"

error_scenarios = [
    {
        "type": "syntax_error",
        "mod": lambda q: (
            q.replace("SELECT", "SELCT", 1) if "SELECT" in q else q + " SYNTAX ERROR"
        ),
        "msg": 'syntax error at or near "SELCT"',
        "clause": "SELECT",
        "keywords": ["syntax", "keyword", "SELECT"],
        "topics": ["SQL Syntax", "Basic Queries"],
        "hint": "Check the spelling of your SQL keywords, particularly SELECT.",
    },
    {
        "type": "column_error",
        "mod": lambda q: (
            q.replace(" FROM", " , non_existent_col FROM", 1) if " FROM" in q else q
        ),
        "msg": 'column "non_existent_col" does not exist',
        "clause": "SELECT",
        "keywords": ["column", "exist", "schema"],
        "topics": ["Schema", "Columns", "Tables"],
        "hint": "Ensure all columns in your SELECT clause actually exist in the table schema.",
    },
    {
        "type": "table_error",
        "mod": lambda q: (
            q.replace("FROM ", "FROM fake_schema.", 1) if "FROM " in q else q
        ),
        "msg": "relation does not exist",
        "clause": "FROM",
        "keywords": ["table", "relation", "FROM"],
        "topics": ["Tables", "FROM clause"],
        "hint": "Check the table name and schema in your FROM clause.",
    },
    {
        "type": "grouping_error",
        "mod": lambda q: (
            q.replace("GROUP BY", "ORDER BY", 1)
            if "GROUP BY" in q
            else q + " GROUP BY missing_col"
        ),
        "msg": "column must appear in the GROUP BY clause or be used in an aggregate function",
        "clause": "GROUP BY",
        "keywords": ["group by", "aggregate", "function"],
        "topics": ["Aggregation", "GROUP BY"],
        "hint": "Make sure all non-aggregated columns are included in your GROUP BY clause.",
    },
]


def main():
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

            scenario = random.choice(
                error_scenarios
            )  # 25% distribution across the four error types (syntax, column, table, grouping).
            student_query = scenario["mod"](a_text)

            # If the modifier didn't change anything, try to append an error
            if student_query == a_text:
                student_query = a_text.rstrip(";") + " LIMIT -1;"

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
