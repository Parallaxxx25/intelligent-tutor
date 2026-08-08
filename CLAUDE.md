# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A bachelor's-thesis multi-agent AI tutoring system for SQL education: students submit SQL against a seeded PostgreSQL "BikeStores" database, the system grades it, diagnoses the error type, and generates leveled pedagogical hints (never the full solution). Backend is FastAPI + LangGraph + Gemini; frontend is a Streamlit playground.

## Commands

### Setup
```bash
docker-compose up -d                    # PostgreSQL (host port 5435) + Redis (6379)
pip install -r backend/requirements.txt
python -m backend.db.seed               # idempotent — creates schema + seeds BikeStores data + problems
```

### Run
```bash
uvicorn backend.main:app --reload       # API at http://localhost:8000/docs
streamlit run frontend/app.py           # playground UI (needs the API running)
```

### Tests
```bash
pytest tests/test_tools.py -v           # no DB needed (error classifier + hint generator)
pytest tests/test_api.py -v             # needs PostgreSQL (docker-compose up -d)
pytest -v                               # full suite
pytest tests/test_tools.py::TestSQLExecutorSecurity::test_blocks_drop_table -v  # single test
```
Async tests run automatically (`asyncio_mode = auto` in `pytest.ini`); no `@pytest.mark.asyncio` needed. Shared fixtures live in `tests/conftest.py`.

### Evaluation
```bash
python -m backend.evaluation.run_evaluation              # RAGAS eval of the RAG layer
python -m backend.evaluation.run_eval_llm_judge           # LLM-as-a-judge on hint quality (OpenRouter)
# both accept --dataset-csv <path> --output csv --csv-path <path>
```

## Architecture

### The three pipelines (`backend/agents/supervisor.py`)
The API can run one of three interchangeable pipelines, selected via `?mode=` on `POST /api/submit` (or `DEFAULT_PIPELINE_MODE` in settings):
- **`run_pipeline_deterministic`** — rule-based only, no LLM calls. Grade → classify error → generate hint, all via plain Python tools.
- **`run_pipeline_langgraph`** — grading happens outside the graph (same as deterministic); a compiled `StateGraph` (`diagnose → tutor → END`) then handles diagnosis + hint generation via `backend/agents/diagnostician.py` and `backend/agents/tutor.py`.
- **`run_pipeline_llm`** — full Gemini + RAG path: input guardrails → deterministic grading → LLM diagnosis (RAG-augmented, rule-based classifier as fallback context) → LLM hint generation → output guardrails. Any LLM/guardrail failure falls back to the deterministic pipeline or rule-based tools at that step — the LLM path is never allowed to hard-fail a submission.

All three pipelines are invoked from `backend/api/routes.py::submit_code` via `run_in_threadpool` (they're sync functions) and converge on the same `SubmissionResponse` schema.

### Grading → Diagnosis → Hint contract
- **Grading** (`backend/tools/test_runner.py` + `backend/tools/code_executor.py`): executes the student query read-only against Postgres (`execute_sql`), comparing results against gold-standard queries stored in `test_cases.input_data`. `code_executor.py` enforces a SQL allowlist (`SELECT`/`WITH`/`EXPLAIN` only) and blocks DDL/DML via regex before anything touches the DB — this is the actual security boundary, not guardrails.
- **Diagnosis**: classifies into a fixed `ErrorType` taxonomy (`backend/db/models.py::ErrorType`, mirrored in `backend/db/schemas.py::ErrorTypeEnum`) — syntax/column/relation/join/aggregation/subquery/type/ambiguity/logic/runtime/timeout/security_violation/no_error.
- **Hints**: 4-level scaffolding (Attention → Category → Concept → Solution template) chosen by `attempt_count`, not by error severity — attempt 1 always gets level 1, attempt 4+ gets level 4, regardless of pipeline. This mapping is duplicated in three places in `supervisor.py`; keep them in sync if you change it.

### Guardrails are a safety net, not the sandbox
`backend/guardrails.py` (input: prompt-injection/topic/length checks; output: solution-leakage via `difflib` similarity to gold-standard, schema hallucination, tone/length) only runs in `run_pipeline_llm`. Query execution safety is entirely `code_executor.py`'s read-only-transaction + regex-blocklist, independent of which pipeline runs.

### Memory layers
- **Short-term** (`backend/memory/redis_session.py`): per `(user_id, problem_id)` session — attempt count, last error type, last hint level. Keyed `session:{user_id}:{problem_id}`, cleared on a passing submission.
- **Long-term** (`backend/memory/long_term.py`): ChromaDB collection of embedded past interactions (code, error_type, hint) for retrieving similar past struggles.
- **Mastery** (`backend/memory/mastery.py`): per-topic `MasteryLevel` progression (novice→expert) updated after every submission.
- Both Redis and Chroma failures during app startup/requests are logged and swallowed (non-fatal) — the system is designed to degrade to stateless grading rather than fail submissions.

### RAG (`backend/rag/`)
ChromaDB, embedding via `GoogleEmbeddingFunction` (Gemini embeddings, `EMBEDDING_MODEL` setting). `sql_knowledge.py` holds the seeded reference content; `retriever.py` does retrieval + knowledge-base init (called from `main.py` lifespan, non-fatal on failure). Only consulted by `run_pipeline_llm`.

### Database
Two logical roles on one Postgres instance (`docker-compose.yml`, host port **5435**, not 5432): the app's own tables (`problems`, `test_cases`, `gold_standards`, `users`, `student_progress`, `interaction_history` — `backend/db/models.py`) plus the seeded **BikeStores sample schema** (`SQL-Server-Sample-Database/`) that students actually query against, spanning `production`/`sales`/`public` schemas (see the `search_path` set in `code_executor.py`). `backend/db/seed.py` is idempotent and loads the BikeStores DDL directly from the `.sql` file in that directory.

### Config
All settings load via `pydantic-settings` from `.env` at repo root (`backend/config.py`, `get_settings()` is `lru_cache`d — settings are effectively process-wide singletons, so tests that need different config must clear the cache). Note `.env.example` ships `POSTGRES_URL` on port 5432 but `docker-compose.yml` maps Postgres to host port **5435** — the real `.env` must use 5435.

### WebSockets
`backend/api/websocket.py`'s `manager` pushes pipeline progress events (`grading_started`, `grading_complete`, `diagnosis_complete`, `hint_ready`) to `/ws/session/{id}` during `submit_code`, keyed by `"{user_id}:{problem_id}"`. Used by the Streamlit playground for live status.
