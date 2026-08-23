"""
Gold-query audit — the grading-correctness gate.

For every gold in the problem CSV: execute it, then self-grade it as if it
were a student's answer (student query == gold query). A gold that doesn't
execute, or that fails its own grading pass, means students who write the
textbook-correct answer will be marked wrong — this must be 24/24 green
before any downstream work (endpoint split, load testing, ...) is trusted.

Usage: python -m scripts.gold_audit [--output gold_audit.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tools.code_executor import MAX_RESULT_ROWS, execute_sql
from backend.tools.test_runner import run_sql_tests

CSV_PATH = (
    Path(__file__).resolve().parents[1]
    / "sql-problem"
    / "Practice-Assignment-Bike shop-2025.csv"
)


def audit_gold(seq: str, kind: str, query: str) -> dict:
    result = execute_sql(query)

    row = {
        "seq": seq,
        "kind": kind,
        "query": query.replace("\n", " ").strip()[:100],
        "executes": result["success"],
        "error_type": result.get("error_type"),
        "row_count": result.get("row_count"),
        "truncated": result.get("truncated"),
        "exceeds_max_rows": (result.get("row_count") or 0) >= MAX_RESULT_ROWS,
        "has_order_by": "ORDER BY" in query.upper(),
        "self_grade_passed": None,
    }

    if not result["success"]:
        return row

    check_order = row["has_order_by"]
    grading = run_sql_tests(
        query,
        [{"test_case_id": 1, "expected_query": query, "check_order": check_order}],
    )
    row["self_grade_passed"] = grading["passed"]
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="gold_audit.csv")
    args = parser.parse_args()

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)

    audit_rows: list[dict] = []
    for r in csv_rows:
        seq = str(r.get("ลำดับ", "")).strip()
        for col, kind in [("Practice Answer", "practice"), ("Assignment Answer", "assignment")]:
            query = (r.get(col) or "").strip()
            if not query or query.lower() in ("nan", "none"):
                continue
            audit_rows.append(audit_gold(seq, kind, query))

    if audit_rows:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()))
            writer.writeheader()
            writer.writerows(audit_rows)

    total = len(audit_rows)
    executes = sum(1 for r in audit_rows if r["executes"])
    self_passes = sum(1 for r in audit_rows if r["self_grade_passed"])
    exceeds = sum(1 for r in audit_rows if r["exceeds_max_rows"])
    truncated = sum(1 for r in audit_rows if r["truncated"])

    print(f"Golds audited: {total}")
    print(f"  Execute successfully : {executes}/{total}")
    print(f"  Self-grade PASS      : {self_passes}/{total}")
    print(f"  >= MAX_RESULT_ROWS   : {exceeds}")
    print(f"  Truncated            : {truncated}")
    print(f"Report written to {args.output}")

    if executes != total or self_passes != total:
        print("\nGATE FAILED — not every gold executes and self-grades PASS.")
        for r in audit_rows:
            if not r["executes"] or not r["self_grade_passed"]:
                print(f"  [{r['seq']} {r['kind']}] executes={r['executes']} "
                      f"self_grade_passed={r['self_grade_passed']} error={r['error_type']}")
        sys.exit(1)

    print("\nGATE PASSED — 24/24 golds execute and self-grade correctly.")


if __name__ == "__main__":
    main()
