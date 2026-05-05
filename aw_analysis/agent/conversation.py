"""Conversation: stateful agent that threads context across turns.

Stage 3 of 8.

Replaces the Stage 1 stateless `run_agent` function. A Conversation
holds the full message history, the tool registry, and per-turn budget
configuration. You call `.send(user_message)` repeatedly; each call
appends to the running history and returns a TurnTrace.

Why a class rather than a closure or module-level state?
- Tests instantiate fresh Conversations cheaply.
- Multiple concurrent conversations don't collide (Stage 7 will route
  by query class — that means multiple Conversations in flight).
- The trace history is inspectable for evals and debugging.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from anthropic.types import MessageParam, ToolUseBlock

from aw_analysis.agent.errors import TurnBudgetExceeded
from aw_analysis.agent.trace import ToolCall, TurnTrace
from aw_analysis.client import AnthropicClient
from aw_analysis.prompts import SYSTEM_PROMPT
from aw_analysis.tools import ToolRegistry


# Default turn budget. A "turn" here means one round-trip to the model.
# Most queries finish in 1-3 turns. The budget is a safety rail, not
# a target.
DEFAULT_TURN_BUDGET = 8


@dataclass
class Conversation:
    """A stateful conversation with the AW Analysis agent.

    Threads message history across .send() calls. The system prompt and
    tool registry are fixed at construction time.
    """

    client: AnthropicClient
    tools: ToolRegistry
    system_prompt: str = SYSTEM_PROMPT
    turn_budget: int = DEFAULT_TURN_BUDGET

    # Internal state — not constructor params.
    _messages: list[MessageParam] = field(default_factory=list)
    _traces: list[TurnTrace] = field(default_factory=list)

    def send(self, user_message: str) -> TurnTrace:
        """Send one user message; return a complete trace of the turn.

        The message is appended to the running history before the call,
        so the model sees prior context. Tool calls and results are
        threaded into the history too.
        """
        trace = TurnTrace(user_message=user_message, final_text="")
        self._messages.append({"role": "user", "content": user_message})

        for iteration in range(self.turn_budget):
            trace.iterations = iteration + 1

            response = self.client.create_message(
                messages=self._messages,
                system=self.system_prompt,
                tools=self.tools.to_anthropic_params(),
            )

            # Token accounting — running total across iterations of this turn.
            trace.input_tokens += response.usage.input_tokens
            trace.output_tokens += response.usage.output_tokens
            trace.stop_reason = response.stop_reason

            # Append the assistant response to the running conversation.
            self._messages.append(
                {"role": "assistant", "content": response.content}
            )

            # If the model is done (didn't request a tool), extract the
            # final text and we're out.
            if response.stop_reason != "tool_use":
                trace.final_text = _extract_text(response.content)
                self._traces.append(trace)
                return trace

            # Otherwise, dispatch every tool the model requested and
            # feed results back in a single user turn.
            tool_use_blocks = [
                b for b in response.content if isinstance(b, ToolUseBlock)
            ]
            tool_results_payload = []
            for block in tool_use_blocks:
                result = self.tools.dispatch(block.name, dict(block.input))
                trace.tool_calls.append(
                    ToolCall(
                        name=result.name,
                        input=dict(block.input),
                        result=result.content,
                        success=result.success,
                        duration_ms=result.duration_ms,
                        error=result.error,
                    )
                )
                tool_results_payload.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result.content,
                        "is_error": not result.success,
                    }
                )

            self._messages.append(
                {"role": "user", "content": tool_results_payload}
            )

        # Fell through the loop without finishing — turn budget exhausted.
        trace.truncated = True
        trace.final_text = (
            f"[Agent stopped after {self.turn_budget} iterations without "
            f"producing a final answer.]"
        )
        self._traces.append(trace)
        raise TurnBudgetExceeded(
            f"Exceeded turn budget of {self.turn_budget} for message: "
            f"{user_message!r}"
        )

    # Inspection helpers — used by CLI and (later) tests/evals.

    def history(self) -> list[MessageParam]:
        """Return the full message history (read-only copy)."""
        return list(self._messages)

    def traces(self) -> list[TurnTrace]:
        """Return all turn traces from this conversation."""
        return list(self._traces)

    def reset(self) -> None:
        """Clear all conversation state."""
        self._messages.clear()
        self._traces.clear()


def _extract_text(content: list) -> str:
    """Pull text content out of a response's content blocks."""
    parts = [b.text for b in content if hasattr(b, "text")]
    return "\n".join(parts) if parts else "[no text response]"