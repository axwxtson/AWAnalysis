"""Emit hooks for the AW Analysis agent and eval harness.

Public API:
  - `turn(...)` context manager — starts a root span; yields a Turn handle.
  - `classifier(turn, plan, usage)` — records the decomposition call.
  - `sub_query(turn, intent, text, index)` context manager — sub-query span.
  - `iteration(parent, usage, text_in, text_out)` — generation observation.
  - `tool_call(parent, tool_call)` — tool span observation.
  - `synthesis(turn, usage, text_in, text_out)` — synthesis generation.
  - `finalise(turn, final_text, trace)` — set output + total attrs on root.
  - `score(turn, name, value, comment)` — attach a Langfuse score.

Every function is a no-op if `is_enabled()` returns False.  The
no-op path returns `None` for non-context-manager calls and a
null-handle for context managers, so call sites do not need to
guard each emit.

The handles (`Turn`, `SubQuery`) are intentionally opaque: call
sites pass them back into emitter functions but never inspect
them.  Internally they wrap the Langfuse observation object;
when observability is disabled they wrap None.
"""
from __future__ import annotations

import contextlib
import uuid
from dataclasses import dataclass
from typing import Any, Iterator

from aw_analysis.obs import attributes as A
from aw_analysis.obs.client import get_langfuse_client, is_enabled


# ── Opaque handles ──────────────────────────────────────────────────


@dataclass
class Turn:
    """Opaque handle for a turn-level trace.

    Call sites should treat this as a token to pass back into
    emitter functions, not as an inspectable object.
    """
    span: Any | None  # The active Langfuse root span, or None if disabled.
    conversation_id: str
    prompt_version: str


@dataclass
class SubQuery:
    """Opaque handle for a sub-query span."""
    span: Any | None


# ── Internal helpers ────────────────────────────────────────────────


def _now_ms_from_duration(duration_ms: int | float | None) -> float | None:
    """Pass-through with type normalisation.  Kept as a function so
    later changes to time semantics live in one place."""
    if duration_ms is None:
        return None
    return float(duration_ms)


def _safe_update(observation: Any | None, **kwargs: Any) -> None:
    """Call `.update(**kwargs)` on an observation if it exists.

    Tolerates `None` (observability disabled) and unexpected
    kwargs by catching exceptions and silently dropping them.
    Rationale: an emit failure must NEVER bring down the agent.
    Failed emits are visible in Langfuse SDK debug logs.
    """
    if observation is None:
        return
    try:
        observation.update(**kwargs)
    except Exception:  # noqa: BLE001 — observability must not raise
        # The Langfuse SDK has its own debug logging; we silently
        # absorb here to keep the agent's critical path clean.
        pass


# ── Top-level turn ──────────────────────────────────────────────────


@contextlib.contextmanager
def turn(
    *,
    user_message: str,
    interface: str,
    prompt_version: str,
    conversation_id: str | None = None,
    query_class: str | None = None,
    eval_case_id: str | None = None,
    eval_run_id: str | None = None,
) -> Iterator[Turn]:
    """Open a root span for one turn of the agent.

    Yields a `Turn` handle to be passed into nested emit calls.
    The root span is closed on exit; on exception, the exception
    is recorded and re-raised.

    `interface` is "cli" for interactive runs, "eval" for harness
    runs.  `conversation_id` becomes the Langfuse session ID so
    multi-turn conversations group correctly in the UI.
    """
    cid = conversation_id or f"conv-{uuid.uuid4().hex[:12]}"

    if not is_enabled():
        # Yield a null handle so call sites are unconditional.
        yield Turn(span=None, conversation_id=cid, prompt_version=prompt_version)
        return

    client = get_langfuse_client()
    assert client is not None  # is_enabled() guards this

    tags = [A.tag_prompt_version(prompt_version), A.tag_interface(interface)]
    if eval_run_id:
        tags.append(f"run:{eval_run_id}")

    metadata: dict[str, Any] = {
        A.PROMPT_VERSION: prompt_version,
        A.INTERFACE: interface,
        A.CONVERSATION_ID: cid,
    }
    if query_class:
        metadata[A.QUERY_CLASS] = query_class
    if eval_case_id:
        metadata[A.EVAL_CASE_ID] = eval_case_id
    if eval_run_id:
        metadata[A.EVAL_RUN_ID] = eval_run_id

    # `start_as_current_observation` puts the span into OTEL
    # context, so nested generations created via `start_generation`
    # automatically attach to it.  See Langfuse v3 docs:
    # https://langfuse.com/docs/observability/sdk/instrumentation
    with client.start_as_current_observation(
        as_type="span",
        name="aw_analysis.turn",
        input={"user_message": user_message},
        metadata=metadata,
    ) as root_span:
        # Apply tags + session id at the trace level (these
        # propagate to the trace, not just the root observation).
        try:
            client.update_current_trace(
                session_id=cid,
                tags=tags,
                input={"user_message": user_message},
            )
        except Exception:  # noqa: BLE001
            pass

        handle = Turn(span=root_span, conversation_id=cid,
                      prompt_version=prompt_version)
        try:
            yield handle
        except Exception as exc:  # propagate after recording
            _safe_update(
                root_span,
                output={"error": f"{type(exc).__name__}: {exc}"},
                level="ERROR",
                status_message=str(exc),
            )
            raise


