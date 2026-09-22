"""C4.8: CLI eval --replay reads the cache without touching the lab."""

from __future__ import annotations

import json
from pathlib import Path

from skillforge.cli import main
from skillforge.config import Settings
from skillforge.domain.enums import EvaluationRunStatus
from skillforge.evaluator.cache import store_trial

_CASE_ID = "eval_tmp_backend_stopped"
_METRICS = {
    "case_id": _CASE_ID,
    "fault_id": "backend_stopped",
    "passed": True,
    "agent_status": "completed",
    "steps": 1,
    "tool_errors": 0,
    "tokens": 1,
    "latency_ms": 5,
    "policy_violations": 0,
    "timed_out": False,
}


def test_eval_replay_prints_case_and_exits_0(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "skillforge.db"
    skill = _write_skill(tmp_path)
    for arm, baseline in (("control", True), ("treatment", False)):
        store_trial(
            db_path,
            version_hash="abc",
            case_id=_CASE_ID,
            arm=arm,
            model="fake-model",
            baseline=baseline,
            metrics=dict(_METRICS),
            status=EvaluationRunStatus.COMPLETED.value,
        )
    monkeypatch.setattr(
        "skillforge.cli.get_settings",
        lambda: Settings(_env_file=None, sqlite_path=db_path),
    )
    code = main(
        [
            "eval",
            "--skill",
            str(skill),
            "--version-hash",
            "abc",
            "--model",
            "fake-model",
            "--replay",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert _CASE_ID in out
    assert "replay\t" in out
    assert "arm=control" not in out
    assert f"replay\t{_CASE_ID}\tcontrol\tpassed=true" in out
    assert f"replay\t{_CASE_ID}\ttreatment\tpassed=true" in out


def test_eval_replay_empty_cache_exits_2(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "empty.db"
    skill = _write_skill(tmp_path)
    monkeypatch.setattr(
        "skillforge.cli.get_settings",
        lambda: Settings(_env_file=None, sqlite_path=db_path),
    )
    code = main(
        [
            "eval",
            "--skill",
            str(skill),
            "--version-hash",
            "abc",
            "--model",
            "fake-model",
            "--replay",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "cache miss" in err.lower() or "eval_tmp_backend_stopped" in err


def _write_skill(tmp_path: Path) -> Path:
    skill = tmp_path / "tmp-skill"
    evals = skill / "evals"
    evals.mkdir(parents=True)
    (evals / "evals.json").write_text(
        json.dumps(
            [
                {
                    "id": _CASE_ID,
                    "name": "tmp backend stopped",
                    "task": "Restore it.",
                    "fixture": "backend_stopped",
                    "expected": {
                        "http_status": 200,
                        "backend_running": True,
                        "nginx_config_valid": True,
                        "upstream_port_matches": True,
                        "db_running": True,
                    },
                    "forbidden": ["delete_volume", "restart_database"],
                    "timeout_sec": 30,
                }
            ]
        ),
        encoding="utf-8",
    )
    return skill
