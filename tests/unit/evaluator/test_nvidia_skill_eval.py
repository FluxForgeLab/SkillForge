"""C10.4: mock SkillEvaluator tiers and an optional CLI wrapper."""

from __future__ import annotations

from pathlib import Path

from skillforge.cli import main
from skillforge.evaluator.benchmark import write_benchmark
from skillforge.evaluator.nvidia import evaluate_skill, mock_skill_evaluation
from skillforge.evaluator.suite import summarize
from tests.unit.evaluator.test_benchmark import _run

_GOLDEN = Path(__file__).resolve().parents[3] / "skills" / "golden" / "service-recovery"


def test_mock_reports_three_tiers() -> None:
    rows = mock_skill_evaluation(_GOLDEN)
    assert [row.tier for row in rows] == [
        "tier1_validation",
        "tier2_deduplication",
        "tier3_live",
    ]
    assert rows[0].passed is True
    assert rows[1].passed is True
    assert rows[2].passed is None
    assert all(row.source == "mock" for row in rows)


def test_missing_binary_uses_the_mock() -> None:
    rows = evaluate_skill(_GOLDEN, command="skillforge-skill-evaluator-missing")
    assert rows[0].source == "mock"


def test_cli_prints_mock_tiers(capsys) -> None:
    code = main(["skill-eval", "--skill", str(_GOLDEN)])
    assert code == 0
    out = capsys.readouterr().out
    assert "tier1_validation\tpass\tmock" in out
    assert "tier3_live\tnot-run\tmock" in out


def test_benchmark_includes_skill_evaluator_section(tmp_path: Path) -> None:
    runs = [
        _run("a_c0", baseline=True, case_id="eval_a", passed=True, latency=100, policy=0),
        _run("a_t0", baseline=False, case_id="eval_a", passed=True, latency=80, policy=0),
    ]
    report = summarize(runs, skill_version_id="ver_1", repeats=1)
    md_path, json_path = write_benchmark(
        report,
        tmp_path,
        skill_eval=mock_skill_evaluation(_GOLDEN),
    )
    text = md_path.read_text(encoding="utf-8")
    assert "## NVIDIA SkillEvaluator" in text
    assert "tier3_live: not run (mock)" in text
    payload = json_path.read_text(encoding="utf-8")
    assert "tier1_validation" in payload
