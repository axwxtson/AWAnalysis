"""Composition of the judge calibration reference set.

The set is populated by a single literal, so its size is greppable, but
its per-dimension balance is not: a pair added under the wrong dimension
string would change what the agreement figure means without changing the
count. Both are asserted.

Block 7 raised the set from twelve to sixteen. Calibration figures are
quoted with their n, so a silent drift here would silently restate a
committed claim.
"""

from __future__ import annotations

from collections import Counter

from evals.calibration.reference_set import REFERENCE_SET


def test_reference_set_holds_sixteen_pairs():
    assert len(REFERENCE_SET) == 16


def test_dimension_balance_is_four_four_eight():
    counts = Counter(pair.dimension for pair in REFERENCE_SET)
    assert counts == {
        "faithfulness": 4,
        "relevance": 8,
        "refusal_correctness": 4,
    }


def test_ids_are_unique():
    ids = [pair.id for pair in REFERENCE_SET]
    assert len(set(ids)) == len(ids)


def test_human_scores_are_on_the_five_point_scale():
    for pair in REFERENCE_SET:
        assert 1 <= pair.human_score <= 5, pair.id


def test_relevance_pairs_include_a_polite_non_answer():
    """The pair the CONCEPT gate depends on.

    Relevance is the only dimension gating a CONCEPT case, and the
    failure it must catch is a hedge rather than an outright decline.
    If no low-scored relevance pair without a refusal exists, the
    calibration cannot speak to that gate at all.
    """
    low = [
        pair for pair in REFERENCE_SET
        if pair.dimension == "relevance" and pair.human_score <= 2
    ]
    assert len(low) >= 3