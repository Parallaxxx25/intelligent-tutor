"""
SQL Knowledge Base — Concept documents for RAG.

Each document covers one SQL topic with:
  - topic : short identifier
  - title : human-readable name
  - content : markdown explanation with examples
  - common_mistakes : typical student errors
  - keywords : for metadata filtering

Version: 2026-02-13
"""

from __future__ import annotations

SQL_KNOWLEDGE_DOCS: list[dict[str, str]] = [
    # ------------------------------------------------------------------
    # 1. SELECT Basics
    # ------------------------------------------------------------------
    {
        "topic": "select_basics",
        "title": "SELECT — Choosing Columns",
        "content": (
            "The SELECT clause specifies which columns to include in the result set.\n\n"
            "## Syntax\n"
            "```sql\n"
            "SELECT column1, column2 FROM table_name;\n"
            "SELECT * FROM table_name;  -- all columns\n"
            "```\n\n"
            "## Key Concepts\n"
            "- Use `SELECT *` sparingly — always prefer naming specific columns.\n"
            "- Column aliases rename output columns: `SELECT name AS employee_name`.\n"
            "- Expressions are allowed: `SELECT price * quantity AS total`.\n"
            "- `SELECT DISTINCT` removes duplicate rows.\n"
        ),
        "common_mistakes": (
            "- Forgetting commas between column names.\n"
            "- Using `SELECT *` when only specific columns are needed.\n"
            "- Not aliasing computed columns, resulting in unnamed output.\n"
        ),
        "keywords": "select columns alias distinct expression",
    },
    # ------------------------------------------------------------------
    # 2. WHERE Clause
    # ------------------------------------------------------------------
    {
        "topic": "where_clause",
        "title": "WHERE — Filtering Rows",
        "content": (
            "The WHERE clause filters rows based on conditions.\n\n"
            "## Syntax\n"
            "```sql\n"
            "SELECT * FROM employees WHERE salary > 50000;\n"
            "SELECT * FROM products WHERE category = 'Electronics' AND price < 100;\n"
            "```\n\n"
            "## Operators\n"
            "| Operator | Meaning |\n"
            "|----------|----------|\n"
            "| `=`      | Equal |\n"
            "| `<>`, `!=` | Not equal |\n"
            "| `>`, `<`, `>=`, `<=` | Comparison |\n"
            "| `BETWEEN a AND b` | Range (inclusive) |\n"
            "| `IN (v1, v2)` | Match any value in list |\n"
            "| `LIKE '%pattern%'` | Pattern matching |\n"
            "| `IS NULL` / `IS NOT NULL` | NULL checks |\n\n"
            "## Key Concepts\n"
            "- WHERE filters rows BEFORE grouping (vs HAVING which filters AFTER).\n"
            "- You cannot use column aliases in WHERE — use the original expression.\n"
            "- Use `AND` / `OR` to combine conditions; use parentheses for clarity.\n"
        ),
        "common_mistakes": (
            "- Using `= NULL` instead of `IS NULL`.\n"
            "- Forgetting quotes around string literals: `WHERE name = Sales` vs `WHERE name = 'Sales'`.\n"
            "- Confusing `AND` and `OR` precedence — use parentheses.\n"
            "- Using aggregate functions in WHERE instead of HAVING.\n"
        ),
        "keywords": "where filter condition comparison operator and or between in like null",
    },
    # ------------------------------------------------------------------
    # 3. JOINs
    # ------------------------------------------------------------------
    {
        "topic": "joins",
        "title": "JOIN — Combining Tables",
        "content": (
            "JOINs combine rows from two or more tables based on related columns.\n\n"
            "## Types\n"
            "```sql\n"
            "-- INNER JOIN: only matching rows from both tables\n"
            "SELECT e.name, d.name FROM employees e\n"
            "INNER JOIN departments d ON e.department_id = d.id;\n\n"
            "-- LEFT JOIN: all rows from left table + matching from right\n"
            "SELECT e.name, d.name FROM employees e\n"
            "LEFT JOIN departments d ON e.department_id = d.id;\n\n"
            "-- RIGHT JOIN: all rows from right table + matching from left\n"
            "-- FULL OUTER JOIN: all rows from both tables\n"
            "-- CROSS JOIN: Cartesian product (every combination)\n"
            "```\n\n"
            "## Key Concepts\n"
            "- Always specify the ON condition — without it you get a Cartesian product.\n"
            "- Use table aliases (e, d) for readability.\n"
            "- Self-JOIN: join a table to itself (e.g., employees and their managers).\n"
            "- Multiple JOINs: chain them sequentially.\n"
        ),
        "common_mistakes": (
            "- Missing ON clause → Cartesian product (huge result, timeouts).\n"
            "- Wrong column in ON clause → incorrect matches.\n"
            "- Using comma syntax `FROM a, b` without WHERE condition.\n"
            "- Not using table aliases → ambiguous column errors.\n"
            "- Confusing INNER JOIN vs LEFT JOIN — INNER drops unmatched rows.\n"
        ),
        "keywords": "join inner left right full outer cross on cartesian product foreign key",
    },
    # ------------------------------------------------------------------
    # 4. GROUP BY
    # ------------------------------------------------------------------
    {
        "topic": "group_by",
        "title": "GROUP BY — Grouping Rows for Aggregation",
        "content": (
            "GROUP BY groups rows that share values in specified columns, enabling "
            "aggregate calculations per group.\n\n"
            "## Syntax\n"
            "```sql\n"
            "SELECT department, COUNT(*) AS emp_count\n"
            "FROM employees\n"
            "GROUP BY department;\n"
            "```\n\n"
            "## The Golden Rule\n"
            "Every column in SELECT must either:\n"
            "1. Appear in GROUP BY, **or**\n"
            "2. Be wrapped in an aggregate function (COUNT, SUM, AVG, MAX, MIN)\n\n"
            "## Key Concepts\n"
            "- GROUP BY collapses rows — you go from individual rows to group summaries.\n"
            "- You can group by multiple columns: `GROUP BY dept, role`.\n"
            "- NULL values form their own group.\n"
        ),
        "common_mistakes": (
            "- Including non-aggregated columns in SELECT without GROUP BY.\n"
            "- Forgetting that WHERE filters BEFORE grouping.\n"
            "- Using column aliases in GROUP BY (not supported everywhere).\n"
            "- Grouping by the wrong column → unexpected aggregations.\n"
        ),
        "keywords": "group by aggregate count sum avg max min grouping",
    },
    # ------------------------------------------------------------------
    # 5. HAVING
    # ------------------------------------------------------------------
    {
        "topic": "having",
        "title": "HAVING — Filtering Groups",
        "content": (
            "HAVING filters groups AFTER aggregation (WHERE filters BEFORE).\n\n"
            "## Syntax\n"
            "```sql\n"
            "SELECT department, AVG(salary) AS avg_sal\n"
            "FROM employees\n"
            "GROUP BY department\n"
            "HAVING AVG(salary) > 50000;\n"
            "```\n\n"
            "## WHERE vs HAVING\n"
            "| Feature | WHERE | HAVING |\n"
            "|---------|-------|--------|\n"
            "| Filters | Individual rows | Groups |\n"
            "| When | Before GROUP BY | After GROUP BY |\n"
            "| Aggregates allowed? | No | Yes |\n\n"
            "## Key Concepts\n"
            "- HAVING requires a GROUP BY clause.\n"
            "- Use HAVING only for conditions on aggregated values.\n"
            "- For non-aggregate filters, always prefer WHERE (more efficient).\n"
        ),
        "common_mistakes": (
            "- Using WHERE instead of HAVING for aggregate conditions.\n"
            "- Using HAVING without GROUP BY.\n"
            "- Using HAVING for non-aggregate conditions (use WHERE instead).\n"
        ),
        "keywords": "having filter group aggregate where vs having",
    },
    # ------------------------------------------------------------------
    # 6. Aggregate Functions
    # ------------------------------------------------------------------
    {
        "topic": "aggregate_functions",
        "title": "Aggregate Functions — COUNT, SUM, AVG, MAX, MIN",
        "content": (
            "Aggregate functions perform calculations across groups of rows.\n\n"
            "## Functions\n"
            "```sql\n"
            "SELECT\n"
            "  COUNT(*)       AS total_rows,\n"
            "  COUNT(DISTINCT dept) AS unique_depts,\n"
            "  SUM(salary)    AS total_salary,\n"
            "  AVG(salary)    AS avg_salary,\n"
            "  MAX(salary)    AS highest,\n"
            "  MIN(salary)    AS lowest\n"
            "FROM employees;\n"
            "```\n\n"
            "## Key Concepts\n"
            "- `COUNT(*)` counts all rows; `COUNT(column)` ignores NULLs.\n"
            "- `COUNT(DISTINCT col)` counts unique non-NULL values.\n"
            "- Use `ROUND(AVG(col), 2)` to control decimal places.\n"
            "- Aggregates can be used in SELECT, HAVING, and ORDER BY.\n"
        ),
        "common_mistakes": (
            "- Using `COUNT(column)` and expecting it to count NULLs (it doesn't).\n"
            "- Forgetting ROUND() on AVG() — messy decimal output.\n"
            "- Mixing aggregated and non-aggregated columns without GROUP BY.\n"
        ),
        "keywords": "count sum avg average max min aggregate round distinct",
    },
    # ------------------------------------------------------------------
    # 7. Subqueries
    # ------------------------------------------------------------------
    {
        "topic": "subqueries",
        "title": "Subqueries — Queries Inside Queries",
        "content": (
            "A subquery is a SELECT statement nested inside another statement.\n\n"
            "## Types\n"
            "```sql\n"
            "-- Scalar subquery (returns one value)\n"
            "SELECT * FROM employees\n"
            "WHERE salary > (SELECT AVG(salary) FROM employees);\n\n"
            "-- Row subquery with IN (returns multiple values)\n"
            "SELECT * FROM orders\n"
            "WHERE customer_id IN (SELECT id FROM customers WHERE city = 'NYC');\n\n"
            "-- Correlated subquery (references outer query)\n"
            "SELECT e.name, e.salary\n"
            "FROM employees e\n"
            "WHERE e.salary > (\n"
            "  SELECT AVG(e2.salary) FROM employees e2\n"
            "  WHERE e2.department_id = e.department_id\n"
            ");\n"
            "```\n\n"
            "## Key Concepts\n"
            "- Use `=` only with scalar subqueries (one row, one column).\n"
            "- Use `IN` when subquery may return multiple rows.\n"
            "- Use `EXISTS` to check if subquery returns any rows.\n"
            "- Correlated subqueries re-execute for each outer row — can be slow.\n"
        ),
        "common_mistakes": (
            "- Using `=` with a subquery that returns multiple rows → error.\n"
            "- Forgetting parentheses around the subquery.\n"
            "- Making correlated subqueries unnecessarily (use JOIN instead).\n"
            "- Not aliasing tables in correlated subqueries → ambiguity.\n"
        ),
        "keywords": "subquery nested inner query scalar correlated exists in",
    },
    # ------------------------------------------------------------------
    # 8. ORDER BY
    # ------------------------------------------------------------------
    {
        "topic": "order_by",
        "title": "ORDER BY — Sorting Results",
        "content": (
            "ORDER BY sorts the result set by one or more columns.\n\n"
            "## Syntax\n"
            "```sql\n"
            "SELECT * FROM employees ORDER BY salary DESC;\n"
            "SELECT * FROM employees ORDER BY department ASC, salary DESC;\n"
            "```\n\n"
            "## Key Concepts\n"
            "- Default order is ASC (ascending).\n"
            "- You can sort by column aliases or positions: `ORDER BY 2 DESC`.\n"
            "- NULLs sort first in ASC (PostgreSQL) — use `NULLS LAST` to change.\n"
            "- ORDER BY is the last clause evaluated in a query.\n"
        ),
        "common_mistakes": (
            "- Forgetting ASC/DESC — assuming DESC by default.\n"
            "- Putting ORDER BY before GROUP BY or HAVING.\n"
            "- Not handling NULL ordering in sorted results.\n"
        ),
        "keywords": "order by sort ascending descending asc desc nulls",
    },
    # ------------------------------------------------------------------
    # 9. NULL Handling
    # ------------------------------------------------------------------
    {
        "topic": "null_handling",
        "title": "NULL — Handling Missing Values",
        "content": (
            "NULL represents unknown or missing data. It is NOT the same as 0 or ''.\n\n"
            "## Rules\n"
            "- Any comparison with NULL returns NULL (not TRUE or FALSE).\n"
            "- Use `IS NULL` / `IS NOT NULL` to test for NULLs.\n"
            "- `COALESCE(col, default)` returns the first non-NULL value.\n"
            "- `NULLIF(a, b)` returns NULL if a = b.\n\n"
            "## Aggregates and NULL\n"
            "- `COUNT(*)` counts all rows including NULLs.\n"
            "- `COUNT(column)`, `SUM()`, `AVG()` ignore NULLs.\n"
            "- `NULL + 5 = NULL` — arithmetic with NULL yields NULL.\n"
        ),
        "common_mistakes": (
            "- Using `= NULL` instead of `IS NULL`.\n"
            "- Expecting `WHERE col <> 'X'` to include NULL rows (it doesn't).\n"
            "- Not accounting for NULLs in LEFT JOIN results.\n"
            "- Forgetting that `IN (1, 2, NULL)` won't match NULL values.\n"
        ),
        "keywords": "null is null coalesce nullif missing unknown",
    },
    # ------------------------------------------------------------------
    # 10. DISTINCT
    # ------------------------------------------------------------------
    {
        "topic": "distinct",
        "title": "DISTINCT — Removing Duplicates",
        "content": (
            "DISTINCT removes duplicate rows from the result set.\n\n"
            "## Syntax\n"
            "```sql\n"
            "SELECT DISTINCT department FROM employees;\n"
            "SELECT DISTINCT department, role FROM employees;  -- unique combinations\n"
            "```\n\n"
            "## Key Concepts\n"
            "- DISTINCT applies to the entire row, not individual columns.\n"
            "- `COUNT(DISTINCT col)` counts unique values.\n"
            "- Consider using GROUP BY instead when aggregating.\n"
        ),
        "common_mistakes": (
            "- Using DISTINCT when GROUP BY is more appropriate.\n"
            "- Not realizing DISTINCT applies to ALL selected columns.\n"
            "- Performance: DISTINCT on large datasets can be slow — filter with WHERE first.\n"
        ),
        "keywords": "distinct unique duplicate remove dedup",
    },
    # ------------------------------------------------------------------
    # 11. Data Types & Type Casting
    # ------------------------------------------------------------------
    {
        "topic": "data_types",
        "title": "Data Types — INTEGER, VARCHAR, DATE, NUMERIC",
        "content": (
            "SQL columns have defined data types that affect comparisons and operations.\n\n"
            "## Common Types (PostgreSQL)\n"
            "| Type | Description |\n"
            "|------|-------------|\n"
            "| INTEGER, BIGINT | Whole numbers |\n"
            "| NUMERIC(p,s), DECIMAL | Exact decimals |\n"
            "| REAL, DOUBLE PRECISION | Floating point |\n"
            "| VARCHAR(n), TEXT | Strings |\n"
            "| DATE, TIMESTAMP | Date/time |\n"
            "| BOOLEAN | true/false |\n\n"
            "## Type Casting\n"
            "```sql\n"
            "SELECT CAST('42' AS INTEGER);   -- ANSI standard\n"
            "SELECT '42'::INTEGER;           -- PostgreSQL shorthand\n"
            "```\n"
        ),
        "common_mistakes": (
            "- Comparing strings to numbers without casting.\n"
            "- Using REAL for financial data (use NUMERIC instead).\n"
            "- Forgetting date format: `'2024-01-15'` not `'01/15/2024'`.\n"
        ),
        "keywords": "data type integer varchar text date numeric cast casting",
    },
    # ------------------------------------------------------------------
    # 12. Window Functions
    # ------------------------------------------------------------------
    {
        "topic": "window_functions",
        "title": "Window Functions — ROW_NUMBER, RANK, OVER",
        "content": (
            "Window functions perform calculations across a set of rows related "
            "to the current row, WITHOUT collapsing groups.\n\n"
            "## Syntax\n"
            "```sql\n"
            "SELECT name, salary,\n"
            "  ROW_NUMBER() OVER (ORDER BY salary DESC) AS rank,\n"
            "  AVG(salary) OVER (PARTITION BY department) AS dept_avg\n"
            "FROM employees;\n"
            "```\n\n"
            "## Common Functions\n"
            "- `ROW_NUMBER()` — unique sequential number per partition.\n"
            "- `RANK()` — rank with gaps for ties.\n"
            "- `DENSE_RANK()` — rank without gaps.\n"
            "- `LAG(col, n)` / `LEAD(col, n)` — access previous/next rows.\n"
            "- `SUM() OVER(...)` — running total.\n\n"
            "## Key Concepts\n"
            "- PARTITION BY divides rows into groups (like GROUP BY, but keeps all rows).\n"
            "- ORDER BY inside OVER() defines the window's row order.\n"
            "- Window functions run AFTER WHERE, GROUP BY, and HAVING.\n"
        ),
        "common_mistakes": (
            "- Confusing window functions with GROUP BY — window functions don't collapse rows.\n"
            "- Forgetting OVER() clause → syntax error.\n"
            "- Using window functions in WHERE (not allowed — use a subquery or CTE).\n"
        ),
        "keywords": "window function row_number rank dense_rank lag lead over partition by running total",
    },
    # ------------------------------------------------------------------
    # 13. CTEs (Common Table Expressions)
    # ------------------------------------------------------------------
    {
        "topic": "ctes",
        "title": "CTEs — WITH Clause for Readable Queries",
        "content": (
            "A CTE (Common Table Expression) is a named temporary result set.\n\n"
            "## Syntax\n"
            "```sql\n"
            "WITH high_earners AS (\n"
            "  SELECT * FROM employees WHERE salary > 80000\n"
            ")\n"
            "SELECT h.name, d.name AS dept\n"
            "FROM high_earners h\n"
            "JOIN departments d ON h.department_id = d.id;\n"
            "```\n\n"
            "## Key Concepts\n"
            "- CTEs make complex queries more readable.\n"
            "- You can define multiple CTEs separated by commas.\n"
            "- A CTE exists only for the duration of the query.\n"
            "- Recursive CTEs can traverse hierarchies (org charts, categories).\n"
        ),
        "common_mistakes": (
            "- Forgetting the `AS` keyword after the CTE name.\n"
            "- Trying to use a CTE in a separate query (it's scoped to the statement).\n"
            "- Not using CTEs when they'd make the query clearer.\n"
        ),
        "keywords": "cte common table expression with clause temporary named recursive",
    },
    # ------------------------------------------------------------------
    # 14. Set Operations
    # ------------------------------------------------------------------
    {
        "topic": "set_operations",
        "title": "Set Operations — UNION, INTERSECT, EXCEPT",
        "content": (
            "Set operations combine results from two or more SELECT queries.\n\n"
            "## Operators\n"
            "```sql\n"
            "-- UNION: combine + remove duplicates\n"
            "SELECT name FROM customers UNION SELECT name FROM suppliers;\n\n"
            "-- UNION ALL: combine + keep duplicates (faster)\n"
            "SELECT name FROM customers UNION ALL SELECT name FROM suppliers;\n\n"
            "-- INTERSECT: rows in both queries\n"
            "-- EXCEPT: rows in first but not second\n"
            "```\n\n"
            "## Rules\n"
            "- Both queries must have the same number of columns.\n"
            "- Column types must be compatible.\n"
            "- ORDER BY goes at the very end (applies to combined result).\n"
        ),
        "common_mistakes": (
            "- Different column counts in UNION queries.\n"
            "- Incompatible column types.\n"
            "- Using UNION when UNION ALL is sufficient (unnecessary dedup cost).\n"
        ),
        "keywords": "union intersect except set operation combine all",
    },
    # ------------------------------------------------------------------
    # 15. SQL Execution Order
    # ------------------------------------------------------------------
    {
        "topic": "execution_order",
        "title": "SQL Execution Order — How Queries Are Processed",
        "content": (
            "Understanding the logical execution order helps debug queries.\n\n"
            "## Order of Operations\n"
            "1. **FROM** / **JOIN** — identify source tables\n"
            "2. **WHERE** — filter individual rows\n"
            "3. **GROUP BY** — form groups\n"
            "4. **HAVING** — filter groups\n"
            "5. **SELECT** — compute output columns + aliases\n"
            "6. **DISTINCT** — remove duplicates\n"
            "7. **ORDER BY** — sort results\n"
            "8. **LIMIT** / **OFFSET** — paginate\n\n"
            "## Implications\n"
            "- You can't use SELECT aliases in WHERE (SELECT runs after WHERE).\n"
            "- You CAN use SELECT aliases in ORDER BY (runs after SELECT).\n"
            "- HAVING can use aggregate functions (runs after GROUP BY).\n"
            "- Window functions run between SELECT and ORDER BY.\n"
        ),
        "common_mistakes": (
            "- Using a column alias in WHERE.\n"
            "- Filtering aggregates in WHERE instead of HAVING.\n"
            "- Expecting ORDER BY to run before DISTINCT.\n"
            "- Not understanding why LIMIT doesn't speed up the whole query.\n"
        ),
        "keywords": "execution order logical processing from where group having select distinct order limit",
    },
]
