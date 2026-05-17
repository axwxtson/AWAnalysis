"""`aw-eval` CLI entry point.

Subcommands:
  calibrate          - run judge calibration; print + save report
  run [--prompt-version V]  - run the full eval harness
  compare BASELINE CANDIDATE - per-case A/B diff between two run JSONs

Each subcommand exits non-zero on failure so the harness slots into CI
unchanged. Module 6 'CI integration' pattern.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.calibration.run import run_calibration
from evals.regression.compare import compare
from evals.runner.report import render
from evals.runner.run import run_eval


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aw-eval")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("calibrate", help="Calibrate the LLM-as-judge")

    run_p = sub.add_parser("run", help="Run the eval harness")
    run_p.add_argument(
        "--prompt-version",
        default=None,
        help="Prompt version to evaluate (defaults to ACTIVE_PROMPT_VERSION)",
    )
    run_p.add_argument(
        "--require-calibration",
        action="store_true",
        help=(
            "Refuse to run if no passing calibration report exists in "
            "evals/results/. Recommended in CI."
        ),
    )

    cmp_p = sub.add_parser("compare", help="Per-case diff between two runs")
    cmp_p.add_argument("baseline", type=Path)
    cmp_p.add_argument("candidate", type=Path)

    args = parser.parse_args(argv)

    if args.cmd == "calibrate":
        report = run_calibration()
        print()
        print(_format_calibration(report))
        return 0 if report.passes_gate else 1

    if args.cmd == "run":
        if args.require_calibration and not _calibration_passed():
            print("ERROR: --require-calibration set but no passing calibration found.")
            print("Run `aw-eval calibrate` first.")
            return 2
        from aw_analysis.prompts.versions import ACTIVE_PROMPT_VERSION
        version = args.prompt_version or ACTIVE_PROMPT_VERSION
        report = run_eval(prompt_version=version)
        print()
        print(render(report))
        return 0 if report.pass_rate == 1.0 else 1

    if args.cmd == "compare":
        result = compare(args.baseline, args.candidate)
        print(json.dumps(result, indent=2))
        return 0 if result["summary"]["regressions"] == 0 else 1

    parser.print_help()
    return 2


def _calibration_passed() -> bool:
    """Look for any calibration report in evals/results that passes_gate."""
    results = Path("evals/results")
    if not results.exists():
        return False
    for path in results.glob("calibration_*.json"):
        try:
            obj = json.loads(path.read_text())
            if obj.get("passes_gate"):
                return True
        except json.JSONDecodeError:
            continue
    return False


def _format_calibration(report) -> str:  # noqa: ANN001 - dataclass
    lines = [
        f"=== Calibration: {report.rubric_version} ===",
        f"passes gate: {report.passes_gate}",
        "",
        "agreement:",
        f"  exact:        {report.exact_agreement:.2f} (target >={0.60})",
        f"  within +/-1:  {report.within_one_agreement:.2f} (target >={0.80})",
        f"  direction:    {report.direction_agreement:.2f} (target >={0.80})",
        f"  signed bias:  {report.mean_signed_bias:+.2f}",
        "",
        f"position bias consistency: {report.position_bias.get('consistency_rate')} (target >={0.75})",
        f"length bias mean signed gap: {report.length_bias.get('mean_signed_gap')} "
        f"(|gap| target <={0.5})",
    ]
    if report.gate_failures:
        lines.append("")
        lines.append("gate failures:")
        for f in report.gate_failures:
            lines.append(f"  - {f}")
    if report.disagreements:
        lines.append("")
        lines.append("disagreements (|diff|>=2):")
        for d in report.disagreements:
            lines.append(
                f"  - {d['id']} ({d['dimension']}): human={d['human']} "
                f"judge={d['judge']} | {d['note']}"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())