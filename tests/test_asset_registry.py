"""Unit tests for symbol -> AssetClass resolution.

resolve_deterministic returns three enum members and None, and the None
is load-bearing: it means "unknown, ask the model", which is
categorically different from UNSUPPORTED, meaning "refuse, no model
call". Collapsing them fails in opposite directions. Return UNSUPPORTED
for an unknown and every non-curated equity is refused rather than
escalated, which is the profile_shopify_fallback path. Return None for
an ETF and SPY buys a Haiku call instead of hitting the deterministic
gate.

Offline and pure: the disambiguator is faked, so nothing here
constructs a client or reads settings.
"""
from __future__ import annotations

import pytest

from aw_analysis.asset_registry import (
    CRYPTO_NAMES,
    CRYPTO_SYMBOLS,
    EQUITY_NAMES,
    EQUITY_SYMBOLS,
    UNSUPPORTED_SYMBOLS,
    AssetClass,
    AssetRegistry,
)
from aw_analysis.data_sources.coingecko import TICKER_TO_ID

resolve_deterministic = AssetRegistry.resolve_deterministic


# --- normalisation ----------------------------------------------------


@pytest.mark.parametrize("symbol", ["AAPL", "aapl", "AaPl", "  aapl  ", "\taapl\n"])
def test_lookup_is_strip_then_upper(symbol: str) -> None:
    """One line of normalisation with nothing referencing it.

    The decomposer emits symbols verbatim from user text, so lower case
    and stray whitespace both arrive in practice. If this is dropped the
    router stops recognising them, with no exception and no eval failure
    that points at the cause.
    """
    assert resolve_deterministic(symbol) is AssetClass.EQUITIES


# --- the three resolved classes ---------------------------------------


@pytest.mark.parametrize("ticker", sorted(TICKER_TO_ID))
def test_every_priceable_crypto_ticker_resolves_to_crypto(ticker: str) -> None:
    """CRYPTO_SYMBOLS is derived from the price layer's ticker map so the
    two cannot drift. Asserting the sets are equal would be tautological,
    since that is the definition. Asserting the behaviour is not: this
    fails if someone replaces the derivation with a hard-coded literal,
    which is how drift actually starts.
    """
    assert resolve_deterministic(ticker) is AssetClass.CRYPTO


@pytest.mark.parametrize("name", ["Bitcoin", "ethereum", "POLYGON"])
def test_curated_crypto_names_resolve_to_crypto(name: str) -> None:
    assert resolve_deterministic(name) is AssetClass.CRYPTO


@pytest.mark.parametrize("symbol", ["AAPL", "V", "Apple", "Johnson & Johnson"])
def test_curated_equities_resolve_to_equities(symbol: str) -> None:
    """V is a single-letter ticker and the J&J entry carries a space and
    an ampersand. Both are shapes a naive normalisation would mangle."""
    assert resolve_deterministic(symbol) is AssetClass.EQUITIES


@pytest.mark.parametrize("symbol", ["SPY", "QQQ", "spx"])
def test_policy_gate_resolves_to_unsupported(symbol: str) -> None:
    """UNSUPPORTED is a decision, not an absence. It is what makes
    decide_route refuse without a model call."""
    assert resolve_deterministic(symbol) is AssetClass.UNSUPPORTED


@pytest.mark.parametrize("symbol", ["ORCL", "SHOP", "ZX9QWP"])
def test_unknown_symbol_is_none_and_not_unsupported(symbol: str) -> None:
    """ORCL and SHOP are real equities absent from the curated list, so
    they must escalate rather than refuse. The second assertion is not
    redundant: returning UNSUPPORTED here is the plausible wrong answer,
    and `is None` alone would not say which mistake was made."""
    assert resolve_deterministic(symbol) is None


# --- the ordering canary ----------------------------------------------


def test_keyspaces_are_pairwise_disjoint() -> None:
    """Lookups are ordered: crypto, then equities, then unsupported.

    A symbol in two keyspaces is therefore decided by precedence rather
    than by anyone's decision. They are disjoint today. If a future
    crypto ticker collides with an equity, this fails and names the
    cause, rather than a class test failing with a message about the
    wrong asset class.
    """
    crypto = CRYPTO_SYMBOLS | CRYPTO_NAMES
    equities = EQUITY_SYMBOLS | EQUITY_NAMES

    assert not crypto & equities
    assert not crypto & UNSUPPORTED_SYMBOLS
    assert not equities & UNSUPPORTED_SYMBOLS


# --- resolve: the boundary --------------------------------------------


class _RecordingDisambiguator:
    """Records what it was asked, and answers without a model."""

    def __init__(self, answer: AssetClass = AssetClass.EQUITIES) -> None:
        self.answer = answer
        self.seen: list[str] = []

    def classify(self, symbol: str) -> AssetClass:
        self.seen.append(symbol)
        return self.answer


def test_resolve_collapses_none_to_unsupported_without_a_disambiguator() -> None:
    """None must never escape resolve(). With no model available the safe
    default is refusal, because guessing a tradeable class for an unknown
    symbol routes it into a price tool."""
    assert AssetRegistry().resolve("ZX9QWP") is AssetClass.UNSUPPORTED


def test_resolve_delegates_unknowns_to_the_disambiguator() -> None:
    """The connection test. A disambiguator that is constructed, held and
    never called would leave every unknown symbol refusing, which looks
    like conservative behaviour rather than a severed call."""
    disambiguator = _RecordingDisambiguator(AssetClass.EQUITIES)

    resolved = AssetRegistry(disambiguator).resolve("SHOP")  # type: ignore[arg-type]

    assert disambiguator.seen == ["SHOP"]
    assert resolved is AssetClass.EQUITIES


def test_resolve_never_calls_the_disambiguator_for_a_curated_symbol() -> None:
    """The deterministic-first cost claim. Without this, a refactor that
    always escalated would pass every other test in this file while
    quietly adding a Haiku call to every symbol in every query."""
    disambiguator = _RecordingDisambiguator()

    resolved = AssetRegistry(disambiguator).resolve("btc")  # type: ignore[arg-type]

    assert disambiguator.seen == []
    assert resolved is AssetClass.CRYPTO