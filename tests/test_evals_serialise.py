"""Unit tests for the shared tool-call serialiser.

The cap guards against an unbounded payload rather than setting a size
policy, so the case that matters is that a capped record still describes
the string it came from: result_bytes and result_sha256 are of the full
result, not of the shortened copy. A record reporting the truncated
length would be self-consistent and useless.
"""
from __future__ import annotations

import hashlib

from aw_analysis.agent.trace import ToolCall
from evals.serialise import RESULT_CAP, tool_detail


def _call(result: str) -> ToolCall:
    return ToolCall(
        name="get_crypto_price",
        duration_ms=8.0,
        success=True,
        error=None,
        result=result,
        arguments={"symbol": "BTC"},
    )


def test_short_result_is_recorded_whole() -> None:
    payload = "BTC 64000 USD"
    got = tool_detail(_call(payload))

    assert got["result"] == payload
    assert got["result_truncated"] is False
    assert got["result_bytes"] == len(payload.encode("utf-8"))
    assert got["result_sha256"] == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert got["arguments"] == {"symbol": "BTC"}


def test_capped_result_still_describes_the_full_string() -> None:
    payload = "x" * (RESULT_CAP + 500)
    got = tool_detail(_call(payload))

    assert got["result_truncated"] is True
    assert len(got["result"]) == RESULT_CAP
    # The two fields that make a capped record checkable rather than
    # merely shorter. Both are of the original, not of got["result"].
    assert got["result_bytes"] == RESULT_CAP + 500
    assert got["result_sha256"] == hashlib.sha256(payload.encode("utf-8")).hexdigest()