"""End-to-end ingestion pipeline.

Run as a one-off script:
    python -m aw_analysis.rag.ingest

Reads markdown from data/asset_profiles/, chunks each file, embeds the
chunks via Voyage, and upserts them into ChromaDB. Wipes the existing
collection first so re-ingestion produces a clean state.

This is intentionally a script, not a tool the agent calls. Embedding
is something that happens at build time, not at query time.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from aw_analysis.config import REPO_ROOT
from aw_analysis.rag.chunker import chunk_directory
from aw_analysis.rag.embedder import VoyageEmbedder
from aw_analysis.rag.store import ChromaStore

console = Console()

ASSET_PROFILES_DIR = REPO_ROOT / "data" / "asset_profiles"


def main() -> int:
    if not ASSET_PROFILES_DIR.exists():
        console.print(
            f"[red]Error:[/red] {ASSET_PROFILES_DIR} does not exist. "
            f"Add markdown profiles before ingesting."
        )
        return 1

    console.print(
        f"[cyan]Chunking[/cyan] {ASSET_PROFILES_DIR.relative_to(REPO_ROOT)}..."
    )
    chunks = chunk_directory(ASSET_PROFILES_DIR)
    if not chunks:
        console.print("[yellow]No chunks produced.[/yellow]")
        return 1

    console.print(f"  produced {len(chunks)} chunks")

    console.print("[cyan]Embedding[/cyan] chunks via Voyage...")
    try:
        embedder = VoyageEmbedder()
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    texts = [c.text for c in chunks]
    embeddings = embedder.embed_documents(texts)
    console.print(f"  embedded {len(embeddings)} chunks "
                  f"({len(embeddings[0])}-dim vectors)")

    console.print("[cyan]Storing[/cyan] in ChromaDB...")
    store = ChromaStore()
    store.reset()  # clean rebuild

    ids = [f"{c.document_id}:{c.section}" for c in chunks]
    metadatas = [
        {
            "document_id": c.document_id,
            "section": c.section,
            "title": c.title,
        }
        for c in chunks
    ]

    store.upsert(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    console.print(f"  stored {len(ids)} chunks at {store.path}")

    console.print("\n[green]Done.[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())