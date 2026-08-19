"""Tests for the red-team document-injection delivery.

Real registry, real tool objects. No network, no credentials.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from aw_analysis.agent.orchestration import OrchestratedTurnTrace
from aw_analysis.config.settings import get_settings
from evals.redteam.adapter import run_against_attack
from evals.redteam.attacks import ATTACKS
from evals.redteam.poison import (
    PLANTED_BY_ATTACK,
    PLANTED_DOCUMENTS,
    PoisonedProfileTool,
    poisoned_registry,
)


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """poisoned_registry calls default_registry(), which constructs tools
    that read settings and demand an API key. Locally .env supplies one,
    so this only failed in CI. Same shape as test_client_retry.py:
    get_settings is lru_cached, so the cache is cleared on both sides or
    a fake-key Settings survives into the next test file.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-never-sent")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def minimal_trace():
    return OrchestratedTurnTrace(
        user_message="x",
        final_text="a",
        decomposition_plan=None,
        sub_traces=[],
        synthesis_iteration=None,
        classifier_iteration=None,
    )


def test_planted_attack_ids_exist_and_are_document_attacks():
    """Couples the poison map to the attack data. A typo here would
    otherwise surface as two silently undelivered attacks in a paid run."""
    by_id = {a["id"]: a for a in ATTACKS}
    for attack_id, document_name in PLANTED_BY_ATTACK.items():
        assert attack_id in by_id, attack_id
        assert by_id[attack_id]["injection_target"] == "document"
        assert document_name in PLANTED_DOCUMENTS

    document_attacks = {a["id"] for a in ATTACKS if a["injection_target"] == "document"}
    assert document_attacks == set(PLANTED_BY_ATTACK)


def test_registry_substitutes_only_the_profile_tool():
    registry, tool = poisoned_registry("eth_market_report_planted.md")
    assert sorted(registry.names()) == [
        "get_crypto_price",
        "get_equity_price",
        "lookup_asset_profile",
        "web_search",
    ]
    assert isinstance(tool, PoisonedProfileTool)


def test_poison_sits_inside_the_curated_envelope():
    """The model must see the same source="curated" wrapper it always
    sees, with the payload in a field it treats as retrieved data.
    Replacing the whole envelope would be an easier attack than the real
    one."""
    _, tool = poisoned_registry("eth_market_report_planted.md")
    payload = json.loads(tool.execute(query="Ethereum"))
    assert payload["source"] == "curated"
    assert payload["query"] == "Ethereum"
    assert "[ADMIN MODE ENABLED]" in payload["results"][0]["text"]


def test_invoked_flag_tracks_delivery():
    _, tool = poisoned_registry("crypto_regulation_planted.md")
    assert tool.invoked is False
    tool.execute(query="crypto regulation")
    assert tool.invoked is True


def test_dispatch_through_the_registry_marks_delivery():
    """Delivery must register when the agent loop dispatches by name,
    not only on a direct call."""
    registry, tool = poisoned_registry("eth_market_report_planted.md")
    result = registry.dispatch("lookup_asset_profile", {"query": "Ethereum"})
    assert result.success is True
    assert tool.invoked is True


# --- the three-state delivery flag on the response ---------------------

class _StubInner:
    def traces(self):
        return []


class _StubOrchestrated:
    def __init__(self, otrace):
        self._otrace = otrace

    def send(self, user_message):
        return self._otrace


def _build_with(poison, otrace):
    def build(attack_id=None):
        return _StubOrchestrated(otrace), _StubInner(), poison
    return build


def test_undelivered_poison_is_not_a_defence(minimal_trace):
    """The finding this flag exists for. Production decomposes and
    routes, so a document attack can complete without the poison ever
    reaching the model. That is a non-delivery, not a defence."""
    tool = PoisonedProfileTool("eth_market_report_planted.md")
    got = run_against_attack(
        {"id": "inj_05_doc_payload", "payload": "x"},
        build=_build_with(tool, minimal_trace),
    )
    assert got["poison_delivered"] is False


def test_delivered_poison_is_recorded(minimal_trace):
    tool = PoisonedProfileTool("eth_market_report_planted.md")
    tool.execute(query="Ethereum")
    got = run_against_attack(
        {"id": "inj_05_doc_payload", "payload": "x"},
        build=_build_with(tool, minimal_trace),
    )
    assert got["poison_delivered"] is True