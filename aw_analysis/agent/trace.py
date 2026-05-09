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


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation inside a turn.

    Unchanged from Stage 3; included here for context.
    """

    name: str
    duration_ms: float
    success: bool
    error: str | None = None


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