"""Write BENCHMARK.md and benchmark.json from a suite report."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from skillforge.domain.entities import EvaluationRun
from skillforge.evaluator.suite import SuiteReport


def write_benchmark(report: SuiteReport, version_dir: Path) -> tuple[Path, Path]:
    """Write headline metrics and per-case matrix into ``version_dir``."""
    version_dir.mkdir(parents=True, exist_ok=True)
    cases = _per_case_rows(report.runs)
    regression_count = sum(
        1 for row in cases if row["treatment_success_rate"] < row["control_success_rate"]
    )
    payload = {
        "task_success_rate": {
            "control": report.control.success_rate,
            "treatment": report.treatment.success_rate,
        },
        "skill_uplift_pp": report.uplift_pp,
        "regression_count": regression_count,
        "policy_violations": {
            "control": report.control.policy_violations,
            "treatment": report.treatment.policy_violations,
        },
        "recovery_time_ms": {
            "control": report.control.avg_latency,
            "treatment": report.treatment.avg_latency,
        },
        "cases": cases,
    }
    md_path = version_dir / "BENCHMARK.md"
    json_path = version_dir / "benchmark.json"
    md_path.write_text(_render_markdown(payload), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return md_path, json_path


def _per_case_rows(runs: list[EvaluationRun]) -> list[dict[str, float | str]]:
    by_case: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: {"control": [], "treatment": []}
    )
    for run in runs:
        case_id = str(run.metrics["case_id"])
        arm = "control" if run.baseline.get("baseline") is True else "treatment"
        by_case[case_id][arm].append(run.metrics.get("passed") is True)

    rows: list[dict[str, float | str]] = []
    for case_id in sorted(by_case):
        control_trials = by_case[case_id]["control"]
        treatment_trials = by_case[case_id]["treatment"]
        control_rate = sum(control_trials) / len(control_trials) if control_trials else 0.0
        treatment_rate = sum(treatment_trials) / len(treatment_trials) if treatment_trials else 0.0
        rows.append(
            {
                "case_id": case_id,
                "control_success_rate": control_rate,
                "treatment_success_rate": treatment_rate,
                "uplift_pp": (treatment_rate - control_rate) * 100,
            }
        )
    return rows


def _pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _pp(value: float) -> str:
    return f"{value:+.1f} pp"


def _ms(value: float) -> str:
    return f"{value:.1f} ms"


def _render_markdown(payload: dict) -> str:
    task = payload["task_success_rate"]
    policy = payload["policy_violations"]
    recovery = payload["recovery_time_ms"]
    lines = [
        "# Benchmark",
        "",
        "## Headline Metrics",
        "",
        f"- Task Success Rate: control {_pct(task['control'])}, "
        f"treatment {_pct(task['treatment'])}",
        f"- Skill Uplift: {_pp(payload['skill_uplift_pp'])}",
        f"- Regression Count: {payload['regression_count']}",
        f"- Policy Violations: control {policy['control']}, treatment {policy['treatment']}",
        f"- Recovery Time: control {_ms(recovery['control'])}, "
        f"treatment {_ms(recovery['treatment'])}",
        "",
        "## Cases",
        "",
    ]
    for case in payload["cases"]:
        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"- control_success_rate: {_pct(case['control_success_rate'])}",
                f"- treatment_success_rate: {_pct(case['treatment_success_rate'])}",
                f"- uplift_pp: {_pp(case['uplift_pp'])}",
                "",
            ]
        )
    return "\n".join(lines)
