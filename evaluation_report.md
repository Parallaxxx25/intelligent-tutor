# Evaluation Report: Intelligent SQL Tutoring System

## 1. Sample-by-Sample Analysis

Below is the detailed context and evaluation for each sample, first detailing its RAGAS pipeline metrics, followed by the independent LLM-as-a-Judge evaluation.

### Sample eval_csv_01
- **Error Type**: grouping_error (Target Hint Level: 4)
- **Problem Description**: Write an SQL statement to display all product information.
- **Student Query**: SELECT * FROM products; GROUP BY missing_col
- **Error Message**: column must appear in the GROUP BY clause or be used in an aggregate function

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.5000
- **Answer Relevancy**: 0.6747
- **Context Precision**: 1.0000
- **Context Recall**: 0.0000
- **Hint Level Compliance**: 0.3000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.0000
- **Judge Rationale**: The generated hint does not provide a template (level 4) and does not match the reference hint at all. It asks a vague question about GROUP BY instead of giving a concrete query template, and it is unrelated to the reference 'SELECT * FROM products;' thus it fails on correctness, pedagogical relevance, and hint level.

---

### Sample eval_csv_02
- **Error Type**: grouping_error (Target Hint Level: 1)
- **Problem Description**: Write an SQL statement to display the email addresses of all staffs
- **Student Query**: SELECT email FROM staffs; GROUP BY missing_col
- **Error Message**: column must appear in the GROUP BY clause or be used in an aggregate function

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.3333
- **Answer Relevancy**: 0.7407
- **Context Precision**: 1.0000
- **Context Recall**: 1.0000
- **Hint Level Compliance**: 1.0000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.9000
- **Judge Rationale**: The hint correctly addresses the grouping error by prompting the student to reconsider the use of GROUP BY, which aligns with the attention level. It is pedagogically sound, encouraging reflection without giving away the answer. Minor deviation from the reference's brevity, but still appropriate.

---

### Sample eval_csv_03
- **Error Type**: column_error (Target Hint Level: 1)
- **Problem Description**: Write an SQL statement to display all brand codes and brand names.
- **Student Query**: SELECT brand_id, brand_name FROM brands LIMIT -1;
- **Error Message**: column "non_existent_col" does not exist

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.2500
- **Answer Relevancy**: 0.7180
- **Context Precision**: 1.0000
- **Context Recall**: 1.0000
- **Hint Level Compliance**: 1.0000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.9000
- **Judge Rationale**: The hint correctly follows level‑1 (Attention) by gently directing the student to review the SELECT clause without giving the solution. It is pedagogically supportive and relevant to the column_error, though it could be slightly more specific about the column issue.

---

### Sample eval_csv_04
- **Error Type**: grouping_error (Target Hint Level: 2)
- **Problem Description**: Write an SQL statement to display the item number, product code, and calculate the price of the product in the item number (quantity is mulitipled by list price). Name the last column 'Total Price'.
- **Student Query**: SELECT item_id, product_id, quantity * list_price AS 'Total Price' FROM order_items; GROUP BY missing_col
- **Error Message**: column must appear in the GROUP BY clause or be used in an aggregate function

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.0000
- **Answer Relevancy**: 0.7269
- **Context Precision**: 1.0000
- **Context Recall**: 0.0000
- **Hint Level Compliance**: 0.5000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.0000
- **Judge Rationale**: The generated hint does not address the reference hint's content or the grouping_error; it fails to provide a category-level hint and is unrelated to the expected SQL example.

---

### Sample eval_csv_05
- **Error Type**: syntax_error (Target Hint Level: 3)
- **Problem Description**: Write an SQL statement to display the product name, year the product was launched, and calculate the number of years the product has been on sale since 2026. Name the last column "Number of Years Launched".
- **Student Query**: SELCT     Product_name,     Model_year,     2026 - Model_year AS 'Product Age' FROM     Products;
- **Error Message**: syntax error at or near "SELCT"

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.0000
- **Answer Relevancy**: 0.7207
- **Context Precision**: 1.0000
- **Context Recall**: 1.0000
- **Hint Level Compliance**: 0.3000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.4000
- **Judge Rationale**: The hint correctly identifies the syntax error (misspelled SELECT) and uses an encouraging tone, which is pedagogically sound. However, the target hint level 3 requires providing an example of the correct query, which the generated hint fails to do. It only points out the error without showing the proper syntax, so it falls short of the required hint level.

