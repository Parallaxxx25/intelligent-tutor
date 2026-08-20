"""
Tests for the slide-material RAG layer (backend/rag/slide_ingest.py,
slide_retriever.py, embeddings.py).

Ingestion tests build tiny synthetic PDFs with PyMuPDF so they don't depend
on the real `slide-material/` directory or its exact contents. Retrieval
tests use those synthetic decks against an in-memory Chroma collection.

Follows the structure of tests/test_rag.py.

Version: 2026-08-10
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from backend.rag.embeddings import FastEmbedEmbeddingFunction
from backend.rag.slide_ingest import (
    LAB_TAXONOMY,
    SlideChunk,
    _clean_page_text,
    _extract_title,
    chunk_all_decks,
    chunk_slide_deck,
)
from backend.rag.slide_retriever import (
    get_slide_collection,
    initialize_slide_kb,
    reset_slide_kb,
    search_slides,
)


# ---------------------------------------------------------------------------
# Synthetic deck builder
# ---------------------------------------------------------------------------

def _make_pdf(path: Path, pages: list[str]) -> None:
    """Write a PDF where each string in `pages` becomes one page of text."""
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        y = 72
        for line in text.splitlines():
            page.insert_text((50, y), line)
            y += 14
    doc.save(str(path))
    doc.close()


@pytest.fixture
def synthetic_slides_dir(tmp_path: Path) -> Path:
    """
    Two small decks mimicking the real corpus: a JOIN lab (LAB 6) and a
    DDL lab (LAB 1), including a Thai line and a duplicate-token artifact.
    """
    _make_pdf(
        tmp_path / "DB66-LAB 6-Join.pdf",
        [
            "INTRODUCTION TO SQL\nDISPLAYING DATA FROM MULTIPLE TABLES",
            "TYPES OF JOINS\n1. Equijoin\n2. Natural joins",
            (
                "EXAMPLE: EQUIJOIN\n21\n"
                "SELECT last_name, department_name\n"
                "FROM employees e, departments d\n"
                "WHERE e.department_id = d.department_id;"
            ),
            "EXERCISE 1\nสำหรับ สำหรับ employees table",
        ],
    )
    _make_pdf(
        tmp_path / "DB66-LAB 1-Data Definition Language.pdf",
        [
            "INTRODUCTION TO DDL\nCREATE, ALTER, DROP",
            "CREATE TABLE EXAMPLE\nCREATE TABLE foo (id INT);",
        ],
    )
    return tmp_path


@pytest.fixture(autouse=True)
def clean_kb():
    reset_slide_kb()
    yield
    reset_slide_kb()


# ---------------------------------------------------------------------------
# Ingestion — pure functions, no PDFs
# ---------------------------------------------------------------------------

class TestCleaning:
    def test_strips_standalone_page_number_line(self):
        cleaned = _clean_page_text("TITLE\n21\nSELECT * FROM foo;")
        assert "\n21\n" not in cleaned
        assert "21" not in cleaned.splitlines()

    def test_collapses_thai_duplicate_tokens(self):
        cleaned = _clean_page_text("สำหรับ สำหรับ employees")
        assert cleaned.count("สำหรับ") == 1

    def test_preserves_sql_numbers(self):
        """A number that isn't alone on its own line must survive."""
        cleaned = _clean_page_text("SELECT * FROM foo WHERE id = 21;")
        assert "21" in cleaned


class TestTitleHeuristic:
    def test_all_caps_line_is_title(self):
        assert _extract_title("TYPES OF JOINS\nSome body text") == "TYPES OF JOINS"

    def test_mixed_case_line_is_not_title(self):
        assert _extract_title("Some body text\nMore text") == ""

    def test_empty_text_returns_empty_title(self):
        assert _extract_title("") == ""


