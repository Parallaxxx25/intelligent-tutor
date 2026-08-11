"""
Slide-material ingestion — PDF lab decks to indexable chunks.

Pure, DB-free, unit-testable: `chunk_slide_deck` / `chunk_all_decks` take a
PDF path (or directory) and return `SlideChunk` objects. No embedding, no
ChromaDB — that happens in `slide_retriever.py`.

Corpus context (measured on `slide-material/`, 2026-08-10):
  - 8 decks, 319 pages, real text layer (no OCR needed).
  - Bilingual: English headings, Thai instructions on ~56% of pages.
  - 85% of pages have an ALL-CAPS first line — used as the title heuristic.
  - ~300 chars/page — thin enough that single-slide chunks lack context,
    hence the parent/child window (see `chunk_slide_deck`).
  - Oracle dialect against the HR schema (employees/departments/locations),
    NOT the PostgreSQL/BikeStores schema students query against — every
    chunk is tagged dialect="oracle" / schema="hr" so callers can warn
    against leaking those table names into a hint.

Version: 2026-08-10
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_THAI_RE = re.compile(r"[฀-๿]")
# PyMuPDF emits the slide's page-number watermark as its own line — usually
# right under the title, sometimes at the very end. Strip any standalone
# digit-only line (max 3 digits, matching the corpus's 29-58 page decks)
# rather than only the trailing one.
_PAGE_NUM_LINE_RE = re.compile(r"^\s*\d{1,3}\s*$", re.MULTILINE)
_DUP_TOKEN_RE = re.compile(r"(\S+)(\s+\1)+(?=\s|$)")

# Lab number -> (topic, category, error_types). Category "ddl_dml" is excluded
# from query-error retrieval by default (backend/tools/code_executor.py only
# allows SELECT/WITH/EXPLAIN — students can never run CREATE/INSERT/etc).
LAB_TAXONOMY: dict[int, dict[str, object]] = {
    1: {"topic": "ddl", "category": "ddl_dml", "error_types": []},
    2: {"topic": "ddl_constraints", "category": "ddl_dml", "error_types": []},
    3: {"topic": "dml", "category": "ddl_dml", "error_types": []},
    4: {"topic": "select", "category": "query", "error_types": ["column_error", "logic_error", "type_error"]},
    6: {"topic": "join", "category": "query", "error_types": ["join_error", "ambiguity_error"]},
    7: {"topic": "outer_join", "category": "query", "error_types": ["join_error", "logic_error"]},
    8: {"topic": "aggregation", "category": "query", "error_types": ["aggregation_error"]},
    9: {"topic": "subquery", "category": "query", "error_types": ["subquery_error"]},
}

_LAB_NO_RE = re.compile(r"LAB\s*(\d+)", re.IGNORECASE)


@dataclass
class SlideChunk:
    """One retrievable unit: a single slide (child) plus its context window (parent)."""

    id: str
    child_text: str          # embedded text — single slide, header-prefixed
    parent_text: str         # returned to the LLM — slide ± 1 neighbour
    source_deck: str
    lab_no: int
    page: int                # 1-indexed
    slide_title: str
    section_title: str
    topic: str
    category: str
    error_types: list[str] = field(default_factory=list)
    dialect: str = "oracle"
    schema: str = "hr"
    has_sql: bool = False
    has_thai: bool = False

    @property
    def citation(self) -> str:
        return f"DB66 LAB {self.lab_no} — {self.section_title or self.slide_title}, slide {self.page}"

    def metadata(self) -> dict[str, str | int | bool]:
        """Flat-scalar metadata dict — Chroma rejects lists/None."""
        return {
            "source_deck": self.source_deck,
            "lab_no": self.lab_no,
            "page": self.page,
            "slide_title": self.slide_title,
            "section_title": self.section_title,
            "topic": self.topic,
            "category": self.category,
            "error_types": ",".join(self.error_types),
            "dialect": self.dialect,
            "schema": self.schema,
            "has_sql": self.has_sql,
            "has_thai": self.has_thai,
            "citation": self.citation,
        }


def _lab_no_from_filename(path: Path) -> int:
    m = _LAB_NO_RE.search(path.stem)
    if not m:
        raise ValueError(f"Cannot determine LAB number from filename: {path.name}")
    return int(m.group(1))


def _clean_page_text(raw: str) -> str:
    """Strip page-number watermark lines and collapse Thai duplicate-token artifacts."""
    text = raw.strip()
    text = _PAGE_NUM_LINE_RE.sub("", text)
    text = re.sub(r"\n{2,}", "\n", text)  # collapse blank lines left by the strip
    # PyMuPDF occasionally emits a Thai word twice in a row where the source
    # PDF wrapped it across a line break (e.g. "สำหรับ หรับ") — collapse runs
    # of an identical token into one occurrence.
    text = _DUP_TOKEN_RE.sub(r"\1", text)
    return text.strip()


def _extract_title(text: str) -> str:
    """First line is the slide title when >80% of its ASCII letters are uppercase."""
    if not text:
        return ""
    first_line = text.splitlines()[0].strip()
    letters = [c for c in first_line if c.isalpha() and ord(c) < 128]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
        return first_line
    return ""


_SQL_KEYWORD_RE = re.compile(
    r"\b(SELECT|FROM|WHERE|JOIN|GROUP BY|HAVING|ORDER BY|INSERT|UPDATE|DELETE|CREATE|ALTER)\b",
    re.IGNORECASE,
)


def chunk_slide_deck(pdf_path: Path) -> list[SlideChunk]:
    """Extract and chunk a single lab deck PDF into parent/child SlideChunks."""
    import fitz  # PyMuPDF

    pdf_path = Path(pdf_path)
    lab_no = _lab_no_from_filename(pdf_path)
    taxonomy = LAB_TAXONOMY.get(
        lab_no, {"topic": "unknown", "category": "query", "error_types": []}
    )
    source_deck = pdf_path.stem
    # Deck-name fallback (e.g. "Data Definition Language") for the handful of
    # cover/title pages that precede the first ALL-CAPS slide heading. Strips
    # the "DB66-LAB <n>-" filename prefix, leaving just the topic.
    deck_display_name = re.sub(r"^.*?LAB\s*\d+\s*-?\s*", "", source_deck, flags=re.IGNORECASE).strip(" -")

    doc = fitz.open(pdf_path)
    try:
        pages_text: list[str] = [_clean_page_text(p.get_text()) for p in doc]
    finally:
        doc.close()

    titles: list[str] = []
    section_title = deck_display_name
    for text in pages_text:
        title = _extract_title(text)
        if title:
            section_title = title
        titles.append(section_title)

    chunks: list[SlideChunk] = []
    n = len(pages_text)
    for i, text in enumerate(pages_text):
        if not text:
            continue
        page_no = i + 1
        slide_title = _extract_title(text) or titles[i]

        header = f"[LAB {lab_no} — {titles[i]} | {slide_title} | slide {page_no}]"
        child_text = f"{header}\n{text}"

        window = pages_text[max(0, i - 1) : min(n, i + 2)]
        parent_text = "\n\n---\n\n".join(t for t in window if t)

        chunks.append(
            SlideChunk(
                id=f"{source_deck}_p{page_no}",
                child_text=child_text,
                parent_text=parent_text,
                source_deck=source_deck,
                lab_no=lab_no,
                page=page_no,
                slide_title=slide_title,
                section_title=titles[i],
                topic=str(taxonomy["topic"]),
                category=str(taxonomy["category"]),
                error_types=list(taxonomy["error_types"]),  # type: ignore[arg-type]
                has_sql=bool(_SQL_KEYWORD_RE.search(text)),
                has_thai=bool(_THAI_RE.search(text)),
            )
        )

    return chunks


def chunk_all_decks(slides_dir: Path) -> list[SlideChunk]:
    """Chunk every PDF in `slides_dir`. Skips files that don't match `LAB <n>`."""
    slides_dir = Path(slides_dir)
    all_chunks: list[SlideChunk] = []
    for pdf_path in sorted(slides_dir.glob("*.pdf")):
        try:
            chunks = chunk_slide_deck(pdf_path)
        except ValueError as e:
            logger.warning("Skipping %s: %s", pdf_path.name, e)
            continue
        all_chunks.extend(chunks)
        logger.info("Chunked %s: %d slides", pdf_path.name, len(chunks))
    return all_chunks