def finalise(
    turn: Turn,
    *,
    final_text: str,
    total_cost_usd: float,
    total_duration_ms: float,
    safety_net_fired: bool,
    decomposition_fallback_reason: str | None,
) -> None:
    """Populate the root span's output + aggregate attributes.

    Must be called inside the `turn(...)` context manager.  Idempotent
    by design: a second call overwrites the output, which is the
    correct behaviour if a caller wants to refine the final text.
    """
    if turn.span is None:
        return
    metadata: dict[str, Any] = {
        A.TOTAL_COST_USD: total_cost_usd,
        A.TOTAL_DURATION_MS: total_duration_ms,
        A.SAFETY_NET_FIRED: safety_net_fired,
    }
    if decomposition_fallback_reason is not None:
        metadata[A.DECOMPOSITION_FALLBACK_REASON] = decomposition_fallback_reason
    _safe_update(turn.span, output={"final_text": final_text}, metadata=metadata)

    # Also push the final text to the trace itself so the trace
    # input/output columns in the Langfuse UI are populated.
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.update_current_trace(output={"final_text": final_text})
    except Exception:  # noqa: BLE001
        pass


# ── Classifier (decomposer call) ────────────────────────────────────


def classifier(
    turn: Turn,
    *,
    plan_intents: list[str],
    plan_texts: list[str],
    usage: Any,  # IterationUsage; typed loosely to avoid import cycle
) -> None:
    """Emit one span + one generation for the classifier call.

    The span carries the decomposition plan as structured output;
    the generation carries the LLM call's token + cost detail.
    """
    if turn.span is None:
        return
    client = get_langfuse_client()
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            as_type="span",
            name="decomposer.classify",
            input={"user_message": getattr(usage, "input_text", None)},
            output={"intents": plan_intents, "texts": plan_texts},
            metadata={A.TASK_TYPE: "intent_classification"},
        ):
            _emit_iteration_generation(
                client,
                name="classifier-llm-call",
                usage=usage,
                text_in=getattr(usage, "input_text", None),
                text_out=getattr(usage, "output_text", None),
            )
    except Exception:  # noqa: BLE001
        pass


# ── Sub-query ───────────────────────────────────────────────────────


@contextlib.contextmanager
def sub_query(
    turn: Turn,
    *,
    intent: str,
    text: str,
    index: int,
) -> Iterator[SubQuery]:
    """Open a span for one sub-query.

    Inside the block, callers emit iterations (LLM calls) and tool
    calls via `iteration(...)` and `tool_call(...)`.  The span is
    automatically the active OTEL parent, so those calls don't
    need to be passed the sub-query span explicitly — but we do
    pass the handle for symmetry and to make the emit graph
    grep-able.
    """
    if turn.span is None:
        yield SubQuery(span=None)
        return
    client = get_langfuse_client()
    if client is None:
        yield SubQuery(span=None)
        return
    try:
        with client.start_as_current_observation(
            as_type="span",
            name=f"sub_query[{index}]",
            input={"text": text},
            metadata={
                A.SUB_QUERY_INTENT: intent,
                A.SUB_QUERY_TEXT: text,
                A.SUB_QUERY_INDEX: index,
            },
        ) as sq_span:
            yield SubQuery(span=sq_span)
    except Exception:  # noqa: BLE001
        yield SubQuery(span=None)


# ── Iteration (LLM call inside the agent loop) ──────────────────────


