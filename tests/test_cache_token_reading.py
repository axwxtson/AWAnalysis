"""Reading cache counts off a usage block that may not have them.

The awkward cases are the normal ones. Today every call is uncached, so
the SDK returns None for both fields rather than 0, and an older SDK
omits them entirely. Both must read as zero rather than raising, because
this lands before the cache breakpoint does and would otherwise fail on
every call until Batch 4b.
"""
from __future__ import annotations

from aw_analysis.agent.trace import cache_tokens


class _Usage:
    def __init__(self, **fields: object) -> None:
        self.__dict__.update(fields)


def test_missing_fields_read_as_zero() -> None:
    """An SDK with no prompt-caching support at all."""
    assert cache_tokens(_Usage(input_tokens=10)) == (0, 0)


def test_none_fields_read_as_zero() -> None:
    """The current state: caching supported, not requested."""
    usage = _Usage(cache_creation_input_tokens=None, cache_read_input_tokens=None)
    assert cache_tokens(usage) == (0, 0)


def test_real_counts_are_returned_in_order() -> None:
    usage = _Usage(cache_creation_input_tokens=2609, cache_read_input_tokens=0)
    assert cache_tokens(usage) == (2609, 0)