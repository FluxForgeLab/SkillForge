"""GET the ops-lab health URL. Prints ``{"http_status": <int>}``."""

from __future__ import annotations

import json
import sys

from skillforge.runtime.tools.opslab import http_get

HEALTH_URL = "http://127.0.0.1:8088/health"


def main() -> int:
    result = http_get(HEALTH_URL)
    status = int(result["http_status"])
    json.dump({"http_status": status}, sys.stdout)
    sys.stdout.write("\n")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
