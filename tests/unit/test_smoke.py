from pathlib import Path

import pytest

from skillforge import __version__
from skillforge.config import Settings, get_settings


def test_package_version() -> None:
    assert __version__ == "0.1.0"


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.model_adapter == "fake"
    assert settings.temperature == 0.0
    assert settings.opslab_project == "skillforge-lab"
    assert settings.demo_mode == "replay"
    assert settings.sqlite_path == Path("data/skillforge.db")
    assert settings.model_api_key.get_secret_value() == ""
    assert settings.cors_origins == ["http://localhost:5173"]


def test_demo_mode_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLFORGE_DEMO_MODE", "live")
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    assert settings.demo_mode == "live"
