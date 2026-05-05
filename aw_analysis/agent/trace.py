"""Structured records of what happens during an agent turn.

A `TurnTrace` captures one user→assistant exchange in full detail:
- The user's message
- Every tool call the model made and what came back
- The final assistant reply
- Token usage and stop reason

This is the substrate for evals (Stage 6) and observability (Stage 8).
The eval harness can assert on traces; observability can stream them
to Langfuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """One tool invocation within a turn."""

    name: str
    input: dict[str, Any]
    result: str
    success: bool
    duration_ms: float
    error: str | None = None


@dataclass
class TurnTrace:
    """A complete record of one user→assistant turn."""

    user_message: str
    final_text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    iterations: int = 0
    truncated: bool = False  # True if we hit the turn budget

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def tool_count(self) -> int:
        return len(self.tool_calls)

    def error_count(self) -> int:
        return sum(1 for tc in self.tool_calls if not tc.success)