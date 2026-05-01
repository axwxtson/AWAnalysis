"""The agent loop: send messages, dispatch tool calls, repeat until done.

This is the Stage 1 minimum-viable loop. It handles:
- The single-turn user → model exchange
- The tool-use → tool-result handshake
- Iteration until the model stops requesting tools

Stage 3 will rebuild this with proper ReAct tracing, planning, and
multi-step memory. For now, this is the simplest thing that works.
"""

from __future__ import annotations

from anthropic.types import MessageParam, ToolUseBlock

from aw_analysis.client import AnthropicClient
from aw_analysis.prompts import SYSTEM_PROMPT
from aw_analysis.tools import ToolRegistry

MAX_AGENT_TURNS = 10


def run_agent(
    user_message: str,
    client: AnthropicClient,
    tools: ToolRegistry,
) -> str:
    """Run the agent loop until the model produces a final text response.

    Returns:
        The final text response from the model.
    """
    messages: list[MessageParam] = [
        {"role": "user", "content": user_message}
    ]

    for turn in range(MAX_AGENT_TURNS):
        response = client.create_message(
            messages=messages,
            system=SYSTEM_PROMPT,
            tools=tools.to_anthropic_params(),
        )

        # Append the assistant's response to the running conversation.
        # Note: response.content is a list of content blocks. We pass
        # them straight back as the assistant turn — the SDK handles
        # serialising them.
        messages.append({"role": "assistant", "content": response.content})

        # If the model is done (didn't request a tool), return its text.
        if response.stop_reason != "tool_use":
            return _extract_text(response.content)

        # Otherwise, run every tool the model asked for and feed
        # results back in a single user turn.
        tool_results = []
        for block in response.content:
            if isinstance(block, ToolUseBlock):
                result = tools.dispatch(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    return f"[agent stopped: exceeded {MAX_AGENT_TURNS} turns]"


def _extract_text(content: list) -> str:
    """Pull text content out of a response's content blocks."""
    parts = []
    for block in content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts) if parts else "[no text response]"