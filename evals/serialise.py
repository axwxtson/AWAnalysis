"""Shared serialisation of a ToolCall into a run artefact record.

Lives here rather than in either caller because the golden runner and the
red-team adapter both write it, and a second copy would drift.

The result string is recorded whole. `evals/results` is 2.7M across 39
artefacts today, largest 111KB, and adding full tool results to a 23-case
run roughly doubles that one file. Worth paying: a truncated result makes
the faithfulness score in the same record unreproducible, because the
judge grades against ToolCall.result at evals/grader/judge.py:159. A
shortened copy would be evidence for a verdict reached on something else.

RESULT_CAP is therefore not a size policy. It guards against an unbounded
payload from a malformed upstream response or a red-team attack that
induces one, and sits far above anything a well-behaved turn produces.
When it fires the record says so, and result_bytes and result_sha256 keep
describing the full string, so a capped record can still be checked
against the original rather than quietly standing in for it.

Diagnostic only. The name lists the graders read stay separate keys, so a
change to this shape cannot move a score.
"""
from __future__ import annotations

import hashlib
from typing import Any

from aw_analysis.agent.trace import ToolCall

RESULT_CAP = 20_000


def tool_detail(tc: ToolCall) -> dict[str, Any]:
    """One tool invocation as a JSON-friendly record."""
    encoded = tc.result.encode("utf-8")
    truncated = len(encoded) > RESULT_CAP
    body = tc.result
    if truncated:
        # Slicing bytes can cut a multi-byte character in half. Replace
        # rather than raise: result_sha256 below still identifies the
        # full string exactly, so nothing that matters is lost.
        body = encoded[:RESULT_CAP].decode("utf-8", errors="replace")
    return {
        "name": tc.name,
        "arguments": tc.arguments,
        "success": tc.success,
        "error": tc.error,
        "duration_ms": tc.duration_ms,
        "result": body,
        "result_bytes": len(encoded),
        "result_sha256": hashlib.sha256(encoded).hexdigest(),
        "result_truncated": truncated,
    }