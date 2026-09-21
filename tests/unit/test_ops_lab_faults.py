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
    sys.modules.pop("catalog", None)
    sys.modules.pop("inject", None)
    sys.modules.pop("reset", None)
    dockerutil = importlib.import_module("dockerutil")
    nginxfault = importlib.import_module("nginxfault")
    inject = importlib.import_module("inject")
    reset = importlib.import_module("reset")
    return dockerutil, nginxfault, inject, reset


class FakeContainer:
    def __init__(
        self,
        service: str,
        *,
        running: bool = True,
        health: str = "healthy",
        exec_exit_codes: list[int] | None = None,
    ) -> None:
        self.service = service
        self.stop_calls = 0
        self.start_calls = 0
        self.exec_calls: list[list[str]] = []
        self.exec_exit_code = 0
        self._exec_exit_codes = list(exec_exit_codes) if exec_exit_codes is not None else None
        self._exec_index = 0
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
        if self._exec_exit_codes is not None:
            index = min(self._exec_index, len(self._exec_exit_codes) - 1)
            code = self._exec_exit_codes[index]
            self._exec_index += 1
        else:
            code = self.exec_exit_code
        return SimpleNamespace(exit_code=code)


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

    def fake_write(port: int) -> None:
        restored.append(port)

    monkeypatch.setattr(reset, "project_name", lambda: "skillforge-lab")
    monkeypatch.setattr(reset, "write_upstream_port", fake_write)
    monkeypatch.setattr(reset, "restart_service", lambda _c, _p, _s: None)
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


def test_reload_nginx_upstream_if_running_skips_when_stopped() -> None:
    _dockerutil, nginxfault, _inject, _reset = _load_faults()
    nginx = FakeContainer("nginx", running=False)
    client = FakeClient({"nginx": nginx})
    nginxfault.reload_nginx_upstream_if_running(client, "skillforge-lab")
    assert nginx.exec_calls == []


def test_write_f3_invalid_conf_keeps_upstream_port() -> None:
    _dockerutil, nginxfault, _inject, _reset = _load_faults()
    render = nginxfault._render_module()
    original = render.CONF_PATH.read_text(encoding="utf-8")
    try:
        nginxfault.write_f3_invalid_conf()
        text = render.CONF_PATH.read_text(encoding="utf-8")
        assert "server backend:8081;" in text
        assert nginxfault.F3_INVALID_DIRECTIVE in text
    finally:
        render.CONF_PATH.write_text(original, encoding="utf-8")


def test_inject_f3_applies_upstream_then_invalid_conf_without_second_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dockerutil, _nginxfault, inject, _reset = _load_faults()
    backend = FakeContainer("backend")
    nginx = FakeContainer("nginx", exec_exit_codes=[1])
    client = FakeClient({"backend": backend, "nginx": nginx})
    phases: list[str] = []

    def fake_f3(client, project: str) -> None:
        phases.append("apply")
        phases.append("invalid")
        try:
            dockerutil.nginx_test(client, project)
        except RuntimeError:
            return

    monkeypatch.setattr(inject, "project_name", lambda: "skillforge-lab")
    monkeypatch.setattr(inject, "inject_f3_bad_config_reload", fake_f3)
    inject.inject("nginx_bad_config_reload", client=client)
    assert phases == ["apply", "invalid"]
    assert backend.stop_calls == 0
    assert nginx.exec_calls == [["nginx", "-t"]]
    assert "nginx -s reload" not in str(nginx.exec_calls)


def test_inject_main_f3_exits_zero_when_nginx_test_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dockerutil, _nginxfault, inject, _reset = _load_faults()

    def fake_f3(_client, _project: str) -> None:
        return

    monkeypatch.setattr(inject, "inject_f3_bad_config_reload", fake_f3)
    assert inject.main(["nginx_bad_config_reload"]) == 0


def test_reset_all_is_reset() -> None:
    _dockerutil, _nginxfault, _inject, reset = _load_faults()
    assert reset.reset_all is reset.reset
