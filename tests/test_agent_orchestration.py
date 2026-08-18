"""Unit tests for decide_route, the Stage 9 (class, intent) -> tool router.

Offline and pure by construction. There is no fixture in this file, no
credentials and no fake client, because decide_route takes enum members
and returns a frozen dataclass. If this file ever needs a fixture, the
function has stopped being the pure decision the design claims it is,
and that is worth noticing.

Decisions are compared whole (RouteDecision(...) == ...) rather than by
.action alone, so an AUTO that carries a stray tool fails here rather
than downstream where a forced tool_choice would reach the API.
"""
from __future__ import annotations

import pytest

from aw_analysis.agent.decomposer import Intent
from aw_analysis.agent.orchestration import (
    FORCE_MAP,
    RouteAction,
    RouteDecision,
    decide_route,
)
from aw_analysis.asset_registry import AssetClass

CRYPTO = AssetClass.CRYPTO
EQUITIES = AssetClass.EQUITIES
UNSUPPORTED = AssetClass.UNSUPPORTED

AUTO = RouteDecision(RouteAction.AUTO)


# --- the assumption the rest of the file rests on ---------------------


def test_force_map_covers_exactly_the_price_intent() -> None:
    """Pin the map's shape, so a new entry fails here first.

    Every AUTO assertion below for a single real class is only true
    while FORCE_MAP has no entry for that (class, intent) pair. Adding
    (CRYPTO, PROFILE) would break those tests with a message about AUTO
    that does not explain itself. This one names the cause.
    """
    assert set(FORCE_MAP) == {
        (CRYPTO, Intent.PRICE),
        (EQUITIES, Intent.PRICE),
    }


# --- the refuse gate --------------------------------------------------


@pytest.mark.parametrize("intent", list(Intent))
@pytest.mark.parametrize("classes", [[UNSUPPORTED], [UNSUPPORTED, UNSUPPORTED]])
def test_all_unsupported_refuses(
    classes: list[AssetClass], intent: Intent
) -> None:
    """The deterministic gate, and it is order-dependent.

    An all-UNSUPPORTED list satisfies both guards: `not real` is true
    and `has_unsupported` is true. REFUSE only wins because its check
    is written first. Swap the two ifs and every ETF query silently
    becomes AUTO, with no error anywhere and probably no eval failure,
    because the prompt makes the model refuse ETFs unaided. That is the
    Stage 9 shape: dead mechanism, unchanged outcome.
    """
    assert decide_route(classes, intent) == RouteDecision(RouteAction.REFUSE)


@pytest.mark.parametrize(
    "classes",
    [
        [CRYPTO, UNSUPPORTED],
        [UNSUPPORTED, EQUITIES],
        [CRYPTO, EQUITIES, UNSUPPORTED],
    ],
)
def test_unsupported_mixed_with_real_is_auto(classes: list[AssetClass]) -> None:
    """Partial support is answered, not refused.

    PRICE is used deliberately: it is the only intent that could force,
    so this proves the mixed case escapes before the FORCE_MAP lookup
    rather than merely missing it.
    """
    assert decide_route(classes, Intent.PRICE) == AUTO


# --- nothing to route on ----------------------------------------------


@pytest.mark.parametrize("intent", list(Intent))
def test_no_symbols_is_auto(intent: Intent) -> None:
    """An empty list is not a refusal. It means the decomposer found no
    symbols, so there is nothing to gate on and the agent decides."""
    assert decide_route([], intent) == AUTO


# --- the force branches -----------------------------------------------


def test_single_crypto_price_forces_the_crypto_tool() -> None:
    assert decide_route([CRYPTO], Intent.PRICE) == RouteDecision(
        RouteAction.FORCE, tool="get_crypto_price"
    )


def test_single_equity_price_forces_the_equity_tool() -> None:
    assert decide_route([EQUITIES], Intent.PRICE) == RouteDecision(
        RouteAction.FORCE, tool="get_equity_price"
    )


def test_repeated_same_class_still_forces() -> None:
    """`set(real)` not `len(real) == 1`, and the difference is load-bearing.

    "Compare Bitcoin and Ethereum" resolves to two symbols of one class.
    A length check would send it to AUTO, which is a plausible-looking
    simplification that would quietly disable forcing on every
    multi-symbol single-class price query.
    """
    assert decide_route([CRYPTO, CRYPTO], Intent.PRICE) == RouteDecision(
        RouteAction.FORCE, tool="get_crypto_price"
    )


# --- single real class, no force-able entry ---------------------------


@pytest.mark.parametrize("intent", [Intent.PROFILE, Intent.NEWS])
@pytest.mark.parametrize("asset_class", [CRYPTO, EQUITIES])
def test_single_class_non_price_is_auto(
    asset_class: AssetClass, intent: Intent
) -> None:
    """Profile and news are single-tool intents, so forcing buys nothing.

    For profile it costs something: speculation queries classify as
    profile, and a forced tool on iteration 0 stops the model refusing
    there, which is where was_refusal is detected.
    """
    assert decide_route([asset_class], intent) == AUTO


# --- mixed real classes -----------------------------------------------


@pytest.mark.parametrize("intent", list(Intent))
def test_mixed_real_classes_is_auto(intent: Intent) -> None:
    """"Compare Apple and Bitcoin" needs both tools in one turn, so
    neither can be forced. This is the Stage 9 permanent regression
    guard's routing half."""
    assert decide_route([CRYPTO, EQUITIES], intent) == AUTO