"""Symbol → asset-class registry.

Stage 9. Resolves a market symbol to its AssetClass so the orchestration
layer can route (asset_class, intent) → tool with no class-branch in the
hot path. Resolution is deterministic-first: known symbols resolve from
curated keyspaces with no model call; only a symbol absent from every
keyspace incurs a Haiku disambiguation call.

This module is the single source of truth for which symbols are known
and which classes are real. The crypto keyspace is derived from
coingecko.TICKER_TO_ID so it cannot drift from the price layer; the
equity keyspace is defined here and mirrored by the curated equity
profiles added in 2b.
"""
from __future__ import annotations

import json
from enum import Enum

from aw_analysis.client.anthropic_client import AnthropicClient
from aw_analysis.config import TaskType, get_model_config
from aw_analysis.data_sources.coingecko import TICKER_TO_ID


class AssetClass(str, Enum):
    """The asset classes the agent can route.

    UNSUPPORTED is a policy gate (ETFs, indices, anything out of scope),
    distinct from a symbol we simply have not heard of — the latter is
    an internal 'unknown' state (None from resolve_deterministic) that
    never escapes resolve().
    """

    CRYPTO = "crypto"
    EQUITIES = "equities"
    UNSUPPORTED = "unsupported"


# The real, tradeable classes — every class with a price/profile tool
# behind it. UNSUPPORTED is deliberately excluded: it has no tool, and
# the absence of an (UNSUPPORTED, *) entry in the routing map IS the
# refuse branch (wired in step 3). Anything meaning "iterate the real
# classes" uses this; anything meaning "what did resolve give me" uses
# the full enum.
REAL_CLASSES: tuple[AssetClass, ...] = (AssetClass.CRYPTO, AssetClass.EQUITIES)


# --- Curated keyspaces -------------------------------------------------

# Crypto: derived from the price layer's ticker map so the two cannot
# drift. Adding a crypto to TICKER_TO_ID makes it known here for free.
CRYPTO_SYMBOLS: frozenset[str] = frozenset(TICKER_TO_ID)

# Equities: the Stage-9 curated large caps. This set is the source of
# truth; the curated equity profiles added in 2b mirror it.
EQUITY_SYMBOLS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
    "META", "TSLA", "JPM", "V", "JNJ",
})

# Curated names → deterministic class, so common cross-asset queries
# ("compare Apple and Bitcoin") resolve without a disambiguation call.
# Aliases not listed here fall through to the Haiku disambiguator, which
# already handles them — this is an optimisation, not a correctness
# requirement.
CRYPTO_NAMES: frozenset[str] = frozenset({
    "BITCOIN", "ETHEREUM", "SOLANA", "RIPPLE", "CARDANO",
    "DOGECOIN", "AVALANCHE", "CHAINLINK", "POLKADOT", "POLYGON",
})
EQUITY_NAMES: frozenset[str] = frozenset({
    "APPLE", "MICROSOFT", "NVIDIA", "ALPHABET", "GOOGLE", "AMAZON",
    "META", "FACEBOOK", "TESLA", "JPMORGAN", "VISA",
    "JOHNSON & JOHNSON",
})

# Policy gate → UNSUPPORTED. ETFs and indices: out of scope by decision,
# gated here so they refuse cleanly instead of leaking a malformed symbol
# into get_equity_price. When indices/ETFs come into scope in a future
# stage, a symbol moves from here to a real keyspace — that reclassify is
# the only edit required.
UNSUPPORTED_SYMBOLS: frozenset[str] = frozenset({
    "SPY", "QQQ", "VOO", "VTI", "IWM", "DIA",   # ETFs
    "SPX", "NDX", "IXIC", "DJI",                 # indices
})


# --- Disambiguation (model call, unknowns only) ------------------------

