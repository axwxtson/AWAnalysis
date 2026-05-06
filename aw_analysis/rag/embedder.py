"""Voyage AI embedding client.

We use voyage-3 by default — Voyage's general-purpose model, which
produces 1024-dimensional embeddings. Voyage also offers voyage-3-large
(better quality, slower, more expensive) and voyage-3-lite (faster,
cheaper, lower quality). For a 50-chunk corpus, the differences are
not worth optimising.

Two methods:
- `embed_documents`: batch-embed text for storage. Voyage requires
  input_type="document" for documents that will be retrieved against.
- `embed_query`: embed a single query. input_type="query" — using a
  different embedding for query vs. document is a Voyage feature that
  improves retrieval quality.

This asymmetric query/document embedding is one of the things that
distinguishes a well-built RAG from a naive one.
"""

from __future__ import annotations

import voyageai

from aw_analysis.config import SETTINGS


class VoyageEmbedder:
    """Wrapper around the Voyage AI embedding client."""

    def __init__(self, model: str | None = None) -> None:
        if not SETTINGS.voyage_api_key:
            raise RuntimeError(
                "VOYAGE_API_KEY is not set — RAG features are unavailable. "
                "Get a key at https://dash.voyageai.com/ and set it in .env."
            )
        self._client = voyageai.Client(api_key=SETTINGS.voyage_api_key)
        self.model = model or SETTINGS.embedding_model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents for storage."""
        result = self._client.embed(
            texts=texts,
            model=self.model,
            input_type="document",
        )
        return result.embeddings

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query for retrieval."""
        result = self._client.embed(
            texts=[query],
            model=self.model,
            input_type="query",
        )
        return result.embeddings[0]    