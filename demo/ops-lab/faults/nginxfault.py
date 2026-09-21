"""Host-side nginx upstream changes for ops-lab faults."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from dockerutil import is_running, nginx_reload, nginx_test, require_container

DEFAULT_UPSTREAM_PORT = 8080
F2_WRONG_UPSTREAM_PORT = 8081

_NGINX_RENDER_PATH = Path(__file__).resolve().parent.parent / "nginx" / "render.py"


def _render_module():
    spec = importlib.util.spec_from_file_location("ops_lab_nginx_render", _NGINX_RENDER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load nginx render from {_NGINX_RENDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_upstream_port(port: int) -> None:
    render = _render_module()
    render.write_conf(port)


def apply_upstream_port(port: int, client, project: str) -> None:
    write_upstream_port(port)
    container = require_container(client, project, "nginx")
    if is_running(container):
        nginx_test(client, project)
        nginx_reload(client, project)


def restore_nginx_upstream(client, project: str, *, port: int = DEFAULT_UPSTREAM_PORT) -> None:
    write_upstream_port(port)
    container = require_container(client, project, "nginx")
    if is_running(container):
        nginx_test(client, project)
        nginx_reload(client, project)
