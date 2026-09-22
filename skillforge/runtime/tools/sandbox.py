"""In-sandbox tools: shell.read, file.read, file.write, and http.get."""

from __future__ import annotations

import shlex
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from skillforge.domain.errors import PolicyViolation
from skillforge.runtime.tools.base import ToolContext, ToolRegistry, ToolSpec
from skillforge.sandbox.policy import SandboxPolicy

_SHELL_ARGV0 = frozenset({"ls", "cat", "head", "tail", "wc"})
_SHELL_FORBIDDEN = frozenset(";|&<>$`()\n")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})
_HTTP_BODY_LIMIT = 4096
_HTTP_SCRIPT = (
    "import sys,urllib.request\n"
    "r=urllib.request.urlopen(sys.argv[1], timeout=2)\n"
    'body=r.read(4096).decode("utf-8","replace")\n'
    "print(r.status)\n"
    "sys.stdout.write(body)\n"
)

_OBJECT = "object"
_STRING = {"type": "string"}


def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": _OBJECT,
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def sandbox_tools() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="shell.read",
            description="Read the workspace with ls, cat, head, tail, or wc.",
            parameters=_object_schema({"command": _STRING}, ["command"]),
            permissions=["filesystem.read", "process"],
        ),
        shell_read,
    )
    registry.register(
        ToolSpec(
            name="file.read",
            description="Read a file under /workspace.",
            parameters=_object_schema({"path": _STRING}, ["path"]),
            permissions=["filesystem.read"],
        ),
        file_read,
    )
    registry.register(
        ToolSpec(
            name="file.write",
            description="Write a file under /workspace/runtime.",
            parameters=_object_schema({"path": _STRING, "content": _STRING}, ["path", "content"]),
            permissions=["filesystem.write"],
        ),
        file_write,
    )
    registry.register(
        ToolSpec(
            name="http.get",
            description="GET the ops-lab origin.",
            parameters=_object_schema({"url": _STRING}, ["url"]),
            permissions=["network"],
        ),
        http_get,
    )
    return registry


async def shell_read(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    command = str(arguments["command"])
    _ensure_shell_read(command, ctx.policy)
    result = await ctx.sandbox.exec(command, timeout_sec=ctx.timeout_sec)
    return {"exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}


async def file_read(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments["path"])
    content = await ctx.sandbox.read_file(path)
    return {"path": path, "content": content}


async def file_write(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    path = str(arguments["path"])
    content = str(arguments["content"])
    await ctx.sandbox.write_file(path, content)
    return {"path": path, "bytes": len(content.encode("utf-8"))}


async def http_get(ctx: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments["url"])
    rewritten = _rewrite_opslab_url(url, ctx.policy, ctx.opslab_base_url)
    command = f"python -c {shlex.quote(_HTTP_SCRIPT)} {shlex.quote(rewritten)}"
    result = await ctx.sandbox.exec(command, timeout_sec=ctx.timeout_sec)
    if result.exit_code != 0:
        raise RuntimeError(result.stderr or result.stdout or "http.get failed")
    status_line, _, body = result.stdout.partition("\n")
    return {"url": url, "status": int(status_line), "body": body[:_HTTP_BODY_LIMIT]}


def _ensure_shell_read(command: str, policy: SandboxPolicy) -> None:
    if any(char in command for char in _SHELL_FORBIDDEN):
        raise PolicyViolation(
            kind="process",
            name="shell.read",
            detail="command contains shell syntax",
        )
    tokens = command.split()
    if not tokens:
        raise PolicyViolation(kind="process", name="shell.read", detail="empty command")
    argv0 = tokens[0].rsplit("/", 1)[-1]
    if argv0 not in _SHELL_ARGV0:
        raise PolicyViolation(
            kind="process",
            name=argv0,
            detail="command is not in the shell.read whitelist",
        )
    for token in tokens:
        if "/" in token:
            policy.ensure_read(token)


def _rewrite_opslab_url(url: str, policy: SandboxPolicy, opslab_base_url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "http":
        raise PolicyViolation(kind="network", name=url, detail="only http is allowed")
    if parsed.username or parsed.password:
        raise PolicyViolation(kind="network", name=url, detail="userinfo is not allowed")
    host = parsed.hostname
    if host is None or host not in _LOOPBACK_HOSTS or host not in policy.network.allow:
        raise PolicyViolation(kind="network", name=url, detail="host is not allowed")
    expected_port = urlsplit(opslab_base_url).port or 80
    port = parsed.port or 80
    if port != expected_port:
        raise PolicyViolation(kind="network", name=url, detail="port is not allowed")
    rewritten = parsed._replace(netloc=f"host.docker.internal:{port}")
    return urlunsplit(rewritten)
