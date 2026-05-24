"""Thin compatibility shim around OrchestratedConversation.

Pre-Stage-3 callers used run_agent(query) -> result. Stage 3 made this
a single-turn invocation of Conversation; Stage 7 makes it a single-
turn invocation of OrchestratedConversation. The shim exists because
older scripts and tests still call run_agent — keeping the surface
stable means we don't have to chase those down.
"""

from __future__ import annotations

from aw_analysis.agent.conversation import Conversation
from aw_analysis.agent.orchestration import (
    OrchestratedConversation,
    OrchestratedTurnTrace,
)
from aw_analysis.client.anthropic_client import AnthropicClient
from aw_analysis.prompts.system import SYSTEM_PROMPT
from aw_analysis.tools import default_registry


def run_agent(user_message: str) -> OrchestratedTurnTrace:
    """Run one user turn through the orchestrated agent.

    Convenience for tests and scripts. Production code goes through
    OrchestratedConversation directly.
    """
    client = AnthropicClient()
    inner = Conversation(
        client=client,
        tools=default_registry(),
        system_prompt=SYSTEM_PROMPT,
    )
    orchestrated = OrchestratedConversation(client=client, conversation=inner)
    return orchestrated.send(user_message)