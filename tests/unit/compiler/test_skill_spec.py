"""C6.1: SkillSpec YAML stays inside the tool registry and the default policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from skillforge.compiler import SkillSpecError, load_skill_spec, validate_skill_spec
from skillforge.domain.entities import SkillSpec

_REPO = Path(__file__).resolve().parents[3]
_GOLDEN = _REPO / "skills" / "golden" / "service-recovery" / "SKILL.md"

_VALID: dict[str, Any] = {
    "name": "service-recovery",
    "description": "Diagnose and recover containerized web services.",
    "triggers": ["HTTP 502", "backend unavailable", "health check failed"],
    "inputs": ["service_name", "incident_context"],
    "outputs": ["diagnosis", "actions", "verification_result"],
    "tools": ["shell.read", "docker.inspect", "docker.restart", "file.read", "http.get"],
    "permissions": {
        "filesystem": {"read": ["/workspace"], "write": ["/workspace/runtime"]},
        "network": {"allow": ["localhost"]},
        "shell": {"destructive_commands": False},
    },
    "success": ["health_status == 200"],
    "sources": ["doc_xxx"],
}


def test_valid_spec_passes() -> None:
    spec = load_skill_spec(_VALID)
    assert spec.tools == _VALID["tools"]
    assert spec.permissions.filesystem.write == ["/workspace/runtime"]


def test_dotted_nginx_tool_passes() -> None:
    spec = validate_skill_spec(
        SkillSpec.model_validate({**_VALID, "tools": ["nginx.read_config"]}),
    )
    assert spec.tools == ["nginx.read_config"]


def test_empty_tools_pass() -> None:
    spec = validate_skill_spec(SkillSpec(name="empty", description="no tools"))
    assert spec.tools == []


def test_yaml_text_round_trip() -> None:
    text = yaml.safe_dump(_VALID, sort_keys=False)
    spec = load_skill_spec(text)
    assert spec.name == "service-recovery"


def test_unknown_tool_is_rejected() -> None:
    spec = SkillSpec.model_validate({**_VALID, "tools": ["docker.nuke"]})
    with pytest.raises(SkillSpecError, match="docker.nuke"):
        validate_skill_spec(spec)


def test_rm_is_not_a_tool() -> None:
    spec = SkillSpec.model_validate({**_VALID, "tools": ["rm"]})
    with pytest.raises(SkillSpecError, match="unknown tool 'rm'"):
        validate_skill_spec(spec)


def test_duplicate_tool_is_rejected() -> None:
    spec = SkillSpec.model_validate({**_VALID, "tools": ["http.get", "http.get"]})
    with pytest.raises(SkillSpecError, match="duplicate tool 'http.get'"):
        validate_skill_spec(spec)


def test_write_outside_runtime_is_rejected() -> None:
    payload = _with_permissions(write=["/workspace/config"])
    with pytest.raises(SkillSpecError, match="write not allowed"):
        load_skill_spec(payload)


def test_network_outside_allow_list_is_rejected() -> None:
    payload = _with_permissions(allow=["8.8.8.8"])
    with pytest.raises(SkillSpecError, match="8.8.8.8"):
        load_skill_spec(payload)


def test_destructive_shell_is_rejected() -> None:
    payload = _with_permissions(destructive=True)
    with pytest.raises(SkillSpecError, match="destructive_commands must be false"):
        load_skill_spec(payload)


def test_extra_top_level_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load_skill_spec({**_VALID, "version": "0.1.0"})


def test_policy_fields_cannot_be_granted() -> None:
    payload = _with_permissions()
    payload["permissions"]["network"]["mode"] = "restricted"
    with pytest.raises(ValidationError):
        load_skill_spec(payload)


def test_golden_skill_md_is_not_a_skill_spec() -> None:
    with pytest.raises((ValidationError, SkillSpecError, yaml.YAMLError)):
        load_skill_spec(_GOLDEN)


def _with_permissions(
    *,
    write: list[str] | None = None,
    allow: list[str] | None = None,
    destructive: bool = False,
) -> dict[str, Any]:
    payload = {
        **_VALID,
        "permissions": {
            "filesystem": {
                "read": ["/workspace"],
                "write": ["/workspace/runtime"] if write is None else write,
            },
            "network": {"allow": ["localhost"] if allow is None else allow},
            "shell": {"destructive_commands": destructive},
        },
    }
    return payload
