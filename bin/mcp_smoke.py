"""Direct stdio client for the AW Analysis MCP server — no host model.

Launches aw_analysis.mcp_server as a subprocess, speaks MCP to it, and
calls ask_aw_analysis with one crypto case. This is the live verify-gate
for the server before any host (Inspector / Claude Desktop) is involved.

Run from the repo root, in the venv:
    python mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from pydantic import AnyUrl

# Launch the server with the SAME interpreter running this script (the
# venv python), so the subprocess has mcp + aw_analysis available.
# PYTHONPATH lets `-m aw_analysis.mcp_server` resolve regardless of cwd.
server_params = StdioServerParameters(
    command=sys.executable,
    args=["-m", "aw_analysis.mcp_server"],
    env={**os.environ, "PYTHONPATH": os.getcwd()},
)


async def main() -> None:
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # MCP handshake: negotiate protocol version + capabilities.
            await session.initialize()

            # Capability discovery — the host learns what the server offers.
            tools = await session.list_tools()
            print("tools advertised:", [t.name for t in tools.tools])

            # The one live case: single-intent, crypto, fast path.
            result = await session.call_tool(
                "ask_aw_analysis",
                {"query": "What is the price of Bitcoin?"},
            )
            print("isError:", result.isError)
            for block in result.content:
                if isinstance(block, types.TextContent):
                    print("ANSWER:\n", block.text)

            # Resources are app-controlled: the client lists them and reads
            # one directly. No model decided to fetch these.
            resources = await session.list_resources()
            print("resources:", [str(r.uri) for r in resources.resources])
            profile = await session.read_resource(AnyUrl("asset://profiles/bitcoin"))
            print("PROFILE (first 200 chars):\n", profile.contents[0].text[:200])

            # Prompts are user-controlled: the client lists them and renders
            # one. No model runs here -- a prompt only produces messages.
            prompts = await session.list_prompts()
            print("prompts:", [p.name for p in prompts.prompts])
            rendered = await session.get_prompt(
                "compare_assets", {"asset_a": "Apple", "asset_b": "Bitcoin"}
            )
            print("RENDERED:", rendered.messages[0].content.text)


if __name__ == "__main__":
    asyncio.run(main())