"""Single-shot agent invocation.

Wraps Conversation for callers that just want one user→assistant exchange
without managing state. The CLI uses Conversation directly for the REPL;
this function exists for tests, scripts, and future single-shot uses.
"""

from __future__ import annotations

from aw_analysis.agent.conversation import Conversation
from aw_analysis.agent.trace import TurnTrace
from aw_analysis.client import AnthropicClient
from aw_analysis.tools import ToolRegistry


def run_agent(
    user_message: str,
    client: AnthropicClient,
    tools: ToolRegistry,
) -> TurnTrace:
    """Run a single user→assistant exchange. Returns a TurnTrace."""
    conversation = Conversation(client=client, tools=tools)
    return conversation.send(user_message)