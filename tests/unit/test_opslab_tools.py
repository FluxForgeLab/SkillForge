from pathlib import Path

import pytest

from skillforge.domain.errors import PolicyViolation
from skillforge.runtime.tools.opslab import (
    docker_restart,
    nginx_write_config,
    runtime_tools,
)
from skillforge.runtime.tools.sandbox import sandbox_tools


class FakeContainer:
    def __init__(self) -> None:
        self.restarted = False
        self.id = "cid-backend"
        self.attrs = {"State": {"Running": True}}

    def restart(self) -> None:
        self.restarted = True

    def reload(self) -> None:
        return None


class FakeContainers:
    def __init__(self, container: FakeContainer) -> None:
        self.container = container
        self.calls = 0

    def list(self, all: bool = True, filters: dict | None = None) -> list[FakeContainer]:
        del all
        self.calls += 1
        labels = (filters or {})["label"]
        assert "com.docker.compose.project=skillforge-lab" in labels
        assert "com.docker.compose.service=backend" in labels
        return [self.container]


class FakeClient:
    def __init__(self, container: FakeContainer) -> None:
        self.containers = FakeContainers(container)


def test_restart_mock_db_never_calls_docker() -> None:
    container = FakeContainer()
    client = FakeClient(container)
    with pytest.raises(PolicyViolation) as denied:
        docker_restart("mock-db", client=client, project="skillforge-lab")
    assert denied.value.name == "restart_database"
    assert client.containers.calls == 0
    assert container.restarted is False


def test_restart_backend_uses_project_label() -> None:
    container = FakeContainer()
    client = FakeClient(container)
    result = docker_restart("backend", client=client, project="skillforge-lab")
    assert result == {"service": "backend", "running": True}
    assert container.restarted is True
    assert client.containers.calls == 1


def test_nginx_write_rejects_rm_token(tmp_path: Path) -> None:
    path = tmp_path / "nginx.conf"
    path.write_text("original", encoding="utf-8")
    with pytest.raises(PolicyViolation) as denied:
        nginx_write_config("rm -rf /", conf_path=path)
    assert denied.value.name == "rm"
    assert path.read_text(encoding="utf-8") == "original"


def test_runtime_tools_add_opslab_without_changing_sandbox_registry() -> None:
    assert [spec.name for spec in sandbox_tools().specs()] == [
        "shell.read",
        "file.read",
        "file.write",
        "http.get",
    ]
    names = [spec.name for spec in runtime_tools().specs()]
    assert names[:4] == ["shell.read", "file.read", "file.write", "http.get"]
    assert "docker.restart" in names
    assert "delete_volume" not in names
    assert names.count("http.get") == 1
