"""Pretty-print an eval RunReport to the terminal.

Aggregate header, per-class table, fail-list. Three layers of detail
because Module 6 said: aggregates can hide failures, per-case is
non-negotiable.
"""

from __future__ import annotations

from evals.runner.run import RunReport


def render(report: RunReport) -> str:
    """Multi-section text report. No colour - keeps grep-ability."""
    out: list[str] = []
    out.append(_header(report))
    out.append("")
    out.append(_per_class_table(report))
    out.append("")
    out.append(_fail_list(report))
    return "\n".join(out)


def _header(report: RunReport) -> str:
    return (
        f"=== AW Analysis eval run {report.run_id} ===\n"
        f"prompt: {report.prompt_version}  "
        f"judge: {report.judge_rubric_version}\n"
        f"overall: {report.passed_count}/{report.total_count} "
        f"({report.pass_rate:.0%})"
    )


def _per_class_table(report: RunReport) -> str:
    by_class = report.by_class()
    if not by_class:
        return "(no cases)"
    rows = ["per-class breakdown:"]
    rows.append(
        f"{'class':<22}{'pass':>10}{'faith':>10}{'rel':>10}"
    )
    for cls, results in sorted(by_class.items(), key=lambda kv: kv[0].value):
        passed = sum(1 for r in results if r.overall_passed)
        total = len(results)
        mean_f = sum(r.judge.faithfulness for r in results) / total
        mean_r = sum(r.judge.relevance for r in results) / total
        rows.append(
            f"{cls.value:<22}{f'{passed}/{total}':>10}{mean_f:>10.2f}{mean_r:>10.2f}"
        )
    return "\n".join(rows)


def _fail_list(report: RunReport) -> str:
    failures = [r for r in report.cases if not r.overall_passed]
    if not failures:
        return "no failures"
    lines = ["failures:"]
    for r in failures:
        lines.append(f"  - {r.case_id} ({r.query_class.value}): {r.failure_summary}")
        det_fails = [ar for ar in r.deterministic if not ar.passed]
        for ar in det_fails:
            lines.append(
                f"      [{ar.assertion.severity.value}] "
                f"{ar.assertion.kind.value}({ar.assertion.target}) -> {ar.detail}"
            )
    return "\n".join(lines)