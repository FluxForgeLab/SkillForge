"""Apply the v0.1 recovery actions. Prints one JSON object to stdout.

Upstream edits replace only the ``server backend:8081;`` token. Reload failure
exits non-zero. This script does not call nginx_test.
"""

from __future__ import annotations

import json
import sys

from skillforge.runtime.tools.opslab import (
    docker_inspect,
    docker_restart,
    nginx_read_config,
    nginx_reload,
    nginx_write_config,
)

WRONG_UPSTREAM = "server backend:8081;"
HEALTHY_UPSTREAM = "server backend:8080;"


def _reload_or_raise() -> None:
    result = nginx_reload()
    if isinstance(result, dict) and result.get("ok") is False:
        message = str(result.get("error") or "nginx.reload failed")
        raise RuntimeError(message)


def main() -> int:
    actions: list[str] = []
    inspected = docker_inspect("backend")
    if not inspected["running"]:
        docker_restart("backend")
        actions.append("docker.restart backend")

    conf = nginx_read_config()
    if WRONG_UPSTREAM in conf:
        nginx_write_config(conf.replace(WRONG_UPSTREAM, HEALTHY_UPSTREAM))
        actions.append("nginx.write_config")
        try:
            _reload_or_raise()
        except RuntimeError as exc:
            json.dump({"ok": False, "actions": actions, "error": str(exc)}, sys.stdout)
            sys.stdout.write("\n")
            return 1
        actions.append("nginx.reload")

    json.dump({"ok": True, "actions": actions}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