---

### Sample eval_csv_07
- **Error Type**: column_error (Target Hint Level: 2)
- **Problem Description**: Write an SQL statement to display the product name and price. Name the columns "Name of Product" and "Price" respectively.
- **Student Query**: SELECT product_name AS `Name of Product`, list_price AS 'Price' FROM products LIMIT -1;
- **Error Message**: column "non_existent_col" does not exist

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.0000
- **Answer Relevancy**: 0.6946
- **Context Precision**: 1.0000
- **Context Recall**: 1.0000
- **Hint Level Compliance**: 0.5000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.2000
- **Judge Rationale**: The generated hint is overly generic praise and suggests reviewing the SELECT clause, which corresponds to an attention‑level hint (level 1). It does not address the specific column_error category, nor does it guide the student toward correct column naming or aliasing as the reference does. Therefore it fails to meet the target level 2 requirement and offers little pedagogical value for the error type.

---

### Sample eval_csv_08
- **Error Type**: grouping_error (Target Hint Level: 2)
- **Problem Description**: Write an SQL statement to display the first and last names of all staffs combined in a single column (separating first and last names with one space, e.g., Fabiola Jackson).
- **Student Query**: SELECT         Concat(First_name , " ", Last_name) FROM         Staffs; GROUP BY missing_col
- **Error Message**: column must appear in the GROUP BY clause or be used in an aggregate function

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.0000
- **Answer Relevancy**: 0.7723
- **Context Precision**: 1.0000
- **Context Recall**: 0.0000
- **Hint Level Compliance**: 0.5000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.2000
- **Judge Rationale**: The hint is vague and does not explain the specific category of the error (grouping misuse). It merely points to a GROUP BY clause without clarifying why it’s wrong or what the correct approach is, falling short of a level‑2 (Category) hint.

---

### Sample eval_csv_09
- **Error Type**: syntax_error (Target Hint Level: 1)
- **Problem Description**: Write an SQL statement to display a list of all customers. Name the first column "full_name" containing the first name, separated by one space, followed by the last name. The second column should display the email address.
- **Student Query**: SELCT      CONCAT(first_name, ' ', last_name) AS full_name,     email FROM customers;
- **Error Message**: syntax error at or near "SELCT"

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.0000
- **Answer Relevancy**: 0.6966
- **Context Precision**: 1.0000
- **Context Recall**: 1.0000
- **Hint Level Compliance**: 1.0000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.9500
- **Judge Rationale**: The hint correctly identifies the syntax error by drawing attention to the misspelled keyword `SELCT`, aligns with the Attention level (1) by focusing on the start of the statement without providing the full solution, and uses encouraging language. It is pedagogically appropriate and accurate.

---

### Sample eval_csv_10
- **Error Type**: column_error (Target Hint Level: 4)
- **Problem Description**: Write an SQL statement to display the city and state where each customer resides, without showing duplicate rows.
- **Student Query**: SELECT DISTINCT city, state FROM customers LIMIT -1;
- **Error Message**: column "non_existent_col" does not exist

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.0000
- **Answer Relevancy**: 0.7137
- **Context Precision**: 1.0000
- **Context Recall**: 1.0000
- **Hint Level Compliance**: 0.3000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.2000
- **Judge Rationale**: The generated hint is overly generic and does not address the column_error or provide a level‑4 template. It lacks the concrete guidance or placeholder structure needed to help the student correct the query, falling far short of the reference hint.

---

### Sample eval_csv_11
- **Error Type**: column_error (Target Hint Level: 3)
- **Problem Description**: Write an SQL statement to display the email addresses of all stores, sorting the results in descending order.
- **Student Query**: SELECT email FROM stores ORDER BY email DESC LIMIT -1;
- **Error Message**: column "non_existent_col" does not exist

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.0000
- **Answer Relevancy**: 0.6811
- **Context Precision**: 0.5833
- **Context Recall**: 1.0000
- **Hint Level Compliance**: 0.3000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.1200
- **Judge Rationale**: The hint is generic encouragement and suggests reviewing the SELECT clause, but it does not provide an example query (required for level 3) nor directly address the column_error. It fails to meet the target hint level and lacks pedagogical specificity.

