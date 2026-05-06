"""Chunking strategy for asset profile markdown.

The corpus is short, well-structured markdown — one document per asset,
roughly 250 words split into 5 H2 sections. The right chunk for this
shape is one chunk per H2 section, plus a "headline" chunk for the
title and opening summary.

Why per-section rather than fixed-size chunks?
- Section boundaries are semantic boundaries. A paragraph about
  consensus and a paragraph about history shouldn't share a chunk.
- Retrieval against a query like "BTC consensus" should hit exactly
  the consensus section, not a window that straddles sections.
- The corpus is small enough that we don't need to worry about chunk
  count blowing up the index.

Each chunk keeps metadata about which document and section it came
from so retrieval results can be cited and filtered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Matches H1 (# Title) and H2 (## Section) markdown headers at line start.
H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)
H2_RE = re.compile(r"^## (.+)$", re.MULTILINE)


@dataclass
class Chunk:
    """One semantic chunk of a document."""

    text: str
    document_id: str  # filename stem, e.g. "bitcoin"
    section: str  # H2 heading, or "headline" for the lead chunk
    title: str  # H1 of the parent document


def chunk_markdown(content: str, document_id: str) -> list[Chunk]:
    """Split a markdown document into headline + per-section chunks.

    The headline chunk is the H1 plus the lead paragraph(s) before the
    first H2. Each subsequent chunk is one H2 section, including its
    heading.
    """
    # Extract H1 title
    title_match = H1_RE.search(content)
    if not title_match:
        raise ValueError(f"Document {document_id} has no H1 title")
    title = title_match.group(1).strip()

    # Locate H2 boundaries
    h2_matches = list(H2_RE.finditer(content))

    chunks: list[Chunk] = []

    # Headline chunk: from the start through the first H2 (or end of doc).
    headline_end = h2_matches[0].start() if h2_matches else len(content)
    headline_text = content[:headline_end].strip()
    if headline_text:
        chunks.append(
            Chunk(
                text=headline_text,
                document_id=document_id,
                section="headline",
                title=title,
            )
        )

    # Per-section chunks
    for i, match in enumerate(h2_matches):
        section_name = match.group(1).strip()
        start = match.start()
        end = h2_matches[i + 1].start() if i + 1 < len(h2_matches) else len(content)
        section_text = content[start:end].strip()
        if section_text:
            chunks.append(
                Chunk(
                    text=section_text,
                    document_id=document_id,
                    section=section_name,
                    title=title,
                )
            )

    return chunks


def chunk_directory(directory: Path) -> list[Chunk]:
    """Chunk every .md file in a directory."""
    chunks: list[Chunk] = []
    for md_file in sorted(directory.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        document_id = md_file.stem
        chunks.extend(chunk_markdown(content, document_id))
    return chunks