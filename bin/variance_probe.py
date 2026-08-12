"""Repeat a single golden case N times and report the spread.

Some cases have non-deterministic inputs by construction. news-class
cases call web_search, which returns different pages on every call, so
the faithfulness judgement is made against different evidence each run.
A single observed score move is not evidence of a regression until you
know the run-to-run spread.

This measures the instrument, not the system. Two noise sources are
stacked and not separable here: varying search results, and the judge
itself being a model call. The question is only how wide the total
spread is.

Results are written to a scratch directory rather than evals/results/,
so repeat runs of one case do not pollute the committed baseline.

Usage:
    PYTHONPATH=$(pwd) .venv/bin/python bin/variance_probe.py <case_id> [n]
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

from aw_analysis.config import get_settings
from evals.golden import cases_for
from evals.runner.run import run_eval

SCRATCH_DIR = Path("evals/results/scratch")


def _find_case(case_id: str) -> tuple[object, str]:
    for asset_class in ("crypto", "equities"):
        for case in cases_for(asset_class):
            if case.id == case_id:
                return case, asset_class
    raise SystemExit(f"case not found in golden set: {case_id}")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: variance_probe.py <case_id> [n]")

    get_settings()  # fail fast

    case_id = argv[1]
    n = int(argv[2]) if len(argv) > 2 else 5
    case, asset_class = _find_case(case_id)

    print(f"case:  {case_id}  ({asset_class}, {case.query_class.value})")
    print(f"query: {case.query!r}")
    print(f"runs:  {n}")
    print()

    rows = []
    for i in range(1, n + 1):
        report = run_eval(
            asset_class=asset_class,
            results_dir=SCRATCH_DIR,
            cases=[case],
        )
        result = report.cases[0]
        j = result.judge
        rows.append((result.overall_passed, j.faithfulness, j.relevance,
                     j.refusal_correctness))
        print(f"  run {i}: passed={result.overall_passed!s:5} "
              f"faithfulness={j.faithfulness} "
              f"relevance={j.relevance} "
              f"refusal={j.refusal_correctness}  "
              f"cost=${result.total_cost_usd:.4f}")

    print()
    faith = [r[1] for r in rows]
    passes = sum(1 for r in rows if r[0])

    print(f"passed:       {passes}/{n}")
    print(f"faithfulness: {sorted(faith)}")
    print(f"  min={min(faith)}  max={max(faith)}  "
          f"median={statistics.median(faith)}")
    if len(set(faith)) == 1:
        print("  no variance observed across runs")
    else:
        print(f"  spread={max(faith) - min(faith)} points")
    print()
    print(f"scratch results in {SCRATCH_DIR}/{asset_class}/ "
          f"(gitignored, safe to delete)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))