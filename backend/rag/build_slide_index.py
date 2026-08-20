"""
Offline index builder for the slide-material knowledge base.

Mirrors the `python -m backend.db.seed` convention: run once to (re)build
the persisted Chroma collection so `uvicorn` startup just opens it instead
of re-embedding 300+ chunks on every reload.

Usage:
    python -m backend.rag.build_slide_index                # build if empty
    python -m backend.rag.build_slide_index --rebuild        # force rebuild
    python -m backend.rag.build_slide_index --dry-run        # chunk only, no embedding
    python -m backend.rag.build_slide_index --slides-dir path/to/pdfs

Version: 2026-08-10
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# The corpus is bilingual (Thai + English); Windows consoles default to
# cp1252, which can't encode Thai text and crashes bare `print()` calls.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the slide-material RAG index.")
    parser.add_argument("--rebuild", action="store_true", help="Drop and re-seed the collection even if it already has data.")
    parser.add_argument("--dry-run", action="store_true", help="Chunk the PDFs and print stats/samples; embed nothing.")
    parser.add_argument("--slides-dir", default=None, help="Override slide-material directory (default: settings.SLIDE_MATERIAL_DIR).")
    args = parser.parse_args()

    from backend.config import get_settings

    settings = get_settings()
    slides_dir = Path(args.slides_dir or settings.SLIDE_MATERIAL_DIR)

    if not slides_dir.exists():
        logger.error("Slide directory not found: %s", slides_dir)
        sys.exit(1)

    from backend.rag.slide_ingest import chunk_all_decks

    chunks = chunk_all_decks(slides_dir)
    if not chunks:
        logger.error("No chunks extracted from %s — nothing to index.", slides_dir)
        sys.exit(1)

    from collections import Counter

    by_lab = Counter(c.lab_no for c in chunks)
    by_category = Counter(c.category for c in chunks)
    print(f"Extracted {len(chunks)} chunks from {slides_dir}")
    print(f"  by lab:      {dict(sorted(by_lab.items()))}")
    print(f"  by category: {dict(by_category)}")
    print()
    print("Sample chunks:")
    for c in chunks[:1] + chunks[len(chunks) // 2 : len(chunks) // 2 + 1] + chunks[-1:]:
        print(f"--- {c.id} ({c.citation}) ---")
        print(c.child_text[:300])
        print()

    if args.dry_run:
        print("Dry run — no embedding, no index written.")
        return

    from backend.rag.slide_retriever import initialize_slide_kb, reset_slide_kb

    if args.rebuild:
        logger.info("--rebuild: clearing existing collection first.")
        try:
            initialize_slide_kb(slides_dir=str(slides_dir))  # open to get a client reference
        except Exception:
            pass
        reset_slide_kb(drop_persisted=True)

    collection = initialize_slide_kb(slides_dir=str(slides_dir))
    print(f"Index ready: '{collection.name}' — {collection.count()} chunks.")
    persist_dir = settings.CHROMA_PERSIST_DIR
    print(f"Persist dir: {persist_dir or '(in-memory — set CHROMA_PERSIST_DIR to persist across restarts)'}")


if __name__ == "__main__":
    main()
