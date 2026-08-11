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

Cross-asset since Stage 9: news applies to cryptocurrencies and to
publicly-traded equities alike. This is the one tool with no class split
— unlike price (get_crypto_price / get_equity_price), a news search is
the same operation whatever the asset is, which is also why routing
never forces it (see orchestration.FORCE_MAP).

Use cases:
- "Did anything happen to Solana this week?"
- "Any recent news on NVIDIA's earnings?"
- "What's the latest on the spot Bitcoin ETF?"
- "Why is Tesla down today?"
- Any question where the answer is in news rather than reference content.
"""

from __future__ import annotations

from typing import Any

from aw_analysis.tools.base import Tool


class MarketNewsTool(Tool):
    # `web_search` is not a name we chose and is not an accidental
    # collision with Anthropic's identifier — it IS that identifier.
    # This tool is a passthrough to the server-side search tool, so the
    # name is fixed by the {"type": "web_search_20250305", "name":
    # "web_search"} contract emitted in to_anthropic_param below.
    #
    # It also never crosses the MCP boundary: mcp_server.py exposes one
    # tool (ask_aw_analysis), so a third-party host cannot see this name
    # and cannot collide with its own search tool. That falls out of the
    # decision to expose the orchestrated agent rather than raw pipeline
    # primitives.
    name = "web_search"
    description = (
        "Search the web for recent news, events, or analysis about "
        "financial markets — both cryptocurrencies and publicly-traded "
        "equities. Use this when the user asks about: recent events "
        "('what happened to Solana this week', 'any news on NVIDIA's "
        "earnings'), current sentiment or analysis ('why is ETH down', "
        "'why did Tesla drop today'), upcoming events ('when is the next "
        "Bitcoin halving in news terms', 'when does Apple report'), or "
        "anything time-sensitive that wouldn't be in static reference "
        "material. Do NOT use this for: current prices (use "
        "get_crypto_price for crypto or get_equity_price for equities), "
        "background/biographical information about an asset (use "
        "lookup_asset_profile), or speculative predictions."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A focused search query. Examples: 'Solana network "
                    "outage 2026', 'spot Bitcoin ETF flows this week', "
                    "'NVIDIA Q2 earnings reaction', 'Tesla delivery "
                    "numbers this quarter'. Be specific about the asset "
                    "and the time-frame if known."
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