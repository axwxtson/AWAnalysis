"""The citation rebuild must preserve every ToolCall field but `result`.

`Conversation._capture_citations` appends cited snippets to the most
recent web_search ToolCall. ToolCall is frozen, so appending means
replacing. Before 36d5179 the replacement named each field explicitly,
so any field added to ToolCall afterwards would be dropped there and
nowhere else: recorded correctly on every tool except the one whose
results most need auditing, and visible only as a missing value in a run
artefact committed long after the change that caused it.

The assertion iterates dataclasses.fields rather than naming fields, so
it covers `arguments` and everything added after it without being
edited. A test that named the fields would need the same maintenance as
the code it guards, and would fail in the same way.
"""
from __future__ import annotations

from dataclasses import fields
from typing import Any

from aw_analysis.agent.conversation import Conversation
from aw_analysis.agent.trace import ToolCall, TurnTrace


class _Attrs:
    """Attribute bag. The citation path reads blocks and citations with
    getattr, so a plain object carrying those attributes is what it
    consumes."""

    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


def _conversation() -> Conversation:
    """_capture_citations reaches no collaborator: it reads the content
    list, mutates the trace, and calls a staticmethod. The client and
    registry are never touched, so stubs keep this offline."""
    return Conversation(client=object(), tools=object(), system_prompt="")


def test_citation_rebuild_preserves_every_field_but_result() -> None:
    original = ToolCall(
        name="web_search",
        duration_ms=12.5,
        success=True,
        error=None,
        result="raw search payload",
        arguments={"query": "bitcoin price"},
    )
    trace = TurnTrace(user_message="what is bitcoin doing")
    trace.tool_calls.append(original)

    citation = _Attrs(cited_text="BTC rose 3%", url="https://example.test/a", title="A")
    content = [_Attrs(type="text", text="Bitcoin is up.", citations=[citation])]

    _conversation()._capture_citations(content, trace)

    rebuilt = trace.tool_calls[0]

    # Load-bearing. _capture_citations returns early when it finds no
    # snippets, leaving the original object in place. Without this the
    # field loop below would compare an object against itself and pass
    # for the wrong reason.
    assert rebuilt is not original
    assert "--- Cited snippets ---" in rebuilt.result

    for f in fields(ToolCall):
        if f.name == "result":
            continue
        assert getattr(rebuilt, f.name) == getattr(original, f.name), f.name