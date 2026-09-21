"""Ops-lab verifier: five-field JSON oracle on the host. Independent of the sandbox."""

import logging
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import docker
import httpx
from docker.errors import DockerException
from pydantic import BaseModel

from skillforge.config import get_settings

logger = logging.getLogger(__name__)

OPS_LAB_DIR = Path(__file__).resolve().parent.parent
NGINX_CONF_PATH = OPS_LAB_DIR / "nginx" / "nginx.conf"
HEALTH_PATH = "/health"
UPSTREAM_RE = re.compile(r"server\s+backend:(\d+)\s*;")
CONNECT_RETRY_SECONDS = 10.0
CONNECT_RETRY_INTERVAL = 0.5
HTTP_TIMEOUT = 2.0
RESULT_FIELDS = (
    "http_status",
    "backend_running",
    "nginx_config_valid",
    "upstream_port_matches",
    "db_running",
)
DEFAULT_BACKEND_PORT = 8080


class VerifierResult(BaseModel):
    http_status: int
    backend_running: bool
    nginx_config_valid: bool
    upstream_port_matches: bool
    db_running: bool

    def healthy(self) -> bool:
        return (
            self.http_status == 200
            and self.backend_running
            and self.nginx_config_valid
            and self.upstream_port_matches
            and self.db_running
        )


@dataclass(frozen=True)
class VerifierDeps:
    health_url: str
    get_http_status: Callable[[str], int]
    service_running: Callable[[str], bool]
    nginx_config_valid: Callable[[], bool]
    backend_listen_port: Callable[[], int]
    read_nginx_conf: Callable[[], str]


def parse_upstream_port(conf_text: str) -> int | None:
    match = UPSTREAM_RE.search(conf_text)
    if match is None:
        return None
    return int(match.group(1))


def fetch_http_status(url: str, *, timeout: float = HTTP_TIMEOUT) -> int:
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=False)
    except httpx.RequestError:
        return 0
    return response.status_code


def collect(deps: VerifierDeps) -> VerifierResult:
    upstream = parse_upstream_port(deps.read_nginx_conf())
    listen_port = deps.backend_listen_port()
    return VerifierResult(
        http_status=deps.get_http_status(deps.health_url),
        backend_running=deps.service_running("backend"),
        nginx_config_valid=deps.nginx_config_valid(),
        upstream_port_matches=upstream is not None and upstream == listen_port,
        db_running=deps.service_running("mock-db"),
    )


def verify(deps: VerifierDeps, *, wait: bool = True) -> VerifierResult:
    deadline = time.monotonic() + CONNECT_RETRY_SECONDS if wait else time.monotonic()
    result = collect(deps)
    while result.http_status == 0 and time.monotonic() < deadline:
        logger.info("health endpoint not reachable yet; retrying")
        time.sleep(CONNECT_RETRY_INTERVAL)
        result = collect(deps)
    return result


def _container_by_service(client: docker.DockerClient, project: str, service: str):
    filters = {
        "label": [
            f"com.docker.compose.project={project}",
            f"com.docker.compose.service={service}",
        ]
    }
    found = client.containers.list(all=True, filters=filters)
    return found[0] if found else None


def _state_running(container) -> bool:
    if container is None:
        return False
    container.reload()
    return bool(container.attrs.get("State", {}).get("Running"))


def _port_from_env(container) -> int:
    if container is None:
        return DEFAULT_BACKEND_PORT
    container.reload()
    env_list = container.attrs.get("Config", {}).get("Env") or []
    for item in env_list:
        if item.startswith("PORT="):
            raw = item.split("=", 1)[1]
            try:
                port = int(raw)
            except ValueError:
                return DEFAULT_BACKEND_PORT
            if port > 0:
                return port
            return DEFAULT_BACKEND_PORT
    return DEFAULT_BACKEND_PORT


def live_deps() -> VerifierDeps:
    settings = get_settings()
    client = docker.from_env()
    project = settings.opslab_project
    health_url = settings.opslab_base_url.rstrip("/") + HEALTH_PATH

    def service_running(service: str) -> bool:
        return _state_running(_container_by_service(client, project, service))

    def nginx_config_valid() -> bool:
        container = _container_by_service(client, project, "nginx")
        if not _state_running(container):
            return False
        try:
            exec_result = container.exec_run(["nginx", "-t"])
        except DockerException:
            logger.warning("nginx -t failed to execute", exc_info=True)
            return False
        return exec_result.exit_code == 0

    def backend_listen_port() -> int:
        return _port_from_env(_container_by_service(client, project, "backend"))

    def read_nginx_conf() -> str:
        return NGINX_CONF_PATH.read_text(encoding="utf-8")

    return VerifierDeps(
        health_url=health_url,
        get_http_status=fetch_http_status,
        service_running=service_running,
        nginx_config_valid=nginx_config_valid,
        backend_listen_port=backend_listen_port,
        read_nginx_conf=read_nginx_conf,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    result = verify(live_deps(), wait=True)
    print(result.model_dump_json(indent=2))
    return 0 if result.healthy() else 1


if __name__ == "__main__":
    raise SystemExit(main())
