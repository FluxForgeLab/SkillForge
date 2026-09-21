"""Emit simulated alert JSON (incident_context) for an ops-lab fault."""

import json
import sys

from catalog import cached_catalog, get_fault


def build_incident(fault_id: str) -> dict:
    catalog = cached_catalog()
    fault = get_fault(fault_id, catalog=catalog)
    return {
        "fault_id": fault.id,
        "fixture": fault.fixture,
        "label": fault.label,
        "title": fault.incident.title,
        "summary": fault.incident.summary,
        "symptoms": list(fault.incident.symptoms),
        "endpoint": catalog.health_url,
        "compose_project": catalog.project,
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or not args[0].strip():
        print("usage: incident.py <fault_id>", file=sys.stderr)
        return 1
    fault_id = args[0].strip()
    try:
        payload = build_incident(fault_id)
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
