"""CoinGecko data source.

This is a *plain HTTP client*, not a tool. Tools wrap this with
agent-facing schemas and descriptions.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Map common tickers to CoinGecko IDs. CoinGecko uses long-form IDs
# (e.g. "bitcoin") rather than tickers (e.g. "BTC"), so we translate.
TICKER_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "POL": "polygon-ecosystem-token",
    "MATIC": "polygon-ecosystem-token",
}

# Strip HTML tags and clean whitespace from CoinGecko description text.
# CoinGecko's descriptions contain inline links (<a href="...">) and
# basic HTML formatting that we don't want in the agent's context.
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

class CoinGeckoError(Exception):
    """Raised when CoinGecko returns an error or unexpected response."""


class CoinGeckoClient:
    """Synchronous CoinGecko client.

    Synchronous because the agent loop is synchronous. We can swap to async
    later without changing the tool surface.
    """

    def __init__(self, timeout: float = 10.0) -> None:
        self._client = httpx.Client(
            base_url=COINGECKO_BASE,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def get_price(self, ticker: str, vs_currency: str = "usd") -> dict[str, Any]:
        """Get current price and 24h change for a ticker.

        Returns:
            {
                "ticker": "BTC",
                "id": "bitcoin",
                "price": 67234.12,
                "currency": "usd",
                "change_24h_pct": 1.84,
                "market_cap": 1325000000000,
                "volume_24h": 28000000000,
            }
        """
        ticker = ticker.upper()
        coin_id = TICKER_TO_ID.get(ticker)
        if coin_id is None:
            # Not in the curated map — try CoinGecko's search to resolve
            # the ticker. _resolve_coin_id raises CoinGeckoError if no
            # match is found, which the tool dispatch surfaces as a tool
            # failure the model can adapt to.
            coin_id = self._resolve_coin_id(ticker)

        params = {
            "ids": coin_id,
            "vs_currencies": vs_currency,
            "include_market_cap": "true",
            "include_24hr_vol": "true",
            "include_24hr_change": "true",
        }
        try:
            resp = self._client.get("/simple/price", params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise CoinGeckoError(f"CoinGecko request failed: {exc}") from exc

        data = resp.json().get(coin_id)
        if not data:
            raise CoinGeckoError(f"No data returned for {ticker} ({coin_id})")

        return {
            "ticker": ticker,
            "id": coin_id,
            "price": data[vs_currency],
            "currency": vs_currency,
            "change_24h_pct": data.get(f"{vs_currency}_24h_change"),
            "market_cap": data.get(f"{vs_currency}_market_cap"),
            "volume_24h": data.get(f"{vs_currency}_24h_vol"),
        }

    def get_description(self, query: str) -> dict[str, Any]:
        """Look up an asset by ticker or name and return its description.

        Unlike get_price, this does not require the ticker to be in our
        curated TICKER_TO_ID map — it uses CoinGecko's `/search` endpoint
        to resolve the query to a coin id, then fetches that coin's
        description from `/coins/{id}`.

        Returns:
            {
                "id": "quant-network",
                "name": "Quant",
                "symbol": "QNT",
                "description": "Quant is a blockchain interoperability...",
                "categories": ["Smart Contract Platform", ...],
            }
        """
        # Resolve query → coin id via search endpoint
        coin_id = self._resolve_coin_id(query)

        try:
            resp = self._client.get(
                f"/coins/{coin_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "false",
                    "community_data": "false",
                    "developer_data": "false",
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise CoinGeckoError(f"CoinGecko coin fetch failed: {exc}") from exc

        data = resp.json()
        description_html = data.get("description", {}).get("en", "")
        description = _clean_description(description_html)

        if not description:
            raise CoinGeckoError(
                f"CoinGecko has no English description for {coin_id}"
            )

        return {
            "id": coin_id,
            "name": data.get("name", ""),
            "symbol": (data.get("symbol") or "").upper(),
            "description": description,
            "categories": [c for c in data.get("categories", []) if c],
        }

    def _resolve_coin_id(self, query: str) -> str:
        """Resolve a freeform query to a CoinGecko coin id."""
        query = query.strip()

        # Fast path: if it's a ticker we already know, skip the search.
        upper = query.upper()
        if upper in TICKER_TO_ID:
            return TICKER_TO_ID[upper]

        try:
            resp = self._client.get("/search", params={"query": query})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise CoinGeckoError(f"CoinGecko search failed: {exc}") from exc

        coins = resp.json().get("coins", [])
        if not coins:
            raise CoinGeckoError(f"No CoinGecko match for '{query}'")

        # CoinGecko ranks search results by market cap rank — top hit is
        # almost always the right one. We trust the ranking.
        return coins[0]["id"]

    def close(self) -> None:
        self._client.close()


def _clean_description(html: str) -> str:
    """Strip HTML tags and collapse whitespace from CoinGecko descriptions."""
    text = _HTML_TAG_RE.sub("", html)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()