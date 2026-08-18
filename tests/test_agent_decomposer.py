"""Unit tests for _parse_plan, the classifier's output contract.

Every failure here raises DecomposerError, and orchestration catches it
and runs the original query through the full agent instead. That
fallback usually produces a good answer, so a decomposer failing on one
hundred per cent of inputs would leave the golden set green: the system
would just be slower, dearer, and no longer decomposing, with the only
signal being decomposition_fallback_reason in trace metadata that no
eval assertion reads.

So the load-bearing tests here are not the obvious ones. They are the
markdown fence stripping, because Haiku emits fences intermittently and
losing that safety belt produces exactly that silent degradation, and
the error message contents, because that string becomes the only
forensic record of why a turn fell back.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from aw_analysis.agent.decomposer import (
    Decomposer,
    DecomposerError,
    Intent,
    QueryPlan,
)
from aw_analysis.agent.orchestration import OrchestratedConversation
from aw_analysis.agent.trace import TurnTrace
from aw_analysis.asset_registry import AssetRegistry
from aw_analysis.config import get_settings

ORIGINAL = "What is Bitcoin and how is Apple doing?"
VALID_BODY = '{"sub_queries": [{"intent": "price", "text": "BTC price", "symbols": ["BTC"]}]}'


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Decomposer.__init__ resolves INTENT_CLASSIFICATION against settings."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-sent")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _parse(raw: str) -> QueryPlan:
    """_parse_plan does not touch self, but it is an instance method and
    tested as one rather than reached unbound, so the test breaks if it
    later starts depending on instance state."""
    return Decomposer(client=object())._parse_plan(ORIGINAL, raw)  # type: ignore[arg-type]


# --- rejection --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("not json at all", "not JSON"),
        ("[1, 2, 3]", "JSON, but not an object"),
        ('{"queries": []}', "sub_queries key absent"),
        ('{"sub_queries": {}}', "sub_queries not a list"),
        ('{"sub_queries": []}', "sub_queries empty"),
        ('{"sub_queries": ["price"]}', "entry not an object"),
        ('{"sub_queries": [{"intent": "sentiment", "text": "x"}]}', "unknown intent"),
        ('{"sub_queries": [{"text": "x"}]}', "intent key absent"),
        ('{"sub_queries": [{"intent": "price"}]}', "text key absent"),
        ('{"sub_queries": [{"intent": "price", "text": "   "}]}', "text whitespace only"),
        ('{"sub_queries": [{"intent": "price", "text": 42}]}', "text not a string"),
    ],
)
def test_malformed_output_raises(raw: str, why: str) -> None:
    """One exception type for every violation, because orchestration
    catches exactly DecomposerError. Anything else escapes the fallback
    and takes the whole turn down."""
    with pytest.raises(DecomposerError):
        _parse(raw)


def test_the_error_carries_the_raw_payload() -> None:
    """That message becomes decomposition_fallback_reason, which is the
    only record of why a turn fell back. Truncating it to something tidy
    would leave the fallback undiagnosable after the fact."""
    with pytest.raises(DecomposerError) as excinfo:
        _parse('{"sub_queries": []}')

    assert "sub_queries" in str(excinfo.value)


def test_an_empty_plan_is_rejected_rather_than_returned() -> None:
    """A zero-sub-query plan would make is_single_intent false and send
    the turn to synthesis with nothing to synthesise. Rejecting it means
    the fallback runs instead."""
    with pytest.raises(DecomposerError):
        _parse('{"sub_queries": []}')


# --- fence stripping, the silent one ----------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        f"```json\n{VALID_BODY}\n```",
        f"```\n{VALID_BODY}\n```",
        f"  ```json\n{VALID_BODY}\n```  ",
    ],
)
def test_markdown_fences_are_stripped(raw: str) -> None:
    """Haiku obeys "no fences" most of the time, not all of it. If this
    belt broke, fenced responses would fail, those turns would fall back
    silently, and the evals would stay green while decomposition
    quietly stopped happening on a fraction of queries."""
    plan = _parse(raw)

    assert plan.sub_queries[0].intent is Intent.PRICE


def test_raw_response_is_kept_verbatim() -> None:
    """The debugging artefact keeps the fences: it records what the model
    actually emitted, not what parsed."""
    raw = f"```json\n{VALID_BODY}\n```"

    assert _parse(raw).raw_response == raw


# --- accepted shapes --------------------------------------------------


def test_symbols_default_to_empty_when_absent() -> None:
    """Empty symbols is the AUTO routing path, not an error. The
    decomposer is allowed to find no assets."""
    plan = _parse('{"sub_queries": [{"intent": "news", "text": "market mood"}]}')

    assert plan.sub_queries[0].symbols == []


def test_non_list_symbols_degrade_to_empty_rather_than_raising() -> None:
    """Deliberately lenient where the field is optional, strict where it
    is not. A bad symbols field costs AUTO routing; a bad intent would
    route wrongly, so that one raises."""
    plan = _parse('{"sub_queries": [{"intent": "price", "text": "x", "symbols": "BTC"}]}')

    assert plan.sub_queries[0].symbols == []


def test_symbols_are_stringified_stripped_and_pruned() -> None:
    raw = '{"sub_queries": [{"intent": "price", "text": "x", "symbols": [" btc ", "", 42, "  "]}]}'

    assert _parse(raw).sub_queries[0].symbols == ["btc", "42"]


def test_text_is_stripped() -> None:
    plan = _parse('{"sub_queries": [{"intent": "price", "text": "  BTC price  "}]}')

    assert plan.sub_queries[0].text == "BTC price"


def test_multiple_sub_queries_are_preserved_in_order() -> None:
    raw = json.dumps(
        {
            "sub_queries": [
                {"intent": "price", "text": "BTC price", "symbols": ["BTC"]},
                {"intent": "news", "text": "Apple news", "symbols": ["AAPL"]},
            ]
        }
    )
    plan = _parse(raw)

    assert [sq.intent for sq in plan.sub_queries] == [Intent.PRICE, Intent.NEWS]
    assert plan.is_single_intent is False


def test_single_sub_query_takes_the_fast_path() -> None:
    """is_single_intent is len(sub_queries) == 1 and nothing else. Its
    docstring claims the text must also equal the original message; the
    code does not check that, and this pins the code. Flagged rather than
    resolved: the code looks right and the docstring overclaims."""
    plan = _parse(VALID_BODY)

    assert plan.original_query == ORIGINAL
    assert plan.is_single_intent is True


# --- the boundary -----------------------------------------------------


class _Block:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class _ScriptedClient:
    def __init__(self, text: str) -> None:
        self._text = text

    def create(self, **_: Any) -> Any:
        return _Block(content=[_Block(type="text", text=self._text)])


def test_classify_parses_a_fenced_response_end_to_end() -> None:
    """_extract_text into _parse_plan, joined. Either half could work
    alone while the join was broken."""
    client = _ScriptedClient(f"```json\n{VALID_BODY}\n```")

    plan = Decomposer(client=client).classify(ORIGINAL)  # type: ignore[arg-type]

    assert plan.sub_queries[0].intent is Intent.PRICE


class _RecordingConversation:
    """Duplicated from test_agent_conversation.py deliberately. A shared
    conftest fixture would couple two files that test different modules,
    and the fake is four lines."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def send(self, text: str, *, forced_tool: str | None = None) -> TurnTrace:
        self.calls.append((text, forced_tool))
        return TurnTrace(user_message=text)


class _RaisingDecomposer:
    def classify(self, user_message: str) -> QueryPlan:
        raise DecomposerError("classifier output is not valid JSON")


def test_a_decomposer_failure_falls_back_to_one_unforced_agent_call() -> None:
    """The silence, made visible.

    This is the path that keeps the golden set green while decomposition
    is dead: one unforced call on the original query, an answer the judge
    will grade normally, and the only trace of the failure in metadata
    nothing asserts on.
    """
    conversation = _RecordingConversation()
    orchestrated = OrchestratedConversation(
        client=object(),  # type: ignore[arg-type]
        conversation=conversation,  # type: ignore[arg-type]
        decomposer=_RaisingDecomposer(),  # type: ignore[arg-type]
        registry=AssetRegistry(),
    )

    trace = orchestrated.send(ORIGINAL)

    assert conversation.calls == [(ORIGINAL, None)]
    assert trace.decomposition_plan is None
    assert trace.decomposition_fallback_reason is not None
    assert "decomposer_error" in trace.decomposition_fallback_reason