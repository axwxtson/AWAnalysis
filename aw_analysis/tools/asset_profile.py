"""Tool: lookup factual asset profile via tiered retrieval.

Tier 1: curated RAG corpus (10 hand-written profiles in data/asset_profiles/).
Tier 2: CoinGecko's /coins/{id} description for any asset they track.

The tool tries Tier 1 first. If the top retrieval score exceeds
CURATED_THRESHOLD, the curated content is authoritative and we return it.
Otherwise we fall back to Tier 2.

Both tiers return content with a `source` field so the model knows
where the information came from. This matters: the prompt instructs
the model to attribute curated content as "from our research" and
fallback content as "from CoinGecko" — preserving honesty about
provenance.
"""

from __future__ import annotations

import json
from typing import Any

from aw_analysis.data_sources import CoinGeckoClient
from aw_analysis.data_sources.coingecko import CoinGeckoError
from aw_analysis.rag import Retriever
from aw_analysis.tools.base import Tool


# Top-1 retrieval score above which the curated corpus is considered
# authoritative. Below this, we fall back to CoinGecko.
# Empirical starting point; Stage 6 evals will tune.
CURATED_THRESHOLD = 0.70

# How many curated chunks to return when the corpus is authoritative.
DEFAULT_K = 4


class AssetProfileTool(Tool):
    name = "lookup_asset_profile"
    description = (
        "Retrieve background information about a cryptocurrency: what "
        "it is, who created it, its consensus mechanism, supply, "
        "founding history, and notable context. Use this when the user "
        "asks definitional or biographical questions about an asset, "
        "for example 'what is Solana?', 'who founded Cardano?', or "
        "'tell me about Quant'. Works for any cryptocurrency CoinGecko "
        "tracks, with deeper editorial profiles for our researched "
        "assets (BTC, ETH, SOL, ADA, AVAX, DOGE, DOT, LINK, MATIC, XRP). "
        "Do NOT use this for live prices, recent news, or real-time "
        "market state — those have their own tools."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A natural-language question, ticker, or asset name. "
                    "Examples: 'Bitcoin consensus', 'Quant', 'who "
                    "founded Polkadot', 'what does Chainlink do'."
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        retriever: Retriever | None = None,
        coingecko: CoinGeckoClient | None = None,
    ) -> None:
        # Lazy-init both retrieval paths so missing credentials only
        # bite when the tool is invoked, not at import time.
        self._retriever = retriever
        self._coingecko = coingecko

    def _get_retriever(self) -> Retriever | None:
        """Return the curated retriever, or None if unavailable."""
        if self._retriever is None:
            try:
                self._retriever = Retriever()
            except RuntimeError:
                # Voyage key missing — RAG path unavailable.
                return None
        return self._retriever

    def _get_coingecko(self) -> CoinGeckoClient:
        if self._coingecko is None:
            self._coingecko = CoinGeckoClient()
        return self._coingecko

    def execute(self, query: str) -> str:
        # Tier 1: curated corpus.
        curated = self._try_curated(query)
        if curated is not None:
            return curated

        # Tier 2: CoinGecko description fallback.
        return self._try_coingecko(query)

    def _try_curated(self, query: str) -> str | None:
        """Attempt curated retrieval. Return JSON string on hit, None on miss."""
        retriever = self._get_retriever()
        if retriever is None:
            return None

        results = retriever.retrieve(query, k=DEFAULT_K)
        if not results:
            return None

        top_score = results[0].score
        if top_score < CURATED_THRESHOLD:
            return None

        payload = {
            "source": "curated",
            "query": query,
            "top_score": round(top_score, 3),
            "results": [
                {
                    "title": r.title,
                    "section": r.section,
                    "score": round(r.score, 3),
                    "text": r.text,
                }
                for r in results
            ],
        }
        return json.dumps(payload, indent=2)

    def _try_coingecko(self, query: str) -> str:
        """Attempt CoinGecko description lookup. Always returns JSON."""
        try:
            data = self._get_coingecko().get_description(query)
        except CoinGeckoError as exc:
            return json.dumps({
                "source": "none",
                "query": query,
                "error": str(exc),
                "note": (
                    "No curated profile or CoinGecko match for this "
                    "query. The asset may not exist or may be too "
                    "obscure to be tracked."
                ),
            })

        return json.dumps({
            "source": "coingecko",
            "query": query,
            "result": {
                "name": data["name"],
                "symbol": data["symbol"],
                "categories": data["categories"],
                "description": data["description"],
            },
        }, indent=2)