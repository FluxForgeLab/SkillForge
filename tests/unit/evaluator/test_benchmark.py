"""C4.7: BENCHMARK.md and benchmark.json writer snapshot test."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from skillforge.domain.entities import EvaluationRun
from skillforge.domain.enums import EvaluationRunStatus
from skillforge.evaluator.benchmark import write_benchmark
from skillforge.evaluator.suite import summarize

_SNAPSHOTS = Path(__file__).resolve().parents[2] / "fixtures" / "snapshots"


def test_write_benchmark_matches_snapshots(tmp_path: Path) -> None:
    runs = [
        _run("a_c0", baseline=True, case_id="eval_a", passed=True, latency=100, policy=0),
        _run("a_c1", baseline=True, case_id="eval_a", passed=False, latency=300, policy=2),
        _run("a_t0", baseline=False, case_id="eval_a", passed=True, latency=80, policy=0),
        _run("a_t1", baseline=False, case_id="eval_a", passed=True, latency=120, policy=1),
        _run("b_c0", baseline=True, case_id="eval_b", passed=True, latency=10, policy=0),
        _run("b_t0", baseline=False, case_id="eval_b", passed=False, latency=40, policy=3),
    ]
    report = summarize(runs, skill_version_id="ver_1", repeats=1)
    version_dir = tmp_path / "skill_version"
    md_path, json_path = write_benchmark(report, version_dir)

    assert md_path == version_dir / "BENCHMARK.md"
    assert json_path == version_dir / "benchmark.json"
    assert md_path.read_text(encoding="utf-8") == (_SNAPSHOTS / "benchmark.md").read_text(
        encoding="utf-8"
    )
    assert json_path.read_text(encoding="utf-8") == (_SNAPSHOTS / "benchmark.json").read_text(
        encoding="utf-8"
    )


def _run(
    run_id: str,
    *,
    baseline: bool,
    case_id: str,
    passed: bool,
    latency: int,
    policy: int,
) -> EvaluationRun:
    now = datetime.now(UTC)
    return EvaluationRun(
        id=run_id,
        skill_version_id="ver_1",
        baseline={"baseline": baseline},
        metrics={
            "passed": passed,
            "case_id": case_id,
            "latency_ms": latency,
            "policy_violations": policy,
            "tool_errors": 0,
        },
        status=EvaluationRunStatus.COMPLETED,
        started_at=now,
        finished_at=now,
    )
