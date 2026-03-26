"""
Long-term Memory — ChromaDB for persisting and retrieving past student interactions.

Every interaction (code, error_type, hint) is embedded and stored. This allows the tutor 
to retrieve similar past struggles to personalize the feedback or notice long-term 
patterns in student behavior.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from backend.config import get_settings
from backend.rag.retriever import GoogleEmbeddingFunction

logger = logging.getLogger(__name__)

class LongTermMemory:
    """Async wrapper for ChromaDB interactions storage."""

    def __init__(self, persist_dir: str, collection_name: str) -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self._client: Optional[chromadb.ClientAPI] = None
        self._collection: Optional[chromadb.Collection] = None

    def initialize(self) -> None:
        """Connect to ChromaDB and ensure the collection exists."""
        if self._client is None:
            try:
                if self.persist_dir:
                    self._client = chromadb.Client(ChromaSettings(
                        anonymized_telemetry=False,
                        is_persistent=True,
                        persist_directory=self.persist_dir,
                    ))
                else:
                    self._client = chromadb.Client(ChromaSettings(
                        anonymized_telemetry=False,
                        is_persistent=False,
                    ))
                
                settings = get_settings()
                embedding_fn = GoogleEmbeddingFunction(
                    model_name=settings.EMBEDDING_MODEL,
                )
                
                self._collection = self._client.get_or_create_collection(
                    name=self.collection_name,
                    embedding_function=embedding_fn,
                    metadata={"description": "Student SQL interaction history for long-term pattern retrieval"},
                )
                logger.info("Long-term memory (ChromaDB) initialized collection: %s", self.collection_name)
            except Exception as e:
                logger.error("Failed to initialize ChromaDB for long-term memory: %s", e)

    def store_interaction(
        self, 
        user_id: int, 
        problem_id: int, 
        code: str, 
        error_type: str, 
        hint_text: str,
        interaction_id: int,
    ) -> None:
        """Embed and store an interaction in ChromaDB."""
        if not self._collection:
            return

        try:
            # Combine context for a rich embedding
            interaction_text = (
                f"SQL Interaction:\n"
                f"Student Code: {code}\n"
                f"Error Classification: {error_type}\n"
                f"Hint Given: {hint_text}"
            )
            
            self._collection.add(
                ids=[str(interaction_id)],
                documents=[interaction_text],
                metadatas=[{
                    "user_id": user_id,
                    "problem_id": problem_id,
                    "error_type": error_type,
                    "interaction_id": interaction_id,
                }]
            )
        except Exception as e:
            logger.error("Error storing interaction in long-term memory: %s", e)

    def retrieve_similar_struggles(
        self, 
        user_id: int, 
        query: str, 
        n_results: int = 3
    ) -> list[dict[str, Any]]:
        """Retrieve historical struggles for a student to personalize feedback."""
        if not self._collection:
            return []

        try:
            # Filter by current user to avoid cross-student confusion
            results = self._collection.query(
                query_texts=[query],
                n_results=n_results,
                where={"user_id": user_id},
                include=["documents", "metadatas", "distances"]
            )
            
            # Format results
            struggles: list[dict[str, Any]] = []
            if results and results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    struggles.append({
                        "id": doc_id,
                        "content": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i] if results["distances"] else None,
                    })
            return struggles
        except Exception as e:
            logger.error("Error retrieving similar struggles from ChromaDB: %s", e)
            return []

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_long_term_memory: Optional[LongTermMemory] = None

def get_long_term_memory() -> LongTermMemory:
    """Return the global LongTermMemory instance."""
    global _long_term_memory
    if _long_term_memory is None:
        settings = get_settings()
        _long_term_memory = LongTermMemory(
            persist_dir=settings.CHROMA_PERSIST_DIR,
            collection_name=settings.CHROMA_STUDENT_COLLECTION,
        )
    return _long_term_memory
