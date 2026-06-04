"""Twelve Data data source.

Plain HTTP client for the Twelve Data API, mirroring the CoinGecko
client. Tools wrap this with agent-facing schemas. Equities are reached
through the free/quote endpoint, which returns price, daily change,
name, exchange, and volume in one credit.

Errors surface as typed exceptions whose class names become the
categorical ToolResult error tag in ToolRegistry.dispatch:
TwelveDataRateLimit, TwelveDataUnknownSymbol, or the TwelveDataError
base for anything else.
"""
from __future__ import annotations

from typing import Any

import httpx

from aw_analysis.config import SETTINGS

TWELVEDATA_BASE = "https://api.twelvedata.com"


class TwelveDataError(Exception):
    """Base for Twelve Data failures."""


class TwelveDataRateLimit(TwelveDataError):
    """Raised when the API credit limit is exhausted (code 429)."""


class TwelveDataUnknownSymbol(TwelveDataError):
    """Raised when the symbol is not found or not accessible (code 400/404)."""


class TwelveDataClient:
    """Synchronous Twelve Data client.

    The API key is read from SETTINGS at construction but not validated
    until a call is made, so a missing key only bites when the tool is
    actually invoked (mirrors the lazy-credential pattern elsewhere).
    """

    def __init__(self, api_key: str | None = None, timeout: float = 10.0) -> None:
        self._api_key = api_key if api_key is not None else SETTINGS.twelvedata_api_key
        self._client = httpx.Client(
            base_url=TWELVEDATA_BASE,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def get_quote(self, ticker: str) -> dict[str, Any]:
        """Get the current quote for an equity ticker.

        Returns:
            {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "exchange": "NASDAQ",
                "price": 201.5,
                "currency": "USD",
                "change_pct": 0.84,   # daily change (cf. crypto's 24h)
                "volume": 48000000,
                "datetime": "2026-06-04",
            }

        Market cap is intentionally absent — it sits behind Twelve Data's
        paid fundamentals tier. This is a documented free-tier limitation.
        """
        if not self._api_key:
            raise TwelveDataError("TWELVEDATA_API_KEY not set")

        ticker = ticker.strip().upper()
        params = {"symbol": ticker, "apikey": self._api_key}
        try:
            resp = self._client.get("/quote", params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise TwelveDataError(f"Twelve Data request failed: {exc}") from exc

        data = resp.json()
        self._raise_on_api_error(data, ticker)

        return {
            "ticker": ticker,
            "name": data.get("name"),
            "exchange": data.get("exchange"),
            "price": _to_float(data.get("close")),
            "currency": data.get("currency"),
            "change_pct": _to_float(data.get("percent_change")),
            "volume": _to_int(data.get("volume")),
            "datetime": data.get("datetime"),
        }

    def get_reference(self, query: str) -> dict[str, Any]:
        """Resolve a name or ticker to basic reference data via symbol
        search. Free-tier reference only — name, exchange, instrument
        type, currency, country; no description or fundamentals.
        """
        if not self._api_key:
            raise TwelveDataError("TWELVEDATA_API_KEY not set")

        q = query.strip()
        params = {"symbol": q, "apikey": self._api_key}
        try:
            resp = self._client.get("/symbol_search", params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise TwelveDataError(f"Twelve Data request failed: {exc}") from exc

        data = resp.json()
        self._raise_on_api_error(data, q)
        matches = data.get("data") or []
        if not matches:
            raise TwelveDataUnknownSymbol(f"Twelve Data: no match for '{q}'")

        best = _best_equity_match(matches, q)
        return {
            "symbol": best.get("symbol"),
            "name": best.get("instrument_name"),
            "exchange": best.get("exchange"),
            "instrument_type": best.get("instrument_type"),
            "currency": best.get("currency"),
            "country": best.get("country"),
        }

    @staticmethod
    def _raise_on_api_error(data: Any, ticker: str) -> None:
        """Twelve Data signals errors in the JSON body (status='error'),
        often with HTTP 200. Map the code to a categorical exception."""
        if isinstance(data, dict) and data.get("status") == "error":
            code = data.get("code")
            message = data.get("message", "unknown error")
            if code == 429:
                raise TwelveDataRateLimit(f"Twelve Data rate limit: {message}")
            if code in (400, 404) or "not found" in str(message).lower():
                raise TwelveDataUnknownSymbol(
                    f"Twelve Data: {message} (symbol={ticker})"
                )
            raise TwelveDataError(f"Twelve Data error {code}: {message}")

    def close(self) -> None:
        self._client.close()

def _best_equity_match(matches: list[dict[str, Any]], query: str) -> dict[str, Any]:
    """Pick the most likely equity from symbol-search results: prefer an
    exact symbol match, then a stock instrument type, then a US listing."""
    q = query.strip().upper()
    exact = [m for m in matches if str(m.get("symbol", "")).upper() == q]
    pool = exact or matches
    stocks = [m for m in pool if "stock" in str(m.get("instrument_type", "")).lower()]
    pool = stocks or pool
    us = [m for m in pool if str(m.get("country", "")).lower() in ("united states", "usa", "us")]
    return (us or pool)[0]
    
def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None