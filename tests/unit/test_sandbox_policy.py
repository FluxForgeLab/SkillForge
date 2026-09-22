from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from skillforge.domain.errors import PolicyViolation
from skillforge.sandbox.base import ExecResult, Sandbox
from skillforge.sandbox.policy import SandboxPolicy, load_default_policy

_SANDBOX_ROOT = Path(__file__).resolve().parents[2] / "skillforge" / "sandbox"


class FakeSandbox(Sandbox):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[str] = []
        self.reads: list[str] = []
        self.writes: list[tuple[str, str]] = []
        self.destroyed = False

    async def _create(self) -> None:
        return None

    async def _exec(self, command: str, *, timeout_sec: float) -> ExecResult:
        self.commands.append(command)
        return ExecResult(exit_code=0, stdout="ok", stderr="")

    async def _read_file(self, path: str) -> str:
        self.reads.append(path)
        return "data"

    async def _write_file(self, path: str, content: str) -> None:
        self.writes.append((path, content))

    async def _destroy(self) -> None:
        self.destroyed = True


class FailingCreateSandbox(FakeSandbox):
    async def _create(self) -> None:
        raise RuntimeError("create failed")


def _policy() -> SandboxPolicy:
    return load_default_policy()


async def _open() -> FakeSandbox:
    sandbox = FakeSandbox()
    await sandbox.create(policy=_policy(), workspace=Path("/tmp/workspace"))
    return sandbox


def test_default_policy_matches_contract() -> None:
    policy = _policy()
    assert policy.network.mode == "restricted"
    assert policy.network.allow == ["localhost", "127.0.0.1"]
    assert policy.filesystem.read == ["/workspace"]
    assert policy.filesystem.write == ["/workspace/runtime"]
    assert policy.process.deny == ["sudo", "mount", "shutdown", "rm"]
    assert policy.dangerous_operations.require_approval is True


def test_policy_rejects_extra_and_missing_fields() -> None:
    with pytest.raises(ValidationError):
        SandboxPolicy.model_validate({"network": {"mode": "restricted", "allow": []}})
    loaded = _policy().model_dump()
    loaded["extra"] = True
    with pytest.raises(ValidationError):
        SandboxPolicy.model_validate(loaded)


def test_sandbox_is_abstract() -> None:
    with pytest.raises(TypeError):
        Sandbox()


def test_sandbox_package_does_not_import_docker() -> None:
    for path in _SANDBOX_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import docker" not in text
        assert "from docker" not in text


async def test_read_and_write_follow_policy_roots() -> None:
    sandbox = await _open()
    assert await sandbox.read_file("/workspace/a") == "data"
    assert sandbox.reads == ["/workspace/a"]
    await sandbox.write_file("/workspace/runtime/a", "body")
    assert sandbox.writes == [("/workspace/runtime/a", "body")]

    with pytest.raises(PolicyViolation) as read_denied:
        await sandbox.read_file("/etc/passwd")
    assert read_denied.value.kind == "filesystem"
    assert sandbox.reads == ["/workspace/a"]

    with pytest.raises(PolicyViolation):
        await sandbox.read_file("/workspace/../etc/passwd")
    with pytest.raises(PolicyViolation) as write_denied:
        await sandbox.write_file("/workspace/a", "nope")
    assert write_denied.value.kind == "filesystem"
    assert sandbox.writes == [("/workspace/runtime/a", "body")]


async def test_denied_commands_never_reach_exec() -> None:
    sandbox = await _open()
    result = await sandbox.exec("echo ok", timeout_sec=5)
    assert result.stdout == "ok"
    assert sandbox.commands == ["echo ok"]

    for command in ("sudo id", "mount /dev", "shutdown -h now", "rm -rf /"):
        with pytest.raises(PolicyViolation) as denied:
            await sandbox.exec(command, timeout_sec=5)
        assert denied.value.kind == "process"
    assert sandbox.commands == ["echo ok"]


async def test_exec_before_create_is_rejected() -> None:
    sandbox = FakeSandbox()
    with pytest.raises(PolicyViolation) as denied:
        await sandbox.exec("echo ok", timeout_sec=1)
    assert denied.value.name == "sandbox"
    assert sandbox.commands == []


async def test_failed_create_does_not_open_sandbox() -> None:
    sandbox = FailingCreateSandbox()
    with pytest.raises(RuntimeError, match="create failed"):
        await sandbox.create(policy=_policy(), workspace=Path("/tmp/workspace"))
    assert sandbox.policy is None
    with pytest.raises(PolicyViolation):
        await sandbox.exec("echo ok", timeout_sec=1)


async def test_destroy_clears_policy() -> None:
    sandbox = await _open()
    await sandbox.destroy()
    assert sandbox.destroyed is True
    assert sandbox.policy is None
    with pytest.raises(PolicyViolation):
        await sandbox.exec("echo ok", timeout_sec=1)
