"""Collect skillforge-lab state. Prints one JSON object to stdout."""

from __future__ import annotations

import json
import sys

from skillforge.runtime.tools.opslab import docker_inspect, docker_logs, nginx_read_config

SERVICES = ("backend", "nginx", "mock-db")


def main() -> int:
    payload = {
        "services": {name: docker_inspect(name) for name in SERVICES},
        "backend_logs": docker_logs("backend", tail=100),
        "nginx_conf": nginx_read_config(),
    }
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
