"""End-to-end eval harness runner.

Drives the full AW Analysis agent against the golden dataset, collects
results from both grader layers, writes JSON, returns a structured
report. The runner is the single place that decides whether a run
"passes" overall — gating logic lives here, not in the grader layers.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from aw_analysis.agent.conversation import Conversation
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

    report = RunReport(
        run_id=run_id,
        prompt_version=prompt_version,
        judge_rubric_version=JUDGE_RUBRIC_VERSION,
    )

    for i, case in enumerate(cases, start=1):
        print(f"[{i:>2}/{len(list(cases)) if hasattr(cases, '__len__') else '?'}] {case.id} ({case.query_class.value})...", end=" ", flush=True)
        result = _run_one(case, client, system_prompt)
        report.cases.append(result)
        print("PASS" if result.overall_passed else "FAIL")

    output_path = results_dir / f"{prompt_version}_{run_id}.json"
    output_path.write_text(json.dumps(report_to_dict(report), indent=2))
    print(f"\nResults written to {output_path}")
    return report


def _run_one(
    case: EvalCase, client: AnthropicClient, system_prompt: str
) -> EvalResult:
    """Execute the agent against one case and grade the result.

    Wraps both agent execution and grading in a try/except so a single
    upstream failure produces a recorded EvalResult rather than aborting
    the run. The recorded failure is informative (Module 3 'errors as
    data' reapplied at the eval layer).
    """
    started = time.perf_counter()
    try:
        conversation = Conversation(
            client=client,
            tools=default_registry(),
            system_prompt=system_prompt,
        )
        trace = conversation.send(case.query)
        final_text = trace.final_text or ""
    except Exception as exc:  # broad on purpose - eval layer must not crash
        elapsed = (time.perf_counter() - started) * 1000.0
        return _failure_eval_result(case, repr(exc), elapsed)

    deterministic = grade_deterministic(case.assertions, trace, final_text)

    try:
        judge = grade_judge(
            case_query=case.query,
            final_text=final_text,
            trace=trace,
            query_class=case.query_class,
            client=client,
        )
    except Exception as exc:
        judge = JudgeScores(
            faithfulness=1,
            relevance=1,
            refusal_correctness=None,
            faithfulness_reason=f"<judge error: {exc!r}>",
            relevance_reason=f"<judge error: {exc!r}>",
            refusal_correctness_reason=None,
        )

    elapsed = (time.perf_counter() - started) * 1000.0
    overall_passed, summary = _adjudicate(case, deterministic, judge)

    return EvalResult(
        case_id=case.id,
        query_class=case.query_class,
        deterministic=deterministic,
        judge=judge,
        final_text=final_text,
        total_input_tokens=trace.total_input_tokens,
        total_output_tokens=trace.total_output_tokens,
        iteration_count=len(trace.iterations),
        duration_ms=elapsed,
        overall_passed=overall_passed,
        failure_summary=summary,
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
        iteration_count=0,
        duration_ms=elapsed_ms,
        overall_passed=False,
        failure_summary=f"agent crashed: {error_repr}",
    )


def report_to_dict(report: RunReport) -> dict:
    """Hand-rolled serialiser - we want stable JSON shape for diffing."""
    return {
        "run_id": report.run_id,
        "prompt_version": report.prompt_version,
        "judge_rubric_version": report.judge_rubric_version,
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
                },
                "final_text": r.final_text,
            }
            for r in report.cases
        ],
    }