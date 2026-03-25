"""
RAG Retriever — ChromaDB-backed SQL knowledge base.

Embeds SQL concept documents into a ChromaDB collection and provides
semantic search via Google's gemini-embedding-001 model.

Usage:
    from backend.rag.retriever import initialize_knowledge_base, retrieve_relevant_context

    # On app startup
    await initialize_knowledge_base()

    # During pipeline
    context = retrieve_relevant_context("student has a JOIN error", n_results=3)

Version: 2026-02-13
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from backend.config import get_settings
from backend.rag.sql_knowledge import SQL_KNOWLEDGE_DOCS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None

COLLECTION_NAME = "sql_knowledge"


# ---------------------------------------------------------------------------
# Embedding function (Google Generative AI)
# ---------------------------------------------------------------------------

class GoogleEmbeddingFunction(chromadb.EmbeddingFunction[list[str]]):
    """
    ChromaDB-compatible embedding function using Google Generative AI.

    Falls back to a simple hash-based embedding if the API is unavailable,
    so that tests and offline development still work.
    """

    def __init__(self, model_name: str = "models/gemini-embedding-001") -> None:
        self.model_name = model_name
        self._client = None
        try:
            from google import genai
            settings = get_settings()
            if settings.GOOGLE_API_KEY:
                self._client = genai.Client(api_key=settings.GOOGLE_API_KEY)
                logger.info("Google embedding model configured: %s", model_name)
            else:
                logger.warning("No GOOGLE_API_KEY — using fallback hash embeddings.")
        except Exception as e:
            logger.warning("Google GenAI not available (%s) — using fallback.", e)

    def __call__(self, input: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if self._client:
            try:
                response = self._client.models.embed_content(
                    model=self.model_name,
                    contents=input,
                    config={"task_type": "RETRIEVAL_DOCUMENT"},
                )
                return [embedding.values for embedding in response.embeddings]
            except Exception as e:
                logger.warning("Embedding API failed (%s) — using fallback.", e)

        # Fallback: deterministic hash-based pseudo-embeddings (768-dim)
        return [self._hash_embed(text) for text in input]

    @staticmethod
    def _hash_embed(text: str, dim: int = 768) -> list[float]:
        """Produce a deterministic pseudo-embedding from text hash."""
        h = hashlib.sha256(text.encode()).hexdigest()
        # Expand to `dim` floats in [-1, 1]
        values: list[float] = []
        for i in range(dim):
            byte_val = int(h[(i * 2) % len(h) : (i * 2) % len(h) + 2], 16)
            values.append((byte_val / 127.5) - 1.0)
        return values

    def name(self) -> str:
        """Return the embedding function name (required by ChromaDB 1.x)."""
        return f"google-{self.model_name}"


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def initialize_knowledge_base(persist_dir: str | None = None) -> chromadb.Collection:
    """
    Create (or open) the ChromaDB collection and populate it with
    SQL knowledge documents.

    Args:
        persist_dir: Directory for persistent storage. If None, uses
                     in-memory storage (good for tests).

    Returns:
        The ChromaDB Collection.
    """
    global _client, _collection

    settings = get_settings()
    chroma_dir = persist_dir or settings.CHROMA_PERSIST_DIR

    # Use chromadb.Client() with explicit settings to avoid the default
    # ONNX embedding model download that hangs on some platforms.
    if chroma_dir:
        _client = chromadb.Client(ChromaSettings(
            anonymized_telemetry=False,
            is_persistent=True,
            persist_directory=chroma_dir,
        ))
        logger.info("ChromaDB persistent client at %s", chroma_dir)
    else:
        _client = chromadb.Client(ChromaSettings(
            anonymized_telemetry=False,
            is_persistent=False,
        ))
        logger.info("ChromaDB in-memory client")

    embedding_fn = GoogleEmbeddingFunction(
        model_name=settings.EMBEDDING_MODEL,
    )

    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"description": "SQL concepts for the tutoring RAG pipeline"},
    )

    # Seed documents if collection is empty
    if _collection.count() == 0:
        _seed_collection(_collection)
        logger.info("Seeded %d SQL knowledge documents.", len(SQL_KNOWLEDGE_DOCS))
    else:
        logger.info("Collection already has %d documents — skipping seed.", _collection.count())

    return _collection


def _seed_collection(collection: chromadb.Collection) -> None:
    """Insert all SQL_KNOWLEDGE_DOCS into the collection."""
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []

    for doc in SQL_KNOWLEDGE_DOCS:
        # Combine content + mistakes for richer embedding
        full_text = (
            f"# {doc['title']}\n\n"
            f"{doc['content']}\n\n"
            f"## Common Mistakes\n{doc['common_mistakes']}"
        )
        ids.append(doc["topic"])
        documents.append(full_text)
        metadatas.append({
            "topic": doc["topic"],
            "title": doc["title"],
            "keywords": doc["keywords"],
        })

    collection.add(ids=ids, documents=documents, metadatas=metadatas)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve_relevant_context(
    query: str,
    error_type: str = "",
    n_results: int = 3,
) -> list[dict[str, Any]]:
    """
    Retrieve the most relevant SQL knowledge documents for a given query.

    Args:
        query: Natural-language search query (e.g., student error + query text).
        error_type: Optional error type for filtering/boosting.
        n_results: Number of results to return.

    Returns:
        List of dicts with keys: topic, title, content, distance.
    """
    if _collection is None:
        logger.warning("Knowledge base not initialized — returning empty context.")
        return []

    # Enrich query with error type for better relevance
    search_query = query
    if error_type:
        search_query = f"{error_type}: {query}"

    try:
        results = _collection.query(
            query_texts=[search_query],
            n_results=min(n_results, _collection.count()),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        logger.error("ChromaDB query failed: %s", e)
        return []

    # Format results
    context_docs: list[dict[str, Any]] = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            context_docs.append({
                "topic": doc_id,
                "title": results["metadatas"][0][i].get("title", ""),
                "content": results["documents"][0][i],
                "distance": results["distances"][0][i] if results["distances"] else None,
            })

    return context_docs


def get_collection() -> chromadb.Collection | None:
    """Return the current ChromaDB collection (for testing)."""
    return _collection


def reset_knowledge_base() -> None:
    """Reset the module-level state (for testing)."""
    global _client, _collection
    if _client and _collection:
        try:
            _client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
    _client = None
    _collection = None
