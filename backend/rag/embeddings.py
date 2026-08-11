"""
Local embedding function — fastembed (ONNX, no PyTorch) for the slide-material
knowledge base.

Free/offline alternative to `GoogleEmbeddingFunction` (retriever.py) for a
bilingual Thai/English corpus. Default model is
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (Apache-2.0,
~220MB, 384-dim) — small enough to pull on a slow connection; swap
`LOCAL_EMBEDDING_MODEL` to `intfloat/multilingual-e5-large` (MIT, ~2.2GB,
1024-dim, needs query/passage prefixes — see below) for materially better
recall if bandwidth allows. Full list: `fastembed.TextEmbedding.list_supported_models()`.

E5-family models are trained with an instruction prefix on both sides of
retrieval — "query: " on the search query, "passage: " on indexed documents
— dropping this quietly degrades retrieval quality. Non-E5 models (MiniLM,
mpnet) don't use this convention, so the prefix is only applied when the
model name contains "e5".

Falls back to the same deterministic hash-embedding scheme as
GoogleEmbeddingFunction when the model can't be loaded (offline CI, no
internet for the first model pull, or an unsupported model name), so tests
keep passing without a download.

Version: 2026-08-10
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import chromadb

from backend.rag.retriever import GoogleEmbeddingFunction

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class FastEmbedEmbeddingFunction(chromadb.EmbeddingFunction[list[str]]):
    """
    ChromaDB-compatible embedding function using `fastembed` (ONNX runtime).

    Args:
        model_name: fastembed/HuggingFace model id.
        mode: "passage" for documents being indexed, "query" for search
              queries — controls which E5 instruction prefix is applied.
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        mode: Literal["passage", "query"] = "passage",
    ) -> None:
        self.model_name = model_name
        self.mode = mode
        self._model: Any = None
        try:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=model_name)
            logger.info("fastembed model loaded: %s", model_name)
        except Exception as e:
            logger.warning(
                "fastembed model unavailable (%s) — using fallback hash embeddings.", e
            )

    def __call__(self, input: list[str]) -> list[list[float]]:
        if "e5" in self.model_name.lower():
            prefix = "query: " if self.mode == "query" else "passage: "
            prefixed = [prefix + text for text in input]
        else:
            prefixed = list(input)

        if self._model is not None:
            try:
                return [vec.tolist() for vec in self._model.embed(prefixed)]
            except Exception as e:
                logger.warning("fastembed inference failed (%s) — using fallback.", e)

        # Fallback: same deterministic hash scheme used by GoogleEmbeddingFunction,
        # so offline behaviour is consistent across both collections.
        return [GoogleEmbeddingFunction._hash_embed(text) for text in prefixed]

    def name(self) -> str:
        """Return the embedding function name (required by ChromaDB 1.x)."""
        return f"fastembed-{self.model_name}-{self.mode}"
