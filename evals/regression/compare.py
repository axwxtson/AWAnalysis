"""Compare two eval runs (typically baseline vs candidate) per case.

Module 6 reference: per-case deltas matter more than the aggregate mean.
A new prompt can score higher on average while breaking critical edge
cases. Always inspect which cases got worse.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CaseDelta:
    case_id: str
    query_class: str
    baseline_passed: bool
    candidate_passed: bool
    baseline_faithfulness: int
    candidate_faithfulness: int
    baseline_relevance: int
    candidate_relevance: int
    verdict: str  # "regression" | "improvement" | "stable"


def compare(baseline_path: Path, candidate_path: Path) -> dict:
    """Diff two eval-run JSON files by case ID.

    Returns a structured dict: per-class summary, per-case deltas,
    and a verdict-level summary (regressions / improvements / stable).
    """
    baseline = json.loads(baseline_path.read_text())
    candidate = json.loads(candidate_path.read_text())

    by_id_baseline = {c["id"]: c for c in baseline["cases"]}
    by_id_candidate = {c["id"]: c for c in candidate["cases"]}

    deltas: list[CaseDelta] = []
    for case_id, b in by_id_baseline.items():
        c = by_id_candidate.get(case_id)
        if c is None:
            continue
        verdict = _classify(b["passed"], c["passed"], b["judge"], c["judge"])
        deltas.append(
            CaseDelta(
                case_id=case_id,
                query_class=b["class"],
                baseline_passed=b["passed"],
                candidate_passed=c["passed"],
                baseline_faithfulness=b["judge"]["faithfulness"],
                candidate_faithfulness=c["judge"]["faithfulness"],
                baseline_relevance=b["judge"]["relevance"],
                candidate_relevance=c["judge"]["relevance"],
                verdict=verdict,
            )
        )

    by_class: dict[str, dict[str, int]] = {}
    for d in deltas:
        cls = by_class.setdefault(
            d.query_class, {"regression": 0, "improvement": 0, "stable": 0}
        )
        cls[d.verdict] += 1

    return {
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "baseline_prompt": baseline["prompt_version"],
        "candidate_prompt": candidate["prompt_version"],
        "regressions": [d.__dict__ for d in deltas if d.verdict == "regression"],
        "improvements": [d.__dict__ for d in deltas if d.verdict == "improvement"],
        "by_class": by_class,
        "summary": {
            "total": len(deltas),
            "regressions": sum(1 for d in deltas if d.verdict == "regression"),
            "improvements": sum(1 for d in deltas if d.verdict == "improvement"),
            "stable": sum(1 for d in deltas if d.verdict == "stable"),
        },
    }


def _classify(b_passed: bool, c_passed: bool, b_judge: dict, c_judge: dict) -> str:
    """A regression is: candidate fails AND baseline passed, or judge
    score dropped by >=2 on faithfulness even if both still pass."""
    if b_passed and not c_passed:
        return "regression"
    if not b_passed and c_passed:
        return "improvement"
    faith_drop = b_judge["faithfulness"] - c_judge["faithfulness"]
    if faith_drop >= 2:
        return "regression"
    if faith_drop <= -2:
        return "improvement"
    return "stable"