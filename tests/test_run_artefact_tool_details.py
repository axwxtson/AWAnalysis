"""The golden run artefact must carry tool arguments and results.

_serialise_trace is the only write site in the golden runner. EvalResult
has no tool list of its own, so in a golden artefact tool names appear
only inside sub_traces. Nothing exercised it before this file, which
meant the tool_details record reached artefacts on the strength of a
grep and nothing else.

tool_calls stays a list of names because graders read that shape.
Asserting both pins the derivation: the names come from the detail
records rather than from a second traversal, so they cannot drift.

The import is private. That is deliberate: _serialise_trace is the
serialisation boundary, and testing the public runner around it would
need a live client.
"""
from __future__ import annotations

from aw_analysis.agent.trace import ToolCall, TurnTrace
from evals.runner.run import _serialise_trace


def test_sub_trace_records_arguments_and_results_with_names_derived() -> None:
    trace = TurnTrace(
        user_message="what is BTC at",
        final_text="BTC is at 64000.",
        tool_calls=[
            ToolCall(
                name="get_crypto_price",
                duration_ms=3.0,
                success=True,
                result="BTC 64000 USD",
                arguments={"symbol": "BTC"},
            )
        ],
    )

    got = _serialise_trace(trace)

    assert got["tool_calls"] == ["get_crypto_price"]
    assert len(got["tool_details"]) == 1

    detail = got["tool_details"][0]
    assert detail["name"] == "get_crypto_price"
    assert detail["result"] == "BTC 64000 USD"
    assert detail["arguments"] == {"symbol": "BTC"}
    assert detail["result_truncated"] is False