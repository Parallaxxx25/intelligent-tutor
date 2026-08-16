# Slide-Material RAG

Course-grounded retrieval layer on top of `slide-material/` (8 DB66 lab decks, KMITL, 319 pages). Additive to the existing curated `SQL_KNOWLEDGE_DOCS` KB — not a replacement. Free/open-source, runs fully offline after first model pull.

## Why

Curated KB (`backend/rag/sql_knowledge.py`) is generic. Slides tie a hint back to the student's actual course: "see LAB 6, slide 21" instead of a floating concept explanation.

## Two traps this design works around

1. **Dialect/schema mismatch.** Slides teach Oracle SQL against the HR sample schema (`employees`, `departments`, `locations`). Student's DB is PostgreSQL + BikeStores. Leaking HR table names into a hint is wrong info, not just style — guarded by a new unconditional check in `guardrails.py`.
2. **Unrunnable content.** LAB 1/2/3 teach DDL/DML (`CREATE`, `INSERT`); `code_executor.py` only allows `SELECT`/`WITH`/`EXPLAIN`. Ingested but tagged `category: ddl_dml` and excluded from query-error retrieval by default.

## Method

Structure-aware slide chunking (parent/child window) + hybrid BM25 ⊕ dense retrieval fused with RRF, metadata-filtered by mapped `ErrorType`, merged with the curated KB at prompt-build time.

Corpus is ~30k tokens total — graph-RAG or multi-vector setups would be overkill. What actually moves retrieval quality here: keyword recall (BM25 catches `HAVING`, `NATURAL JOIN` where dense embeddings blur them) and clean chunk boundaries.

### Stack — all free / open-source, no API keys

| Layer | Choice | Why |
|---|---|---|
| PDF extract | PyMuPDF (`fitz`) | already a dep |
| Lexical | `rank_bm25` | pure Python, tiny |
| Dense | `fastembed` + `paraphrase-multilingual-MiniLM-L12-v2` | ONNX, **no PyTorch**, 220MB (see model note below) |
| Vector store | ChromaDB | already wired for the curated KB |
| Fusion | Reciprocal Rank Fusion | ~15 lines, no trained weights |

**Model note:** plan originally specified `intfloat/multilingual-e5-base`, but fastembed's registry only has `multilingual-e5-large` (2.24GB) — too big for the slow connection observed during build. Swapped default to MiniLM (Apache-2.0, 220MB, no query/passage prefix needed). `LOCAL_EMBEDDING_MODEL` in `backend/config.py` is a one-line swap to `e5-large` later if retrieval quality needs the bump — `embeddings.py` only applies E5-style prefixes when the model name contains `"e5"`, so nothing else has to change.

## What each file does

```
backend/rag/
├── embeddings.py         FastEmbedEmbeddingFunction — local ONNX embedder,
│                         hash-embedding fallback if model unavailable
├── slide_ingest.py       PDF → SlideChunk (pure, DB-free, unit-testable)
├── slide_retriever.py    "slide_material" Chroma collection + hybrid search
└── build_slide_index.py  offline CLI: python -m backend.rag.build_slide_index
```

### `slide_ingest.py` — PDF → chunks

- **Title heuristic:** first line is the slide title when >80% of its ASCII letters are uppercase. Holds on 85% of the real corpus. Cover pages before the first heading fall back to a deck-name derived from the filename.
- **Cleaning:** strips page-number watermark lines; collapses Thai duplicate-token OCR artifacts (`สำหรับ สำหรับ` → `สำหรับ`, ~24 pages affected).
- **Parent/child chunking:** *child* = one slide, embedded, prefixed with a synthetic header (`[LAB 6 — JOIN WITH ON CLAUSE | slide 21]`) so the embedding carries its own context. *parent* = that slide ± 1 neighbour, returned to the LLM — a lone ~300-char slide is too thin to reason from alone.
- **Lab → `ErrorType` taxonomy:** maps each lab to `topic`/`category`/`error_types` (e.g. LAB 6/7 → `join_error`, `ambiguity_error`; LAB 8 → `aggregation_error`). DDL/DML labs (1/2/3) get `category: ddl_dml`.

