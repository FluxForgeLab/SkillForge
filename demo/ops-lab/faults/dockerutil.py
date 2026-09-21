"""Docker helpers for ops-lab faults. Host-side; never stop mock-db."""

import logging
import time

import docker
from docker.errors import DockerException

from skillforge.config import get_settings

logger = logging.getLogger(__name__)

PROTECTED_SERVICES = frozenset({"mock-db"})
HEALTHY_WAIT_SECONDS = 30.0
HEALTHY_POLL_INTERVAL = 0.5


def docker_client() -> docker.DockerClient:
    return docker.from_env()


def project_name() -> str:
    return get_settings().opslab_project


def container_by_service(client: docker.DockerClient, project: str, service: str):
    filters = {
        "label": [
            f"com.docker.compose.project={project}",
            f"com.docker.compose.service={service}",
        ]
    }
    found = client.containers.list(all=True, filters=filters)
    return found[0] if found else None


def require_container(client: docker.DockerClient, project: str, service: str):
    container = container_by_service(client, project, service)
    if container is None:
        raise LookupError(f"service {service!r} not found in project {project!r}")
    return container


def is_running(container) -> bool:
    if container is None:
        return False
    container.reload()
    return bool(container.attrs.get("State", {}).get("Running"))


def is_healthy(container) -> bool:
    if not is_running(container):
        return False
    health = container.attrs.get("State", {}).get("Health")
    if not health:
        return True
    return health.get("Status") == "healthy"


def stop_service(client: docker.DockerClient, project: str, service: str) -> None:
    if service in PROTECTED_SERVICES:
        raise PermissionError(f"refusing to stop protected service {service!r}")
    container = require_container(client, project, service)
    logger.info("stopping service %s", service)
    try:
        container.stop()
    except DockerException:
        logger.exception("failed to stop service %s", service)
        raise


def start_service(client: docker.DockerClient, project: str, service: str) -> None:
    container = require_container(client, project, service)
    if is_running(container):
        return
    logger.info("starting service %s", service)
    container.start()


def restart_service(client: docker.DockerClient, project: str, service: str) -> None:
    container = require_container(client, project, service)
    logger.info("restarting service %s", service)
    try:
        container.restart()
    except DockerException:
        logger.exception("failed to restart service %s", service)
        raise


def wait_until_healthy(
    client: docker.DockerClient,
    project: str,
    service: str,
    *,
    timeout: float = HEALTHY_WAIT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    container = require_container(client, project, service)
    while time.monotonic() < deadline:
        if is_healthy(container):
            return
        time.sleep(HEALTHY_POLL_INTERVAL)
    raise TimeoutError(f"service {service!r} did not become healthy within {timeout}s")


def nginx_exec(client: docker.DockerClient, project: str, cmd: list[str]) -> int:
    container = require_container(client, project, "nginx")
    if not is_running(container):
        raise RuntimeError("nginx is not running")
    try:
        result = container.exec_run(cmd)
    except DockerException as exc:
        logger.exception("nginx exec failed: %s", cmd)
        raise RuntimeError(f"nginx exec failed: {cmd!r}") from exc
    return int(result.exit_code)


def nginx_test(client: docker.DockerClient, project: str) -> None:
    if nginx_exec(client, project, ["nginx", "-t"]) != 0:
        raise RuntimeError("nginx -t failed")


def nginx_reload(client: docker.DockerClient, project: str) -> None:
    if nginx_exec(client, project, ["nginx", "-s", "reload"]) != 0:
        raise RuntimeError("nginx reload failed")
