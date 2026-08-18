"""Unit tests for forced-tool forwarding, from RouteDecision to tool_choice.

The Stage 9 regression, in full: Conversation.send accepted forced_tool
and never passed it to _run_loop. Fixed in 1453796, one line. tool_choice
was always None, FORCE_MAP routing never reached the API, and the
equities golden set still read 16/16 because the model selected the
right tool unaided. The eval measured the outcome; the mechanism was
dead.

Every assertion here is on the tool_choice kwarg the client receives,
because that is the observable that changes when that line is reverted.
Asserting on the trace, on tool_calls, or on final_text would all pass
against the severed code.

Offline: a recording fake client, a real ToolRegistry with a stub tool,
no wall-clock and no credentials beyond the fake key.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from aw_analysis.agent.conversation import Conversation
from aw_analysis.agent.decomposer import Intent, SubQuery
from aw_analysis.agent.orchestration import OrchestratedConversation
from aw_analysis.agent.trace import TurnTrace
from aw_analysis.asset_registry import AssetRegistry
from aw_analysis.config import TaskType, get_settings
from aw_analysis.config.model_config import MODEL_CONFIG_REGISTRY
from aw_analysis.tools.base import Tool, ToolRegistry

FORCED_TOOL = "get_equity_price"
FORCED_CHOICE = {"type": "tool", "name": FORCED_TOOL}

# No recency cue in this text, deliberately. has_recency_cue would
# inject a reminder message and change the message list under the test.
PRICE_QUERY = "What is Apple trading at?"


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """get_model_config resolves DEFAULT_MODEL against live settings.

    Same shape as test_client_retry.py: get_settings is lru_cached, so
    the cache is cleared on the way in and on the way out, or a fake-key
    Settings survives into whichever test file runs next.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-sent")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- fakes ------------------------------------------------------------


class _Block:
    """Stand-in for a response content block.

    The loop reads blocks with getattr(block, "type", None) and then
    named attributes, so a plain object carrying those attributes is
    exactly what it consumes.
    """

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class _Response:
    def __init__(self, stop_reason: str, content: list[Any]) -> None:
        self.stop_reason = stop_reason
        self.content = content
        self.usage = _Block(input_tokens=1, output_tokens=1)


def _tool_use_response() -> _Response:
    return _Response(
        "tool_use",
        [_Block(type="tool_use", id="toolu_1", name=FORCED_TOOL, input={})],
    )


def _text_response() -> _Response:
    return _Response("end_turn", [_Block(type="text", text="done", citations=None)])


class _RecordingClient:
    """Scripted client that records the tool_choice of every call.

    Not an AnthropicClient subclass: Conversation annotates the field
    but never checks it, and subclassing would construct an SDK client
    for no gain.

    count_tokens returns 0 so the context-budget guard is a stated
    no-op. Omitting it would also work, because the guard wraps the call
    in a bare except, but then these tests would pass because an
    AttributeError was swallowed rather than because the budget was
    under.
    """

    def __init__(self, *responses: Any) -> None:
        self._responses = list(responses)
        self.tool_choices: list[Any] = []

    def count_tokens(self, **_: Any) -> int:
        return 0

    def create(self, **kwargs: Any) -> Any:
        self.tool_choices.append(kwargs.get("tool_choice"))
        index = min(len(self.tool_choices) - 1, len(self._responses) - 1)
        return self._responses[index]


class _StubTool(Tool):
    """Registered in a real ToolRegistry so dispatch runs for real.

    Attributes are set on the instance rather than the class: the base
    class declares them as annotations, and a mutable class attribute
    here would trip RUF012, which is exempted for aw_analysis/tools/*
    but not for tests.
    """

    def __init__(self) -> None:
        self.name = FORCED_TOOL
        self.description = "stub tool for offline dispatch"
        self.input_schema = {"type": "object", "properties": {}}

    def execute(self, **kwargs: Any) -> str:
        return "stub result"


def _conversation(client: Any) -> Conversation:
    registry = ToolRegistry()
    registry.register(_StubTool())
    return Conversation(client=client, tools=registry, system_prompt="system")


# --- send -> _run_loop -> client.create -------------------------------


def test_forced_tool_is_sent_on_the_first_call_only() -> None:
    """The severed line, and the reason forcing must stop.

    First half: reverting 1453796 makes tool_choices[0] None and this
    fails. Second half: forced_tool is threaded into the whole loop, not
    just the first call, so forcing every iteration would trap the model
    in tool calls and it would never synthesise an answer.
    """
    client = _RecordingClient(_tool_use_response(), _text_response())

    _conversation(client).send(PRICE_QUERY, forced_tool=FORCED_TOOL)

    assert client.tool_choices == [FORCED_CHOICE, None]


def test_unforced_send_never_sets_tool_choice() -> None:
    """The control. Without it, code that hard-codes forcing on would
    pass the test above and nothing would notice."""
    client = _RecordingClient(_tool_use_response(), _text_response())

    _conversation(client).send(PRICE_QUERY)

    assert client.tool_choices == [None, None]


# --- decide_route -> _run_sub_query -> send ---------------------------


class _RecordingConversation:
    """Stands in for Conversation, to isolate the routing translation.

    Paired with the tests above, the chain RouteDecision -> forced_tool
    -> tool_choice is covered in two hops with no untested join.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def send(self, text: str, *, forced_tool: str | None = None) -> TurnTrace:
        self.calls.append((text, forced_tool))
        return TurnTrace(user_message=text)


def _orchestrated(conversation: Any) -> OrchestratedConversation:
    """A registry with no disambiguator, so resolution is deterministic:
    AAPL is a curated equity, SPY is in the UNSUPPORTED gate, and no
    model call is reachable. The decomposer stub is never classified
    with; these tests call _run_sub_query directly."""
    return OrchestratedConversation(
        client=object(),
        conversation=conversation,
        decomposer=object(),
        registry=AssetRegistry(),
    )


def test_force_decision_reaches_send_as_forced_tool() -> None:
    conversation = _RecordingConversation()

    _orchestrated(conversation)._run_sub_query(
        SubQuery(intent=Intent.PRICE, text=PRICE_QUERY, symbols=["AAPL"])
    )

    assert conversation.calls == [(PRICE_QUERY, FORCED_TOOL)]


def test_refuse_decision_never_calls_the_agent() -> None:
    """The deterministic gate is a cost claim as well as a behaviour one:
    refusal is meant to happen at zero model cost."""
    conversation = _RecordingConversation()

    trace = _orchestrated(conversation)._run_sub_query(
        SubQuery(intent=Intent.PRICE, text="What is SPY trading at?", symbols=["SPY"])
    )

    assert conversation.calls == []
    assert trace.was_refusal is True


def test_price_intent_restores_the_tool_selection_config() -> None:
    """_run_sub_query mutates MODEL_CONFIG_REGISTRY in place for PRICE
    and restores it in a finally. A test that left it swapped would
    corrupt every test that ran afterwards, so the round-trip is pinned
    here rather than assumed."""
    before = MODEL_CONFIG_REGISTRY[TaskType.TOOL_SELECTION]
    conversation = _RecordingConversation()

    _orchestrated(conversation)._run_sub_query(
        SubQuery(intent=Intent.PRICE, text=PRICE_QUERY, symbols=["AAPL"])
    )

    assert MODEL_CONFIG_REGISTRY[TaskType.TOOL_SELECTION] is before