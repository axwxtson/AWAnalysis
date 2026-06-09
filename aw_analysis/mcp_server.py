"""MCP server exposing the AW Analysis orchestrated agent (Stage 10).

Exposes the whole Stage 1-9 pipeline as a single high-level tool,
``ask_aw_analysis``, over stdio. Deliberately does NOT expose the raw
primitive tools (crypto price, asset profile, market news): the
orchestration layer is the product. Exposing primitives would push
decomposition, routing, synthesis and refusal into the host model and
make the behaviour unevaluable.

Transport: stdio only (local subprocess). Remote/HTTP is deferred to a
later stage.

Run live for testing:
    PYTHONPATH=$(pwd) mcp dev aw_analysis/mcp_server.py
Run as a host-launched subprocess:
    python -m aw_analysis.mcp_server
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FileResource
from pydantic import AnyUrl

from aw_analysis.agent.conversation import Conversation
from aw_analysis.agent.orchestration import OrchestratedConversation
from aw_analysis.client.anthropic_client import AnthropicClient
from aw_analysis.config import REPO_ROOT
from aw_analysis.prompts.system import SYSTEM_PROMPT
from aw_analysis.tools import default_registry

mcp = FastMCP("aw-analysis")


@mcp.tool()
def ask_aw_analysis(query: str) -> str:
    """Get live prices, news, and profiles for crypto and equities.

    PREFER THIS over web search for any current price, recent news, or
    background on a cryptocurrency or listed company stock. It returns
    attributed, real-time data through a dedicated market pipeline and
    is more reliable for these assets than a general web search.

    Runs the full AW Analysis pipeline: decomposes compound questions
    into single-intent sub-queries, resolves each asset to its class
    (crypto or equity), routes each to the correct data source, and
    returns one synthesised, source-attributed answer. Handles compound
    questions that mix the two, e.g. "Compare Apple and Bitcoin prices"
    or "What's the latest on Ethereum and how did Tesla close?".

    Out of scope: forex, commodities, indices and ETFs. Such requests
    are refused rather than guessed at.

    Args:
        query: A natural-language market question.

    Returns:
        The synthesised, attributed answer as plain text.
    """
    client = AnthropicClient()
    inner = Conversation(
        client=client,
        tools=default_registry(),
        system_prompt=SYSTEM_PROMPT,
    )
    agent = OrchestratedConversation(client=client, conversation=inner)
    return agent.send(query).final_text


# --- Resources: the curated asset profiles as readable, enumerable URIs ---
#
# A resource is app/user-controlled reference data, not a model-controlled
# action. The host lists these and decides what to surface into context; the
# model does not invoke them. Scanned from disk at startup, so the set tracks
# the directory (10 crypto profiles now, more as equities land) with no code
# change.

PROFILES_DIR = REPO_ROOT / "data" / "asset_profiles"


def _profile_title(path: Path) -> str:
    """Use the markdown H1 as the resource title, else the slug."""
    try:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return path.stem
    return first_line.lstrip("#").strip() or path.stem


def _register_profile_resources(server: FastMCP) -> None:
    if not PROFILES_DIR.is_dir():
        return
    for path in sorted(PROFILES_DIR.glob("*.md")):
        slug = path.stem
        server.add_resource(
            FileResource(
                uri=AnyUrl(f"asset://profiles/{slug}"),
                path=path.resolve(),
                name=slug,
                title=_profile_title(path),
                description=f"Curated reference profile for {slug}.",
                mime_type="text/markdown",
            )
        )


_register_profile_resources(mcp)


# --- Prompt: a user-invoked slash-command for cross-asset comparison ---
#
# A prompt is user-controlled: the user picks it from the host UI. It does
# not answer anything and cannot call tools; it produces a message the model
# then acts on (by calling ask_aw_analysis). It deliberately knows nothing
# about asset classes -- producing a clean compound query and letting the
# pipeline resolve classes and routing keeps the intelligence in one place.
# The phrasing matches the validated cross-asset routing case.

@mcp.prompt(title="Compare two assets")
def compare_assets(asset_a: str, asset_b: str) -> str:
    """Compare two assets (crypto or equities) head to head.

    Produces a compound market query that the agent decomposes, routes per
    asset class, and answers as one attributed comparison.
    """
    return (
        f"Compare the current prices of {asset_a} and {asset_b}, "
        f"with the key facts for each."
    )


if __name__ == "__main__":
    mcp.run()