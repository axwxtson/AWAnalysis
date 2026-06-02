"""OrchestratedConversation.

Wrapping class that owns one Conversation and a Decomposer. The user-
facing entry point in Stage 7. Public surface mirrors Conversation
(send, history, traces, reset) so call sites in cli/main.py and the
eval runner change minimally.

Design:
- Decomposition runs as a pre-flight pass on the user message.
- Single-intent plans take the fast path: delegate directly to the
  wrapped Conversation. No synthesis step needed.
- Multi-intent plans run each sub-query through the same Conversation
  instance — this preserves cross-sub-query context implicitly (each
  sub-query sees what the previous ones found). Sequential, not
  parallel: simpler error handling, and on the AW Analysis golden
  dataset there are never more than 3 sub-queries per turn.
- After all sub-queries return, a FINAL_SYNTHESIS call composes a
  single user-facing answer from the sub-trace final_texts. The
  synthesis call is Sonnet (Stage 5 default for FINAL_SYNTHESIS).
- Decomposer failure (API error, malformed JSON) → fall back to
  running the original user message through the wrapped Conversation.
  decomposition_fallback_reason is recorded on the OrchestratedTurnTrace.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from aw_analysis.agent.conversation import Conversation
from aw_analysis.agent.decomposer import (
    Decomposer,
    DecomposerError,
    Intent,
    QueryPlan,
    SubQuery,
)
from aw_analysis.agent.trace import IterationUsage, TurnTrace
from aw_analysis.client.anthropic_client import AnthropicClient
from aw_analysis.config import TaskType, cost_for, get_model_config
from aw_analysis.obs import emitter as obs
import uuid
from aw_analysis.prompts.versions import ACTIVE_PROMPT_VERSION


# Per-intent routing override for the TOOL_SELECTION model. The
# wrapping Conversation continues to call get_model_config(TOOL_SELECTION)
# internally — we don't intercept that call. Instead, before running a
# sub-query, we (a) decide which intent it is, (b) swap the registry's
# TOOL_SELECTION entry to the routed config for the duration of that
# sub-query, (c) swap it back.
#
# This keeps the Conversation class entirely unchanged and makes the
# routing decision a single, localised, well-tested boundary.
ROUTING_OVERRIDES: dict[Intent, TaskType] = {
    Intent.PRICE: TaskType.TOOL_SELECTION,  # rule: route price-only sub-queries
    Intent.PROFILE: TaskType.TOOL_SELECTION,
    Intent.NEWS: TaskType.TOOL_SELECTION,
}


# Note: ROUTING_OVERRIDES as defined above does NOT yet route price
# sub-queries to Haiku — it returns the default TOOL_SELECTION (Sonnet).
# The actual override of model is done via a parallel registry below.
# Keeping this two-table structure makes "what gets routed where"
# extremely explicit in code review.
#
# Per-intent ModelConfig override for sub-query tool selection.
# If the entry is None, use the default get_model_config(TOOL_SELECTION).
# If the entry is a ModelConfig, use it for that intent's sub-query
# instead.
from aw_analysis.config import ModelConfig
from aw_analysis.config.model_pricing import HAIKU_MODEL

_HAIKU_TOOL_SELECTION = ModelConfig(
    model=HAIKU_MODEL,
    temperature=0.2,
    max_tokens=1024,
    rationale=(
        "Stage 7 routing: price-only sub-queries are deterministic tool "
        "calls; Haiku at temp 0.2 is sufficient and ~3x cheaper"
    ),
)

INTENT_TO_TOOL_SELECTION_CONFIG: dict[Intent, ModelConfig | None] = {
    Intent.PRICE: _HAIKU_TOOL_SELECTION,
    Intent.PROFILE: None,  # keep Sonnet — curated/fallback branch needs prose
    Intent.NEWS: None,     # keep Sonnet — web_search synthesis quality
}


SYNTHESIS_SYSTEM_PROMPT = """\
You are composing one user-facing answer from a set of partial
answers that were produced separately for sub-queries of the user's
original question.

You will be given:
- The user's original question.
- A list of (intent, partial_answer) pairs, one per sub-query.

Your job: produce ONE coherent answer that combines the partial
answers into a single response. Do not invent content. Do not add
sources or citations that aren't already in the partial answers.
Preserve any refusal language from any partial answer that refused —
if even one sub-query was refused, the user must see that refusal in
the final answer rather than have it elided.

