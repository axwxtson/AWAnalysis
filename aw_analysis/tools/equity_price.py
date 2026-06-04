"""Tool: get current equity price and daily metrics."""

from __future__ import annotations

import json
from typing import Any

from aw_analysis.data_sources.twelvedata import TwelveDataClient
from aw_analysis.tools.base import Tool


class EquityPriceTool(Tool):
    name = "get_equity_price"
    description = (
        "Get the current price, daily price change, and trading volume "
        "for a publicly-traded company stock (equity), e.g. 'AAPL', "
        "'MSFT', 'TSLA'. Use this when the user asks about the current "
        "market state of a stock. Do NOT use this for cryptocurrencies "
        "(use get_crypto_price), nor for ETFs or market indices."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": (
                    "Ticker symbol of the equity (e.g. 'AAPL', 'MSFT'). "
                    "Case-insensitive."
                ),
            },
        },
        "required": ["ticker"],
    }

    def __init__(self, data_source: TwelveDataClient | None = None) -> None:
        self._source = data_source or TwelveDataClient()

    def execute(self, ticker: str) -> str:
        data = self._source.get_quote(ticker)
        return json.dumps(data, indent=2)