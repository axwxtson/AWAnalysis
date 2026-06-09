"""Few-shot example registry.

Module 2 finding: example coverage matters more than count. Adding examples
that don't extend the model's behaviour to new patterns can hurt — the
3-shot vs 0-shot regression in Exercise 2.3 is the canonical case.

Rule for adding an example here: it must demonstrate a pattern the model
won't otherwise handle. If the model already does the right thing without
the example, the example is noise.

Each example is a (user_message, assistant_response) tuple, formatted as
a plain dialogue. They get inlined into the system prompt rather than
sent as actual messages, because:
- Sending as messages wastes tokens on every turn
- The model treats system-prompt examples as instruction, which is what
  we want for output-format demonstration
"""

from __future__ import annotations

# Example 1: demonstrates the output format for a single-asset price query.
# Without this, the model produces wordy responses with the price buried
# in the third paragraph. With this, it leads with the number.
EXAMPLE_PRICE_FORMAT = """\
User: What's the price of BTC?
Assistant: BTC is at $67,234 (+1.84% in 24h).

Market cap: $1.33T. Volume (24h): $28B."""


# Example 2: demonstrates parallel tool use for comparisons. Without this,
# the model tends to call tools sequentially even when the queries are
# independent, which doubles latency.
EXAMPLE_COMPARISON = """\
User: Compare BTC and ETH right now.
Assistant: I'll fetch both prices.

[Calls get_crypto_price for BTC and get_crypto_price for ETH in parallel]

BTC: $67,234 (+1.84% in 24h, $1.33T market cap)
ETH: $3,421 (+2.12% in 24h, $411B market cap)

ETH is outperforming BTC over the last 24h by ~0.3 percentage points."""


# Example 3: demonstrates principled refusal for out-of-scope assets.
# Without this, the model sometimes attempts to call get_crypto_price
# with non-crypto tickers (e.g. AAPL), which errors clumsily.
EXAMPLE_REFUSAL = """\
User: What's Microsoft stock at?
Assistant: I don't cover equities yet — only cryptocurrencies (BTC, ETH, \
SOL, ADA, AVAX, DOGE, DOT, LINK, MATIC, XRP). Equity coverage is on \
the roadmap. Anything I can help with on the crypto side?"""


# Example 3 (v2.5.0): equities are first-class. This REPLACES the old
# crypto-only refusal example, which actively taught the model to refuse
# in-scope equity queries. Demonstrates: an equity name the model might
# not assume is supported still routes to the equity price tool, and the
# refusal is reserved for genuinely out-of-scope instruments (ETFs).
EXAMPLE_EQUITY_AND_SCOPE = """\
User: What's the price of MSFT?
Assistant: MSFT is at $412.50 (-1.00% today).
Volume: 22.1M shares.

User: And the S&P 500 ETF, SPY?
Assistant: I don't cover ETFs, indices, forex, or commodities — only \
individual company stocks (equities) and cryptocurrencies. Happy to help \
with a specific stock or crypto asset instead."""


FEW_SHOT_EXAMPLES = [
    EXAMPLE_PRICE_FORMAT,
    EXAMPLE_COMPARISON,
    EXAMPLE_REFUSAL,
]

# v2.5.0 swaps the crypto-only refusal example for the cross-asset one.
# Kept as a separate list so older prompt builds remain byte-for-byte
# unchanged (and their locked eval baselines stay valid).
FEW_SHOT_EXAMPLES_V2_5_0 = [
    EXAMPLE_PRICE_FORMAT,
    EXAMPLE_COMPARISON,
    EXAMPLE_EQUITY_AND_SCOPE,
]


def _render(examples: list[str]) -> str:
    if not examples:
        return ""
    sep = "\n\n---\n\n"
    return f"## Examples\n\n{sep.join(examples)}"


def render_examples() -> str:
    """Format examples for inlining into the system prompt (legacy builds)."""
    return _render(FEW_SHOT_EXAMPLES)


def render_examples_v2_5_0() -> str:
    """Cross-asset few-shot set: equities answered, ETFs/indices refused."""
    return _render(FEW_SHOT_EXAMPLES_V2_5_0)