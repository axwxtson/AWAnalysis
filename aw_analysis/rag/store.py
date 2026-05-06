"""ChromaDB wrapper.

ChromaDB is used here in "persistent client" mode: an embedded database
backed by a directory on disk. No server process required. Good for a
single-process portfolio project; not appropriate for a multi-process
production service (which would want pgvector or a hosted Chroma server).

Why ChromaDB and not pgvector for Stage 4?
- Setup friction: ChromaDB needs no Postgres install, no migrations,
  no SQL.
- The data here is regenerable from the markdown corpus, so a
  file-backed store with a clean wipe-and-rebuild is fine.
- We will likely revisit storage in a later stage when persistence
  becomes more central. Swapping ChromaDB for pgvector is a one-file
  change because the retrieval interface is decoupled from the store.
"""

from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.api.models.Collection import Collection

from aw_analysis.config import SETTINGS


COLLECTION_NAME = "asset_profiles"


class ChromaStore:
    """Persistent ChromaDB client for the asset profile collection."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SETTINGS.chroma_path
        self.path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.path))

    def collection(self) -> Collection:
        """Get or create the asset_profiles collection."""
        return self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},  # cosine similarity
        )

    def reset(self) -> None:
        """Wipe the collection — used during ingestion."""
        try:
            self._client.delete_collection(COLLECTION_NAME)
        except Exception:  # noqa: BLE001 — collection may not exist
            pass

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        """Upsert chunks into the collection."""
        self.collection().upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 4,
    ) -> dict:
        """Return top-N results for a query embedding."""
        return self.collection().query(
            query_embeddings=[query_embedding],
            n_results=n_results,
        )