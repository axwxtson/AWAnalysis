"""Tool: get current crypto price and 24h metrics."""

from __future__ import annotations

import json
from typing import Any

from aw_analysis.data_sources import CoinGeckoClient
from aw_analysis.tools.base import Tool


class CryptoPriceTool(Tool):
    name = "get_crypto_price"
    description = (
        "Get the current price, 24-hour price change, market cap, and 24-hour "
        "trading volume for a cryptocurrency. Use this when the user asks "
        "about the current state of a crypto asset."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": (
                    "Ticker symbol of the cryptocurrency (e.g. 'BTC', 'ETH', "
                    "'SOL'). Case-insensitive."
                ),
            },
        },
        "required": ["ticker"],
    }

    def __init__(self, data_source: CoinGeckoClient | None = None) -> None:
        self._source = data_source or CoinGeckoClient()

    def execute(self, ticker: str) -> str:
        data = self._source.get_price(ticker)
        return json.dumps(data, indent=2)