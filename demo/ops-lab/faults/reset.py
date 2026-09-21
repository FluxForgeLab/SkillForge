"""Reset ops-lab to a healthy baseline (catalog reset.command). Host-side; not the sandbox."""

import logging
import sys

from dockerutil import (
    docker_client,
    is_running,
    project_name,
    require_container,
    restart_service,
    start_service,
    wait_until_healthy,
)
from nginxfault import DEFAULT_UPSTREAM_PORT, write_upstream_port


def reset(*, client=None) -> None:
    docker = client if client is not None else docker_client()
    project = project_name()
    write_upstream_port(DEFAULT_UPSTREAM_PORT)
    start_service(docker, project, "backend")
    wait_until_healthy(docker, project, "backend")
    nginx = require_container(docker, project, "nginx")
    if is_running(nginx):
        restart_service(docker, project, "nginx")
    else:
        start_service(docker, project, "nginx")
    wait_until_healthy(docker, project, "nginx")


reset_all = reset


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    try:
        reset()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
