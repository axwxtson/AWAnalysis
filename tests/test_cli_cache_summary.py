"""The bin/aw cache line is the only instrument for the Stage 4 claim.

A single turn writes no artefact and the cheapest eval run is a whole
asset class, so this footer is what a live measurement reads.
"""
from __future__ import annotations

from aw_analysis.cli.main import _format_cache


class _Iteration:
    def __init__(self, created: int, read: int) -> None:
        self.cache_creation_input_tokens = created
        self.cache_read_input_tokens = read


def test_totals_sum_across_iterations() -> None:
    """The shape a working cache produces: one creation on the first
    iteration, a read on each one after it."""
    iterations = [_Iteration(2609, 0), _Iteration(0, 2609), _Iteration(0, 2609)]

    assert _format_cache(iterations) == "cache: created=2609 read=5218"


def test_zeros_are_printed_rather_than_suppressed() -> None:
    assert _format_cache([_Iteration(0, 0)]) == "cache: created=0 read=0"


def test_no_iterations_is_not_an_error() -> None:
    assert _format_cache([]) == "cache: created=0 read=0"