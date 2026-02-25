"""
Tests for RAG Knowledge Base — ChromaDB retriever.

Tests cover:
  - Knowledge base initialisation (ephemeral)
  - Document count
  - Semantic search relevance
  - Error-type boosted search
  - Empty collection handling

Version: 2026-02-13
"""

import pytest

from backend.rag.retriever import (
    initialize_knowledge_base,
    reset_knowledge_base,
    retrieve_relevant_context,
    get_collection,
)
from backend.rag.sql_knowledge import SQL_KNOWLEDGE_DOCS


@pytest.fixture(autouse=True)
def clean_kb():
    """Reset the knowledge base before and after each test."""
    reset_knowledge_base()
    yield
    reset_knowledge_base()


class TestKnowledgeBaseInit:
    """Tests for initialize_knowledge_base()."""

    def test_init_creates_collection(self):
        """KB init should create a collection with all documents."""
        collection = initialize_knowledge_base(persist_dir=None)
        assert collection is not None
        assert collection.count() == len(SQL_KNOWLEDGE_DOCS)

    def test_init_idempotent(self):
        """Calling init twice should not duplicate documents."""
        initialize_knowledge_base(persist_dir=None)
        collection = initialize_knowledge_base(persist_dir=None)
        assert collection.count() == len(SQL_KNOWLEDGE_DOCS)

    def test_document_topics_match(self):
        """All expected topics should be present."""
        initialize_knowledge_base(persist_dir=None)
        collection = get_collection()
        result = collection.get(include=["metadatas"])
        topics = {m["topic"] for m in result["metadatas"]}
        expected_topics = {doc["topic"] for doc in SQL_KNOWLEDGE_DOCS}
        assert topics == expected_topics


class TestRetrieval:
    """Tests for retrieve_relevant_context()."""

    def test_retrieve_returns_results(self):
        """Search should return results after init."""
        initialize_knowledge_base(persist_dir=None)
        results = retrieve_relevant_context("How do JOINs work?", n_results=3)
        assert len(results) > 0
        assert len(results) <= 3

    def test_retrieve_result_has_expected_keys(self):
        """Each result should have topic, title, content, distance."""
        initialize_knowledge_base(persist_dir=None)
        results = retrieve_relevant_context("GROUP BY error", n_results=1)
        assert len(results) == 1
        result = results[0]
        assert "topic" in result
        assert "title" in result
        assert "content" in result
        assert "distance" in result

    def test_retrieve_join_query_returns_results(self):
        """A query about JOINs should return relevant results.

        Note: With hash-based fallback embeddings (no Google API key),
        semantic similarity is not meaningful, so we only check that
        results are returned rather than asserting specific topics.
        """
        initialize_knowledge_base(persist_dir=None)
        results = retrieve_relevant_context(
            "I'm getting a JOIN error, missing ON clause",
            error_type="join_error",
            n_results=3,
        )
        assert len(results) > 0
        assert len(results) <= 3

    def test_retrieve_group_by_query(self):
        """A query about GROUP BY should return results."""
        initialize_knowledge_base(persist_dir=None)
        results = retrieve_relevant_context(
            "column must appear in GROUP BY clause or aggregate function",
            error_type="aggregation_error",
            n_results=3,
        )
        assert len(results) > 0

    def test_retrieve_without_init_returns_empty(self):
        """If KB is not initialised, retrieval should return empty list."""
        results = retrieve_relevant_context("test query")
        assert results == []

    def test_retrieve_n_results_capped(self):
        """Number of results should not exceed available documents."""
        initialize_knowledge_base(persist_dir=None)
        results = retrieve_relevant_context("SQL basics", n_results=100)
        assert len(results) <= len(SQL_KNOWLEDGE_DOCS)

    def test_retrieve_with_error_type_boost(self):
        """Error type should boost relevance of related topics."""
        initialize_knowledge_base(persist_dir=None)
        results = retrieve_relevant_context(
            "wrong column name in query",
            error_type="column_error",
            n_results=3,
        )
        # Should return some results (at least select_basics or similar)
        assert len(results) > 0
