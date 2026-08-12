"""Probe the decomposition and routing path for named golden cases.

Answers one question: does any sub-query of a given eval case route to
FORCE? The two Stage 9 faithfulness regressions (profile_shopify_fallback,
news_nvidia_event) are PROFILE and NEWS intent respectively, and FORCE_MAP
holds only (CRYPTO, PRICE) and (EQUITIES, PRICE). So both should route
AUTO with forced_tool=None, which makes the forced-tool fix in 1453796 a
provable no-op on them.

That argument depends on the decomposer producing a single non-price
sub-query per case. This script checks that empirically.

Costs a Haiku classifier call per case plus any long-tail symbol
disambiguation. No agent loop, no tools, no synthesis, no judge.

Usage:
    PYTHONPATH=$(pwd) .venv/bin/python bin/route_probe.py [case_id ...]
"""

from __future__ import annotations

import sys

from aw_analysis.agent.decomposer import Decomposer
from aw_analysis.agent.orchestration import RouteAction, decide_route
from aw_analysis.asset_registry import AssetRegistry, SymbolDisambiguator
from aw_analysis.client.anthropic_client import AnthropicClient
from aw_analysis.config import get_settings
from evals.golden import cases_for

DEFAULT_CASES = ["profile_shopify_fallback", "news_nvidia_event"]


def _find_case(case_id: str):
    """Look the case up in the golden set rather than hardcoding its
    query text, so the probe cannot drift from what the eval runs."""
    for asset_class in ("crypto", "equities"):
        for case in cases_for(asset_class):
            if case.id == case_id:
                return case
    raise SystemExit(f"case not found in golden set: {case_id}")


def main(argv: list[str]) -> int:
    get_settings()  # fail fast

    case_ids = argv[1:] or DEFAULT_CASES

    client = AnthropicClient()
    decomposer = Decomposer(client)
    registry = AssetRegistry(SymbolDisambiguator(client))

    any_force = False

    for case_id in case_ids:
        case = _find_case(case_id)
        print("=" * 72)
        print(f"case:  {case.id}")
        print(f"class: {case.query_class.value}")
        print(f"query: {case.query!r}")
        print("-" * 72)

        plan = decomposer.classify(case.query)
        print(f"sub-queries: {len(plan.sub_queries)}  "
              f"single_intent={plan.is_single_intent}")
        print()

        for i, sub in enumerate(plan.sub_queries):
            classes = [registry.resolve(s) for s in sub.symbols]
            decision = decide_route(classes, sub.intent)
            forced = decision.tool if decision.action is RouteAction.FORCE else None
            if forced is not None:
                any_force = True

            print(f"  [{i}] intent={sub.intent.value}")
            print(f"      text={sub.text!r}")
            print(f"      symbols={sub.symbols}")
            print(f"      classes={[c.value for c in classes]}")
            print(f"      action={decision.action.value}")
            print(f"      forced_tool={forced}")
            print()

        print("raw classifier JSON:")
        print(plan.raw_response)
        print()

    print("=" * 72)
    if any_force:
        print("VERDICT: at least one sub-query FORCES.")
        print("The forced-tool fix could have changed behaviour here.")
        print("A paired counterfactual run is warranted on that case.")
        return 1

    print("VERDICT: no sub-query forces. forced_tool is None throughout.")
    print("The 1453796 fix (send -> _run_loop forwarding) is a provable")
    print("no-op on these cases. Attribution closed by construction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))