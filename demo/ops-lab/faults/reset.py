"""Reset ops-lab to a healthy backend. Host-side; does not use the sandbox."""

import logging
import sys

from dockerutil import docker_client, project_name, start_service, wait_until_healthy
from nginxfault import restore_nginx_upstream


def reset(*, client=None) -> None:
    docker = client if client is not None else docker_client()
    project = project_name()
    restore_nginx_upstream(docker, project)
    start_service(docker, project, "backend")
    wait_until_healthy(docker, project, "backend")
    # nginx resolves `backend` at start; if F1 raced nginx boot, nginx has exited.
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
