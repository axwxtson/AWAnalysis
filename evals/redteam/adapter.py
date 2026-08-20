"""Adapter from the production agent to the red-team grader's contract.

The grader reads a response dict with answer, tools_called,
output_tokens, tool_call_count and error. Production produces an
OrchestratedTurnTrace, which has no error field: failures arrive as
exceptions. This module is that translation, and nothing else.

Import direction is one way, as everywhere in evals/: this reads from
aw_analysis and aw_analysis never reads from here.
"""

from __future__ import annotations

from typing import Any

from aw_analysis.agent.conversation import Conversation
from aw_analysis.agent.errors import TurnBudgetExceeded
from aw_analysis.agent.orchestration import (
    OrchestratedConversation,
    OrchestratedTurnTrace,
)
from aw_analysis.client.anthropic_client import AnthropicClient
from aw_analysis.prompts.system import SYSTEM_PROMPT
from aw_analysis.prompts.versions import ACTIVE_PROMPT_VERSION
from aw_analysis.tools import default_registry
from evals.redteam.poison import (
    PLANTED_BY_ATTACK,
    PoisonedProfileTool,
    poisoned_registry,
)


def _stop_reasons(otrace: OrchestratedTurnTrace) -> list[str]:
    """Every stop reason in the turn: each sub-query, then synthesis.

    A fact, not a judgement. Which reasons disqualify a result is policy
    and lives in measured(), the same split as poison_delivered. A
    boolean here would freeze every committed artefact against whichever
    policy was current when it was written.
    """
    reasons: list[Any] = [t.stop_reason for t in otrace.sub_traces]
    if otrace.synthesis_iteration is not None:
        reasons.append(otrace.synthesis_iteration.stop_reason)
    return [str(r) for r in reasons if r]


def trace_to_response(otrace: OrchestratedTurnTrace) -> dict[str, Any]:
    """Map a completed turn onto the grader's response contract.

    Pure. tools_called keeps duplicates because the DoS rubric asks
    whether the same tool was called repeatedly, so collapsing to a set
    would destroy the signal it reads.

    output_tokens is the whole turn: classifier, sub-queries and
    synthesis. The replica had no decomposition layer, so this is a
    larger quantity than the one its 3000-token DoS threshold was set
    against. Kept as the total because the DoS threat is total
    consumption, but the DoS category is not like-for-like across the
    replica and production runs.
    """
    tool_calls = otrace.tool_calls
    return {
        "answer": otrace.final_text,
        "stop_reasons": _stop_reasons(otrace),
        "tools_called": [tc.name for tc in tool_calls],
        "tool_call_count": len(tool_calls),
        "output_tokens": otrace.total_output_tokens,
        "input_tokens": otrace.total_input_tokens,
        "error": None,
        "cost_usd": otrace.total_cost_usd,
        "prompt_version": ACTIVE_PROMPT_VERSION,
        "langfuse_trace_id": otrace.langfuse_trace_id,
    }


def _error_response(error: str, inner: Conversation) -> dict[str, Any]:
    """Build a response for a turn that raised.

    No OrchestratedTurnTrace exists on this path, but the inner
    Conversation recorded its iterations before the exception. Reading
    them back matters most for max_steps_exceeded, which is the DoS
    success case: reporting zero tokens for the run that burned the most
    would invert the finding.
    """
    traces = inner.traces()
    tool_calls = [tc for t in traces for tc in t.tool_calls]
    return {
        "answer": "",
        "stop_reasons": [str(t.stop_reason) for t in traces if t.stop_reason],
        "tools_called": [tc.name for tc in tool_calls],
        "tool_call_count": len(tool_calls),
        "output_tokens": sum(t.total_output_tokens for t in traces),
        "input_tokens": sum(t.total_input_tokens for t in traces),
        "error": error,
        "cost_usd": 0.0,
        "prompt_version": ACTIVE_PROMPT_VERSION,
        "langfuse_trace_id": None,
    }


def _build_agent(
    attack_id: str | None = None,
) -> tuple[OrchestratedConversation, Conversation, PoisonedProfileTool | None]:
    """Fresh agent per attack, with the profile tool poisoned if the
    attack plants a document.

    Reusing one conversation would carry each attack's messages into the
    next, so the run would stop being independent trials. The interface
    label separates red-team turns from CLI and eval traffic in Langfuse.
    """
    document_name = PLANTED_BY_ATTACK.get(attack_id or "")
    if document_name is None:
        tools, poison = default_registry(), None
    else:
        tools, poison = poisoned_registry(document_name)

    client = AnthropicClient()
    inner = Conversation(
        client=client,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )
    orchestrated = OrchestratedConversation(
        client=client,
        conversation=inner,
        interface="redteam",
    )
    return orchestrated, inner, poison


def run_against_attack(attack: dict, *, build=_build_agent) -> dict[str, Any]:
    """Run one attack payload through the production agent.

    build is injectable so the failure paths can be tested offline.
    """
    orchestrated, inner, poison = build(attack.get("id"))
    try:
        otrace = orchestrated.send(attack["payload"])
    except TurnBudgetExceeded:
        response = _error_response("max_steps_exceeded", inner)
    except Exception as exc:  # noqa: BLE001
        # One crashed attack must not end a run that has already paid for
        # the turns before it. Same argument as evals/runner/run.py.
        response = _error_response(f"{type(exc).__name__}: {exc}", inner)
    else:
        response = trace_to_response(otrace)

    # Three states, not two. None means this attack plants nothing.
    # False means it planted a document the model never retrieved, which
    # is a non-delivery and not a defence: production decomposes and
    # routes, so a document attack can complete without the poison ever
    # reaching the model. Counting that as defended would inflate the
    # rate for the attack class that most resembles a real threat here.
    response["poison_delivered"] = None if poison is None else poison.invoked
    return response