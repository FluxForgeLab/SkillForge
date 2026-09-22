"""Sandbox port. Implementations provide container lifecycle; policy checks stay here."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from skillforge.domain.errors import PolicyViolation
from skillforge.sandbox.policy import SandboxPolicy


class ExecResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_code: int
    stdout: str
    stderr: str


class Sandbox(ABC):
    def __init__(self) -> None:
        self.policy: SandboxPolicy | None = None
        self.workspace: Path | None = None

    async def create(self, *, policy: SandboxPolicy, workspace: Path) -> None:
        self.policy = policy
        self.workspace = workspace
        try:
            await self._create()
        except Exception:
            self.policy = None
            self.workspace = None
            raise

    async def exec(self, command: str, *, timeout_sec: float) -> ExecResult:
        policy = self._require_open()
        denied = policy.denied_command(command)
        if denied is not None:
            raise PolicyViolation(kind="process", name=denied, detail=command)
        return await self._exec(command, timeout_sec=timeout_sec)

    async def read_file(self, path: str) -> str:
        policy = self._require_open()
        policy.ensure_read(path)
        return await self._read_file(path)

    async def write_file(self, path: str, content: str) -> None:
        policy = self._require_open()
        policy.ensure_write(path)
        await self._write_file(path, content)

    async def destroy(self) -> None:
        try:
            await self._destroy()
        finally:
            self.policy = None
            self.workspace = None

    def _require_open(self) -> SandboxPolicy:
        if self.policy is None:
            raise PolicyViolation(kind="process", name="sandbox", detail="sandbox is not created")
        return self.policy

    @abstractmethod
    async def _create(self) -> None: ...

    @abstractmethod
    async def _exec(self, command: str, *, timeout_sec: float) -> ExecResult: ...

    @abstractmethod
    async def _read_file(self, path: str) -> str: ...

    @abstractmethod
    async def _write_file(self, path: str, content: str) -> None: ...

    @abstractmethod
    async def _destroy(self) -> None: ...
