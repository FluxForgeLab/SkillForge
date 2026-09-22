from __future__ import annotations

import os
from pathlib import Path

import pytest
from docker.errors import NotFound

import docker
from skillforge.config import get_settings
from skillforge.domain.entities import TraceEvent
from skillforge.domain.enums import TraceEventType
from skillforge.domain.errors import PolicyViolation
from skillforge.sandbox.docker import DockerSandbox
from skillforge.sandbox.policy import load_default_policy
from skillforge.tracing.bus import EventBus

_IMAGE_CONTEXT = Path(__file__).resolve().parents[2] / "docker" / "sandbox"


class ListSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def write(self, event: TraceEvent) -> None:
        self.events.append(event)


@pytest.fixture(scope="session")
def sandbox_image(docker_available: None) -> str:
    client = docker.from_env()
    image = get_settings().sandbox_image
    try:
        _built, logs = client.images.build(path=str(_IMAGE_CONTEXT), tag=image, rm=True)
        for _item in logs:
            pass
    finally:
        client.close()
    return image


async def _open(tmp_path: Path, image: str, sink: ListSink) -> DockerSandbox:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    os.chmod(workspace, 0o777)
    sandbox = DockerSandbox(run_id="run_c33", sink=sink, bus=EventBus(), image=image)
    await sandbox.create(policy=load_default_policy(), workspace=workspace)
    return sandbox


def _assert_removed(container_id: str) -> None:
    client = docker.from_env()
    try:
        with pytest.raises(NotFound):
            client.containers.get(container_id)
    finally:
        client.close()


@pytest.mark.integration
async def test_echo_write_read_sudo_and_sandbox_created(
    tmp_path: Path,
    sandbox_image: str,
) -> None:
    sink = ListSink()
    sandbox = await _open(tmp_path, sandbox_image, sink)
    try:
        echoed = await sandbox.exec("echo ok", timeout_sec=5)
        assert echoed.exit_code == 0
        assert "ok" in echoed.stdout

        identity = await sandbox.exec("id -u", timeout_sec=5)
        assert identity.stdout.strip() == "1000"

        await sandbox.write_file("/workspace/runtime/note.txt", "hello")
        assert await sandbox.read_file("/workspace/runtime/note.txt") == "hello"
        listed = await sandbox.exec("cat /workspace/runtime/note.txt", timeout_sec=5)
        assert listed.stdout.strip() == "hello"

        with pytest.raises(PolicyViolation) as denied:
            await sandbox.exec("sudo id", timeout_sec=5)
        assert denied.value.kind == "process"

        assert len(sink.events) == 1
        event = sink.events[0]
        assert event.type is TraceEventType.SANDBOX_CREATED
        assert event.name == "docker"
        assert event.stage == "runtime"
        assert event.run_id == "run_c33"
        assert event.input["workspace"] == "/workspace"
        assert event.input["image"] == sandbox_image
        container_id = event.output["container_id"]
        assert isinstance(container_id, str) and container_id
    finally:
        container_id = sink.events[0].output["container_id"] if sink.events else ""
        await sandbox.destroy()
    if container_id:
        _assert_removed(container_id)


@pytest.mark.integration
async def test_exec_timeout_then_destroy(tmp_path: Path, sandbox_image: str) -> None:
    sink = ListSink()
    sandbox = await _open(tmp_path, sandbox_image, sink)
    container_id = sink.events[0].output["container_id"]
    try:
        with pytest.raises(TimeoutError):
            await sandbox.exec("sleep 30", timeout_sec=1)
    finally:
        await sandbox.destroy()
    _assert_removed(container_id)