def iteration(
    parent: SubQuery | Turn,
    *,
    usage: Any,  # IterationUsage
    text_in: str | None = None,
    text_out: str | None = None,
) -> None:
    """Record one IterationUsage as a Langfuse generation observation."""
    if parent.span is None:
        return
    client = get_langfuse_client()
    if client is None:
        return
    try:
        _emit_iteration_generation(
            client,
            name=f"iteration:{usage.task_type}",
            usage=usage,
            text_in=text_in,
            text_out=text_out,
        )
    except Exception:  # noqa: BLE001
        pass


def _emit_iteration_generation(
    client: Any,
    *,
    name: str,
    usage: Any,
    text_in: str | None,
    text_out: str | None,
) -> None:
    """Shared implementation for classifier + iteration + synthesis.

    Each call to this function opens a single generation
    observation, populates it with the IterationUsage data, and
    ends it.  Langfuse's cost + token dashboards read directly off
    the standardised attributes set here.
    """
    metadata = {
        A.TASK_TYPE: usage.task_type,
        A.MODEL_NAME: usage.model,
        A.MODEL_TEMPERATURE: usage.temperature,
        A.MODEL_MAX_TOKENS: usage.max_tokens,
        A.STOP_REASON: usage.stop_reason,
        A.RATIONALE: usage.rationale,
        A.DURATION_MS: _now_ms_from_duration(getattr(usage, "duration_ms", None)),
    }
    usage_details = {
        "input": usage.input_tokens,
        "output": usage.output_tokens,
        "total": usage.input_tokens + usage.output_tokens,
    }
    cost_details = {
        "total": float(getattr(usage, "cost_usd", 0.0) or 0.0),
    }
    with client.start_as_current_observation(
        as_type="generation",
        name=name,
        input=text_in,
        output=text_out,
        model=usage.model,
        usage_details=usage_details,
        cost_details=cost_details,
        metadata=metadata,
    ):
        # No body — the context manager closes the generation on
        # exit and Langfuse computes start/end times automatically.
        pass


# ── Tool call ───────────────────────────────────────────────────────


def tool_call(parent: SubQuery | Turn, *, tool_call_obj: Any) -> None:
    """Record one ToolCall as a Langfuse span observation.

    `tool_call_obj` is the existing `ToolCall` dataclass from
    `aw_analysis.agent.trace` — passed by reference so this module
    stays decoupled from the trace's internal layout.  We only
    read public fields.
    """
    if parent.span is None:
        return
    client = get_langfuse_client()
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            as_type="span",
            name=f"tool:{tool_call_obj.name}",
            input={"args": getattr(tool_call_obj, "args", None)},
            output={"result": getattr(tool_call_obj, "result", None)},
            metadata={
                A.TOOL_NAME: tool_call_obj.name,
                A.TOOL_SUCCESS: tool_call_obj.success,
                A.TOOL_ERROR_TAG: getattr(tool_call_obj, "error", None),
                A.TOOL_DURATION_MS: tool_call_obj.duration_ms,
            },
            level="ERROR" if not tool_call_obj.success else "DEFAULT",
        ):
            pass
    except Exception:  # noqa: BLE001
        pass


# ── Synthesis (final composition call in multi-intent turns) ────────


def synthesis(
    turn: Turn,
    *,
    usage: Any,
    text_in: str | None = None,
    text_out: str | None = None,
) -> None:
    """Emit the synthesis-call generation, parented to the turn."""
    if turn.span is None:
        return
    client = get_langfuse_client()
    if client is None:
        return
    try:
        with client.start_as_current_observation(
            as_type="span",
            name="synthesis",
            metadata={A.TASK_TYPE: "final_synthesis"},
        ):
            _emit_iteration_generation(
                client,
                name="synthesis-llm-call",
                usage=usage,
                text_in=text_in,
                text_out=text_out,
            )
    except Exception:  # noqa: BLE001
        pass


# ── Scores (eval integration) ───────────────────────────────────────


def score(
    turn: Turn,
    *,
    name: str,
    value: float,
    comment: str | None = None,
) -> None:
    """Attach a Langfuse score to the turn's trace.

    Used by the eval runner to record per-case grading outcomes.
    Score names follow the convention `assertion.<id>` for
    deterministic checks, `judge.<dimension>` for LLM-judge
    dimensions, and `case.passed` for the overall outcome.
    """
    if turn.span is None:
        return
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.score_current_trace(name=name, value=value, comment=comment)
    except Exception:  # noqa: BLE001
        pass