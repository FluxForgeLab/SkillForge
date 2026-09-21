"""Inject a named ops-lab fault. Host-side; does not use the sandbox."""

import logging
import sys

from dockerutil import docker_client, project_name, stop_service

FAULT_BACKEND_STOPPED = "backend_stopped"
KNOWN_FAULTS = frozenset({FAULT_BACKEND_STOPPED})


def inject(fault_id: str, *, client=None) -> None:
    if fault_id not in KNOWN_FAULTS:
        known = ", ".join(sorted(KNOWN_FAULTS))
        raise ValueError(f"unknown fault_id {fault_id!r}; known: {known}")
    docker = client if client is not None else docker_client()
    project = project_name()
    if fault_id == FAULT_BACKEND_STOPPED:
        stop_service(docker, project, "backend")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].strip():
        print("usage: inject.py <fault_id>", file=sys.stderr)
        return 1
    try:
        inject(args[0].strip())
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
