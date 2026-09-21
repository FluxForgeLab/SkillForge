from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from skillforge.config import get_settings

_VERIFY_PATH = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "verifier" / "verify.py"
_NGINX_CONF = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "nginx" / "nginx.conf"


def _load_verifier():
    spec = importlib.util.spec_from_file_location("ops_lab_verifier", _VERIFY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ops_lab_verifier"] = module
    spec.loader.exec_module(module)
    return module


def _healthy_conf() -> str:
    return "upstream skillforge_backend { server backend:8080; }\n"


def _deps(module, **overrides):
    defaults = {
        "health_url": "http://127.0.0.1:8088/health",
        "get_http_status": lambda url: 200,
        "service_running": lambda name: True,
        "nginx_config_valid": lambda: True,
        "backend_listen_port": lambda: 8080,
        "read_nginx_conf": _healthy_conf,
    }
    defaults.update(overrides)
    return module.VerifierDeps(**defaults)


def test_result_json_keys_are_exactly_the_five_fields() -> None:
    module = _load_verifier()
    result = module.collect(_deps(module))
    assert set(result.model_dump()) == set(module.RESULT_FIELDS)


def test_healthy_snapshot_is_healthy() -> None:
    module = _load_verifier()
    result = module.collect(_deps(module))
    assert result.http_status == 200
    assert result.backend_running is True
    assert result.nginx_config_valid is True
    assert result.upstream_port_matches is True
    assert result.db_running is True
    assert result.healthy() is True


def test_f1_shape_backend_stopped() -> None:
    module = _load_verifier()

    def service_running(name: str) -> bool:
        return name != "backend"

    result = module.collect(
        _deps(module, get_http_status=lambda url: 502, service_running=service_running)
    )
    assert result.http_status == 502
    assert result.backend_running is False
    assert result.healthy() is False


def test_f2_shape_upstream_mismatch() -> None:
    module = _load_verifier()
    result = module.collect(
        _deps(
            module,
            get_http_status=lambda url: 502,
            read_nginx_conf=lambda: "server backend:8081;",
            backend_listen_port=lambda: 8080,
        )
    )
    assert result.http_status == 502
    assert result.upstream_port_matches is False
    assert result.healthy() is False


def test_f3_shape_nginx_config_invalid() -> None:
    module = _load_verifier()
    result = module.collect(_deps(module, nginx_config_valid=lambda: False))
    assert result.nginx_config_valid is False
    assert result.healthy() is False


def test_mock_db_missing() -> None:
    module = _load_verifier()

    def service_running(name: str) -> bool:
        return name != "mock-db"

    result = module.collect(_deps(module, service_running=service_running))
    assert result.db_running is False
    assert result.healthy() is False


def test_parse_committed_nginx_conf_upstream_8080() -> None:
    module = _load_verifier()
    text = _NGINX_CONF.read_text(encoding="utf-8")
    assert module.parse_upstream_port(text) == 8080


def test_connect_failure_records_http_status_zero() -> None:
    module = _load_verifier()
    result = module.collect(_deps(module, get_http_status=lambda url: 0))
    assert result.http_status == 0
    assert result.healthy() is False


def test_verify_does_not_retry_after_http_status_arrives(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_verifier()
    calls = {"n": 0}

    def get_http_status(url: str) -> int:
        calls["n"] += 1
        return 502

    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    result = module.verify(_deps(module, get_http_status=get_http_status), wait=True)
    assert result.http_status == 502
    assert calls["n"] == 1


def test_verify_retries_while_http_status_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_verifier()
    statuses = iter([0, 0, 200])

    def get_http_status(url: str) -> int:
        return next(statuses)

    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    result = module.verify(_deps(module, get_http_status=get_http_status), wait=True)
    assert result.http_status == 200
    assert result.healthy() is True


def test_main_exit_zero_when_healthy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_verifier()
    healthy = module.collect(_deps(module))
    monkeypatch.setattr(module, "live_deps", lambda: SimpleNamespace())
    monkeypatch.setattr(module, "verify", lambda _deps, wait=True: healthy)
    assert module.main() == 0
    dumped = capsys.readouterr().out
    assert '"http_status": 200' in dumped


def test_opslab_base_url_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLFORGE_OPSLAB_BASE_URL", "http://127.0.0.1:18088")
    get_settings.cache_clear()
    from skillforge.config import Settings

    settings = Settings(_env_file=None)
    assert settings.opslab_base_url == "http://127.0.0.1:18088"
    get_settings.cache_clear()
