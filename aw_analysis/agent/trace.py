# aw_analysis/agent/trace.py
"""Per-turn execution trace.

Stage 5 additions:
  - IterationUsage: per-iteration record of which ModelConfig was
    used, the input/output token counts, and the post-hoc
    classification (was this iteration actually a refusal?).
  - TurnTrace gains `iterations` and a `was_refusal` summary.
British English throughout.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation inside a turn.

    `arguments` holds the tool input as the model emitted it. A result is
    only interpretable against the input that produced it: a profile
    lookup returning `source=none` means one thing for a symbol that is
    in the curated corpus and another for a symbol that never was, and
    the tool name alone cannot separate those.

    Last in the field order and defaulted, so positional construction and
    every existing call site are unaffected.
    """

    name: str
    duration_ms: float
    success: bool
    error: str | None = None
    result: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IterationUsage:
    """One iteration of the agent loop's call to the model.

    A single send() can produce multiple iterations: one for tool
    selection, one or more for tool-result-handling and synthesis.
    Each gets one of these.
    """

    task_type: str  # TaskType.value
    model: str
    temperature: float
    max_tokens: int
    input_tokens: int
    output_tokens: int
    stop_reason: str
    rationale: str  # Carried from ModelConfig for trace readability.
    duration_ms: int = 0  # Wall-clock time of the model call, populated by Conversation.
    cost_usd: float = 0.0 # Populated by Conversation, summed by TurnTrace
    retries: int = 0  # Client retry attempts for this iteration, 0 on the happy path.
    # From the API usage block. Zero on an uncached call, and zero on the
    # intent-classifier iteration, which is reconstructed from an estimate
    # rather than read from a response and so has no usage block at all.
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    retry_wait_ms: int = 0  # Time spent sleeping between those attempts.
    # duration_ms includes retry_wait_ms: the sleeps happen inside the
    # client.create call that Conversation times. Subtract to get the
    # real model latency, or a retried iteration reads as a slow one.


def cache_tokens(usage: Any) -> tuple[int, int]:
    """Cache creation and read counts from an API usage block.

    Neither field can be read directly. They are absent on responses from
    an SDK predating prompt caching, and None rather than 0 on a call
    that used no cache, so `int(usage.cache_read_input_tokens)` raises on
    exactly the path that is currently the only path.

    Returned as a pair because recording one without the other says
    nothing: a read of zero means a miss only if a creation is non-zero,
    and means caching is off if both are.
    """
    created = getattr(usage, "cache_creation_input_tokens", None)
    read = getattr(usage, "cache_read_input_tokens", None)
    return int(created or 0), int(read or 0)


@dataclass
class TurnTrace:
    """Complete record of a single send() call.

    Mutable because the loop appends iterations and tool calls as it
    progresses. Stage 5 extensions are additive — every Stage 3
    field is preserved.
    """

    user_message: str
    final_text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    iterations: list[IterationUsage] = field(default_factory=list)
    stop_reason: str | None = None
    iteration_count: int = 0
    truncated: bool = False
    was_refusal: bool = False  # Set post-hoc by the loop.
    context_summarised: bool = False  # True if the soft budget guard fired.

    @property
    def total_input_tokens(self) -> int:
        return sum(it.input_tokens for it in self.iterations)

    @property
    def total_output_tokens(self) -> int:
        return sum(it.output_tokens for it in self.iterations)

    @property
    def model_configs_used(self) -> list[str]:
        """Ordered list of task_type values, useful for the CLI summary."""
        return [it.task_type for it in self.iterations]

    @property
    def total_cost_usd(self) -> float:
        """Stage-7: sum cost across iterations."""
        return sum(i.cost_usd for i in self.iterations)

    @property
    def total_retries(self) -> int:
        """Block 3: retry attempts across the turn.

        Non-zero means the API pushed back somewhere in this turn.
        Per-iteration counts say where.
        """
        return sum(i.retries for i in self.iterations)