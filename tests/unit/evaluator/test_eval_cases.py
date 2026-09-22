"""C4.1: load golden evals and map fixtures onto the fault catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from skillforge.evaluator import EvalLoadError, load_eval_cases

_REPO = Path(__file__).resolve().parents[3]
_GOLDEN = _REPO / "skills" / "golden" / "service-recovery"
_CATALOG = _REPO / "demo" / "ops-lab" / "faults" / "catalog.yaml"
_VERIFIER_FIELDS = {
    "http_status",
    "backend_running",
    "nginx_config_valid",
    "upstream_port_matches",
    "db_running",
}
_FAULT_IDS = (
    "backend_stopped",
    "nginx_wrong_upstream",
    "nginx_bad_config_reload",
)


def test_golden_evals_load() -> None:
    loaded = load_eval_cases(_GOLDEN, _CATALOG)
    assert [item.fault_id for item in loaded] == list(_FAULT_IDS)
    assert [item.case.fixture for item in loaded] == list(_FAULT_IDS)
    for item in loaded:
        assert set(item.case.expected) == _VERIFIER_FIELDS
        assert item.case.forbidden == ["delete_volume", "restart_database"]
        assert item.case.timeout_sec == 180


def test_skill_dir_and_evals_file_match() -> None:
    from_dir = load_eval_cases(_GOLDEN)
    from_file = load_eval_cases(_GOLDEN / "evals" / "evals.json")
    assert [item.model_dump() for item in from_dir] == [item.model_dump() for item in from_file]


def test_fixture_maps_to_catalog_fault_id(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path, [("backend_stopped", "f1_fixture")])
    skill = _write_evals(tmp_path / "skill", [_case(fixture="f1_fixture")])
    loaded = load_eval_cases(skill, catalog)
    assert loaded[0].case.fixture == "f1_fixture"
    assert loaded[0].fault_id == "backend_stopped"


def test_unknown_fixture_raises(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path, [("backend_stopped", "backend_stopped")])
    skill = _write_evals(tmp_path / "skill", [_case(fixture="missing_fault")])
    with pytest.raises(EvalLoadError, match="unknown fixture 'missing_fault'"):
        load_eval_cases(skill, catalog)


def test_duplicate_id_raises(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path, [("backend_stopped", "backend_stopped")])
    skill = _write_evals(tmp_path / "skill", [_case(), _case(name="again")])
    with pytest.raises(EvalLoadError, match="duplicate eval case id"):
        load_eval_cases(skill, catalog)


def test_unexpected_expected_key_raises(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path, [("backend_stopped", "backend_stopped")])
    skill = _write_evals(tmp_path / "skill", [_case(expected={"http_status": 200, "extra": True})])
    with pytest.raises(EvalLoadError, match="unexpected expected keys"):
        load_eval_cases(skill, catalog)


def test_missing_evals_raises(tmp_path: Path) -> None:
    with pytest.raises(EvalLoadError, match="evals.json not found"):
        load_eval_cases(tmp_path / "missing-skill")


def test_evals_root_must_be_a_list(tmp_path: Path) -> None:
    catalog = _write_catalog(tmp_path, [("backend_stopped", "backend_stopped")])
    skill = tmp_path / "skill"
    path = skill / "evals" / "evals.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(EvalLoadError, match="root must be a list"):
        load_eval_cases(skill, catalog)


def _case(**overrides: object) -> dict[str, object]:
    case: dict[str, object] = {
        "id": "eval_backend_stopped",
        "name": "backend process stopped",
        "task": "Restore it.",
        "fixture": "backend_stopped",
        "expected": {"http_status": 200},
        "forbidden": ["delete_volume"],
        "timeout_sec": 180,
    }
    case.update(overrides)
    return case


def _write_evals(root: Path, cases: list[dict[str, object]]) -> Path:
    path = root / "evals" / "evals.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cases), encoding="utf-8")
    return root


def _write_catalog(root: Path, faults: list[tuple[str, str]]) -> Path:
    path = root / "catalog.yaml"
    payload = {"faults": [{"id": fault_id, "fixture": fixture} for fault_id, fixture in faults]}
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path
