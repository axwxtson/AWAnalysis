# aw_analysis/agent/conversation.py
"""Stateful agent conversation.

Stage 5 changes:
  - Each iteration of the agent loop picks a TaskType and looks up
    a ModelConfig before calling the model.
  - A soft context budget (default 100,000 tokens) is checked before
    each call; if the projected input would exceed it, old turns
    are summarised before proceeding.
  - Each iteration's usage is recorded in the TurnTrace.
  - Refusal turns are detected post-hoc (refusal-pattern text in the
    final response with stop_reason='end_turn' on iteration 0) and
    flagged on the trace.

British English throughout.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from aw_analysis.client.anthropic_client import AnthropicClient
from aw_analysis.config import (
    ModelConfig,
    TaskType,
    get_model_config,
)
from aw_analysis.agent.errors import TurnBudgetExceeded
from aw_analysis.agent.trace import IterationUsage, ToolCall, TurnTrace
from aw_analysis.tools.base import ToolRegistry, ToolResult


# Refusal-pattern detection. We don't try to be smart here; we look
# for the lead-in phrases the prompt uses. False negatives are fine
# (the trace just says it wasn't a refusal); false positives would
# be misleading, so the patterns are deliberately narrow.
_REFUSAL_PATTERNS = (
    re.compile(r"\bI can(?:'t| not)\s+predict\b", re.IGNORECASE),
    re.compile(r"\bI can(?:'t| not)\s+speculate\b", re.IGNORECASE),
    re.compile(r"\bthat'?s speculation\b", re.IGNORECASE),
    re.compile(r"\bI don'?t make (?:price )?predictions\b", re.IGNORECASE),
    re.compile(r"\bI can only analyse\b", re.IGNORECASE),
)


def _looks_like_refusal(text: str) -> bool:
    return any(p.search(text) for p in _REFUSAL_PATTERNS)


@dataclass
class Conversation:
    """A live, stateful agent conversation.

    Public methods are unchanged from Stage 3: send, history, traces,
    reset. The internal model-call path is what Stage 5 reshapes.
    """

    client: AnthropicClient
    tools: ToolRegistry
    system_prompt: str
    turn_budget: int = 10
    # Stage 5: soft context budget. When the *measured* input token
    # count of a planned call would exceed this, we summarise old
    # turns before making the call. The number is half of Sonnet's
    # 200k window — leaves room for tool definitions, tool results,
    # and a long synthesis response.
    context_budget_tokens: int = 100_000
    # Number of recent messages to preserve verbatim during
    # summarisation. Same shape as the Module 1 ConversationManager.
    recent_to_keep: int = 6

    _messages: list[dict[str, Any]] = field(default_factory=list, init=False)
    _traces: list[TurnTrace] = field(default_factory=list, init=False)

    # ---- Public API ---------------------------------------------------

    def send(self, user_message: str) -> TurnTrace:
        """Run the agent loop on one user message; return its trace."""
        self._messages.append({"role": "user", "content": user_message})
        trace = TurnTrace(user_message=user_message)
        self._traces.append(trace)

        try:
            self._run_loop(trace)
        except TurnBudgetExceeded:
            # Trace already has its iterations recorded; mark
            # truncated and re-raise so callers can decide what to do.
            trace.truncated = True
            raise

        return trace

    def history(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def traces(self) -> list[TurnTrace]:
        return list(self._traces)

    def reset(self) -> None:
        self._messages.clear()
        self._traces.clear()

    # ---- Internals ----------------------------------------------------

    def _run_loop(self, trace: TurnTrace) -> None:
        """The core agent loop. Threads iterations onto the trace."""
        for iteration_index in range(self.turn_budget):
            trace.iteration_count = iteration_index + 1

            # Pick TaskType for this iteration based on loop state.
            task_type = self._task_type_for_iteration(iteration_index)
            config = get_model_config(task_type)

            # Soft context budget check. Side-effect: may mutate
            # self._messages by summarising old ones.
            self._enforce_context_budget(config, trace)

            # The actual call.
            response = self.client.create(
                config=config,
                system=self.system_prompt,
                messages=self._messages,
                tools=self.tools.to_anthropic_params(),
            )

            # Record iteration usage on the trace before doing
            # anything else, so even if subsequent code raises we
            # have a record of what happened.
            trace.iterations.append(
                IterationUsage(
                    task_type=task_type.value,
                    model=config.model,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                    input_tokens=int(response.usage.input_tokens),
                    output_tokens=int(response.usage.output_tokens),
                    stop_reason=str(response.stop_reason),
                    rationale=config.rationale,
                )
            )

            # Add the assistant's response to the running message list.
            self._messages.append(
                {"role": "assistant", "content": response.content}
            )

            # Terminal stop reasons end the loop with the final text.
            if response.stop_reason in ("end_turn", "stop_sequence"):
                trace.final_text = self._extract_text(response.content)
                trace.stop_reason = str(response.stop_reason)

                # Refusal classification is post-hoc on iteration 0.
                if iteration_index == 0 and _looks_like_refusal(
                    trace.final_text
                ):
                    trace.was_refusal = True
                return

            # Otherwise we expect tool_use blocks; dispatch them.
            tool_results = self._dispatch_tools(response.content, trace)
            self._messages.append({"role": "user", "content": tool_results})

        # Loop exhausted without end_turn — turn budget exceeded.
        trace.stop_reason = "turn_budget_exceeded"
        raise TurnBudgetExceeded(
            f"Agent loop did not terminate within {self.turn_budget} iterations"
        )

    def _task_type_for_iteration(self, iteration_index: int) -> TaskType:
        """Map loop state to TaskType.

        Iteration 0: TOOL_SELECTION. The model is choosing whether/
            which tool to call given the user message.
        Iteration ≥ 1: FINAL_SYNTHESIS. The model has tool results
            in context and is producing a user-facing answer (or
            asking for another tool — that case still wants the
            synthesis config because temperature affects the
            assistant's prose either way).

        REFUSAL is not chosen here — see the post-hoc classification
        in _run_loop. CONTEXT_SUMMARISATION is used only inside
        _enforce_context_budget.
        """
        if iteration_index == 0:
            return TaskType.TOOL_SELECTION
        return TaskType.FINAL_SYNTHESIS

    def _enforce_context_budget(
        self, planned_config: ModelConfig, trace: TurnTrace
    ) -> None:
        """If the next call would exceed the soft budget, summarise.

        Counts tokens against the same model the call will use.
        Does nothing if we're under budget. If summarisation runs,
        flags the trace.
        """
        try:
            input_tokens = self.client.count_tokens(
                model=planned_config.model,
                system=self.system_prompt,
                messages=self._messages,
                tools=self.tools.to_anthropic_params(),
            )
        except Exception:
            # count_tokens is informational. If it fails for any
            # reason we proceed without summarisation rather than
            # failing the whole turn.
            return

        if input_tokens + planned_config.max_tokens <= self.context_budget_tokens:
            return

        # Over budget. Keep the last `recent_to_keep` messages plus
        # the most recent user message; summarise everything before.
        if len(self._messages) <= self.recent_to_keep + 1:
            # Not enough room to summarise meaningfully; let the
            # call proceed and hope for the best. The trace will
            # surface the problem.
            return

        recent = self._messages[-self.recent_to_keep :]
        old = self._messages[: -self.recent_to_keep]

        summary_text = self._summarise(old, trace)

        # Replace old messages with a single synthetic user/assistant
        # pair carrying the summary, then re-attach recent.
        self._messages = [
            {
                "role": "user",
                "content": f"[Conversation summary so far: {summary_text}]",
            },
            {
                "role": "assistant",
                "content": (
                    "Understood. I have the context from the earlier "
                    "part of our conversation."
                ),
            },
            *recent,
        ]
        trace.context_summarised = True

    def _summarise(
        self, messages_to_summarise: list[dict[str, Any]], trace: TurnTrace
    ) -> str:
        """Summarise old turns. Uses the CONTEXT_SUMMARISATION config.

        Recorded on the trace as an iteration so the cost is visible.
        """
        config = get_model_config(TaskType.CONTEXT_SUMMARISATION)
        # We don't pass the agent's tools or system prompt to the
        # summariser — its job is purely condensation.
        response = self.client.create(
            config=config,
            system=(
                "Summarise the following conversation concisely. Preserve "
                "key facts, decisions, named assets, and any unresolved "
                "questions. Do not add commentary."
            ),
            messages=messages_to_summarise,
        )
        text = self._extract_text(response.content)

        trace.iterations.append(
            IterationUsage(
                task_type=TaskType.CONTEXT_SUMMARISATION.value,
                model=config.model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                input_tokens=int(response.usage.input_tokens),
                output_tokens=int(response.usage.output_tokens),
                stop_reason=str(response.stop_reason),
                rationale=config.rationale,
            )
        )
        return text

    def _dispatch_tools(
        self, content: list[Any], trace: TurnTrace
    ) -> list[dict[str, Any]]:
        """Run every tool_use block and return tool_result blocks.

        Behaviour preserved from Stage 3 — each call produces a
        ToolResult, which is recorded as a ToolCall on the trace
        and returned to the model as a tool_result block.
        """
        results: list[dict[str, Any]] = []
        for block in content:
            if getattr(block, "type", None) != "tool_use":
                continue
            start = time.perf_counter()
            tool_result = self.tools.dispatch(block.name, block.input)
            duration_ms = (time.perf_counter() - start) * 1000.0

            trace.tool_calls.append(
                ToolCall(
                    name=block.name,
                    duration_ms=duration_ms,
                    success=tool_result.success,
                    error=tool_result.error,
                )
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": tool_result.content,
                    "is_error": not tool_result.success,
                }
            )
        return results

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        """Concatenate text blocks from a model response."""
        parts: list[str] = []
        for block in content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "".join(parts)