"""C6.4: generated scripts only call allowed ops-lab functions."""

from __future__ import annotations

import json
import py_compile
import re
from pathlib import Path

from skillforge.compiler import render_scripts
from skillforge.config import Settings
from skillforge.domain.entities import SkillSpec
from skillforge.models.adapters.fake import FakeModelAdapter
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ModelResponse
from skillforge.tracing.bus import EventBus

_HEALTH = "http://127.0.0.1:8088/health"


async def test_illegal_calls_are_dropped_and_sources_compile(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        sqlite_path=tmp_path / "app.sqlite",
        data_dir=tmp_path / "data",
        opslab_base_url="http://127.0.0.1:8088",
    )
    rendered = await render_scripts(_spec(), _gateway(settings), settings=settings)
    diagnose = rendered.files["diagnose.py"]
    recover = rendered.files["recover.py"]
    verify = rendered.files["verify.py"]
    combined = "\n".join(rendered.files.values())

    assert "nginx_test" not in combined
    assert re.search(r"import docker\b", combined) is None
    assert "subprocess" not in combined
    assert 'docker_restart("mock-db")' not in combined
    assert "rm -rf" not in recover
    assert 'docker_inspect("backend")' in diagnose
    assert f"http_get({json.dumps(_HEALTH)})" in verify
    for name, source in rendered.files.items():
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        py_compile.compile(str(path), doraise=True)


def _spec() -> SkillSpec:
    return SkillSpec(
        name="service-recovery",
        description="Diagnose and recover the edge service.",
        tools=[
            "docker.inspect",
            "docker.restart",
            "nginx.read_config",
            "nginx.write_config",
            "nginx.reload",
            "http.get",
        ],
    )


def _gateway(settings: Settings) -> ModelGateway:
    payload = {
        "calls": [
            {"function": "nginx_test"},
            {"function": "import docker"},
            {"function": "docker_restart", "service": "mock-db"},
            {"function": "docker_inspect", "service": "backend"},
            {"function": "http_get", "url": "http://evil.example/health"},
            {"function": "nginx_write_config", "content": "rm -rf /"},
        ],
    }
    adapter = FakeModelAdapter([ModelResponse(content=json.dumps(payload))])
    return ModelGateway(adapter, settings=settings, sink=_Sink(), bus=EventBus())


class _Sink:
    async def write(self, event: object) -> None:
        del event
