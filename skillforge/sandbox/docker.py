"""DockerSandbox: one workspace mount, no docker.sock, bridge network."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from docker.errors import APIError, NotFound
from docker.models.containers import Container
from docker.types import Mount

import docker
from skillforge.config import get_settings
from skillforge.domain.enums import TraceEventType
from skillforge.sandbox.base import ExecResult, Sandbox
from skillforge.tracing.bus import EventBus
from skillforge.tracing.emitter import emit
from skillforge.tracing.sink import TraceSink

logger = logging.getLogger(__name__)

_CONTAINER_WORKSPACE = "/workspace"
_EXEC_BACKSTOP_SEC = 5.0


def container_run_kwargs(workspace: Path, *, name: str) -> dict[str, Any]:
    source = str(workspace.resolve())
    return {
        "command": ["sleep", "infinity"],
        "detach": True,
        "user": "1000:1000",
        "read_only": True,
        "tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"},
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "mem_limit": "256m",
        "pids_limit": 64,
        "network_mode": "bridge",
        "extra_hosts": {"host.docker.internal": "host-gateway"},
        "working_dir": _CONTAINER_WORKSPACE,
        "mounts": [
            Mount(target=_CONTAINER_WORKSPACE, source=source, type="bind", read_only=False),
        ],
        "name": name,
        "labels": {"skillforge.role": "sandbox"},
    }


def _prepare_workspace(workspace: Path) -> Path:
    root = workspace.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"sandbox workspace is not a directory: {root}")
    runtime = root / "runtime"
    runtime.mkdir(exist_ok=True)
    for path in (root, runtime):
        try:
            os.chmod(path, 0o777)
        except OSError:
            logger.warning("could not chmod sandbox workspace path %s", path, exc_info=True)
    return root


class DockerSandbox(Sandbox):
    def __init__(
        self,
        *,
        run_id: str,
        client: docker.DockerClient | None = None,
        sink: TraceSink | None = None,
        bus: EventBus | None = None,
        image: str | None = None,
    ) -> None:
        super().__init__()
        self._run_id = run_id
        self._image = image if image is not None else get_settings().sandbox_image
        self._client = client
        self._owns_client = False
        self._sink = sink
        self._bus = bus
        self._container: Container | None = None
        self._name = f"sbx-{uuid4().hex[:12]}"

    async def _create(self) -> None:
        if self._container is not None:
            await asyncio.to_thread(self._remove_container)
        if self.workspace is None:
            raise NotADirectoryError("sandbox workspace is not set")
        prepared = await asyncio.to_thread(_prepare_workspace, self.workspace)
        self._container = await asyncio.to_thread(self._start, prepared)
        try:
            await emit(
                self._run_id,
                TraceEventType.SANDBOX_CREATED,
                name="docker",
                input={"image": self._image, "workspace": _CONTAINER_WORKSPACE},
                output={"container_id": self._container.id},
                stage="runtime",
                sink=self._sink,
                bus=self._bus,
            )
        except Exception:
            await asyncio.to_thread(self._remove_container)
            raise

    async def _exec(self, command: str, *, timeout_sec: float) -> ExecResult:
        started = time.monotonic()
        try:
            code, stdout_b, stderr_b = await asyncio.wait_for(
                asyncio.to_thread(self._exec_blocking, command, timeout_sec),
                timeout=timeout_sec + _EXEC_BACKSTOP_SEC,
            )
        except TimeoutError:
            await asyncio.to_thread(self._kill_container)
            raise
        elapsed = time.monotonic() - started
        if code == 124 and elapsed + 0.05 >= timeout_sec:
            raise TimeoutError(f"exec exceeded {timeout_sec}s")
        return ExecResult(
            exit_code=code,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )

    async def _read_file(self, path: str) -> str:
        return await asyncio.to_thread(self._read_archive, path)

    async def _write_file(self, path: str, content: str) -> None:
        await asyncio.to_thread(self._write_archive, path, content)

    async def _destroy(self) -> None:
        await asyncio.to_thread(self._teardown)

    def _ensure_client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
            self._owns_client = True
        return self._client

    def _start(self, workspace: Path) -> Container:
        client = self._ensure_client()
        kwargs = container_run_kwargs(workspace, name=self._name)
        logger.info("creating sandbox container %s", self._name)
        return client.containers.run(self._image, **kwargs)

    def _exec_blocking(self, command: str, timeout_sec: float) -> tuple[int, bytes, bytes]:
        container = self._require_container()
        api = self._ensure_client().api
        created = api.exec_create(
            container.id,
            ["timeout", str(timeout_sec), "/bin/sh", "-c", command],
            stdout=True,
            stderr=True,
        )
        output = api.exec_start(created["Id"], demux=True)
        info = api.exec_inspect(created["Id"])
        stdout_b, stderr_b = _split_exec_output(output)
        exit_code = info.get("ExitCode")
        return (1 if exit_code is None else int(exit_code), stdout_b, stderr_b)

    def _read_archive(self, path: str) -> str:
        container = self._require_container()
        stream, _stat = container.get_archive(path)
        raw = b"".join(stream)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            member = archive.next()
            if member is None:
                raise RuntimeError(f"empty archive for {path}")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"not a file: {path}")
            return extracted.read().decode("utf-8")

    def _write_archive(self, path: str, content: str) -> None:
        container = self._require_container()
        posix = PurePosixPath(path)
        payload = io.BytesIO()
        encoded = content.encode("utf-8")
        with tarfile.open(fileobj=payload, mode="w") as archive:
            info = tarfile.TarInfo(name=posix.name)
            info.size = len(encoded)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(encoded))
        payload.seek(0)
        written = container.put_archive(str(posix.parent), payload.getvalue())
        if not written:
            raise RuntimeError(f"failed to write {path}")

    def _require_container(self) -> Container:
        if self._container is None:
            raise RuntimeError("sandbox container is not running")
        return self._container

    def _kill_container(self) -> None:
        if self._container is None:
            return
        try:
            self._container.kill()
        except (APIError, NotFound):
            logger.warning("failed to kill sandbox container %s", self._name, exc_info=True)

    def _remove_container(self) -> None:
        container = self._container
        if container is None:
            return
        try:
            container.remove(force=True)
        except NotFound:
            pass
        self._container = None

    def _teardown(self) -> None:
        self._remove_container()
        if self._owns_client and self._client is not None:
            self._owns_client = False
            self._client.close()


def _split_exec_output(output: object) -> tuple[bytes, bytes]:
    if isinstance(output, tuple):
        stdout_b, stderr_b = output
        return stdout_b or b"", stderr_b or b""
    if isinstance(output, bytes):
        return output, b""
    return b"", b""
