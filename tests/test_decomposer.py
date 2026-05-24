"""Unit tests + calibration for the Stage-7 decomposer.

Real API calls. Run with:

    cd /Users/alex/Documents/Graft/ClaudeCode/AWAnalysis
    PYTHONPATH=$(pwd) python3 -m pytest tests/test_decomposer.py -v

Or directly:

    PYTHONPATH=$(pwd) python3 tests/test_decomposer.py

The CALIBRATION_SET is 30 hand-graded cases mirroring the Stage 6
judge-calibration protocol. Targets: ≥90% exact-plan agreement, ≥95%
intent-set agreement.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from aw_analysis.agent.decomposer import Decomposer, Intent
from aw_analysis.client.anthropic_client import AnthropicClient


@dataclass(frozen=True)
class CalibrationCase:
    query: str
    expected_intents: tuple[Intent, ...]  # ordered: profile, price, news


CALIBRATION_SET: list[CalibrationCase] = [
    # --- single-intent: price (8 cases) ---
    CalibrationCase("What's the price of BTC?", (Intent.PRICE,)),
    CalibrationCase("Current ETH price", (Intent.PRICE,)),
    CalibrationCase("How much is Solana trading at?", (Intent.PRICE,)),
    CalibrationCase("BTC market cap", (Intent.PRICE,)),
    CalibrationCase("ETH 24 hour change", (Intent.PRICE,)),
    CalibrationCase("Price of Arbitrum", (Intent.PRICE,)),
    CalibrationCase("What is BTC worth right now?", (Intent.PRICE,)),
    CalibrationCase("Solana trading volume", (Intent.PRICE,)),

    # --- single-intent: profile (8 cases) ---
    CalibrationCase("What is Bitcoin?", (Intent.PROFILE,)),
    CalibrationCase("Tell me about Ethereum", (Intent.PROFILE,)),
    CalibrationCase("What does Solana do?", (Intent.PROFILE,)),
    CalibrationCase("Explain Arbitrum", (Intent.PROFILE,)),
    CalibrationCase("What is Ethereum and what does it do?", (Intent.PROFILE,)),
    CalibrationCase("Background on Avalanche", (Intent.PROFILE,)),
    CalibrationCase("What makes Polygon different?", (Intent.PROFILE,)),
    CalibrationCase("Tell me what BNB is", (Intent.PROFILE,)),

    # --- single-intent: news (6 cases) ---
    CalibrationCase("Latest news on Ethereum", (Intent.NEWS,)),
    CalibrationCase("What's happening with BTC today?", (Intent.NEWS,)),
    CalibrationCase("Recent Solana developments", (Intent.NEWS,)),
    CalibrationCase("Any current news on Arbitrum?", (Intent.NEWS,)),
    CalibrationCase("What is the latest news on Solana?", (Intent.NEWS,)),
    CalibrationCase("Recent events for Ethereum", (Intent.NEWS,)),

    # --- multi-intent: profile + news (4 cases — the load-bearing class) ---
    CalibrationCase(
        "What is Solana and what is the latest news on it?",
        (Intent.PROFILE, Intent.NEWS),
    ),
    CalibrationCase(
        "Tell me about Arbitrum and any recent news",
        (Intent.PROFILE, Intent.NEWS),
    ),
    CalibrationCase(
        "What is BTC and what's happening with it today?",
        (Intent.PROFILE, Intent.NEWS),
    ),
    CalibrationCase(
        "Explain Ethereum and the latest developments",
        (Intent.PROFILE, Intent.NEWS),
    ),

    # --- multi-intent: 3-way (2 cases) ---
    CalibrationCase(
        "Give me the full picture on Ethereum: price, what it does, "
        "and any recent news",
        (Intent.PROFILE, Intent.PRICE, Intent.NEWS),
    ),
    CalibrationCase(
        "BTC: current price, background, and what's been happening lately",
        (Intent.PROFILE, Intent.PRICE, Intent.NEWS),
    ),

    # --- multi-intent: profile + price (2 cases) ---
    CalibrationCase(
        "What is Solana and what's its current price?",
        (Intent.PROFILE, Intent.PRICE),
    ),
    CalibrationCase(
        "Price of Arbitrum and what it does",
        (Intent.PROFILE, Intent.PRICE),
    ),

    # --- comparison and history cases added after Stage 7 baseline run ---
    CalibrationCase(
        "Compare BTC and ETH prices", 
        (Intent.PRICE,)
        ),
    CalibrationCase(
        "BTC vs ETH market cap",
        (Intent.PRICE,)
        ),
    CalibrationCase(
        "What's BTC trading at and what was the most significant event in its history?",
        (Intent.PRICE, Intent.PROFILE),
    ),
]


def run_calibration() -> int:
    """Run the calibration set and report agreement rates.

    Returns 0 if both targets (exact-plan ≥90%, intent-set ≥95%) are
    hit, 1 otherwise — usable as a CI gate.
    """
    client = AnthropicClient()
    decomposer = Decomposer(client)

    exact_hits = 0
    intent_set_hits = 0
    failures: list[tuple[CalibrationCase, str]] = []

    for case in CALIBRATION_SET:
        try:
            plan = decomposer.classify(case.query)
        except Exception as exc:  # noqa: BLE001
            failures.append((case, f"DECOMPOSER_ERROR: {exc}"))
            continue

        actual = tuple(sq.intent for sq in plan.sub_queries)
        if actual == case.expected_intents:
            exact_hits += 1
            intent_set_hits += 1
        elif set(actual) == set(case.expected_intents):
            intent_set_hits += 1
            failures.append(
                (case, f"order/phrasing differs: expected {case.expected_intents}, got {actual}")
            )
        else:
            failures.append(
                (case, f"intent mismatch: expected {case.expected_intents}, got {actual}")
            )

    n = len(CALIBRATION_SET)
    exact_rate = exact_hits / n
    intent_set_rate = intent_set_hits / n

    print(f"\nDecomposer calibration ({n} cases):")
    print(f"  Exact-plan agreement:    {exact_hits}/{n} = {exact_rate:.1%}")
    print(f"  Intent-set agreement:    {intent_set_hits}/{n} = {intent_set_rate:.1%}")

    if failures:
        print(f"\nFailures / partial matches ({len(failures)}):")
        for case, reason in failures:
            print(f"  - {case.query!r}: {reason}")

    exact_target = 0.90
    intent_set_target = 0.95
    passed = exact_rate >= exact_target and intent_set_rate >= intent_set_target
    print(
        f"\nTargets: exact ≥{exact_target:.0%}, intent-set ≥{intent_set_target:.0%}"
    )
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(run_calibration())