---

### Sample eval_csv_12
- **Error Type**: syntax_error (Target Hint Level: 3)
- **Problem Description**: Write an SQL statement to display the first and last names of all stafss, sorting the results by first name in ascending order.
- **Student Query**: SELCT first_name, last_name FROM staffs ORDER BY first_name;
- **Error Message**: syntax error at or near "SELCT"

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.0000
- **Answer Relevancy**: 0.7328
- **Context Precision**: 0.5000
- **Context Recall**: 1.0000
- **Hint Level Compliance**: 0.3000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 
- **Judge Rationale**: API error: Expecting property name enclosed in double quotes: line 2 column 1 (char 2)

---

### Sample eval_csv_13
- **Error Type**: grouping_error (Target Hint Level: 4)
- **Problem Description**: Write an SQL statement to display the names of all stores (name the first column "Store") and the phone numbers of those stores (name the second column "Tel"), sorting the results by state name in descending order, and then alphabetically by city name in ascending order for stores in the same state.
- **Student Query**: SELECT store_name AS Store, phone AS Tel FROM stores ORDER BY state DESC, city; GROUP BY missing_col
- **Error Message**: column must appear in the GROUP BY clause or be used in an aggregate function

#### 1. RAGAS Pipeline Metrics
- **Faithfulness**: 0.3333
- **Answer Relevancy**: 0.7069
- **Context Precision**: 1.0000
- **Context Recall**: 1.0000
- **Hint Level Compliance**: 0.3000
- **No Solution Leakage**: 1.0000

#### 2. LLM-as-a-Judge Evaluation
- **Quality Score**: 0.2000
- **Judge Rationale**: The hint is a vague prompt about GROUP BY rather than a concrete template (level 4). It does not give a fill‑in‑the‑blank query or structure, and it lacks the specific guidance shown in the reference. Hence it falls short of the required hint level and pedagogical usefulness.

---
## 2. Overall RAGAS Pipeline Metrics
The RAGAS (Retrieval-Augmented Generation Assessment) evaluation focuses on the mechanical success of the vector database retrieval (ChromaDB) and how accurately the LLM leverages the retrieved context to answer the student\'s problem.

| Metric | Average | Score Interpretation |
| :--- | :--- | :--- |
| **Context Precision** | **0.9236** | **Excellent.** The retriever fetches highly relevant SQL knowledge and ranks it correctly. |
| **Context Recall** | **0.7500** | **Good.** The vector database successfully contains and returns the knowledge needed to solve most errors. |
| **Answer Relevancy** | **0.7149** | **Decent.** The hints remain largely on-topic regarding the student\'s specific SQL query. |
| **Faithfulness** | **0.1181** | **Critically Poor.** The LLM is largely ignoring the retrieved RAG context and generating responses based on base training. |
| **Hint Level Compliance**| **0.5250** | **Poor.** Fails to adapt its response style based on the requested scaffolding level. |
| **No Solution Leakage** | **1.0000** | **Perfect.** The AI perfectly safeguards the final answer from the student. |

## 3. Overall LLM-as-a-Judge Evaluation
The independent LLM Judge acts as a seasoned SQL instructor reviewing the tutor's hints, providing high-level pedagogical alignment reviews based on overall hint quality, hint level compliance, and strictness against solution leakage.

| Metric | Average Score | Interpretation |
| :--- | :--- | :--- |
| **Quality Score** | **37.0%** | **Needs Improvement.** Overall pedagogical value is low, generally because the hint provided fails to correctly address the prompt's required hint level. |
| **Hint Level Compliance**| **56.7%** | **Poor.** The hints struggle to conform to the required pedagogical scaffolding level, often providing too little or too much guidance. |
| **No Solution Leakage** | **100%**| **Perfect.** The AI maintains a strict guardrail and never accidentally outputs the direct SQL solution. |

### Summary
The Intelligent Tutor maintains a perfect guard against leaking direct solutions (100% No Solution Leakage). However, its overall pedagogical quality is currently poor (37.0% Quality Score). The primary weakness lies heavily in **Hint Level Compliance (56.7%)** and **Faithfulness (11.8%)** - the system frequently ignores RAG guidelines and fails to adapt its scaffolding levels properly or output the expected concrete templates.
