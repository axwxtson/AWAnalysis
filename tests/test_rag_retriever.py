"""Unit tests for the retriever's distance-to-score inversion.

The inversion is score = max(0.0, 1.0 - distance / 2.0), and
asset_profile._try_curated reads results[0].score as the top score
without sorting. That is only correct because two things hold at once:
Chroma returns ascending distance, and the inversion is monotonically
decreasing. Flip the sign and results[0] becomes the worst result while
the gate keeps comparing against it.

A sign error would not produce nonsense. It would produce curated
misses, which fall through to the CoinGecko or Twelve Data fallback,
which returns a plausible profile the judge may pass. Same shape as
profile_shopify_fallback: a wrong path with a gradeable answer.

Tested through retrieve() with fake collaborators rather than against an
extracted helper. A pure _score(distance) would test the arithmetic and
leave the wiring untested, and the wiring is the part that goes silently
wrong.
"""
from __future__ import annotations

from typing import Any

import pytest

from aw_analysis.rag.retriever import Retriever
from aw_analysis.tools.asset_profile import CURATED_THRESHOLD

QUERY_VECTOR = [0.1, 0.2, 0.3]


def _distance_for(cosine_similarity: float) -> float:
    """Chroma's cosine space: distance = 1 - cosine similarity.

    Written as a conversion rather than a literal so the gate test reads
    as the claim it is checking: 0.70 is cosine 0.40.
    """
    return 1.0 - cosine_similarity


class _RecordingEmbedder:
    """Records which embedding method was used.

    VoyageEmbedder splits embed_query (input_type="query") from
    embed_documents (input_type="document"). Calling the wrong one
    raises nothing and only shifts scores slightly, so the symptom is a
    few borderline cases dropping under the gate.
    """

    def __init__(self) -> None:
        self.query_calls: list[str] = []

    def embed_query(self, query: str) -> list[float]:
        self.query_calls.append(query)
        return QUERY_VECTOR

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError("retrieve must embed with input_type=query")


class _ScriptedStore:
    """Returns Chroma's raw shape: lists of lists, one per query."""

    def __init__(self, distances: list[float], metadatas: list[dict] | None = None) -> None:
        self._distances = distances
        self._metadatas = metadatas or [
            {"document_id": f"doc{i}", "section": f"sec{i}", "title": f"title{i}"}
            for i in range(len(distances))
        ]
        self.n_results_seen: list[int] = []
        self.embeddings_seen: list[list[float]] = []

    def query(self, query_embedding: list[float], n_results: int = 4) -> dict[str, Any]:
        self.embeddings_seen.append(query_embedding)
        self.n_results_seen.append(n_results)
        count = len(self._distances)
        return {
            "ids": [[f"id{i}" for i in range(count)]],
            "documents": [[f"chunk {i}" for i in range(count)]],
            "metadatas": [self._metadatas],
            "distances": [self._distances],
        }


def _retrieve(distances: list[float], **kwargs: Any) -> list[Any]:
    store = _ScriptedStore(distances)
    retriever = Retriever(embedder=_RecordingEmbedder(), store=store)  # type: ignore[arg-type]
    return retriever.retrieve("what is bitcoin", **kwargs)


# --- the transform ----------------------------------------------------


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        (0.0, 1.0),  # identical
        (1.0, 0.5),  # orthogonal, cosine 0
        (2.0, 0.0),  # opposite, cosine -1
    ],
)
def test_distance_maps_to_score(distance: float, expected: float) -> None:
    assert _retrieve([distance])[0].score == pytest.approx(expected)


def test_the_gate_is_cosine_zero_point_four() -> None:
    """Makes the standing claim about 0.70 an artefact rather than a note.

    CURATED_THRESHOLD is a hand-tuned cut on the rescaled score, not a
    cosine threshold. This pins the conversion so the claim cannot drift
    from the code without a test failing.
    """
    at_the_gate = _retrieve([_distance_for(0.40)])[0].score

    assert at_the_gate == pytest.approx(CURATED_THRESHOLD)


def test_scores_fall_as_distances_rise() -> None:
    """The assumption _try_curated rests on when it reads results[0].

    Chroma returns ascending distance and this returns descending score,
    so results[0] is the best match. A sign error would leave results[0]
    the worst match with the gate still comparing against it.
    """
    scores = [r.score for r in _retrieve([0.1, 0.4, 0.9, 1.6])]

    assert scores == sorted(scores, reverse=True)
    assert scores[0] == max(scores)


def test_score_is_clamped_at_zero() -> None:
    """The max() guard. Normalised vectors cannot exceed distance 2, so
    this is defensive; pinned because a negative score would compare
    against the gate perfectly happily and never be noticed."""
    assert _retrieve([2.4])[0].score == 0.0


# --- the wiring -------------------------------------------------------


def test_k_is_forwarded_to_the_store() -> None:
    """If forwarding broke you would silently get the store default of 4,
    which is also the asset_profile DEFAULT_K, so no eval would see it."""
    store = _ScriptedStore([0.1, 0.2])
    Retriever(embedder=_RecordingEmbedder(), store=store).retrieve("q", k=7)  # type: ignore[arg-type]

    assert store.n_results_seen == [7]


def test_the_query_embedding_reaches_the_store() -> None:
    embedder = _RecordingEmbedder()
    store = _ScriptedStore([0.1])
    Retriever(embedder=embedder, store=store).retrieve("what is bitcoin")  # type: ignore[arg-type]

    assert embedder.query_calls == ["what is bitcoin"]
    assert store.embeddings_seen == [QUERY_VECTOR]


# --- result construction ----------------------------------------------


def test_metadata_is_mapped_onto_the_result() -> None:
    store = _ScriptedStore(
        [0.2],
        metadatas=[{"document_id": "d1", "section": "overview", "title": "Bitcoin"}],
    )
    result = Retriever(  # type: ignore[arg-type]
        embedder=_RecordingEmbedder(), store=store
    ).retrieve("q")[0]

    assert (result.document_id, result.section, result.title) == ("d1", "overview", "Bitcoin")
    assert result.text == "chunk 0"


def test_missing_metadata_keys_become_empty_strings() -> None:
    """The .get() defaults. Chunks written before a metadata field
    existed would otherwise raise KeyError inside the tool dispatch and
    surface as a tool failure rather than a degraded result."""
    store = _ScriptedStore([0.2], metadatas=[{}])
    result = Retriever(  # type: ignore[arg-type]
        embedder=_RecordingEmbedder(), store=store
    ).retrieve("q")[0]

    assert (result.document_id, result.section, result.title) == ("", "", "")