class TestLabTaxonomy:
    def test_every_lab_maps_to_a_category(self):
        for lab_no, entry in LAB_TAXONOMY.items():
            assert entry["category"] in ("query", "ddl_dml")

    def test_ddl_labs_have_no_error_types(self):
        for lab_no in (1, 2, 3):
            assert LAB_TAXONOMY[lab_no]["error_types"] == []

    def test_query_labs_have_error_types(self):
        for lab_no in (4, 6, 7, 8, 9):
            assert len(LAB_TAXONOMY[lab_no]["error_types"]) > 0


# ---------------------------------------------------------------------------
# Ingestion — real PDF parsing on synthetic decks
# ---------------------------------------------------------------------------

class TestChunkSlideDeck:
    def test_chunks_one_per_nonempty_page(self, synthetic_slides_dir: Path):
        chunks = chunk_slide_deck(synthetic_slides_dir / "DB66-LAB 6-Join.pdf")
        assert len(chunks) == 4
        assert all(isinstance(c, SlideChunk) for c in chunks)

    def test_lab_number_parsed_from_filename(self, synthetic_slides_dir: Path):
        chunks = chunk_slide_deck(synthetic_slides_dir / "DB66-LAB 6-Join.pdf")
        assert all(c.lab_no == 6 for c in chunks)

    def test_taxonomy_applied(self, synthetic_slides_dir: Path):
        chunks = chunk_slide_deck(synthetic_slides_dir / "DB66-LAB 6-Join.pdf")
        assert all(c.category == "query" for c in chunks)
        assert all("join_error" in c.error_types for c in chunks)

    def test_ddl_lab_tagged_ddl_dml(self, synthetic_slides_dir: Path):
        chunks = chunk_slide_deck(synthetic_slides_dir / "DB66-LAB 1-Data Definition Language.pdf")
        assert all(c.category == "ddl_dml" for c in chunks)

    def test_dialect_and_schema_tagged(self, synthetic_slides_dir: Path):
        chunks = chunk_slide_deck(synthetic_slides_dir / "DB66-LAB 6-Join.pdf")
        assert all(c.dialect == "oracle" and c.schema == "hr" for c in chunks)

    def test_parent_window_includes_neighbours(self, synthetic_slides_dir: Path):
        chunks = chunk_slide_deck(synthetic_slides_dir / "DB66-LAB 6-Join.pdf")
        middle = chunks[1]  # page 2 of 4 — has both a prev and next neighbour
        assert "TYPES OF JOINS" in middle.parent_text
        assert "EXAMPLE: EQUIJOIN" in middle.parent_text

    def test_parent_window_at_deck_boundary(self, synthetic_slides_dir: Path):
        chunks = chunk_slide_deck(synthetic_slides_dir / "DB66-LAB 6-Join.pdf")
        first, last = chunks[0], chunks[-1]
        assert first.parent_text  # doesn't crash indexing before page 1
        assert last.parent_text   # doesn't crash indexing past the last page

    def test_child_text_has_citation_header(self, synthetic_slides_dir: Path):
        chunks = chunk_slide_deck(synthetic_slides_dir / "DB66-LAB 6-Join.pdf")
        assert chunks[0].child_text.startswith("[LAB 6")

    def test_metadata_is_flat_scalars(self, synthetic_slides_dir: Path):
        chunks = chunk_slide_deck(synthetic_slides_dir / "DB66-LAB 6-Join.pdf")
        for c in chunks:
            for v in c.metadata().values():
                assert isinstance(v, (str, int, bool))

    def test_unrecognised_filename_raises(self, tmp_path: Path):
        bad = tmp_path / "not-a-lab-deck.pdf"
        _make_pdf(bad, ["hello"])
        with pytest.raises(ValueError):
            chunk_slide_deck(bad)


class TestChunkAllDecks:
    def test_chunks_every_pdf_in_dir(self, synthetic_slides_dir: Path):
        chunks = chunk_all_decks(synthetic_slides_dir)
        assert len(chunks) == 6  # 4 + 2
        labs = {c.lab_no for c in chunks}
        assert labs == {1, 6}

    def test_skips_unrecognised_filenames(self, synthetic_slides_dir: Path):
        _make_pdf(synthetic_slides_dir / "random.pdf", ["hello"])
        chunks = chunk_all_decks(synthetic_slides_dir)
        assert len(chunks) == 6  # random.pdf silently skipped, not counted


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

