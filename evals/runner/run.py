"""End-to-end eval harness runner.

Drives the full AW Analysis agent against the golden dataset, collects
results from both grader layers, writes JSON, returns a structured
report. The runner is the single place that decides whether a run
"passes" overall — gating logic lives here, not in the grader layers.
"""

from __future__ import annotations

import json
import time
import anthropic
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
import uuid
from datetime import datetime
from aw_analysis.obs import emitter as obs



from aw_analysis.agent.conversation import Conversation
from aw_analysis.agent.orchestration import OrchestratedConversation
from aw_analysis.client import AnthropicClient
from aw_analysis.prompts.versions import PROMPT_VERSIONS, ACTIVE_PROMPT_VERSION
from aw_analysis.tools import default_registry  # see CLI for current factory
from evals.golden.dataset import GOLDEN_DATASET
from evals.grader.deterministic import grade_deterministic
from evals.grader.judge import JUDGE_RUBRIC_VERSION, grade_judge
from evals.grader.types import (
    Assertion,
    AssertionResult,
    EvalCase,
    EvalResult,
    JudgeScores,
    QueryClass,
    Severity,
)


# Threshold for judge-as-gate. Below this on faithfulness or refusal
# correctness, a case fails overall. Module 6 reference: "faithfulness
# below 3 is contradicting context or fabricating" - that is failing.
JUDGE_PASS_THRESHOLD: int = 3


@dataclass
class RunReport:
    """Aggregate output of a full eval run."""

    run_id: str
    prompt_version: str
    judge_rubric_version: str
    cases: list[EvalResult] = field(default_factory=list)
    # Stage 8: optional Langfuse project URL for clickable links in
    # the serialised JSON.  Set from LANGFUSE_PROJECT_URL env var.
    langfuse_project_url: str | None = None

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.cases if c.overall_passed)

    @property
    def total_count(self) -> int:
        return len(self.cases)

    @property
    def pass_rate(self) -> float:
        return self.passed_count / self.total_count if self.total_count else 0.0

    def by_class(self) -> dict[QueryClass, list[EvalResult]]:
        out: dict[QueryClass, list[EvalResult]] = {}
        for r in self.cases:
            out.setdefault(r.query_class, []).append(r)
        return out


