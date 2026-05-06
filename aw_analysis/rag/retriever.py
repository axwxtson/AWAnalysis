"""Retrieval interface.

Retriever is the agent-facing API: given a query string, return a list
of relevant chunks with scores. It hides the embedder + store wiring
from the rest of the codebase.

Score semantics:
- ChromaDB returns "distances" (lower is more similar) for cosine space.
- We invert this to a "score" (higher is more similar) for the agent's
  benefit. Score is in [0, 1] approximately; 1.0 means identical.
"""

from __future__ import annotations

from dataclasses import dataclass

from aw_analysis.rag.embedder import VoyageEmbedder
from aw_analysis.rag.store import ChromaStore


@dataclass
class RetrievalResult:
    """One result from a retrieval query."""

    text: str
    document_id: str
    section: str
    title: str
    score: float  # higher = more relevant


class Retriever:
    """High-level retrieval API."""

    def __init__(
        self,
        embedder: VoyageEmbedder | None = None,
        store: ChromaStore | None = None,
    ) -> None:
        self._embedder = embedder or VoyageEmbedder()
        self._store = store or ChromaStore()

    def retrieve(self, query: str, k: int = 4) -> list[RetrievalResult]:
        """Return the top-k chunks for a query."""
        query_embedding = self._embedder.embed_query(query)
        raw = self._store.query(query_embedding, n_results=k)

        # Chroma returns lists of lists (one per query); we sent one query
        # so we want the inner list.
        ids = raw["ids"][0]
        documents = raw["documents"][0]
        metadatas = raw["metadatas"][0]
        distances = raw["distances"][0]

        results: list[RetrievalResult] = []
        for i, doc_id in enumerate(ids):
            metadata = metadatas[i]
            # Distance for cosine space is in [0, 2]; convert to a
            # similarity score in approximately [0, 1].
            distance = distances[i]
            score = max(0.0, 1.0 - distance / 2.0)
            results.append(
                RetrievalResult(
                    text=documents[i],
                    document_id=metadata.get("document_id", ""),
                    section=metadata.get("section", ""),
                    title=metadata.get("title", ""),
                    score=score,
                )
            )
        return results