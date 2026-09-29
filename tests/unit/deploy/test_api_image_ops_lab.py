"""The API image must contain the ops-lab tree compile and inject already read."""

from __future__ import annotations

from pathlib import Path

from skillforge.compiler.evals import _DEFAULT_CATALOG

_REPO = Path(__file__).resolve().parents[3]


def test_compiler_catalog_path_exists_in_the_repo() -> None:
    assert _DEFAULT_CATALOG == _REPO / "demo" / "ops-lab" / "faults" / "catalog.yaml"
    assert _DEFAULT_CATALOG.is_file()


def test_api_image_copies_ops_lab() -> None:
    dockerfile = (_REPO / "deploy" / "api.Dockerfile").read_text(encoding="utf-8")
    assert "COPY demo/ops-lab ./demo/ops-lab" in dockerfile


def test_api_service_mounts_live_ops_lab() -> None:
    compose = (_REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./demo/ops-lab:/app/demo/ops-lab" in compose