def run_eval(
    cases: Iterable[EvalCase] = GOLDEN_DATASET,
    prompt_version: str = ACTIVE_PROMPT_VERSION,
    results_dir: Path = Path("evals/results"),
) -> RunReport:
    """Execute the harness end to end.

    Each case gets a fresh Conversation - eval cases must be independent.
    Failures within a case are caught and recorded so one broken case
    doesn't abort the run.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%dT%H%M%S")

    client = AnthropicClient()
    system_prompt = PROMPT_VERSIONS[prompt_version]

    import os
    report = RunReport(
        run_id=run_id,
        prompt_version=prompt_version,
        judge_rubric_version=JUDGE_RUBRIC_VERSION,
        langfuse_project_url=os.environ.get("LANGFUSE_PROJECT_URL"),
    )

    for i, case in enumerate(cases, start=1):
        print(f"[{i:>2}/{len(list(cases)) if hasattr(cases, '__len__') else '?'}] {case.id} ({case.query_class.value})...", end=" ", flush=True)
        result = _run_one(case, client, system_prompt)
        report.cases.append(result)
        print("PASS" if result.overall_passed else "FAIL")
        # Stage 6 operational fix: pace requests to avoid rolling-minute
        # rate limits on Tier 1 (30K input tokens/min). The news class
        # produces large web_search results that compound the per-case
        # input-token cost when run back-to-back. A 1.5s pause between
        # cases keeps the rolling window healthy. Adds ~36s to a 24-case
        # run; trivial compared to the call latency.
        last_case_tokens = result.total_input_tokens + result.total_output_tokens
        if last_case_tokens > 5000:
            time.sleep(12.0)   # heavy case; let the rolling window meaningfully drain
        elif last_case_tokens > 2000:
            time.sleep(3.0)
        else:
            time.sleep(0.5)

    output_path = results_dir / f"{prompt_version}_{run_id}.json"
    output_path.write_text(json.dumps(report_to_dict(report), indent=2))
    print(f"\nResults written to {output_path}")
    return report


def _serialise_plan(plan):
    """Serialise a QueryPlan into a JSON-friendly dict.

    Returns None when the decomposer didn't run (i.e. the fallback
    path was taken, or there was no plan to begin with).
    """
    if plan is None:
        return None
    return {
        "original_query": plan.original_query,
        "is_single_intent": plan.is_single_intent,
        "sub_queries": [
            {"intent": sq.intent.value, "text": sq.text}
            for sq in plan.sub_queries
        ],
    }


def _serialise_trace(turn_trace):
    """Serialise one sub-trace (a TurnTrace) into a JSON-friendly dict.

    Mirrors the shape used for top-level case records so sub-traces are
    inspectable in the same way as the parent case in the eval JSON.
    """
    return {
        "final_text": turn_trace.final_text,
        "tool_calls": [tc.name for tc in turn_trace.tool_calls],
        "was_refusal": turn_trace.was_refusal,
        "stop_reason": turn_trace.stop_reason,
        "total_input_tokens": turn_trace.total_input_tokens,
        "total_output_tokens": turn_trace.total_output_tokens,
        "iterations": [
            {
                "task_type": i.task_type,
                "model": i.model,
                "input_tokens": i.input_tokens,
                "output_tokens": i.output_tokens,
                "cost_usd": i.cost_usd,
                "duration_ms": i.duration_ms,
            }
            for i in turn_trace.iterations
        ],
    }

def _run_one(
    case: EvalCase, client: AnthropicClient, system_prompt: str
) -> EvalResult:
    """Execute the agent against one case and grade the result.

    Stage 7: the system under test is now OrchestratedConversation,
    which decomposes the user query into single-intent sub-queries
    before dispatching to the wrapped Conversation. The returned
    OrchestratedTurnTrace exposes flattened tool_calls,
    was_refusal, and total_cost_usd properties so existing
    deterministic assertions keep working unchanged.

    Wraps both agent execution and grading in a try/except so a single
    upstream failure produces a recorded EvalResult rather than aborting
    the run. The recorded failure is informative (Module 3 'errors as
    data' reapplied at the eval layer).
    """
    started = time.perf_counter()

    inner_conversation = Conversation(
        client=client,
        tools=default_registry(),
        system_prompt=system_prompt,
    )
    conversation = OrchestratedConversation(
        client=client,
        conversation=inner_conversation,
        interface="eval",
        conversation_id=f"eval-{case.id}",
    )

    # Stage 6 operational fix: rate-limit retry. Tier 1's 30K input
    # tokens/min budget can be tripped by news cases running in close
    # sequence (the trace grows large from web_search results, the
    # judge call sends the full trace, three of them in a 60s window
    # exceeds the budget). A single retry after 30s clears the rolling
    # window enough to proceed.
    max_rate_limit_retries = 2
    trace = None
    final_text = ""
    for attempt in range(max_rate_limit_retries + 1):
        try:
            trace = conversation.send(case.query)
            final_text = trace.final_text or ""
            break
        
        except anthropic.RateLimitError:
            if attempt == max_rate_limit_retries:
                # Final attempt failed — fall through to broad handler.
                # No bare-except equivalent here; re-raise so the
                # outer try captures and records the failure.
                raise
            # Reset the conversation state (the failed send may have
            # left partial messages) and back off. Stage 7: rebuild the
            # OrchestratedConversation, not the bare Conversation —
            # otherwise the next send() returns a TurnTrace instead of
            # an OrchestratedTurnTrace and downstream code crashes.
            inner_conversation = Conversation(
                client=client,
                tools=default_registry(),
                system_prompt=system_prompt,
            )
            conversation = OrchestratedConversation(
                client=client,
                conversation=inner_conversation,
                interface="eval",
                conversation_id=f"eval-{case.id}",
            )
            time.sleep(30.0)
            
            time.sleep(30.0)
        except Exception as exc:  # broad on purpose - eval layer must not crash
            elapsed = (time.perf_counter() - started) * 1000.0
            return _failure_eval_result(case, repr(exc), elapsed)

    if trace is None:
        # Shouldn't be reachable — either the loop broke after success or
        # raised after exhausting retries. Defensive fallback.
        elapsed = (time.perf_counter() - started) * 1000.0
        return _failure_eval_result(
            case, "rate-limit retries exhausted with no recorded trace", elapsed
        )

    deterministic = grade_deterministic(case.assertions, trace, final_text)

    judge = None
    for attempt in range(max_rate_limit_retries + 1):
        try:
            judge = grade_judge(
                case_query=case.query,
                final_text=final_text,
                trace=trace,
                query_class=case.query_class,
                client=client,
            )
            break
        except anthropic.RateLimitError:
            if attempt == max_rate_limit_retries:
                # Final attempt failed — record a sentinel judge so
                # the case shows up as failed-with-context rather than
                # silently passing.
                judge = JudgeScores(
                    faithfulness=1,
                    relevance=1,
                    refusal_correctness=None,
                    faithfulness_reason=(
                        "<judge rate-limited after retries; case not graded>"
                    ),
                    relevance_reason=(
                        "<judge rate-limited after retries; case not graded>"
                    ),
                    refusal_correctness_reason=None,
                )
                break
            time.sleep(30.0)
        except Exception as exc:
            judge = JudgeScores(
                faithfulness=1,
                relevance=1,
                refusal_correctness=None,
                faithfulness_reason=f"<judge error: {exc!r}>",
                relevance_reason=f"<judge error: {exc!r}>",
                refusal_correctness_reason=None,
            )
            break

    elapsed = (time.perf_counter() - started) * 1000.0
    overall_passed, summary = _adjudicate(case, deterministic, judge)

    # Stage 8: attach deterministic + judge scores to the Langfuse
    # trace that this case ran on.  The trace_id was captured on the
    # OrchestratedTurnTrace by orchestration.py while the obs.turn
    # context was still active; we use it here to score the trace
    # by ID, which works even though the obs.turn context has exited.
    langfuse_trace_id = getattr(trace, "langfuse_trace_id", None)
    _attach_eval_scores(
        trace_id=langfuse_trace_id,
        case=case,
        deterministic=deterministic,
        judge=judge,
        overall_passed=overall_passed,
    )

    return EvalResult(
        case_id=case.id,
        query_class=case.query_class,
        deterministic=deterministic,
        judge=judge,
        final_text=final_text,
        total_input_tokens=trace.total_input_tokens,
        total_output_tokens=trace.total_output_tokens,
        total_cost_usd=trace.total_cost_usd,
        iteration_count=len(trace.iterations),
        duration_ms=elapsed,
        overall_passed=overall_passed,
        failure_summary=summary,
        safety_net_fired=trace.safety_net_fired,
        decomposition=_serialise_plan(trace.decomposition_plan),
        decomposition_fallback_reason=trace.decomposition_fallback_reason,
        sub_traces=[_serialise_trace(t) for t in trace.sub_traces],
        langfuse_trace_id=langfuse_trace_id,
    )


def _adjudicate(
    case: EvalCase,
    deterministic: list[AssertionResult],
    judge: JudgeScores,
) -> tuple[bool, str]:
    """Decide whether the case passed overall.

    Pass criteria:
      1. All P0 deterministic assertions passed, EXCEPT for the
         `refused` kind on refusal-class cases (deferred to the
         refusal branch — the LLM judge can override classifier
         false negatives).
      2. Non-refusal cases: faithfulness >= JUDGE_PASS_THRESHOLD.
         Refusal cases don't make tool calls so faithfulness is
         undefined for them; refusal_correctness is the load-
         bearing judge dimension instead.
      3. Refusal cases: refusal_correctness >= JUDGE_PASS_THRESHOLD,
         plus layer-disagreement and classifier-override logic.

    Module 6 'disagreement is signal' applied: we don't average the
    two layers; we treat strong disagreement as failure pending
    investigation.
    """
    # P0 deterministic failures. On refusal-class cases, defer the
    # `refused` assertion to the refusal branch below — the judge may
    # override the classifier's false negative.
    p0_failures = [
        ar for ar in deterministic
        if not ar.passed
        and ar.assertion.severity == Severity.P0
        and not (
            case.query_class == QueryClass.REFUSAL
            and ar.assertion.kind.value == "refused"
        )
    ]
    if p0_failures:
        names = ", ".join(_pretty_assertion(ar.assertion) for ar in p0_failures)
        return False, f"P0 deterministic failures: {names}"

    # Faithfulness gates non-refusal cases only. Refusal cases by
    # definition don't make tool calls, so the faithfulness rubric
    # (which grades claims against tool-result context) is undefined
    # for them — any factual claim in the refusal text looks
    # unsupported because there are no tool results to support it
    # against.
    if case.query_class != QueryClass.REFUSAL:
        if judge.faithfulness < JUDGE_PASS_THRESHOLD:
            return False, (
                f"faithfulness={judge.faithfulness} below threshold "
                f"({JUDGE_PASS_THRESHOLD}); reason='{judge.faithfulness_reason}'"
            )

    if case.query_class == QueryClass.REFUSAL:
        # Judge-side refusal-correctness gate.
        if (
            judge.refusal_correctness is not None
            and judge.refusal_correctness < JUDGE_PASS_THRESHOLD
        ):
            return False, (
                f"refusal_correctness={judge.refusal_correctness} below threshold; "
                f"reason='{judge.refusal_correctness_reason}'"
            )

        # Layer disagreement: classifier says refused, judge says not
        # refused. Treat as failure pending inspection.
        det_refused = any(
            ar.passed and ar.assertion.kind.value == "refused"
            for ar in deterministic
        )
        if det_refused and (judge.refusal_correctness or 5) <= 1:
            return False, (
                "layer disagreement: deterministic says refused, judge says not refused"
            )

        # Judge override on classifier false negative. The post-hoc
        # refusal classifier is pattern-based and brittle by design
        # (Module 6 Ex 6.1 lesson). When the judge gives a high-
        # confidence refusal score AND the only failing P0 deterministic
        # assertion was the `refused` flag itself, trust the judge: the
        # agent is refusing, the classifier just doesn't recognise the
        # idiom.
        det_refused_failed = any(
            not ar.passed and ar.assertion.kind.value == "refused"
            for ar in deterministic
        )
        if det_refused_failed:
            if (
                judge.refusal_correctness is not None
                and judge.refusal_correctness >= 4
            ):
                return True, ""
            return False, (
                f"refusal_correctness={judge.refusal_correctness} insufficient to "
                f"override classifier false negative on refused flag"
            )

    return True, ""


def _pretty_assertion(a: Assertion) -> str:
    return f"{a.kind.value}({a.target})"


def _failure_eval_result(case: EvalCase, error_repr: str, elapsed_ms: float) -> EvalResult:
    return EvalResult(
        case_id=case.id,
        query_class=case.query_class,
        deterministic=[],
        judge=JudgeScores(
            faithfulness=1,
            relevance=1,
            refusal_correctness=None,
            faithfulness_reason=f"<agent error: {error_repr}>",
            relevance_reason=f"<agent error: {error_repr}>",
            refusal_correctness_reason=None,
        ),
        final_text="",
        total_input_tokens=0,
        total_output_tokens=0,
        total_cost_usd=0.0,
        iteration_count=0,
        duration_ms=elapsed_ms,
        overall_passed=False,
        failure_summary=f"upstream error: {error_repr}",
        safety_net_fired=False,
        decomposition=None,
        decomposition_fallback_reason=f"agent_error: {error_repr}",
        sub_traces=[],
        langfuse_trace_id=None,  # Stage 8
    )

def _attach_eval_scores(
    *,
    trace_id: str | None,
    case: EvalCase,
    deterministic: list[AssertionResult],
    judge: JudgeScores,
    overall_passed: bool,
) -> None:
    """Attach per-case scores to the Langfuse trace by ID.

    Called after the obs.turn(...) context has closed, so we score
    the trace directly by ID rather than via the current-context
    helper.  If observability is disabled the trace_id is None and
    this function returns immediately.

    Score naming convention:
      - assertion.<kind>.<target>  = 1.0 / 0.0 per deterministic check
      - judge.faithfulness          = 1-5
      - judge.relevance             = 1-5
      - judge.refusal_correctness   = 1-5 (refusal cases only)
      - case.passed                 = 1.0 / 0.0
    """
    if trace_id is None:
        return
    # Lazy import — observability is optional.
    from aw_analysis.obs.client import get_langfuse_client
    client = get_langfuse_client()
    if client is None:
        return
    try:
        # Deterministic assertions: one score per assertion, named
        # with both kind and target so the dashboard can slice on
        # specific assertions (e.g. "which cases failed
        # assertion.tool_called.web_search").
        for ar in deterministic:
            score_name = f"assertion.{ar.assertion.kind.value}.{ar.assertion.target}"
            # Langfuse score names have length limits; truncate
            # defensively.
            score_name = score_name[:100]
            client.create_score(
                trace_id=trace_id,
                name=score_name,
                value=1.0 if ar.passed else 0.0,
            )
        # Judge dimensions.
        client.create_score(
            trace_id=trace_id,
            name="judge.faithfulness",
            value=float(judge.faithfulness),
            comment=judge.faithfulness_reason,
        )
        client.create_score(
            trace_id=trace_id,
            name="judge.relevance",
            value=float(judge.relevance),
            comment=judge.relevance_reason,
        )
        if judge.refusal_correctness is not None:
            client.create_score(
                trace_id=trace_id,
                name="judge.refusal_correctness",
                value=float(judge.refusal_correctness),
                comment=judge.refusal_correctness_reason,
            )
        # Overall pass / fail.
        client.create_score(
            trace_id=trace_id,
            name="case.passed",
            value=1.0 if overall_passed else 0.0,
        )
    except Exception as exc:  # noqa: BLE001
        # Eval grading must not fail because Langfuse refused a score.
        import sys
        sys.stderr.write(
            f"WARN obs: failed to attach scores for {case.id}: {exc}\n"
        )

def report_to_dict(report: RunReport) -> dict:
    """Hand-rolled serialiser - we want stable JSON shape for diffing."""
    return {
        "run_id": report.run_id,
        "prompt_version": report.prompt_version,
        "judge_rubric_version": report.judge_rubric_version,
        "langfuse_project_url": report.langfuse_project_url,  # Stage 8
        "summary": {
            "total": report.total_count,
            "passed": report.passed_count,
            "pass_rate": round(report.pass_rate, 3),
            "by_class": {
                cls.value: {
                    "total": len(rs),
                    "passed": sum(1 for r in rs if r.overall_passed),
                    "mean_faithfulness": round(
                        sum(r.judge.faithfulness for r in rs) / len(rs), 2
                    ),
                    "mean_relevance": round(
                        sum(r.judge.relevance for r in rs) / len(rs), 2
                    ),
                }
                for cls, rs in report.by_class().items()
            },
        },
        "cases": [
            {
                "id": r.case_id,
                "class": r.query_class.value,
                "passed": r.overall_passed,
                "summary": r.failure_summary,
                "deterministic": [
                    {
                        "kind": ar.assertion.kind.value,
                        "target": ar.assertion.target,
                        "severity": ar.assertion.severity.value,
                        "passed": ar.passed,
                        "detail": ar.detail,
                    }
                    for ar in r.deterministic
                ],
                "judge": {
                    "faithfulness": r.judge.faithfulness,
                    "relevance": r.judge.relevance,
                    "refusal_correctness": r.judge.refusal_correctness,
                    "faithfulness_reason": r.judge.faithfulness_reason,
                    "relevance_reason": r.judge.relevance_reason,
                    "refusal_correctness_reason": r.judge.refusal_correctness_reason,
                },
                "trace": {
                    "input_tokens": r.total_input_tokens,
                    "output_tokens": r.total_output_tokens,
                    "iterations": r.iteration_count,
                    "duration_ms": round(r.duration_ms, 1),
                    "total_cost_usd": round(r.total_cost_usd, 6),
                },
                "decomposition": r.decomposition,
                "decomposition_fallback_reason": r.decomposition_fallback_reason,
                "safety_net_fired": r.safety_net_fired,
                "sub_traces": r.sub_traces,
                "final_text": r.final_text,
                # Stage 8: direct link to the Langfuse trace.
                "langfuse_trace_id": r.langfuse_trace_id,
                "langfuse_trace_url": (
                    f"{report.langfuse_project_url}/traces/{r.langfuse_trace_id}"
                    if (report.langfuse_project_url and r.langfuse_trace_id)
                    else None
                ),
            }
            for r in report.cases
        ],
    }