Be concise. Lead with the price if a price sub-query is present.
Maintain inline citations from the news sub-query verbatim. British
English.
"""

def _current_trace_id() -> str | None:
    """Return the current Langfuse trace ID, or None if disabled.

    Module-level helper.  Called from inside OrchestratedConversation.send
    while the obs.turn() context is still active.  Outside that context
    the OTEL stack has popped and this returns either None or the
    previous turn's id, so placement of the call matters.
    """
    from aw_analysis.obs.client import get_langfuse_client
    client = get_langfuse_client()
    if client is None:
        return None
    try:
        return client.get_current_trace_id()
    except Exception:  # noqa: BLE001
        return None


class OrchestratedConversation:
    ...

@dataclass
class OrchestratedTurnTrace:
    """One user-facing turn that may have run multiple agent turns.

    The eval runner reads this. Existing per-turn assertions (e.g.
    tool_called(web_search)) are evaluated against the flattened
    tool_calls property.
    """

    user_message: str
    final_text: str
    decomposition_plan: QueryPlan | None
    sub_traces: list[TurnTrace] = field(default_factory=list)
    synthesis_iteration: IterationUsage | None = None
    classifier_iteration: IterationUsage | None = None
    decomposition_fallback_reason: str | None = None
    langfuse_trace_id: str | None = None  # Stage 8

    @property
    def tool_calls(self) -> list[Any]:
        """Flattened tool calls across all sub-traces.

        Existing eval assertions like tool_called(web_search) check this.
        """
        flat: list[Any] = []
        for t in self.sub_traces:
            flat.extend(t.tool_calls)
        return flat

    @property
    def iterations(self) -> list[IterationUsage]:
        """Flattened iterations across classifier + sub-traces + synthesis."""
        flat: list[IterationUsage] = []
        if self.classifier_iteration is not None:
            flat.append(self.classifier_iteration)
        for t in self.sub_traces:
            flat.extend(t.iterations)
        if self.synthesis_iteration is not None:
            flat.append(self.synthesis_iteration)
        return flat

    @property
    def total_input_tokens(self) -> int:
        return sum(i.input_tokens for i in self.iterations)

    @property
    def total_output_tokens(self) -> int:
        return sum(i.output_tokens for i in self.iterations)

    @property
    def total_cost_usd(self) -> float:
        return sum(i.cost_usd for i in self.iterations)

    @property
    def total_duration_ms(self) -> int:
        """Sum of duration_ms across classifier + sub-traces + synthesis."""
        return sum(i.duration_ms or 0 for i in self.iterations)

    @property
    def was_refusal(self) -> bool:
        """A user-facing turn is a refusal if any sub-trace refused."""
        return any(t.was_refusal for t in self.sub_traces)

    @property
    def safety_net_fired(self) -> bool:
        """Did the Stage-6 safety net fire on any sub-trace?

        After Stage 7, this should rarely be True. Useful as a regression
        signal in the eval JSON.
        """
        return any(
            t.stop_reason == "safety_net_fabrication" for t in self.sub_traces
        )


class OrchestratedConversation:
    """User-facing conversation entry point for Stage 7.

    Owns a Decomposer and a Conversation. send() returns an
    OrchestratedTurnTrace. Public surface deliberately mirrors
    Conversation so the CLI and eval runner change minimally.
    """

    def __init__(
        self,
        client: AnthropicClient,
        conversation: Conversation,
        decomposer: Decomposer | None = None,
        *,
        interface: str = "cli",
        conversation_id: str | None = None,
    ) -> None:
        self._client = client
        self._conversation = conversation
        self._decomposer = decomposer or Decomposer(client)
        self._traces: list[OrchestratedTurnTrace] = []
        self._interface_label = interface
        self._conversation_id = conversation_id or f"conv-{uuid.uuid4().hex[:12]}"

    # ---- public surface mirroring Conversation -------------------------

    def send(self, user_message: str) -> OrchestratedTurnTrace:
        """Decompose, route per sub-query, synthesise, record.

        Stage 8: emits the full trace hierarchy to Langfuse via
        `aw_analysis.obs`.  Behaviour is otherwise identical to Stage 7.
        """
        with obs.turn(
            user_message=user_message,
            interface=self._interface_label,
            prompt_version=ACTIVE_PROMPT_VERSION,
            conversation_id=self._conversation_id,
        ) as _obs_turn:

            # 1. Classify.  Fall back on any failure.
            plan: QueryPlan | None = None
            classifier_iteration: IterationUsage | None = None
            fallback_reason: str | None = None
            try:
                t0 = time.perf_counter()
                plan = self._decomposer.classify(user_message)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                classifier_iteration = self._classifier_iteration_record(
                    plan, elapsed_ms
                )
            except DecomposerError as exc:
                fallback_reason = f"decomposer_error: {exc}"

            # Emit the classifier span only when classification succeeded.
            # The fallback branch deliberately has no classifier observation —
            # the trace's decomposition_fallback_reason metadata is the signal.
            if plan is not None and classifier_iteration is not None:
                obs.classifier(
                    _obs_turn,
                    plan_intents=[sq.intent.value for sq in plan.sub_queries],
                    plan_texts=[sq.text for sq in plan.sub_queries],
                    usage=classifier_iteration,
                )

            # 2. Fallback path: no plan, run the original query through the
            #    full agent and return.  `_run_fallback` already builds the
            #    otrace and appends to self._traces; we emit iterations and
            #    tool calls directly under the turn (no sub_query span,
            #    because there was no decomposition).
            if plan is None:
                otrace = self._run_fallback(user_message, fallback_reason)
                if otrace.sub_traces:
                    inner = otrace.sub_traces[0]
                    for it in inner.iterations:
                        obs.iteration(_obs_turn, usage=it)
                    for tc in inner.tool_calls:
                        obs.tool_call(_obs_turn, tool_call_obj=tc)
                obs.finalise(
                    _obs_turn,
                    final_text=otrace.final_text,
                    total_cost_usd=otrace.total_cost_usd,
                    total_duration_ms=sum(i.duration_ms or 0 for i in otrace.iterations),
                    safety_net_fired=getattr(otrace, "safety_net_fired", False),
                    decomposition_fallback_reason=fallback_reason,
                )
                otrace.langfuse_trace_id = _current_trace_id()
                return otrace

            # 3. Single-intent fast path: one sub-query, no synthesis.
            if plan.is_single_intent:
                sq_obj = plan.sub_queries[0]
                with obs.sub_query(
                    _obs_turn,
                    intent=sq_obj.intent.value,
                    text=sq_obj.text,
                    index=0,
                ) as _obs_sq:
                    sub_trace = self._run_sub_query(sq_obj)
                    for it in sub_trace.iterations:
                        obs.iteration(_obs_sq, usage=it)
                    for tc in sub_trace.tool_calls:
                        obs.tool_call(_obs_sq, tool_call_obj=tc)

                otrace = OrchestratedTurnTrace(
                    user_message=user_message,
                    final_text=sub_trace.final_text,
                    decomposition_plan=plan,
                    sub_traces=[sub_trace],
                    classifier_iteration=classifier_iteration,
                    synthesis_iteration=None,
                    decomposition_fallback_reason=None,
                )
                obs.finalise(
                    _obs_turn,
                    final_text=otrace.final_text,
                    total_cost_usd=otrace.total_cost_usd,
                    total_duration_ms=sum(i.duration_ms or 0 for i in otrace.iterations),
                    safety_net_fired=getattr(otrace, "safety_net_fired", False),
                    decomposition_fallback_reason=None,
                )
                otrace.langfuse_trace_id = _current_trace_id()
                self._traces.append(otrace)
                return otrace

            # 4. Multi-intent: run each sub-query, then synthesise.
            sub_traces: list[TurnTrace] = []
            for index, sq_obj in enumerate(plan.sub_queries):
                with obs.sub_query(
                    _obs_turn,
                    intent=sq_obj.intent.value,
                    text=sq_obj.text,
                    index=index,
                ) as _obs_sq:
                    st = self._run_sub_query(sq_obj)
                    for it in st.iterations:
                        obs.iteration(_obs_sq, usage=it)
                    for tc in st.tool_calls:
                        obs.tool_call(_obs_sq, tool_call_obj=tc)
                    sub_traces.append(st)

            final_text, synthesis_iteration = self._synthesise(
                user_message, plan.sub_queries, sub_traces
            )
            obs.synthesis(
                _obs_turn,
                usage=synthesis_iteration,
                text_in=user_message,
                text_out=final_text,
            )

            otrace = OrchestratedTurnTrace(
                user_message=user_message,
                final_text=final_text,
                decomposition_plan=plan,
                sub_traces=sub_traces,
                classifier_iteration=classifier_iteration,
                synthesis_iteration=synthesis_iteration,
                decomposition_fallback_reason=None,
            )
            obs.finalise(
                _obs_turn,
                final_text=otrace.final_text,
                total_cost_usd=otrace.total_cost_usd,
                total_duration_ms=sum(i.duration_ms or 0 for i in otrace.iterations),
                safety_net_fired=getattr(otrace, "safety_net_fired", False),
                decomposition_fallback_reason=None,
            )
            otrace.langfuse_trace_id = _current_trace_id()
            self._traces.append(otrace)
            return otrace


    def history(self) -> list[dict[str, Any]]:
        return self._conversation.history()

    def traces(self) -> list[OrchestratedTurnTrace]:
        return list(self._traces)

    def reset(self) -> None:
        self._conversation.reset()
        self._traces.clear()

    # ---- internals ------------------------------------------------------

    def _classifier_iteration_record(
        self, plan: QueryPlan, elapsed_ms: int
    ) -> IterationUsage:
        """Build an IterationUsage for the classifier call.

        We don't have token counts on the plan object; the Decomposer
        could expose them but the simpler approach for Stage 7 is to
        estimate via the configured max_tokens for the classifier and
        count_tokens on the prompt. For trace accuracy this is good
        enough; the dominant cost terms are sub-query agent calls.
        """
        # Use count_tokens for input; output is bounded by classifier
        # max_tokens but the raw_response gives us a better estimate.
        config = get_model_config(TaskType.INTENT_CLASSIFICATION)
        try:
            input_tokens = self._client.count_tokens(
                model=config.model,
                messages=[{"role": "user", "content": plan.original_query}],
                system="",
            )
        except Exception:  # noqa: BLE001
            input_tokens = 0
        # Approximate output_tokens from raw_response length using the
        # ~4 chars/token rule. Module 5 Ex 5.1: this under-counts by
        # ~20% for dense numerical content, but the classifier output
        # is short JSON so the approximation is acceptable for cost
        # accounting at this granularity.
        output_tokens = max(1, len(plan.raw_response) // 4)
        return IterationUsage(
            task_type=TaskType.INTENT_CLASSIFICATION.value,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason="end_turn",
            rationale=config.rationale,
            duration_ms=elapsed_ms,
            cost_usd=cost_for(config.model, input_tokens, output_tokens),
        )

    def _run_sub_query(self, sub_query: SubQuery) -> TurnTrace:
        """Run one sub-query through the wrapped Conversation, with
        per-intent ModelConfig override applied for TOOL_SELECTION.

        The override is implemented by temporarily mutating the
        MODEL_CONFIG_REGISTRY entry for TOOL_SELECTION. The Conversation
        class itself stays unaware of routing. This is the simplest
        composition that doesn't require changing Conversation's
        interface.
        """
        override = INTENT_TO_TOOL_SELECTION_CONFIG.get(sub_query.intent)
        if override is None:
            return self._conversation.send(sub_query.text)

        # Apply temporary override for the duration of this sub-query.
        from aw_analysis.config.model_config import MODEL_CONFIG_REGISTRY

        previous = MODEL_CONFIG_REGISTRY[TaskType.TOOL_SELECTION]
        MODEL_CONFIG_REGISTRY[TaskType.TOOL_SELECTION] = override
        try:
            return self._conversation.send(sub_query.text)
        finally:
            MODEL_CONFIG_REGISTRY[TaskType.TOOL_SELECTION] = previous

    def _synthesise(
        self,
        user_message: str,
        sub_queries: list[SubQuery],
        sub_traces: list[TurnTrace],
    ) -> tuple[str, IterationUsage]:
        """Combine sub-trace final_texts into one user-facing answer."""
        config = get_model_config(TaskType.FINAL_SYNTHESIS)

        parts = []
        for sq, tr in zip(sub_queries, sub_traces, strict=True):
            parts.append(f"[{sq.intent.value}] {tr.final_text}")

        user_block = (
            f"Original user question: {user_message}\n\n"
            f"Partial answers (one per sub-query):\n\n"
            + "\n\n".join(parts)
        )

        t0 = time.perf_counter()
        response = self._client.create(
            config=config,
            system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_block}],
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        text = ""
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", "")
                break

        usage = response.usage
        iteration = IterationUsage(
            task_type=config.rationale and TaskType.FINAL_SYNTHESIS.value,
            model=config.model,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            stop_reason=response.stop_reason,
            rationale=config.rationale,
            duration_ms=elapsed_ms,
            cost_usd=cost_for(
                config.model, usage.input_tokens, usage.output_tokens
            ),
        )
        return text, iteration

    def _run_fallback(
        self, user_message: str, reason: str | None
    ) -> OrchestratedTurnTrace:
        """Decomposer failed; run the original query through the agent."""
        sub_trace = self._conversation.send(user_message)
        otrace = OrchestratedTurnTrace(
            user_message=user_message,
            final_text=sub_trace.final_text,
            decomposition_plan=None,
            sub_traces=[sub_trace],
            classifier_iteration=None,
            synthesis_iteration=None,
            decomposition_fallback_reason=reason,
        )
        self._traces.append(otrace)
        return otrace

 