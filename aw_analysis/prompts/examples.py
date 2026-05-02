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


FEW_SHOT_EXAMPLES = [
    EXAMPLE_PRICE_FORMAT,
    EXAMPLE_COMPARISON,
    EXAMPLE_REFUSAL,
]


def render_examples() -> str:
    """Format examples for inlining into the system prompt."""
    if not FEW_SHOT_EXAMPLES:
        return ""
    sep = "\n\n---\n\n"
    body = sep.join(FEW_SHOT_EXAMPLES)
    return f"## Examples\n\n{body}"