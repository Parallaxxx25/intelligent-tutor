"""
One-shot repair of the gold-standard queries in the problem CSV.

The catalog was authored for MySQL (single-quoted aliases, backtick
identifiers, `" "` string literals); the grader runs on PostgreSQL. This
script:

  1. Hand-fixes the one gold with a missing comma (ROW3 Assignment Answer —
     sqlglot silently accepts `product_id\\n quantity` as an implicit alias,
     so this can't be caught by transpiling; it has to be fixed by hand).
  2. For every other gold cell, executes it against the real database. If it
     already runs, it's left byte-for-byte untouched. If it fails, retries
     via ``sqlglot.transpile(read="mysql", write="postgres")`` and keeps the
     transpiled text only if *that* then executes successfully.

Only touches cells that are actually broken — this is a repair, not a
reformat. Run it, then eyeball the diff (`git diff sql-problem/`) before
committing; #16 is a manual hand-fix, everything else is machine-verified
against the live database.

Usage: python -m scripts.repair_golds
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlglot

from backend.tools.code_executor import execute_sql

CSV_PATH = (
    Path(__file__).resolve().parents[1]
    / "sql-problem"
    / "Practice-Assignment-Bike shop-2025.csv"
)

GOLD_COLUMNS = ["Practice Answer", "Assignment Answer"]

# Hand-fix: ROW index 3 (0-based, matching csv.DictReader row order),
# "Assignment Answer" column — missing comma after `product_id` makes
# sqlglot silently read it as `product_id AS quantity` instead of erroring,
# so it can't be caught by the automated execute-then-transpile pass below.
_HAND_FIXES = {
    (3, "Assignment Answer"): (
        "SELECT \n"
        "    item_id, product_id,\n"
        "    quantity, list_price,\n"
        "    (quantity * list_price) - (quantity * discount) AS `net_price`\n"
        "FROM order_items;"
    ),
}


def repair_query(query: str) -> tuple[str, str]:
    """Return (repaired_query, status) where status is one of:
    'unchanged' (already valid Postgres), 'transpiled' (fixed via sqlglot),
    'unfixable' (still broken — needs a manual look)."""
    if not query.strip():
        return query, "unchanged"

    result = execute_sql(query)
    if result["success"]:
        return query, "unchanged"

    try:
        transpiled = sqlglot.transpile(query, read="mysql", write="postgres")[0]
    except Exception:
        return query, "unfixable"

    retry = execute_sql(transpiled)
    if retry["success"]:
        return transpiled, "transpiled"
    return query, "unfixable"


def main() -> None:
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    changes: list[tuple[int, str, str, str]] = []  # (row, col, old, new)

    for idx, row in enumerate(rows):
        for col in GOLD_COLUMNS:
            original = (row.get(col) or "").strip()
            if not original:
                continue

            # Apply the hand-fix (if any) first, then still run it through
            # the normal execute-then-transpile pass below — the hand-fix
            # only corrects the one thing sqlglot can't catch (a missing
            # comma), it doesn't also fix any remaining dialect syntax.
            working = _HAND_FIXES.get((idx, col), original)

            fixed, status = repair_query(working)
            if status == "unfixable":
                print(f"UNFIXABLE — row {idx} [{col}]: {original[:80]!r}")
            elif fixed != original:
                changes.append((idx, col, original, fixed))
                row[col] = fixed

    if not changes:
        print("No changes needed — all golds already execute cleanly.")
        return

    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Repaired {len(changes)} cell(s):\n")
    for idx, col, old, new in changes:
        print(f"row {idx} [{col}]")
        print(f"  old: {old!r}")
        print(f"  new: {new!r}\n")


if __name__ == "__main__":
    main()
