"""Host-visible workspace directories for sandboxes started through docker.sock."""

from __future__ import annotations

import tempfile
from pathlib import Path

from skillforge.config import get_settings


def open_workspace(prefix: str) -> tempfile.TemporaryDirectory[str]:
    """Create a temp dir the host Docker daemon can bind-mount.

    Inside the API container, the default ``/tmp`` is not the host's ``/tmp``.
    ``SKILLFORGE_SANDBOX_WORKSPACE_ROOT`` must be mounted at the same path on
    both sides. An empty setting keeps the process temp dir for local runs.
    """
    root = get_settings().sandbox_workspace_root.strip()
    if not root:
        return tempfile.TemporaryDirectory(prefix=prefix)
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=path)
