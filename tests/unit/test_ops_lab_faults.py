from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_FAULTS_DIR = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "faults"


def _load_faults():
    if str(_FAULTS_DIR) not in sys.path:
        sys.path.insert(0, str(_FAULTS_DIR))
    sys.modules.pop("dockerutil", None)
    sys.modules.pop("inject", None)
    sys.modules.pop("reset", None)
    dockerutil = importlib.import_module("dockerutil")
    inject = importlib.import_module("inject")
    reset = importlib.import_module("reset")
    return dockerutil, inject, reset


class FakeContainer:
    def __init__(self, service: str, *, running: bool = True, health: str = "healthy") -> None:
        self.service = service
        self.stop_calls = 0
        self.start_calls = 0
        self.attrs = {"State": {"Running": running, "Health": {"Status": health}}}

    def reload(self) -> None:
        return None

    def stop(self) -> None:
        self.stop_calls += 1
        self.attrs["State"]["Running"] = False

    def start(self) -> None:
        self.start_calls += 1
        self.attrs["State"]["Running"] = True
        health = self.attrs["State"].get("Health")
        if health is None:
            self.attrs["State"]["Health"] = {"Status": "healthy"}
        else:
            health["Status"] = "healthy"


class FakeClient:
    def __init__(self, containers: dict[str, FakeContainer]) -> None:
        self._containers = containers
        self.containers = SimpleNamespace(list=self._list)

    def _list(self, all: bool = True, filters: dict | None = None) -> list[FakeContainer]:
        del all
        service = None
        for label in (filters or {}).get("label", []):
            if label.startswith("com.docker.compose.service="):
                service = label.split("=", 1)[1]
        if service is None or service not in self._containers:
            return []
        return [self._containers[service]]


def test_inject_backend_stopped_stops_only_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    dockerutil, inject, _reset = _load_faults()
    backend = FakeContainer("backend")
    mock_db = FakeContainer("mock-db")
    nginx = FakeContainer("nginx")
    client = FakeClient({"backend": backend, "mock-db": mock_db, "nginx": nginx})
    monkeypatch.setattr(inject, "project_name", lambda: "skillforge-lab")
    inject.inject("backend_stopped", client=client)
    assert backend.stop_calls == 1
    assert mock_db.stop_calls == 0
    assert nginx.stop_calls == 0


def test_inject_unknown_fault_id_raises() -> None:
    _dockerutil, inject, _reset = _load_faults()
    with pytest.raises(ValueError, match="unknown fault_id"):
        inject.inject("not-a-fault")


def test_inject_main_unknown_fault_exits_one() -> None:
    _dockerutil, inject, _reset = _load_faults()
    assert inject.main(["nope"]) == 1


def test_stop_service_refuses_mock_db() -> None:
    dockerutil, _inject, _reset = _load_faults()
    mock_db = FakeContainer("mock-db")
    client = FakeClient({"mock-db": mock_db})
    with pytest.raises(PermissionError, match="mock-db"):
        dockerutil.stop_service(client, "skillforge-lab", "mock-db")
    assert mock_db.stop_calls == 0


def test_reset_starts_backend_and_nginx(monkeypatch: pytest.MonkeyPatch) -> None:
    _dockerutil, _inject, reset = _load_faults()
    backend = FakeContainer("backend", running=False, health="starting")
    nginx = FakeContainer("nginx", running=False, health="")
    nginx.attrs["State"]["Health"] = None
    client = FakeClient({"backend": backend, "nginx": nginx})
    monkeypatch.setattr(reset, "project_name", lambda: "skillforge-lab")
    reset.reset(client=client)
    assert backend.start_calls == 1
    assert nginx.start_calls == 1
    assert backend.attrs["State"]["Running"] is True
    assert nginx.attrs["State"]["Running"] is True
