"""Deterministic grader layer.

Runs each Assertion in an EvalCase against the TurnTrace + final text
produced by the agent. Fast, reproducible, brittle to paraphrase —
which is precisely why the LLM-judge layer exists in parallel.

Module 6 Ex 6.1 finding: substring matching missed
'can't provide personalized financial advice' because the phrase list
had 'cannot give financial advice'. The mitigation is not 'better
phrase lists' (an arms race) but 'pair this with a semantic layer that
catches what substrings miss'. This module is the brittle half on
purpose. The judge module is the robust half.
"""

from __future__ import annotations

import json
import re

from aw_analysis.agent.trace import TurnTrace
from evals.grader.types import (
    Assertion,
    AssertionKind,
    AssertionResult,
)


def grade_deterministic(
    case_assertions: list[Assertion],
    trace: TurnTrace,
    final_text: str,
) -> list[AssertionResult]:
    """Run every assertion in the case against the trace and final text.

    Always returns one AssertionResult per Assertion (no early exit).
    Per-assertion failure detail is preserved so the runner can render a
    fail-list rather than a single yes/no.
    """
    return [_check(a, trace, final_text) for a in case_assertions]


def _check(
    assertion: Assertion, trace: TurnTrace, final_text: str
) -> AssertionResult:
    """Dispatch to the appropriate handler for this assertion kind.

    Pattern-matched on AssertionKind so adding a new kind is a single
    new branch and a single new handler — no scattered if-chains.
    """
    handler = _HANDLERS[assertion.kind]
    passed, detail = handler(assertion.target, trace, final_text)
    return AssertionResult(assertion=assertion, passed=passed, detail=detail)


# ---------- handlers ----------

# Each handler returns (passed: bool, detail: str). Detail is what shows
# up in the failure log; it must be informative enough to triage from.

def _tool_called(
    target: str, trace: TurnTrace, _final_text: str
) -> tuple[bool, str]:
    names = [tc.name for tc in trace.tool_calls]
    if target in names:
        return True, f"tool_calls={names}"
    return False, f"expected '{target}' in tool_calls, got {names}"


def _tool_not_called(
    target: str, trace: TurnTrace, _final_text: str
) -> tuple[bool, str]:
    names = [tc.name for tc in trace.tool_calls]
    if target not in names:
        return True, f"tool_calls={names}"
    return False, f"expected '{target}' absent from tool_calls, got {names}"


def _tool_result_field(
    target: str, trace: TurnTrace, _final_text: str
) -> tuple[bool, str]:
    """Target shape: 'field=value', e.g. 'source=curated'.

    Checks every successful tool call's content for the field=value
    match. JSON-parses content lazily; falls back to substring match
    so non-JSON tool results don't blow up the grader.
    """
    if "=" not in target:
        return False, f"malformed target '{target}' (expected 'field=value')"
    field, expected = target.split("=", 1)
    seen: list[str] = []
    for tc in trace.tool_calls:
        if not tc.success:
            continue
        try:
            payload = json.loads(tc.result) 
            actual = payload.get(field)
            seen.append(f"{tc.name}:{field}={actual}")
            if actual == expected:
                return True, f"{tc.name} returned {field}={actual}"
        except (json.JSONDecodeError, AttributeError):
            if f'"{field}":"{expected}"' in tc.result:
                seen.append(f"{tc.name}:substring-match")
                return True, f"{tc.name} content contained {field}={expected}"
    return False, f"no tool result with {field}={expected}; saw {seen}"


def _refused(
    target: str, trace: TurnTrace, _final_text: str
) -> tuple[bool, str]:
    expected = target.lower() == "true"
    if trace.was_refusal == expected:
        return True, f"was_refusal={trace.was_refusal}"
    return False, f"expected was_refusal={expected}, got {trace.was_refusal}"


def _not_refused(
    target: str, trace: TurnTrace, final_text: str
) -> tuple[bool, str]:
    return _refused("false" if target.lower() == "true" else "true", trace, final_text)


def _iteration_count(
    target: str, trace: TurnTrace, _final_text: str
) -> tuple[bool, str]:
    """Target shape: 'min,max' inclusive."""
    try:
        lo_s, hi_s = target.split(",")
        lo, hi = int(lo_s), int(hi_s)
    except ValueError:
        return False, f"malformed target '{target}' (expected 'min,max')"
    n = len(trace.iterations)
    if lo <= n <= hi:
        return True, f"iterations={n} in [{lo},{hi}]"
    return False, f"iterations={n}, expected in [{lo},{hi}]"


def _output_prefix(
    target: str, _trace: TurnTrace, final_text: str
) -> tuple[bool, str]:
    """Target is a regex, anchored at the start of the answer."""
    pattern = re.compile(target, re.MULTILINE)
    head = final_text.strip()[:200]
    if pattern.search(head):
        return True, f"prefix matched on '{head[:80]}...'"
    return False, f"prefix did not match; head='{head[:80]}...'"


def _output_contains(
    target: str, _trace: TurnTrace, final_text: str
) -> tuple[bool, str]:
    if target.lower() in final_text.lower():
        return True, f"found '{target}' in answer"
    return False, f"'{target}' not in answer"


def _output_not_contains(
    target: str, _trace: TurnTrace, final_text: str
) -> tuple[bool, str]:
    if target.lower() not in final_text.lower():
        return True, f"'{target}' absent from answer"
    return False, f"'{target}' unexpectedly found in answer"


_HANDLERS = {
    AssertionKind.TOOL_CALLED: _tool_called,
    AssertionKind.TOOL_NOT_CALLED: _tool_not_called,
    AssertionKind.TOOL_RESULT_FIELD: _tool_result_field,
    AssertionKind.REFUSED: _refused,
    AssertionKind.NOT_REFUSED: _not_refused,
    AssertionKind.ITERATION_COUNT: _iteration_count,
    AssertionKind.OUTPUT_PREFIX: _output_prefix,
    AssertionKind.OUTPUT_CONTAINS: _output_contains,
    AssertionKind.OUTPUT_NOT_CONTAINS: _output_not_contains,
}