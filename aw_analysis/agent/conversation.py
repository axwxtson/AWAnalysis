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

from aw_analysis.agent.recency import (
    SAFETY_NET_MESSAGE,
    has_recency_cue,
    looks_like_news_fabrication,
)


# Refusal-pattern detection. We don't try to be smart here; we look
# for the lead-in phrases the prompt uses. False negatives are fine
# (the trace just says it wasn't a refusal); false positives would
# be misleading, so the patterns are deliberately narrow.
_REFUSAL_PATTERNS = (
    # Speculation refusals (existing).
    re.compile(r"\bI can(?:'t| not)\s+predict\b", re.IGNORECASE),
    re.compile(r"\bI can(?:'t| not)\s+speculate\b", re.IGNORECASE),
    re.compile(r"\bthat'?s speculation\b", re.IGNORECASE),
    re.compile(r"\bI don'?t make (?:price )?predictions\b", re.IGNORECASE),
    re.compile(r"\bI can only analyse\b", re.IGNORECASE),
    # Stage 6: widened after the first eval surfaced false negatives.
    # Module 6 Ex 6.1 finding applied — pattern matching was missing
    # actual refusals because the prompt's idioms had drifted from
    # the original pattern set. The widened set is intent-shaped
    # rather than string-shaped.
    # Advice/recommendation refusals.
    re.compile(
        r"\bI can(?:'t| not)\s+(?:make|provide|give)\s+"
        r"(?:[\w\s-]{0,40})\s*(?:recommendations|advice)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bspeculative advice\b", re.IGNORECASE),
    # Scope refusals (asset class out of remit).
    re.compile(r"\bI (?:don'?t|do not) cover\s+\w+\b", re.IGNORECASE),
    re.compile(r"\bonly cryptocurrencies\b", re.IGNORECASE),
    re.compile(r"\bcrypto-only\b", re.IGNORECASE),
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
            # Stage 6 v2.2.2 follow-up: pass the query through so the loop
              # can apply recency-cue enforcement and post-hoc safety check.
            self._run_loop(trace, user_query=user_message)
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

    def _run_loop(self, trace: TurnTrace, user_query: str = "") -> None:
        """The core agent loop. Threads iterations onto the trace."""
        # Stage 6 v2.2.2 follow-up: programmatic recency-cue enforcement.
        # Three layers of prompt engineering failed to make the model
        # reliably call web_search on compound queries. The model treats
        # profile data as "enough" and short-circuits the news call,
        # fabricating confident news content from training data. The fix
        # is a per-turn reminder injected as a system-side message — the
        # model finds it much harder to ignore than a system-prompt rule
        # set at session start.
        if user_query and has_recency_cue(user_query):
            self._messages.append(
                {
                    "role": "user",
                    "content": (
                        "[SYSTEM REMINDER, NOT FROM USER] This query contains "
                        "a recency cue (news / latest / today / recent / "
                        "current / what happened / breaking / this week). "
                        "You MUST call web_search before completing this "
                        "turn. Do not synthesise news content from training "
                        "data — your training cutoff means you don't know "
                        "what's happened recently. If you cannot call "
                        "web_search for any reason, say so explicitly "
                        "rather than inventing news content."
                    ),
                }
            )
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
            # Stage 6: capture server-tool calls from the response.
            self._capture_server_tool_calls(response.content, trace)
            self._capture_citations(response.content, trace)


            if response.stop_reason in ("end_turn", "stop_sequence"):
                trace.final_text = self._extract_text(response.content)
                trace.stop_reason = str(response.stop_reason)

                # Refusal classification is post-hoc on iteration 0.
                if iteration_index == 0 and _looks_like_refusal(
                    trace.final_text
                ):
                    trace.was_refusal = True

                # Stage 6 v2.2.2 follow-up: safety net for the recency-cue
                # short-circuit. If the query needed web_search AND web_search
                # didn't fire AND the synthesis output looks news-shaped, the
                # model has fabricated. Replace the answer with an honest refusal
                # rather than ship invented news.
                if user_query and has_recency_cue(user_query):
                    web_search_fired = any(
                        tc.name == "web_search" for tc in trace.tool_calls
                    )
                    if not web_search_fired and looks_like_news_fabrication(
                        trace.final_text
                    ):
                        trace.final_text = SAFETY_NET_MESSAGE
                        trace.stop_reason = "safety_net_fabrication"

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
                    result=tool_result.content,
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

    def _capture_server_tool_calls(
        self, content: list[Any], trace: TurnTrace
    ) -> None:
        """Record server-side tool calls onto the trace.

        Server tools (web_search, code_execution, etc.) execute on
        Anthropic's infrastructure, not in our agent loop. They appear in
        the response as pairs of content blocks: a `server_tool_use` block
        (what the model asked for) followed by a `web_search_tool_result`
        block (what came back). We don't dispatch them — they've already
        run — but the eval harness asserts against `trace.tool_calls`, so
        they need to be recorded there alongside client-tool calls.

        Stage 6: added when the eval harness surfaced that news cases
        appeared to make no tool calls. The model was calling web_search
        correctly; the trace just wasn't capturing it.
        """
        pending_server_use: Any | None = None
        for block in content:
            block_type = getattr(block, "type", None)
            if block_type == "server_tool_use":
                pending_server_use = block
            elif block_type == "web_search_tool_result" and pending_server_use is not None:
                # The pairing: this result corresponds to the most recent
                # server_tool_use we saw. Anthropic emits them in pairs
                # adjacent in the content array.
                result_payload = self._render_server_tool_result(block)
                trace.tool_calls.append(
                    ToolCall(
                        name=getattr(pending_server_use, "name", "web_search"),
                        duration_ms=0.0,  # server-executed; we don't measure latency here
                        success=True,
                        error=None,
                        result=result_payload,
                    )
                )
                pending_server_use = None


    def _capture_citations(
        self, content: list[Any], trace: TurnTrace
    ) -> None:
        """Record citation snippets attached to assistant text blocks.

        When server tools (web_search) run, the model surfaces evidence
        for each claim as `citation` objects on each text block, each
        carrying a `cited_text` snippet. These snippets are the closest
        thing user-side code gets to the underlying search content; the
        raw search results themselves return only titles, URLs, and
        encrypted blobs.

        Stage 6 finding: the eval's faithfulness judge needs grounding
        text to grade against. Web search results are encrypted server-
        side; citations are the visible substitute.

        We collect every unique (cited_text, url) pair across all text
        blocks and attach the rendered list to the most recent web_search
        ToolCall on the trace. This makes the citations available to the
        judge via the same `result` field the judge already reads.
        """
        seen: set[tuple[str, str]] = set()
        snippets: list[tuple[str, str, str]] = []  # (cited_text, title, url)
        for block in content:
            if getattr(block, "type", None) != "text":
                continue
            citations = getattr(block, "citations", None) or []
            for cit in citations:
                cited = (getattr(cit, "cited_text", "") or "").strip()
                url = getattr(cit, "url", "") or ""
                title = getattr(cit, "title", "") or ""
                if not cited or (cited, url) in seen:
                    continue
                seen.add((cited, url))
                snippets.append((cited, title, url))

        if not snippets:
            return

        # Find the most recent web_search ToolCall on the trace and extend
        # its result with the citation list. If there isn't one (e.g. the
        # model chose to answer without searching), do nothing — there's
        # no tool result to ground citations against.
        for tc in reversed(trace.tool_calls):
            if tc.name == "web_search":
                citation_block = self._render_citations(snippets)
                # ToolCall is frozen; replace it with an updated copy.
                updated = ToolCall(
                    name=tc.name,
                    duration_ms=tc.duration_ms,
                    success=tc.success,
                    error=tc.error,
                    result=f"{tc.result}\n\n--- Cited snippets ---\n{citation_block}",
                )
                idx = trace.tool_calls.index(tc)
                trace.tool_calls[idx] = updated
                return

    @staticmethod
    def _render_citations(
        snippets: list[tuple[str, str, str]]
    ) -> str:
        """Render the citation list as readable grounding context."""
        lines: list[str] = []
        for cited, title, url in snippets:
            source = f"{title} ({url})" if title else url
            lines.append(f"[{source}] {cited}")
        return "\n".join(lines)            

    @staticmethod
    def _render_server_tool_result(block: Any) -> str:
        """Compact rendering of a web_search_tool_result block for the trace.

        Each result item has title, url, and a content text excerpt. The
        judge's faithfulness rubric grades against this string as the
        tool's grounding context — so capture the excerpts, not just the
        URLs. URLs alone make every factual claim look ungrounded.

        Stage 6 finding: the first version of this rendering only captured
        title + url. That was insufficient grounding context; the judge
        correctly marked news answers down for claims that were actually
        supported by the search excerpts but invisible to the trace.

        On any unexpected shape, fall back to repr(block) so the trace is
        never empty.
        """
        try:
            items = getattr(block, "content", None) or []
            lines: list[str] = []
            for item in items:
                title = getattr(item, "title", "") or ""
                url = getattr(item, "url", "") or ""
                # The text excerpt the API returns. Field name varies by
                # SDK version: try `encrypted_content` first (newer SDKs
                # return cipher-wrapped excerpts), then `content` for the
                # plain-text variant. Fall back to empty string.
                excerpt = (
                    getattr(item, "encrypted_content", None)
                    or getattr(item, "content", None)
                    or ""
                )
                # If content is a list of blocks (newer SDKs), join their
                # text. If it's a string, use as-is.
                if isinstance(excerpt, list):
                    excerpt = " ".join(
                        getattr(b, "text", str(b)) for b in excerpt
                    )
                header = f"{title} ({url})" if title else url
                lines.append(f"{header}: {excerpt}" if excerpt else header)
            return "\n".join(lines) if lines else repr(block)
        except Exception:
            return repr(block)

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        """Concatenate text blocks from a model response."""
        parts: list[str] = []
        for block in content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "".join(parts)