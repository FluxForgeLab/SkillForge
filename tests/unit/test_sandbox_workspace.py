from pathlib import Path

from skillforge.config import get_settings
from skillforge.sandbox.workspace import open_workspace


def test_workspace_uses_configured_root(tmp_path: Path, monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SKILLFORGE_SANDBOX_WORKSPACE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    try:
        with open_workspace("skillforge-eval-") as workspace:
            assert Path(workspace).parent == tmp_path
            assert Path(workspace).name.startswith("skillforge-eval-")
    finally:
        get_settings.cache_clear()
