"""Manual end-to-end smoke check for the AW Analysis MCP server.

NOT a unit test — this launches the real server as a stdio subprocess and
makes live API calls (Anthropic, CoinGecko). It is the no-host verify-gate:
it speaks MCP directly with no host model in the loop, exercising all three
primitives — the ask_aw_analysis tool, the asset-profile resources, and the
compare_assets prompt.

Run from anywhere, with the venv interpreter:
    .venv/bin/python bin/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pydantic import AnyUrl

# Repo root derived from this file's location (bin/ -> repo root), not the
# working directory, so the launched subprocess resolves aw_analysis no
# matter where the script is run from.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Launch the server with the SAME interpreter running this script (the venv
# python), so the subprocess has mcp + aw_analysis available.
server_params = StdioServerParameters(
    command=sys.executable,
    args=["-m", "aw_analysis.mcp_server"],
    env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
)


async def main() -> None:
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # MCP handshake: negotiate protocol version + capabilities.
            await session.initialize()

            # Tool (model-controlled). Single-intent crypto: the fast path.
            tools = await session.list_tools()
            print("tools advertised:", [t.name for t in tools.tools])
            result = await session.call_tool(
                "ask_aw_analysis",
                {"query": "What is the price of Bitcoin?"},
            )
            print("isError:", result.isError)
            for block in result.content:
                if isinstance(block, types.TextContent):
                    print("ANSWER:\n", block.text)

            # Resources (app-controlled): list them, read one directly.
            resources = await session.list_resources()
            print("resources:", [str(r.uri) for r in resources.resources])
            profile = await session.read_resource(AnyUrl("asset://profiles/bitcoin"))
            print("PROFILE (first 200 chars):\n", profile.contents[0].text[:200])

            # Prompt (user-controlled): list it, render it. No model runs.
            prompts = await session.list_prompts()
            print("prompts:", [p.name for p in prompts.prompts])
            rendered = await session.get_prompt(
                "compare_assets", {"asset_a": "Apple", "asset_b": "Bitcoin"}
            )
            print("RENDERED:", rendered.messages[0].content.text)


if __name__ == "__main__":
    asyncio.run(main())