"""OpenShell stays off the main path."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillforge.config import Settings
from skillforge.runtime.agent import _sandbox_for
from skillforge.sandbox.docker import DockerSandbox
from skillforge.sandbox.openshell import OpenShellSandbox, OpenShellUnavailable
from skillforge.sandbox.policy import load_default_policy


def test_default_backend_is_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "skillforge.runtime.agent.get_settings",
        lambda: Settings(_env_file=None),
    )
    sandbox = _sandbox_for("run_default", None, None)
    assert isinstance(sandbox, DockerSandbox)


@pytest.mark.asyncio
async def test_openshell_backend_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "skillforge.runtime.agent.get_settings",
        lambda: Settings(_env_file=None, sandbox_backend="openshell"),
    )
    sandbox = _sandbox_for("run_openshell", None, None)
    assert isinstance(sandbox, OpenShellSandbox)
    with pytest.raises(OpenShellUnavailable):
        await sandbox.create(policy=load_default_policy(), workspace=tmp_path)
