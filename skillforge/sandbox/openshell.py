"""OpenShell sandbox skeleton. The flag defaults off and the main path stays Docker.

The class implements the Sandbox port and fails closed. It does not launch OpenShell.
"""

from __future__ import annotations

import shutil

from skillforge.sandbox.base import ExecResult, Sandbox


class OpenShellUnavailable(RuntimeError):
    """Raised when OpenShell is selected but cannot run."""


class OpenShellSandbox(Sandbox):
    async def _create(self) -> None:
        if shutil.which("openshell") is None:
            raise OpenShellUnavailable("openshell is not on PATH")
        raise OpenShellUnavailable("OpenShellSandbox does not launch the binary")

    async def _exec(self, command: str, *, timeout_sec: float) -> ExecResult:
        del command, timeout_sec
        raise OpenShellUnavailable("OpenShellSandbox does not exec")

    async def _read_file(self, path: str) -> str:
        del path
        raise OpenShellUnavailable("OpenShellSandbox does not read files")

    async def _write_file(self, path: str, content: str) -> None:
        del path, content
        raise OpenShellUnavailable("OpenShellSandbox does not write files")

    async def _destroy(self) -> None:
        return None
