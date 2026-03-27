# 🎓 Intelligent SQL Tutoring System

A **multi-agent AI tutoring system** for personalized SQL education, built with LangGraph, FastAPI, and Google Gemini. Provides automated query grading, SQL error diagnosis, and adaptive pedagogical hints through a 4-level scaffolding system.

> **Master's Thesis Project** — An experimental platform for studying the effectiveness of AI-driven pedagogical scaffolding in SQL education.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                 Interaction Layer (Blue)                  │
│              FastAPI REST + WebSocket API                 │
├─────────────────────────────────────────────────────────┤
│            Agent Orchestration Layer (Green)              │
│     ┌──────────┐  ┌──────────────┐  ┌───────────┐       │
│     │  Grader  │→ │ Diagnostician│→ │   Tutor   │       │
│     │  Agent   │  │    Agent     │  │   Agent   │       │
│     └──────────┘  └──────────────┘  └───────────┘       │
│              LangGraph StateGraph Pipeline                   │
├─────────────────────────────────────────────────────────┤
│              Cognitive Layer (Orange)                     │
│         Google Gemini  •  RAG  •  Guardrails             │
├─────────────────────────────────────────────────────────┤
│           Data & Memory Layer (Purple)                    │
│      PostgreSQL (Target + Profile)  •  Redis             │
└─────────────────────────────────────────────────────────┘
```

## SQL Error Taxonomy

| Error Type         | Description                                  | Example                                        |
|-------------------|----------------------------------------------|------------------------------------------------|
| `syntax_error`     | Malformed SQL                                | `SELCT * FROM employees`                       |
| `column_error`     | Wrong/misspelled column name                 | `SELECT employee_name FROM ...`                |
| `relation_error`   | Wrong/misspelled table name                  | `FROM employes`                                |
| `join_error`       | Incorrect or missing JOIN condition          | `FROM orders, customers` (no ON)               |
| `aggregation_error`| GROUP BY / HAVING misuse                     | `SELECT name, COUNT(*) FROM ... GROUP BY dept` |
| `subquery_error`   | Subquery returns wrong shape                 | `WHERE id = (SELECT id FROM ...)` (multi-row)  |
| `type_error`       | Data-type mismatch                           | `WHERE salary = 'abc'`                         |
| `ambiguity_error`  | Ambiguous column in multi-table query        | `SELECT id FROM t1 JOIN t2 ...`                |
| `logic_error`      | Query runs but returns wrong results         | Wrong WHERE condition or missing JOIN          |
| `timeout_error`    | Query too slow (Cartesian product, etc.)     | `FROM orders, products` (no JOIN ON)           |

## Hint Scaffolding Levels

| Level | Name       | Description                            | Example                                          |
|-------|------------|----------------------------------------|--------------------------------------------------|
| 1     | Attention  | Point to the problematic SQL clause    | "Look at your JOIN clause"                       |
| 2     | Category   | Explain the SQL error type             | "Every column in SELECT must be in GROUP BY..."  |
| 3     | Concept    | Show a similar SQL example             | "Here's how a similar JOIN works: ..."           |
| 4     | Solution   | Provide fill-in-the-blanks SQL template| `SELECT ___ FROM ___ JOIN ___ ON ___`            |

## Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Google API Key (Gemini)

### 1. Clone & configure
```bash
cd d:\Inte_\intelligent-tutor
copy .env.example .env
# Edit .env and add your GOOGLE_API_KEY
# (Optional) Add LANGSMITH_API_KEY for LLM token cost & tracing
```

### 2. Start databases
```bash
docker-compose up -d
```

### 3. Install dependencies
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r backend/requirements.txt
```

### 4. Initialize & seed database
```bash
python -m backend.db.seed
```

### 5. Start the server
```bash
uvicorn backend.main:app --reload
```

### 6. Open API docs
Visit [http://localhost:8000/docs](http://localhost:8000/docs) for the Swagger UI.

## API Endpoints

| Method | Path                 | Description                    |
|--------|----------------------|--------------------------------|
| GET    | `/api/health`        | Health check                   |
| GET    | `/api/problems`      | List all SQL problems          |
| GET    | `/api/problems/{id}` | Get problem with test queries  |
| POST   | `/api/submit`        | Submit SQL → grade + hints     |
| WS     | `/ws/session/{id}`   | Real-time session updates      |

## Seed Problems

| # | Title                         | Topic             | Difficulty |
|---|-------------------------------|--------------------|-----------|
| 1 | Basic SELECT — Employee Names | SELECT basics      | Easy      |
| 2 | WHERE — High Salary           | WHERE filtering    | Easy      |
| 3 | INNER JOIN — Employees & Depts| JOINs              | Medium    |
| 4 | GROUP BY — Dept Avg Salary    | Aggregation        | Medium    |
| 5 | Subquery — Above-Average      | Subqueries         | Medium    |
| 6 | HAVING — Big Spender Customers| HAVING clause      | Hard      |

## Project Structure

```
intelligent-tutor/
├── backend/
│   ├── agents/           # LangGraph agent node definitions
│   │   ├── grader.py         # SQL query grader
│   │   ├── diagnostician.py  # SQL error classifier
│   │   ├── tutor.py          # Hint generator
│   │   └── supervisor.py     # Pipeline orchestrator
│   ├── tools/            # LangGraph tools
│   │   ├── code_executor.py  # SQL executor (PostgreSQL)
│   │   ├── test_runner.py    # SQL result-set comparison
│   │   ├── error_classifier.py # SQL error taxonomy
│   │   └── hint_generator.py # SQL-specific hint scaffolding
│   ├── db/               # Database layer
│   │   ├── models.py     # SQLAlchemy ORM models
│   │   ├── schemas.py    # Pydantic validation schemas
│   │   ├── database.py   # Async DB connection
│   │   └── seed.py       # Reference data + SQL problems
│   ├── api/              # FastAPI endpoints
│   │   ├── routes.py
│   │   └── websocket.py
│   ├── prompts/          # Versioned prompt templates
│   ├── config.py
│   └── main.py
├── tests/                # Pytest test suite
├── docker-compose.yml
├── .env.example
└── README.md
```

## Running Tests

```bash
# Tool tests (error classifier + hint generator — no DB needed)
pytest tests/test_tools.py -v

# API tests (requires PostgreSQL)
pytest tests/test_tools.py -v

# All tests
pytest -v
```

## License

This project is part of a master's thesis and is for academic use.
