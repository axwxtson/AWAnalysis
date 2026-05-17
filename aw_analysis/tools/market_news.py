"""Tool: search recent market news and events via Anthropic's web search.

Unlike our other tools, this is a *server-side* tool — Anthropic performs
the search, fetches pages, and returns results inline. We register it in
our tool list so the model knows when to use it, but our ToolRegistry
won't dispatch it directly.

This means the AnthropicClient needs to know about it (to include it in
the API call's tools list), but our agent loop and CLI can treat it
mostly like any other tool. The tool-activity line will not show a
duration for it because we don't time the dispatch — the search happens
inside the model's response generation.

Use cases:
- "Did anything happen to Solana this week?"
- "What's the latest on the spot Bitcoin ETF?"
- "Why is ETH down today?"
- Any question where the answer is in news rather than reference content.
"""

from __future__ import annotations

from typing import Any

from aw_analysis.tools.base import Tool


class MarketNewsTool(Tool):
    name = "web_search"
    description = (
        "Search the web for recent news, events, or analysis about "
        "cryptocurrency markets and assets. Use this when the user asks "
        "about: recent events ('what happened to Solana this week'), "
        "current sentiment or analysis ('why is ETH down'), upcoming "
        "events ('when is the next Bitcoin halving in news terms'), or "
        "anything time-sensitive that wouldn't be in static reference "
        "material. Do NOT use this for: current prices (use "
        "get_crypto_price), background/biographical information about "
        "an asset (use lookup_asset_profile), or speculative predictions."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A focused search query. Examples: 'Solana network "
                    "outage 2026', 'spot Bitcoin ETF flows this week', "
                    "'Ethereum upgrade news'. Be specific about the "
                    "asset and the time-frame if known."
                ),
            },
        },
        "required": ["query"],
    }

    # This tool is dispatched by Anthropic, not our registry. execute()
    # exists to satisfy the Tool interface but should never be called.
    def execute(self, query: str) -> str:
        return (
            "[server-side tool — should not have been dispatched locally; "
            "this indicates a bug in the agent loop's tool routing]"
        )

    # Anthropic's web search has a different shape than our client-tool
    # schema. We override to_anthropic_param to emit the server-tool
    # form instead.
    def to_anthropic_param(self) -> dict[str, Any]:
        return {
            "type": "web_search_20250305",
            "name": self.name,
        }