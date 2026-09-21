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
    sys.modules.pop("nginxfault", None)
    sys.modules.pop("inject", None)
    sys.modules.pop("reset", None)
    dockerutil = importlib.import_module("dockerutil")
    nginxfault = importlib.import_module("nginxfault")
    inject = importlib.import_module("inject")
    reset = importlib.import_module("reset")
    return dockerutil, nginxfault, inject, reset


class FakeContainer:
    def __init__(self, service: str, *, running: bool = True, health: str = "healthy") -> None:
        self.service = service
        self.stop_calls = 0
        self.start_calls = 0
        self.exec_calls: list[list[str]] = []
        self.exec_exit_code = 0
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

    def exec_run(self, cmd: list[str]):
        self.exec_calls.append(list(cmd))
        return SimpleNamespace(exit_code=self.exec_exit_code)


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
    dockerutil, _nginxfault, inject, _reset = _load_faults()
    backend = FakeContainer("backend")
    mock_db = FakeContainer("mock-db")
    nginx = FakeContainer("nginx")
    client = FakeClient({"backend": backend, "mock-db": mock_db, "nginx": nginx})
    monkeypatch.setattr(inject, "project_name", lambda: "skillforge-lab")
    inject.inject("backend_stopped", client=client)
    assert backend.stop_calls == 1
    assert mock_db.stop_calls == 0
    assert nginx.stop_calls == 0


def test_inject_nginx_wrong_upstream_reloads_without_stopping_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dockerutil, nginxfault, inject, _reset = _load_faults()
    backend = FakeContainer("backend")
    nginx = FakeContainer("nginx")
    client = FakeClient({"backend": backend, "nginx": nginx})
    ports: list[int] = []

    def fake_write(port: int) -> None:
        ports.append(port)

    monkeypatch.setattr(inject, "project_name", lambda: "skillforge-lab")
    monkeypatch.setattr(nginxfault, "write_upstream_port", fake_write)
    inject.inject("nginx_wrong_upstream", client=client)
    assert ports == [8081]
    assert backend.stop_calls == 0
    assert nginx.exec_calls == [["nginx", "-t"], ["nginx", "-s", "reload"]]


def test_apply_upstream_port_skips_reload_when_nginx_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dockerutil, nginxfault, _inject, _reset = _load_faults()
    nginx = FakeContainer("nginx", running=False)
    client = FakeClient({"nginx": nginx})
    ports: list[int] = []

    monkeypatch.setattr(nginxfault, "write_upstream_port", lambda port: ports.append(port))
    nginxfault.apply_upstream_port(8081, client, "skillforge-lab")
    assert ports == [8081]
    assert nginx.exec_calls == []


def test_nginx_test_failure_aborts_before_reload() -> None:
    dockerutil, _nginxfault, _inject, _reset = _load_faults()
    nginx = FakeContainer("nginx")
    nginx.exec_exit_code = 1
    client = FakeClient({"nginx": nginx})
    with pytest.raises(RuntimeError, match="nginx -t failed"):
        dockerutil.nginx_test(client, "skillforge-lab")
    assert nginx.exec_calls == [["nginx", "-t"]]


def test_inject_unknown_fault_id_raises() -> None:
    _dockerutil, _nginxfault, inject, _reset = _load_faults()
    with pytest.raises(ValueError, match="unknown fault_id"):
        inject.inject("not-a-fault")


def test_inject_main_unknown_fault_exits_one() -> None:
    _dockerutil, _nginxfault, inject, _reset = _load_faults()
    assert inject.main(["nope"]) == 1


def test_stop_service_refuses_mock_db() -> None:
    dockerutil, _nginxfault, _inject, _reset = _load_faults()
    mock_db = FakeContainer("mock-db")
    client = FakeClient({"mock-db": mock_db})
    with pytest.raises(PermissionError, match="mock-db"):
        dockerutil.stop_service(client, "skillforge-lab", "mock-db")
    assert mock_db.stop_calls == 0


def test_reset_starts_backend_and_nginx(monkeypatch: pytest.MonkeyPatch) -> None:
    _dockerutil, _nginxfault, _inject, reset = _load_faults()
    backend = FakeContainer("backend", running=False, health="starting")
    nginx = FakeContainer("nginx", running=False, health="")
    nginx.attrs["State"]["Health"] = None
    client = FakeClient({"backend": backend, "nginx": nginx})
    restored: list[int] = []

    def fake_restore(docker, project: str, *, port: int = 8080) -> None:
        del docker, project
        restored.append(port)

    monkeypatch.setattr(reset, "project_name", lambda: "skillforge-lab")
    monkeypatch.setattr(reset, "restore_nginx_upstream", fake_restore)
    reset.reset(client=client)
    assert restored == [8080]
    assert backend.start_calls == 1
    assert nginx.start_calls == 1
    assert backend.attrs["State"]["Running"] is True
    assert nginx.attrs["State"]["Running"] is True


def test_reset_restore_reloads_when_nginx_running(monkeypatch: pytest.MonkeyPatch) -> None:
    _dockerutil, nginxfault, _inject, _reset = _load_faults()
    nginx = FakeContainer("nginx")
    client = FakeClient({"nginx": nginx})
    ports: list[int] = []

    monkeypatch.setattr(nginxfault, "write_upstream_port", lambda port: ports.append(port))
    nginxfault.restore_nginx_upstream(client, "skillforge-lab")
    assert ports == [8080]
    assert nginx.exec_calls == [["nginx", "-t"], ["nginx", "-s", "reload"]]
