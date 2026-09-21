from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_FAULTS_DIR = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "faults"


def _load_incident():
    if str(_FAULTS_DIR) not in sys.path:
        sys.path.insert(0, str(_FAULTS_DIR))
    sys.modules.pop("catalog", None)
    sys.modules.pop("incident", None)
    return importlib.import_module("incident")


@pytest.mark.parametrize(
    "fault_id",
    ["backend_stopped", "nginx_wrong_upstream", "nginx_bad_config_reload"],
)
def test_build_incident_required_fields(fault_id: str) -> None:
    incident = _load_incident()
    payload = incident.build_incident(fault_id)
    assert payload["fault_id"] == fault_id
    assert payload["fixture"] == fault_id
    assert payload["label"] in {"F1", "F2", "F3"}
    assert payload["title"]
    assert payload["summary"]
    assert isinstance(payload["symptoms"], list) and payload["symptoms"]
    assert payload["endpoint"] == "http://127.0.0.1:8088/health"
    assert payload["compose_project"] == "skillforge-lab"
    json.dumps(payload)


def test_incident_main_unknown_fault_exits_one() -> None:
    incident = _load_incident()
    assert incident.main(["unknown"]) == 1


def test_incident_main_known_fault_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    incident = _load_incident()
    assert incident.main(["backend_stopped"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["fault_id"] == "backend_stopped"
