from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_RENDER_PATH = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "nginx" / "render.py"


def _load_render():
    spec = importlib.util.spec_from_file_location("ops_lab_nginx_render", _RENDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_default_upstream_is_8080() -> None:
    text = _load_render().render(8080)
    assert "server backend:8080;" in text
    assert "backend:8081" not in text
    assert "__UPSTREAM_PORT__" not in text


def test_render_can_point_upstream_at_8081() -> None:
    text = _load_render().render(8081)
    assert "server backend:8081;" in text
    assert "server backend:8080;" not in text


def test_committed_nginx_conf_matches_render_8080() -> None:
    render = _load_render()
    committed = render.CONF_PATH.read_text(encoding="utf-8")
    assert committed == render.render(8080)


def test_render_rejects_non_positive_port() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _load_render().render(0)
