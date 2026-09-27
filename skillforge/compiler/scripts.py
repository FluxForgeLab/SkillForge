"""Pass 5: render diagnose, recover, and verify from a fixed ops-lab template."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, Field

from skillforge.config import Settings
from skillforge.domain.entities import SkillSpec
from skillforge.models.gateway import ModelGateway
from skillforge.models.structured import generate_structured
from skillforge.models.types import ChatMessage

_SYSTEM = (
    "Propose ops-lab calls as structured steps. "
    "Use only the allowed function names. Do not write Python imports."
)

_DIAGNOSE = ("docker_inspect", "docker_logs", "nginx_read_config")
_RECOVER = (
    "docker_restart",
    "nginx_read_config",
    "nginx_write_config",
    "nginx_reload",
    "nginx_test",
)
_VERIFY = ("http_get",)
_TOOL = {
    "docker_inspect": "docker.inspect",
    "docker_logs": "docker.logs",
    "docker_restart": "docker.restart",
    "nginx_read_config": "nginx.read_config",
    "nginx_write_config": "nginx.write_config",
    "nginx_test": "nginx.test",
    "nginx_reload": "nginx.reload",
    "http_get": "http.get",
}
_READ_SERVICES = frozenset({"backend", "nginx", "mock-db"})
_RESTART_SERVICES = frozenset({"backend", "nginx"})
_FORBIDDEN = (
    re.compile(r"import subprocess\b"),
    re.compile(r"import docker\b"),
    re.compile(r"\bos\.system\b"),
    re.compile(r"\beval\("),
    re.compile(r"\bexec\("),
    re.compile(r"\bsudo\b"),
)


class ScriptCall(BaseModel):
    """One literal call. The compiler decides which file receives it."""

    model_config = ConfigDict(extra="forbid")

    function: str
    service: str = ""
    tail: int | None = None
    content: str = ""
    url: str = ""


class ScriptBatch(BaseModel):
    """Structured output for pass 5."""

    model_config = ConfigDict(extra="forbid")

    calls: list[ScriptCall] = Field(default_factory=list)


class SkillScripts(BaseModel):
    """In-memory script sources, keyed by filename."""

    model_config = ConfigDict(extra="forbid")

    files: dict[str, str]


async def render_scripts(
    spec: SkillSpec,
    gateway: ModelGateway,
    *,
    settings: Settings,
) -> SkillScripts:
    """Keep whitelist calls that the spec allows, then render three scripts."""
    batch = await generate_structured(
        gateway,
        ScriptBatch,
        run_id="compile_scripts",
        messages=[
            ChatMessage(role="system", content=_SYSTEM),
            ChatMessage(role="user", content=_prompt(spec)),
        ],
        stage="compiler",
        settings=settings,
    )
    health = settings.opslab_base_url.rstrip("/") + "/health"
    kept = [call for call in batch.calls if _allowed(call, spec)]
    files = {
        "diagnose.py": _render("diagnose", _lines(kept, _DIAGNOSE, health)),
        "recover.py": _render("recover", _lines(kept, _RECOVER, health)),
        "verify.py": _render("verify", _lines(kept, _VERIFY, health)),
    }
    return SkillScripts(files={name: _clean(source) for name, source in files.items()})


def _allowed(call: ScriptCall, spec: SkillSpec) -> bool:
    tool = _TOOL.get(call.function)
    if tool is None or tool not in spec.tools:
        return False
    if call.function in {"docker_inspect", "docker_logs"}:
        return call.service in _READ_SERVICES
    if call.function == "docker_restart":
        return call.service in _RESTART_SERVICES
    if call.function == "nginx_write_config":
        return not _mentions_rm(call.content)
    return True


def _mentions_rm(text: str) -> bool:
    for token in text.split():
        name = token.rsplit("/", 1)[-1]
        if name == "rm" or name.startswith("rm"):
            return True
    return False


def _lines(calls: list[ScriptCall], functions: tuple[str, ...], health: str) -> list[str]:
    lines: list[str] = []
    for call in calls:
        if call.function not in functions:
            continue
        rendered = _call(call, health)
        if rendered is not None:
            lines.append(rendered)
    return lines


def _call(call: ScriptCall, health: str) -> str | None:
    if call.function == "docker_inspect":
        return f"docker_inspect({json.dumps(call.service)})"
    if call.function == "docker_logs":
        tail = 100 if call.tail is None else call.tail
        return f"docker_logs({json.dumps(call.service)}, tail={int(tail)})"
    if call.function == "docker_restart":
        return f"docker_restart({json.dumps(call.service)})"
    if call.function == "nginx_read_config":
        return "nginx_read_config()"
    if call.function == "nginx_write_config":
        return f"nginx_write_config({json.dumps(call.content)})"
    if call.function == "nginx_test":
        return "nginx_test()"
    if call.function == "nginx_reload":
        return "nginx_reload()"
    if call.function == "http_get":
        return f"http_get({json.dumps(health)})"
    return None


def _render(role: str, calls: list[str]) -> str:
    names = sorted({line.split("(", 1)[0] for line in calls})
    import_line = ""
    if names:
        joined = ", ".join(names)
        import_line = f"from skillforge.runtime.tools.opslab import {joined}\n\n"
    if calls:
        inner = "\n".join(f"            {line}," for line in calls)
        body = f'        "calls": [\n{inner}\n        ]\n'
    else:
        body = '        "calls": []\n'
    return (
        f'"""Generated {role} script. Prints one JSON object."""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n"
        "import sys\n\n"
        f"{import_line}"
        "def main() -> int:\n"
        "    payload = {\n"
        f"{body}"
        "    }\n"
        "    json.dump(payload, sys.stdout)\n"
        '    sys.stdout.write("\\n")\n'
        "    return 0\n\n\n"
        'if __name__ == "__main__":\n'
        "    raise SystemExit(main())\n"
    )


def _clean(source: str) -> str:
    for pattern in _FORBIDDEN:
        if pattern.search(source):
            raise RuntimeError(f"generated script contains {pattern.pattern}")
    return source


def _prompt(spec: SkillSpec) -> str:
    tools = ", ".join(spec.tools)
    return f"Allowed tools: {tools}"