### `slide_retriever.py` — hybrid search

- Second Chroma collection (`slide_material`), same singleton pattern as the curated KB's `retriever.py`.
- `initialize_slide_kb()` — seeds from `slide-material/*.pdf` if empty, idempotent, also builds an in-process BM25 index over the collection's contents.
- `search_slides(query, error_type, n_results, include_ddl)`:
  1. Dense query (Chroma) + BM25 query, both restricted to `category: query` unless `include_ddl=True`.
  2. RRF fusion of the two ranked lists.
  3. Soft multiplier boost (not a hard filter — Chroma metadata can't hold list values) for chunks tagged with the diagnosed `error_type`.
  4. Returns the same dict shape as the curated KB's `retrieve_relevant_context` (`topic`, `title`, `content`, `distance`) plus `citation`, so the caller merges both sources with one formatting loop.
- **Thai tokenization:** Thai has no word spaces — naive `.split()` collapses a whole sentence into one BM25 token. Character-bigrams cover Thai spans; whitespace tokens cover ASCII (where the SQL keywords BM25 exists to catch all live anyway).

### Wiring

- `main.py` — non-fatal `initialize_slide_kb()` call at startup, gated by `SLIDE_RAG_ENABLED`.
- `supervisor.py` (`run_pipeline_llm`) — after the existing curated-KB retrieval, calls `search_slides()` in a `try/except` (never allowed to fail a submission), merges results, and appends a prompt note warning the LLM never to name HR-schema tables/columns.
- `guardrails.py` (`validate_output`) — new unconditional check for `employees`/`departments`/`locations`/`job_id`/`department_id`/`location_id`/`hire_date`/`job_history` in any hint. Runs regardless of whether `schema_info` is passed (unlike the existing hallucination check). `manager_id` deliberately excluded — BikeStores' `sales.staffs` legitimately has that column.

## Config (`backend/config.py`)

```python
SLIDE_MATERIAL_DIR: str = "slide-material"
CHROMA_SLIDE_COLLECTION: str = "slide_material"
LOCAL_EMBEDDING_MODEL: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
USE_LOCAL_EMBEDDINGS: bool = True
SLIDE_RAG_ENABLED: bool = True
SLIDE_RAG_N_RESULTS: int = 2
```

Set `CHROMA_PERSIST_DIR` (in `.env`) to persist the index across restarts — otherwise all 314 chunks re-embed on every `uvicorn` reload.

## Building the index

```bash
python -m backend.rag.build_slide_index --dry-run   # chunk only, print stats + samples, no embedding
python -m backend.rag.build_slide_index              # build if empty
python -m backend.rag.build_slide_index --rebuild    # force re-seed
```

First run downloads the MiniLM ONNX model (~220MB, cached by `fastembed`/`huggingface_hub`).

## Verification performed

- 314 chunks extracted from all 8 decks (`{1: 29, 2: 57, 3: 37, 4: 46, 6: 47, 7: 33, 8: 33, 9: 32}`).
- Real persisted index at `.chroma/` (gitignored, rebuildable) — reopens without reseeding.
- Sanity probes: `"HAVING vs WHERE"` → LAB 8; `"NULL rows missing from join"` → LAB 7; `"correlated subquery"` → LAB 9; `"CREATE TABLE"` → empty by default, LAB 1 with `include_ddl=True`; Thai-language query → non-empty relevant results.
- **112/112 tests pass**: `tests/test_slide_rag.py` (34, new — synthetic PDFs, no dependency on the gitignored `slide-material/` dir) + full regression on `test_llm_pipeline.py`, `test_guardrails.py` (3 new HR-leakage tests), `test_rag.py`, `test_tools.py`.

## Known non-issue

`slide-material/` is already `.gitignore`d (pre-existing, not part of this change). On a fresh clone without it, `initialize_slide_kb()` logs a warning and leaves the collection empty — same non-fatal degrade-to-stateless pattern the rest of the RAG/memory layer already follows.
