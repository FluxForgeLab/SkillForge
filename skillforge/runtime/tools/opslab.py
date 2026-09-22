"""Host-side whitelist for the skillforge-lab compose project."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from docker.errors import DockerException

import docker
from skillforge.config import get_settings
from skillforge.domain.errors import PolicyViolation
from skillforge.runtime.tools.base import ToolContext, ToolRegistry, ToolSpec
from skillforge.runtime.tools.sandbox import ensure_opslab_http_url, sandbox_tools
from skillforge.sandbox.policy import SandboxPolicy, load_default_policy

logger = logging.getLogger(__name__)

_READ_SERVICES = frozenset({"backend", "nginx", "mock-db"})
_RESTART_SERVICES = frozenset({"backend", "nginx"})
_DATABASE_SERVICES = frozenset({"mock-db", "database"})
_STRING = {"type": "string"}


def docker_inspect(
    service: str,
    *,
    client: docker.DockerClient | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    _refuse_read(service)
    with _docker_client(client) as docker_client:
        container = _require_service(docker_client, _project(project), service)
        container.reload()
        return {
            "service": service,
            "running": _running(container),
            "id": container.id,
        }


def docker_logs(
    service: str,
    tail: int = 100,
    *,
    client: docker.DockerClient | None = None,
    project: str | None = None,
) -> str:
    _refuse_read(service)
    with _docker_client(client) as docker_client:
        container = _require_service(docker_client, _project(project), service)
        raw = container.logs(tail=tail)
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def docker_restart(
    service: str,
    *,
    client: docker.DockerClient | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    _refuse_restart(service)
    with _docker_client(client) as docker_client:
        container = _require_service(docker_client, _project(project), service)
        logger.info("restarting ops-lab service %s", service)
        container.restart()
        container.reload()
        return {"service": service, "running": _running(container)}


def nginx_read_config(*, conf_path: Path | None = None) -> str:
    return _conf_path(conf_path).read_text(encoding="utf-8")


def nginx_write_config(text: str, *, conf_path: Path | None = None) -> None:
    _refuse_rm(text)
    _conf_path(conf_path).write_text(text, encoding="utf-8")


def nginx_test(
    *,
    client: docker.DockerClient | None = None,
    project: str | None = None,
) -> dict[str, bool]:
    _nginx_exec(["nginx", "-t"], client=client, project=project, failure="nginx -t failed")
    return {"ok": True}


def nginx_reload(
    *,
    client: docker.DockerClient | None = None,
    project: str | None = None,
) -> dict[str, bool]:
    _nginx_exec(
        ["nginx", "-s", "reload"],
        client=client,
        project=project,
        failure="nginx reload failed",
    )
    return {"ok": True}


def http_get(
    url: str,
    *,
    opslab_base_url: str | None = None,
    policy: SandboxPolicy | None = None,
) -> dict[str, int]:
    base = opslab_base_url if opslab_base_url is not None else get_settings().opslab_base_url
    active = policy if policy is not None else load_default_policy()
    ensure_opslab_http_url(url, active, base)
    response = httpx.get(url, timeout=2.0, follow_redirects=False)
    return {"http_status": int(response.status_code)}


def register_opslab(registry: ToolRegistry) -> None:
    registry.register(
        _spec("docker.inspect", "Inspect a skillforge-lab service.", ["service"]), _inspect
    )
    registry.register(
        _spec(
            "docker.logs",
            "Read the last log lines of a skillforge-lab service.",
            ["service"],
            extra={"tail": {"type": "integer"}},
        ),
        _logs,
    )
    registry.register(_spec("docker.restart", "Restart backend or nginx.", ["service"]), _restart)
    registry.register(_spec("nginx.read_config", "Read the ops-lab nginx.conf.", []), _read_config)
    registry.register(
        _spec("nginx.write_config", "Replace the ops-lab nginx.conf.", ["content"]),
        _write_config,
    )
    registry.register(
        _spec("nginx.test", "Run nginx -t in the ops-lab nginx container.", []), _test
    )
    registry.register(_spec("nginx.reload", "Reload the ops-lab nginx container.", []), _reload)


def runtime_tools() -> ToolRegistry:
    registry = sandbox_tools()
    register_opslab(registry)
    return registry


async def _inspect(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx
    return await asyncio.to_thread(docker_inspect, str(arguments["service"]))


async def _logs(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx
    service = str(arguments["service"])
    tail = int(arguments.get("tail", 100))
    text = await asyncio.to_thread(docker_logs, service, tail)
    return {"service": service, "logs": text}


async def _restart(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx
    return await asyncio.to_thread(docker_restart, str(arguments["service"]))


async def _read_config(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx, arguments
    content = await asyncio.to_thread(nginx_read_config)
    return {"content": content}


async def _write_config(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx
    content = str(arguments["content"])
    await asyncio.to_thread(nginx_write_config, content)
    return {"bytes": len(content.encode("utf-8"))}


async def _test(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx, arguments
    return await asyncio.to_thread(nginx_test)


async def _reload(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx, arguments
    return await asyncio.to_thread(nginx_reload)


def _spec(
    name: str,
    description: str,
    required: list[str],
    *,
    extra: dict[str, Any] | None = None,
) -> ToolSpec:
    properties: dict[str, Any] = {key: _STRING for key in required}
    if extra:
        properties.update(extra)
    return ToolSpec(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        permissions=["opslab"],
    )


def _refuse_read(service: str) -> None:
    if service not in _READ_SERVICES:
        raise PolicyViolation(
            kind="process",
            name=service,
            detail="inspect is limited to skillforge-lab services",
        )


def _refuse_restart(service: str) -> None:
    if service in _DATABASE_SERVICES:
        raise PolicyViolation(
            kind="process",
            name="restart_database",
            detail=f"refusing to restart {service}",
        )
    if service not in _RESTART_SERVICES:
        raise PolicyViolation(
            kind="process",
            name=service,
            detail="restart is limited to backend and nginx",
        )


def _refuse_rm(text: str) -> None:
    for token in text.split():
        name = token.rsplit("/", 1)[-1]
        if name == "rm" or name.startswith("rm"):
            raise PolicyViolation(kind="process", name="rm", detail="rm is not allowed")


def _project(project: str | None) -> str:
    return project if project is not None else get_settings().opslab_project


def _conf_path(conf_path: Path | None) -> Path:
    return conf_path if conf_path is not None else get_settings().opslab_nginx_conf


@contextmanager
def _docker_client(client: docker.DockerClient | None) -> Iterator[docker.DockerClient]:
    if client is not None:
        yield client
        return
    owned = docker.from_env()
    try:
        yield owned
    finally:
        owned.close()


def _require_service(client: docker.DockerClient, project: str, service: str):
    found = client.containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={project}",
                f"com.docker.compose.service={service}",
            ]
        },
    )
    if not found:
        raise LookupError(f"service {service!r} not found in project {project!r}")
    return found[0]


def _running(container) -> bool:
    return bool(container.attrs.get("State", {}).get("Running"))


def _nginx_exec(
    cmd: list[str],
    *,
    client: docker.DockerClient | None,
    project: str | None,
    failure: str,
) -> None:
    with _docker_client(client) as docker_client:
        container = _require_service(docker_client, _project(project), "nginx")
        container.reload()
        if not _running(container):
            raise RuntimeError("nginx is not running")
        try:
            result = container.exec_run(cmd)
        except DockerException as exc:
            raise RuntimeError(failure) from exc
    if int(result.exit_code) != 0:
        raise RuntimeError(failure)
