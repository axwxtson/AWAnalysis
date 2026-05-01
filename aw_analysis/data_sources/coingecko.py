"""CoinGecko data source.

This is a *plain HTTP client*, not a tool. Tools wrap this with
agent-facing schemas and descriptions.
"""

from __future__ import annotations

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
    "MATIC": "matic-network",
}


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
            raise CoinGeckoError(
                f"Unknown ticker '{ticker}'. "
                f"Known: {', '.join(sorted(TICKER_TO_ID))}"
            )

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

    def close(self) -> None:
        self._client.close()