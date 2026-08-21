"""
Few-shot exemplars for LLM diagnosis and hint generation.

Kept separate from supervisor.py so prompt tuning doesn't require touching
pipeline logic.
"""

# Few-shot exemplars for LLM diagnosis (kept short to limit token cost).
DIAGNOSIS_FEW_SHOT = """\
EXAMPLES:

Example 1
STUDENT QUERY: SELECT product_name, list_price FROM products WHERE list_prices > 100;
ERROR MESSAGE: column "list_prices" does not exist
OUTPUT: {"error_type": "column_error", "error_message": "The column list_prices does not exist; the products table uses list_price (singular).", "problematic_clause": "WHERE", "severity": "low", "recommended_hint_level": 1, "pedagogical_rationale": "First attempt with a simple typo — pointing at the clause is enough."}

Example 2
STUDENT QUERY: SELECT b.brand_name, COUNT(*) FROM products p JOIN brands b ON p.brand_id = b.brand_id;
ERROR MESSAGE: column "b.brand_name" must appear in the GROUP BY clause or be used in an aggregate function
OUTPUT: {"error_type": "aggregation_error", "error_message": "brand_name is selected alongside COUNT(*) but never grouped, so Postgres cannot decide which row to show per group.", "problematic_clause": "GROUP BY", "severity": "medium", "recommended_hint_level": 2, "pedagogical_rationale": "Second attempt — naming the error category guides without solving it."}

Example 3
STUDENT QUERY: SELECT o.order_id, c.first_name FROM orders o, customers c;
ERROR MESSAGE: (no error — wrong result set, 8000+ rows returned)
OUTPUT: {"error_type": "join_error", "error_message": "The two tables are cross-joined with no join predicate, producing a Cartesian product instead of matching each order to its customer.", "problematic_clause": "FROM", "severity": "high", "recommended_hint_level": 3, "pedagogical_rationale": "Third attempt on a conceptual gap — a parallel example is warranted."}
"""

# Few-shot exemplars for hint generation, one per scaffolding level.
HINT_FEW_SHOT = """\
EXAMPLES (note how specificity grows with the level — never past a template):

Example — LEVEL 1 (Attention)
DIAGNOSIS: column_error on WHERE
HINT: Nice work getting the query structure down! Take another look at your WHERE clause — one of the column names there doesn't match what the table actually offers. What does the products table call its price column?

Example — LEVEL 2 (Category)
DIAGNOSIS: aggregation_error on GROUP BY
HINT: You're close! This is a grouping problem: whenever you mix a plain column with an aggregate like COUNT(), SQL needs to know how to bucket the rows. Every non-aggregated column in your SELECT has to appear in GROUP BY. Which column in your SELECT isn't aggregated?

Example — LEVEL 3 (Concept)
DIAGNOSIS: join_error on FROM
HINT: Good instinct pulling from both tables. Here's the same idea on a different pair — counting staff per store:
```sql
SELECT s.store_name, COUNT(*)
FROM staffs st
JOIN stores s ON st.store_id = s.store_id
GROUP BY s.store_name;
```
Notice the ON clause states which columns must match. What column do your two tables share?

Example — LEVEL 4 (Solution Scaffold)
DIAGNOSIS: subquery_error on WHERE
HINT: Let's build it together — fill in the blanks:
```sql
SELECT product_name
FROM products
WHERE list_price > (
    SELECT ___(list_price)
    FROM ___
);
```
The inner query has to collapse to a single value before the comparison works. Which aggregate gives you that?
"""
