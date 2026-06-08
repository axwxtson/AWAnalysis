"""The AW Analysis equities golden dataset.

Stage 9 step 5. ~16 cases across the six query classes (reused from the
crypto suite — query-class is orthogonal to asset-class). Includes the
cross-asset comparison case (the thesis test as a permanent guard), an
equity honesty trap, and refusal_msft_stock migrated from the crypto
refusal suite to a deterministic equity price case.
"""
from __future__ import annotations

from evals.grader.types import (
    Assertion,
    AssertionKind,
    EvalCase,
    QueryClass,
    Severity,
)

_NUMERIC_LEAD = r"^[^\n]*\$?[\d,]+"

EQUITY_DATASET: list[EvalCase] = [
    # --- price -------------------------------------------------------
    EvalCase(
        id="price_msft",
        query="What's the price of MSFT?",
        query_class=QueryClass.PRICE,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="get_equity_price",
                description="Equity price query must call the equity price tool",
            ),
            Assertion(
                kind=AssertionKind.OUTPUT_PREFIX,
                target=_NUMERIC_LEAD,
                description="Answer leads with a numeric figure (prompt contract)",
            ),
        ],
        rationale=(
            "Migrated from refusal_msft_stock (Stage 1, crypto-only). "
            "Equities are now first-class, so MSFT must be priced via "
            "get_equity_price, not refused. A deterministic price "
            "assertion replaces the former judge-graded refusal."
        ),
        difficulty="easy",
    ),
    EvalCase(
        id="price_tsla",
        query="What is Tesla trading at?",
        query_class=QueryClass.PRICE,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="get_equity_price",
                description="Curated equity name must resolve and price via the equity tool",
            ),
            Assertion(
                kind=AssertionKind.OUTPUT_PREFIX,
                target=_NUMERIC_LEAD,
                description="Lead-with-the-number contract",
            ),
        ],
        rationale=(
            "Name (not ticker) for a curated large cap. Exercises "
            "deterministic name resolution -> EQUITIES -> forced "
            "get_equity_price."
        ),
        difficulty="easy",
    ),
    EvalCase(
        id="price_equity_long_tail",
        query="What's the price of Oracle stock?",
        query_class=QueryClass.PRICE,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="get_equity_price",
                description="Non-curated equity still routes to the equity price tool",
            ),
            Assertion(
                kind=AssertionKind.OUTPUT_PREFIX,
                target=_NUMERIC_LEAD,
                description="Lead-with-the-number contract",
            ),
        ],
        rationale=(
            "Long-tail equity (Oracle is not in the curated keyspace): "
            "Haiku disambiguation -> EQUITIES -> get_equity_price. The "
            "equity equivalent of price_long_tail."
        ),
        difficulty="medium",
    ),
    EvalCase(
        id="price_compare_apple_btc",
        query="Compare Apple and Bitcoin prices",
        query_class=QueryClass.PRICE,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="get_equity_price",
                description="Equity leg of the cross-asset comparison",
            ),
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="get_crypto_price",
                description="Crypto leg of the cross-asset comparison",
            ),
        ],
        rationale=(
            "THE thesis test, as a permanent regression guard: a single "
            "mixed-class price sub-query must fire BOTH class price tools "
            "in one turn, with no class-branch in the hot path."
        ),
        difficulty="hard",
    ),
    # --- profile_curated ---------------------------------------------
    EvalCase(
        id="profile_aapl_curated",
        query="What is Apple?",
        query_class=QueryClass.PROFILE_CURATED,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="lookup_asset_profile",
                description="Profile query routes to the profile tool",
            ),
            Assertion(
                kind=AssertionKind.OUTPUT_CONTAINS,
                target="Apple",
                severity=Severity.P1,
                description="Answer should name the asset",
            ),
        ],
        rationale=(
            "Curated equity profile hit. The shared curated tier serves "
            "equities after re-ingest, no retriever change."
        ),
        difficulty="easy",
    ),
    EvalCase(
        id="profile_nvda_curated",
        query="Tell me about NVIDIA and what it does",
        query_class=QueryClass.PROFILE_CURATED,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="lookup_asset_profile",
                description="Profile query routes to the profile tool",
            ),
            Assertion(
                kind=AssertionKind.OUTPUT_CONTAINS,
                target="GPU",
                severity=Severity.P1,
                description="NVIDIA profile should mention its core product",
            ),
        ],
        rationale="Second curated equity profile; ticker-by-name resolution.",
        difficulty="easy",
    ),
    EvalCase(
        id="profile_jpm_curated",
        query="What is JPMorgan?",
        query_class=QueryClass.PROFILE_CURATED,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="lookup_asset_profile",
                description="Profile query routes to the profile tool",
            ),
        ],
        rationale="Curated financials profile; non-tech sector coverage.",
        difficulty="easy",
    ),
    # --- profile_fallback --------------------------------------------
    EvalCase(
        id="profile_oracle_fallback",
        query="Tell me about Oracle the company",
        query_class=QueryClass.PROFILE_FALLBACK,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="lookup_asset_profile",
                description="Long-tail equity profile still routes to the profile tool",
            ),
            Assertion(
                kind=AssertionKind.OUTPUT_CONTAINS,
                target="Oracle",
                severity=Severity.P1,
                description="Answer should name the asset",
            ),
        ],
        rationale=(
            "Curated miss -> EQUITIES -> Twelve Data reference fallback "
            "(source 'twelvedata'). Equity equivalent of profile_*_fallback."
        ),
        difficulty="medium",
    ),
    EvalCase(
        id="profile_shopify_fallback",
        query="What is Shopify?",
        query_class=QueryClass.PROFILE_FALLBACK,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="lookup_asset_profile",
                description="Long-tail equity profile routes to the profile tool",
            ),
        ],
        rationale="Second long-tail equity fallback; confirms the reference tier generalises.",
        difficulty="medium",
    ),
    # --- news --------------------------------------------------------
    EvalCase(
        id="news_tesla",
        query="What's the latest news on Tesla?",
        query_class=QueryClass.NEWS,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="web_search",
                description="News query must hit web_search (recency enforcement)",
            ),
        ],
        rationale="Equity news routes to the class-agnostic news tool; recency rule holds for equities.",
        difficulty="easy",
    ),
    EvalCase(
        id="news_nvidia_event",
        query="Any recent news on NVIDIA's latest earnings?",
        query_class=QueryClass.NEWS,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="web_search",
                description="Recency cue forces web_search",
            ),
        ],
        rationale="Equity news with an event framing; web_search must fire rather than answering from memory.",
        difficulty="medium",
    ),
    # --- refusal -----------------------------------------------------
    EvalCase(
        id="refusal_etf_spy",
        query="What's the price of SPY?",
        query_class=QueryClass.REFUSAL,
        assertions=[
            Assertion(
                kind=AssertionKind.REFUSED,
                target="true",
                description="ETF is gated UNSUPPORTED -> deterministic refusal",
            ),
            Assertion(
                kind=AssertionKind.OUTPUT_CONTAINS,
                target="ETF",
                severity=Severity.P1,
                description="Refusal should name the unsupported class",
            ),
        ],
        rationale=(
            "SPY is in the UNSUPPORTED gate -> decide_route REFUSE -> "
            "deterministic refusal trace, no agent call. No judge flake."
        ),
        difficulty="easy",
    ),
    EvalCase(
        id="refusal_index_spx",
        query="What is the SPX index trading at right now?",
        query_class=QueryClass.REFUSAL,
        assertions=[
            Assertion(
                kind=AssertionKind.REFUSED,
                target="true",
                description="Index ticker is gated UNSUPPORTED -> deterministic refusal",
            ),
        ],
        rationale="SPX is gated UNSUPPORTED; indices refuse deterministically, same path as ETFs.",
        difficulty="easy",
    ),
    EvalCase(
        id="refusal_equity_speculation",
        query="Should I buy Apple stock?",
        query_class=QueryClass.REFUSAL,
        assertions=[
            Assertion(
                kind=AssertionKind.REFUSED,
                target="true",
                description="Speculation/advice refusal applies to equities too",
            ),
        ],
        rationale=(
            "Apple is in scope, but 'should I buy' is advice. Routes "
            "profile (AUTO, not forced) so the model refuses on iteration "
            "0 — confirms not-forcing profile preserves equity refusals."
        ),
        difficulty="medium",
    ),
    # --- combined_tools ----------------------------------------------
    EvalCase(
        id="combined_aapl_price_history",
        query="What's AAPL trading at and what was the most significant event in its history?",
        query_class=QueryClass.COMBINED_TOOLS,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="get_equity_price",
                description="Current price half (equity)",
            ),
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="lookup_asset_profile",
                description="Historical context half (curated) — must not answer from memory",
            ),
        ],
        rationale=(
            "Equity honesty trap, equivalent of combined_btc_price_history: "
            "the 'most significant event' half tempts a from-memory answer; "
            "the profile tool must fire."
        ),
        difficulty="hard",
    ),
    EvalCase(
        id="combined_msft_full",
        query="Give me the full picture on Microsoft: what it does, its price, and any recent news",
        query_class=QueryClass.COMBINED_TOOLS,
        assertions=[
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="lookup_asset_profile",
                description="Profile leg",
            ),
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="get_equity_price",
                description="Price leg (equity)",
            ),
            Assertion(
                kind=AssertionKind.TOOL_CALLED,
                target="web_search",
                description="News leg",
            ),
        ],
        rationale=(
            "Three-part equity query: profile + equity price + news in one "
            "turn. Equity equivalent of combined_eth_full."
        ),
        difficulty="hard",
    ),
]