class TestFastEmbedEmbeddingFunction:
    def test_fallback_hash_embed_is_deterministic(self):
        fn = FastEmbedEmbeddingFunction(model_name="not-a-real-model/xyz", mode="passage")
        assert fn._model is None  # forced fallback
        v1 = [list(v) for v in fn(["SELECT * FROM foo"])]
        v2 = [list(v) for v in fn(["SELECT * FROM foo"])]
        assert v1 == v2

    def test_fallback_embeddings_have_fixed_dimension(self):
        fn = FastEmbedEmbeddingFunction(model_name="not-a-real-model/xyz", mode="query")
        vecs = fn(["a", "bb", "ccc"])
        assert len(vecs) == 3
        assert len({len(v) for v in vecs}) == 1

    def test_name_reflects_model_and_mode(self):
        fn = FastEmbedEmbeddingFunction(model_name="foo/bar", mode="query")
        assert "foo/bar" in fn.name()
        assert "query" in fn.name()


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

class TestInitializeSlideKB:
    def test_init_seeds_from_directory(self, synthetic_slides_dir: Path):
        collection = initialize_slide_kb(persist_dir="", slides_dir=str(synthetic_slides_dir))
        assert collection.count() == 6

    def test_init_idempotent(self, synthetic_slides_dir: Path):
        initialize_slide_kb(persist_dir="", slides_dir=str(synthetic_slides_dir))
        collection = initialize_slide_kb(persist_dir="", slides_dir=str(synthetic_slides_dir))
        assert collection.count() == 6

    def test_init_missing_dir_leaves_collection_empty(self, tmp_path: Path):
        collection = initialize_slide_kb(persist_dir="", slides_dir=str(tmp_path / "nope"))
        assert collection.count() == 0


class TestSearchSlides:
    def test_search_without_init_returns_empty(self):
        assert search_slides("join error") == []

    def test_search_returns_results_shaped_like_curated_kb(self, synthetic_slides_dir: Path):
        initialize_slide_kb(persist_dir="", slides_dir=str(synthetic_slides_dir))
        results = search_slides("JOIN clause error", n_results=2)
        assert len(results) > 0
        for r in results:
            assert {"topic", "title", "content", "citation", "distance"} <= r.keys()

    def test_ddl_excluded_by_default(self, synthetic_slides_dir: Path):
        initialize_slide_kb(persist_dir="", slides_dir=str(synthetic_slides_dir))
        results = search_slides("CREATE TABLE", n_results=5)
        assert all(r["topic"] != "ddl" for r in results)

    def test_ddl_included_when_requested(self, synthetic_slides_dir: Path):
        initialize_slide_kb(persist_dir="", slides_dir=str(synthetic_slides_dir))
        results = search_slides("CREATE TABLE", n_results=5, include_ddl=True)
        topics = {r["topic"] for r in results}
        assert "ddl" in topics

    def test_citation_mentions_lab_and_slide(self, synthetic_slides_dir: Path):
        initialize_slide_kb(persist_dir="", slides_dir=str(synthetic_slides_dir))
        results = search_slides("JOIN", n_results=1)
        assert "LAB" in results[0]["citation"]
        assert "slide" in results[0]["citation"]

    def test_n_results_respected(self, synthetic_slides_dir: Path):
        initialize_slide_kb(persist_dir="", slides_dir=str(synthetic_slides_dir))
        results = search_slides("SQL", n_results=1)
        assert len(results) <= 1

    def test_reset_then_search_returns_empty(self, synthetic_slides_dir: Path):
        initialize_slide_kb(persist_dir="", slides_dir=str(synthetic_slides_dir))
        reset_slide_kb()
        assert search_slides("JOIN") == []
