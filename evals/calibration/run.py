"""Calibration runner.

Two passes:
  1. Reference-set agreement: how often does the judge agree with the
     human grades on the 12 hand-graded reference pairs?
  2. Bias tests: position bias and length bias.

Either pass can fail. The runner returns a structured report; the CLI
prints it; the eval runner is gated on the calibration passing its
thresholds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
import time

from aw_analysis.client import AnthropicClient
from aw_analysis.config.model_config import TaskType, get_model_config
from evals.calibration.bias import run_length_bias, run_position_bias
from evals.calibration.reference_set import REFERENCE_SET, ReferencePair
from evals.grader.judge import (
    JUDGE_RUBRIC_VERSION,
    _faithfulness_rubric,
    _judge_one,
    _refusal_correctness_rubric,
    _relevance_rubric,
)


# Calibration thresholds. Pulled directly from Module 6 Ex 6.2 findings.
EXACT_AGREEMENT_TARGET: float = 0.60  # 60%
WITHIN_ONE_TARGET: float = 0.80  # 80% (Ex 6.2 hit 93.3%, threshold is the floor)
DIRECTION_AGREEMENT_TARGET: float = 0.80  # 80%
POSITION_CONSISTENCY_TARGET: float = 0.75  # 75% (Ex 6.2 hit 0%; threshold is meaningful)
LENGTH_BIAS_ABS_GAP_LIMIT: float = 0.5  # mean |gap| <= 0.5


@dataclass
class CalibrationReport:
    """Structured calibration output."""

    rubric_version: str
    exact_agreement: float = 0.0
    within_one_agreement: float = 0.0
    direction_agreement: float = 0.0
    mean_signed_bias: float = 0.0
    per_dimension: dict[str, dict[str, float]] = field(default_factory=dict)
    disagreements: list[dict] = field(default_factory=list)
    position_bias: dict = field(default_factory=dict)
    length_bias: dict = field(default_factory=dict)
    passes_gate: bool = False
    gate_failures: list[str] = field(default_factory=list)


def run_calibration(out_dir: Path = Path("evals/results")) -> CalibrationReport:
    """Run both calibration passes and write the report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    client = AnthropicClient()

    print("Running reference-set agreement...")
    judge_scores = _grade_reference_set(client)
    report = _agreement_report(judge_scores)

    print("Running position bias test...")
    report.position_bias = run_position_bias(client)

    print("Running length bias test...")
    report.length_bias = run_length_bias(client)

    # ---- gating ----
    failures: list[str] = []
    if report.exact_agreement < EXACT_AGREEMENT_TARGET:
        failures.append(
            f"exact_agreement={report.exact_agreement:.2f} < {EXACT_AGREEMENT_TARGET}"
        )
    if report.within_one_agreement < WITHIN_ONE_TARGET:
        failures.append(
            f"within_one_agreement={report.within_one_agreement:.2f} < {WITHIN_ONE_TARGET}"
        )
    if report.direction_agreement < DIRECTION_AGREEMENT_TARGET:
        failures.append(
            f"direction_agreement={report.direction_agreement:.2f} < {DIRECTION_AGREEMENT_TARGET}"
        )
    if report.position_bias.get("consistency_rate", 0) < POSITION_CONSISTENCY_TARGET:
        failures.append(
            f"position_consistency={report.position_bias.get('consistency_rate')} "
            f"< {POSITION_CONSISTENCY_TARGET}"
        )
    if report.length_bias.get("abs_gap", 99) > LENGTH_BIAS_ABS_GAP_LIMIT:
        failures.append(
            f"length_bias_abs_gap={report.length_bias.get('abs_gap')} "
            f"> {LENGTH_BIAS_ABS_GAP_LIMIT}"
        )
    report.gate_failures = failures
    report.passes_gate = not failures

    timestamp = time.strftime("%Y%m%dT%H%M%S")
    out_path = out_dir / f"calibration_{report.rubric_version}_{timestamp}.json"
    out_path.write_text(json.dumps(_calibration_to_dict(report), indent=2))
    print(f"Calibration report written to {out_path}")
    return report


def _grade_reference_set(client: AnthropicClient) -> list[tuple[ReferencePair, int]]:
    """Run the judge on every ReferencePair and pair with human scores."""
    rubrics = {
        "faithfulness": _faithfulness_rubric(),
        "relevance": _relevance_rubric(),
        "refusal_correctness": _refusal_correctness_rubric(),
    }
    results: list[tuple[ReferencePair, int]] = []
    for pair in REFERENCE_SET:
        rubric = rubrics[pair.dimension]
        context_label = "Tool results:" if pair.context else None
        score, _reason = _judge_one(
            client=client,
            rubric=rubric,
            query=pair.query,
            answer=pair.answer,
            context_label=context_label,
            context_body=pair.context,
        )
        results.append((pair, score))
        print(f"  {pair.id} ({pair.dimension}): human={pair.human_score} judge={score}")
    return results


def _agreement_report(scored: list[tuple[ReferencePair, int]]) -> CalibrationReport:
    """Compute exact / within-1 / direction agreement and per-dimension splits."""
    exact = 0
    within_one = 0
    direction = 0
    bias_sum = 0.0
    by_dim: dict[str, list[tuple[int, int]]] = {}
    disagreements: list[dict] = []

    for pair, judge in scored:
        diff = judge - pair.human_score
        bias_sum += diff
        if diff == 0:
            exact += 1
        if abs(diff) <= 1:
            within_one += 1
        # direction agreement: both >=4, both <=2, or both ==3
        if (
            (pair.human_score >= 4 and judge >= 4)
            or (pair.human_score <= 2 and judge <= 2)
            or (pair.human_score == 3 and judge == 3)
        ):
            direction += 1
        by_dim.setdefault(pair.dimension, []).append((pair.human_score, judge))
        if abs(diff) >= 2:
            disagreements.append(
                {
                    "id": pair.id,
                    "dimension": pair.dimension,
                    "human": pair.human_score,
                    "judge": judge,
                    "note": pair.note,
                }
            )

    n = len(scored)
    per_dim = {
        d: {
            "exact": round(sum(1 for h, j in pairs if h == j) / len(pairs), 2),
            "within_one": round(sum(1 for h, j in pairs if abs(h - j) <= 1) / len(pairs), 2),
            "n": len(pairs),
        }
        for d, pairs in by_dim.items()
    }

    return CalibrationReport(
        rubric_version=JUDGE_RUBRIC_VERSION,
        exact_agreement=round(exact / n, 2) if n else 0.0,
        within_one_agreement=round(within_one / n, 2) if n else 0.0,
        direction_agreement=round(direction / n, 2) if n else 0.0,
        mean_signed_bias=round(bias_sum / n, 2) if n else 0.0,
        per_dimension=per_dim,
        disagreements=disagreements,
    )


def _calibration_to_dict(report: CalibrationReport) -> dict:
    return {
        "rubric_version": report.rubric_version,
        "passes_gate": report.passes_gate,
        "gate_failures": report.gate_failures,
        "agreement": {
            "exact": report.exact_agreement,
            "within_one": report.within_one_agreement,
            "direction": report.direction_agreement,
            "mean_signed_bias": report.mean_signed_bias,
            "per_dimension": report.per_dimension,
        },
        "disagreements": report.disagreements,
        "position_bias": report.position_bias,
        "length_bias": report.length_bias,
    }