_DISAMBIGUATION_SYSTEM_PROMPT = """\
You classify a single financial symbol or short asset name into exactly \
one asset class.

Classes:
- "crypto": a cryptocurrency or crypto token (e.g. BTC, ETH, QNT, Quant).
- "equities": an individual publicly-traded company stock (e.g. AAPL, \
Oracle, Shopify).
- "unsupported": anything else — ETFs, indices, mutual funds, forex \
pairs, commodities, or a symbol you cannot confidently identify.

Rules:
- Output strict JSON, no prose, no markdown fences: \
{"class": "crypto" | "equities" | "unsupported"}.
- If you are not confident the symbol is a specific cryptocurrency or a \
specific individual company stock, return "unsupported". Do not guess.

Examples:
QNT -> {"class": "crypto"}
Quant -> {"class": "crypto"}
ORCL -> {"class": "equities"}
Shopify -> {"class": "equities"}
SPY -> {"class": "unsupported"}
EURUSD -> {"class": "unsupported"}
ZX9QWP -> {"class": "unsupported"}
"""


class SymbolDisambiguator:
    """Haiku-backed classifier for symbols absent from every keyspace.

    Mirrors the decomposer pattern: a fixed-schema JSON call via
    AnthropicClient.create with an explicit ModelConfig. Any failure
    (API, JSON, schema, unexpected class) resolves to UNSUPPORTED — the
    safe default is to refuse, never to mis-route to a price tool.
    """

    def __init__(self, client: AnthropicClient) -> None:
        self._client = client
        self._config = get_model_config(TaskType.SYMBOL_DISAMBIGUATION)

    def classify(self, symbol: str) -> AssetClass:
        try:
            response = self._client.create(
                config=self._config,
                system=_DISAMBIGUATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": symbol}],
            )
            return _parse_class(_extract_text(response))
        except Exception:  # noqa: BLE001 — safe default is refusal
            return AssetClass.UNSUPPORTED


class AssetRegistry:
    """Resolves a symbol to its AssetClass, per symbol.

    Deterministic-first: curated keyspaces resolve with no model call.
    Only a symbol absent from all three keyspaces incurs the Haiku
    disambiguation call, and only if a disambiguator is present. resolve()
    never returns the internal 'unknown' state — it collapses to a
    concrete AssetClass here.
    """

    def __init__(self, disambiguator: SymbolDisambiguator | None = None) -> None:
        self._disambiguator = disambiguator

    @staticmethod
    def resolve_deterministic(symbol: str) -> AssetClass | None:
        """Pure, offline-testable core. Returns None for a symbol absent
        from every curated keyspace (i.e. 'unknown, ask the model').
        None never escapes resolve()."""
        s = symbol.strip().upper()
        if s in CRYPTO_SYMBOLS or s in CRYPTO_NAMES:
            return AssetClass.CRYPTO
        if s in EQUITY_SYMBOLS or s in EQUITY_NAMES:
            return AssetClass.EQUITIES
        if s in UNSUPPORTED_SYMBOLS:
            return AssetClass.UNSUPPORTED
        return None

    def resolve(self, symbol: str) -> AssetClass:
        """Resolve a symbol to a concrete AssetClass. Deterministic for
        known symbols; one Haiku call for unknowns when a disambiguator
        is present, else a safe UNSUPPORTED default."""
        deterministic = self.resolve_deterministic(symbol)
        if deterministic is not None:
            return deterministic
        if self._disambiguator is None:
            # Cannot disambiguate without a model, and we must not guess a
            # tradeable class for an unknown symbol — refuse.
            return AssetClass.UNSUPPORTED
        return self._disambiguator.classify(symbol)


# --- Parsing helpers (mirror the decomposer) ---------------------------

def _extract_text(response: object) -> str:
    """Pull the single text block out of an Anthropic Messages response."""
    content = getattr(response, "content", None)
    if not content:
        raise ValueError("disambiguator response had no content")
    for block in content:
        if getattr(block, "type", None) == "text":
            return getattr(block, "text", "")
    raise ValueError("disambiguator response had no text block")


def _parse_class(raw_text: str) -> AssetClass:
    """Parse the classifier's JSON. Raises on anything unexpected; the
    caller (classify) catches and defaults to UNSUPPORTED."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if "\n" in cleaned:
            cleaned = cleaned.split("\n", 1)[1]
    data = json.loads(cleaned)
    return AssetClass(data["class"])  # ValueError on unknown value