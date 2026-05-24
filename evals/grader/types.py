"""Shared types for the eval grader.

EvalCase is the input shape (one entry in the golden dataset).
EvalResult is the output shape (one row in the report).
AssertionResult is the deterministic-layer line item.
JudgeScores is the LLM-judge-layer line item.

Pydantic for both schema validation at module load and editor type
support when hand-writing dataset entries.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class QueryClass(str, Enum):
    """The six query classes the golden dataset partitions into."""

    PRICE = "price"
    PROFILE_CURATED = "profile_curated"
    PROFILE_FALLBACK = "profile_fallback"
    NEWS = "news"
    REFUSAL = "refusal"
    COMBINED_TOOLS = "combined_tools"


class AssertionKind(str, Enum):
    """The taxonomy of deterministic assertions.

    Module 6 Ex 6.1 finding: when an eval fails, you need to know which
    *kind* of thing broke, fast. Tag every assertion so triage knows
    where to look first.
    """

    TOOL_CALLED = "tool_called"  # specific tool name appeared in trace
    TOOL_NOT_CALLED = "tool_not_called"  # specific tool name absent
    TOOL_RESULT_FIELD = "tool_result_field"  # tool returned a JSON field with a value
    REFUSED = "refused"  # was_refusal flag check
    NOT_REFUSED = "not_refused"  # inverse
    ITERATION_COUNT = "iteration_count"  # n iterations between bounds
    OUTPUT_PREFIX = "output_prefix"  # final text starts with a regex
    OUTPUT_CONTAINS = "output_contains"  # final text contains substring (case-insensitive)
    OUTPUT_NOT_CONTAINS = "output_not_contains"  # negative substring


class Severity(str, Enum):
    """P0 fails the run; P1 is reported but does not gate."""

    P0 = "p0"
    P1 = "p1"


class Assertion(BaseModel):
    """One deterministic assertion against a turn trace.

    `target` is interpreted by `AssertionKind` — for TOOL_CALLED it's the
    tool name; for OUTPUT_CONTAINS it's the substring; for ITERATION_COUNT
    it's an inclusive [min, max] tuple serialised as "min,max"; etc.
    """

    kind: AssertionKind
    target: str
    severity: Severity = Severity.P0
    description: str  # human-readable; appears in the failure log


class EvalCase(BaseModel):
    """One entry in the golden dataset.

    `rationale` is mandatory. A case without a rationale is a vibe.
    """

    id: str = Field(..., min_length=3)
    query: str = Field(..., min_length=3)
    query_class: QueryClass
    assertions: list[Assertion] = Field(..., min_length=1)
    rationale: str = Field(..., min_length=10)
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class AssertionResult(BaseModel):
    """One assertion checked against one turn."""

    assertion: Assertion
    passed: bool
    detail: str  # e.g. "expected 'get_crypto_price' in tool_calls, got ['lookup_asset_profile']"


class JudgeScores(BaseModel):
    """Output of the LLM-as-judge layer for one case.

    Faithfulness and relevance are the two dimensions Module 4 / Module 6
    converged on as the load-bearing axes for an LLM-judge over a
    grounded-text agent. Refusal correctness is reported only on cases
    of class `refusal`; for other classes it is None.
    """

    faithfulness: int = Field(..., ge=1, le=5)
    relevance: int = Field(..., ge=1, le=5)
    refusal_correctness: int | None = None
    faithfulness_reason: str
    relevance_reason: str
    refusal_correctness_reason: str | None = None


class EvalResult(BaseModel):
    """One case after the harness has run end-to-end."""

    case_id: str
    query_class: QueryClass
    deterministic: list[AssertionResult]
    judge: JudgeScores
    final_text: str
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float = 0.0
    iteration_count: int
    duration_ms: float
    overall_passed: bool  # all P0 deterministic + judge thresholds + agreement
    failure_summary: str  # empty if passed; else short explanation
    # Stage 7 additions — orchestration layer visibility.
    safety_net_fired: bool = False
    decomposition: dict | None = None
    decomposition_fallback_reason: str | None = None
    sub_traces: list[dict] = Field(default_factory=list)