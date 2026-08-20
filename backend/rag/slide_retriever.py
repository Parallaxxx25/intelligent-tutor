"""
Slide-material retriever — hybrid (BM25 + dense) search over the ingested
lab-deck chunks, fused with Reciprocal Rank Fusion (RRF).

Second, sibling collection to `sql_knowledge` (see retriever.py): the
curated docs stay the Postgres-correct pedagogical backbone; this collection
adds course-aligned grounding + citations ("DB66 LAB 6, slide 21") on top.
Merged by the caller (`backend/agents/supervisor.py`), not here.

Why hybrid: the corpus is small (~319 slides, ~30k tokens) and highly
technical/bilingual. Dense embeddings alone blur SQL keywords (`HAVING` vs
`WHERE`, `NATURAL JOIN` vs `CROSS JOIN`); BM25 recovers exact-keyword recall
cheaply. RRF fusion needs no trained weights.

Chroma stores the *child* text (single slide) for retrieval precision but
the caller gets the *parent* text (slide ± 1 neighbour) back, since a lone
~300-char slide is usually too thin to reason from.

Version: 2026-08-10
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import chromadb
from rank_bm25 import BM25Okapi

from backend.config import get_settings
from backend.rag.embeddings import FastEmbedEmbeddingFunction
from backend.rag.retriever import GoogleEmbeddingFunction, get_chroma_client
from backend.rag.slide_ingest import chunk_all_decks

logger = logging.getLogger(__name__)

COLLECTION_NAME = "slide_material"
RRF_K = 60  # standard RRF damping constant

_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None
_persist_dir: str = ""  # "" = in-memory
_query_embedder: Any = None  # embedding function in "query" mode

# In-process BM25 index, rebuilt from whatever the collection holds after
# init (fresh seed or reopened persisted store) — not itself persisted.
_bm25: BM25Okapi | None = None
_bm25_ids: list[str] = []
_bm25_docs: list[dict[str, Any]] = []  # {id, child, parent, metadata}

_THAI_RE = re.compile(r"[฀-๿]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    """
    Whitespace/word tokens for ASCII (catches SQL keywords exactly), plus
    character-bigrams for Thai spans (Thai has no word spaces, so a naive
    split collapses an entire Thai sentence into one token and BM25 gets no
    signal from it).
    """
    tokens = [t.lower() for t in _WORD_RE.findall(text)]
    for run in re.findall(r"[฀-๿]+", text):
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _make_embedding_functions(settings: Any) -> tuple[Any, Any]:
    """Return (passage_fn, query_fn). Same family so both use one vector space."""
    if settings.USE_LOCAL_EMBEDDINGS:
        model = settings.LOCAL_EMBEDDING_MODEL
        return (
            FastEmbedEmbeddingFunction(model_name=model, mode="passage"),
            FastEmbedEmbeddingFunction(model_name=model, mode="query"),
        )
    fn = GoogleEmbeddingFunction(model_name=settings.EMBEDDING_MODEL)
    return fn, fn


def initialize_slide_kb(
    persist_dir: str | None = None,
    slides_dir: str | None = None,
) -> chromadb.Collection:
    """
    Create/open the `slide_material` Chroma collection, seeding it from
    `slide-material/*.pdf` if empty, and rebuild the in-process BM25 index
    from whatever the collection ends up holding.
    """
    global _client, _collection, _persist_dir, _query_embedder, _bm25, _bm25_ids, _bm25_docs

    settings = get_settings()
    chroma_dir = persist_dir if persist_dir is not None else settings.CHROMA_PERSIST_DIR

    # Shared client — a second chromadb.Client() on the same directory would
    # invalidate the sql_knowledge collection handle held by retriever.py.
    _client = get_chroma_client(chroma_dir)
    _persist_dir = chroma_dir

    passage_fn, query_fn = _make_embedding_functions(settings)
    _query_embedder = query_fn

    _collection = _client.get_or_create_collection(
        name=settings.CHROMA_SLIDE_COLLECTION,
        embedding_function=passage_fn,
        metadata={"description": "DB66 lab-deck slides for course-grounded RAG"},
    )

    if _collection.count() == 0:
        deck_dir = Path(slides_dir or settings.SLIDE_MATERIAL_DIR)
        if deck_dir.exists():
            _seed_collection(_collection, deck_dir)
        else:
            logger.warning("Slide directory not found: %s — collection stays empty.", deck_dir)
    else:
        logger.info("slide_material collection already has %d chunks — skipping seed.", _collection.count())

    _rebuild_bm25_index()
    return _collection


def _seed_collection(collection: chromadb.Collection, slides_dir: Path) -> None:
    chunks = chunk_all_decks(slides_dir)
    if not chunks:
        logger.warning("No slide chunks extracted from %s.", slides_dir)
        return

    ids = [c.id for c in chunks]
    documents = [c.child_text for c in chunks]
    metadatas = [{**c.metadata(), "parent_text": c.parent_text} for c in chunks]

    # Chroma add() has a batch-size ceiling on some backends; 319 chunks is
    # small enough to add in one call, but chunk defensively anyway.
    batch = 200
    for i in range(0, len(ids), batch):
        collection.add(
            ids=ids[i : i + batch],
            documents=documents[i : i + batch],
            metadatas=metadatas[i : i + batch],  # type: ignore[arg-type]
        )
    logger.info("Seeded %d slide chunks into %s.", len(chunks), COLLECTION_NAME)


def _rebuild_bm25_index() -> None:
    global _bm25, _bm25_ids, _bm25_docs

    if _collection is None or _collection.count() == 0:
        _bm25, _bm25_ids, _bm25_docs = None, [], []
        return

    got = _collection.get(include=["documents", "metadatas"])
    ids = got["ids"]
    documents = got["documents"]
    metadatas = got["metadatas"]

    _bm25_ids = ids
    _bm25_docs = [
        {"id": i, "child": d, "parent": (m or {}).get("parent_text", d), "metadata": m or {}}
        for i, d, m in zip(ids, documents, metadatas)
    ]
    tokenized = [_tokenize(d) for d in documents]
    _bm25 = BM25Okapi(tokenized) if tokenized else None


def _dense_candidates(query: str, where: dict[str, Any] | None, k: int) -> list[str]:
    """Return doc ids ranked by dense similarity (best first)."""
    if _collection is None or _collection.count() == 0 or _query_embedder is None:
        return []
    try:
        query_embedding = _query_embedder([query])[0]
        results = _collection.query(
            query_embeddings=[query_embedding],
            n_results=min(k, _collection.count()),
            where=where,
            include=[],
        )
    except Exception as e:
        logger.error("Slide KB dense query failed: %s", e)
        return []
    ids = results.get("ids") or []
    return ids[0] if ids else []


def _bm25_candidates(query: str, allowed_ids: set[str] | None, k: int) -> list[str]:
    """Return doc ids ranked by BM25 score (best first), restricted to `allowed_ids`."""
    if _bm25 is None:
        return []
    scores = _bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(_bm25_ids, scores), key=lambda p: p[1], reverse=True)
    if allowed_ids is not None:
        ranked = [(i, s) for i, s in ranked if i in allowed_ids]
    return [i for i, _ in ranked[:k]]


def search_slides(
    query: str,
    error_type: str = "",
    n_results: int = 2,
    include_ddl: bool = False,
) -> list[dict[str, Any]]:
    """
    Hybrid search over the slide-material collection.

    Returns dicts shaped like `retriever.retrieve_relevant_context`'s output
    (`topic`, `title`, `content`, `distance`) plus a `citation` field, so the
    caller can merge both sources with one formatting loop.
    """
    if _collection is None or _collection.count() == 0:
        return []

    # `error_type` isn't used as a hard Chroma filter: metadata stores
    # error_types as a flat comma-joined string (Chroma rejects list values),
    # so exact $eq would only match single-tag chunks. It's folded into the
    # query text instead by the caller (supervisor.py prefixes the RAG query
    # with the error type), letting BM25/dense ranking do the work.
    where: dict[str, Any] | None = None if include_ddl else {"category": "query"}

    fetch_k = max(n_results * 4, 8)
    dense_ids = _dense_candidates(query, where, fetch_k)

    allowed_ids: set[str] | None = None
    if where is not None:
        # BM25 has no native metadata filter — restrict its candidate pool to
        # the same `where` clause by intersecting with a plain dense fetch,
        # or (cheap fallback) all docs matching category via bm25_docs.
        allowed_ids = {
            d["id"] for d in _bm25_docs if d["metadata"].get("category") == where.get("category")
        }
    bm25_ids = _bm25_candidates(query, allowed_ids, fetch_k)

    # Reciprocal Rank Fusion
    scores: dict[str, float] = {}
    for rank, doc_id in enumerate(dense_ids):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, doc_id in enumerate(bm25_ids):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)

    if not scores:
        return []

    by_id = {d["id"]: d for d in _bm25_docs}

    # Soft boost (not a hard filter, see note above) for chunks tagged with
    # the diagnosed error type — e.g. "join_error" nudges LAB 6/7 chunks up.
    if error_type and error_type not in ("no_error", ""):
        for doc_id in list(scores):
            meta = by_id.get(doc_id, {}).get("metadata", {})
            tagged = (meta.get("error_types") or "").split(",")
            if error_type in tagged:
                scores[doc_id] *= 1.5

    fused = sorted(scores.items(), key=lambda p: p[1], reverse=True)[:n_results]

    out: list[dict[str, Any]] = []
    for doc_id, score in fused:
        d = by_id.get(doc_id)
        if d is None:
            continue
        meta = d["metadata"]
        out.append(
            {
                "topic": meta.get("topic", ""),
                "title": meta.get("citation", doc_id),
                "content": d["parent"],
                "citation": meta.get("citation", doc_id),
                "distance": 1.0 - score,  # lower = better, consistent with retriever.py's convention
            }
        )
    return out


def get_slide_collection() -> chromadb.Collection | None:
    """Return the current slide_material collection (for testing)."""
    return _collection


def reset_slide_kb(drop_persisted: bool = False) -> None:
    """
    Reset all module-level state (for testing).

    Only drops the collection when it lives in memory. Deleting a *persisted*
    collection throws away a real seeded index (re-ingesting the decks takes
    minutes), so that needs ``drop_persisted=True`` — as `build_slide_index
    --rebuild` passes.
    """
    global _client, _collection, _persist_dir, _query_embedder, _bm25, _bm25_ids, _bm25_docs
    if _client and _collection and (not _persist_dir or drop_persisted):
        try:
            _client.delete_collection(_collection.name)
        except Exception:
            pass
    _client = None
    _collection = None
    _persist_dir = ""
    _query_embedder = None
    _bm25, _bm25_ids, _bm25_docs = None, [], []
