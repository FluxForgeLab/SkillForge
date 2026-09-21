"""Shared helpers for ops-lab integration tests (not collected as tests)."""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "demo" / "ops-lab" / "docker-compose.yml"
FAULTS_DIR = REPO_ROOT / "demo" / "ops-lab" / "faults"
VERIFY_PATH = REPO_ROOT / "demo" / "ops-lab" / "verifier" / "verify.py"
COMPOSE_PROJECT = "skillforge-lab"
HEALTH_WAIT_SECONDS = 120.0
HEALTH_POLL_INTERVAL = 2.0


def load_verifier_module():
    spec = importlib.util.spec_from_file_location("ops_lab_verifier_integration", VERIFY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier from {VERIFY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_fault_modules():
    path = str(FAULTS_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    for name in ("dockerutil", "nginxfault", "catalog", "inject", "reset"):
        sys.modules.pop(name, None)
    catalog = importlib.import_module("catalog")
    inject = importlib.import_module("inject")
    reset = importlib.import_module("reset")
    return catalog, inject, reset


def catalog_fault_entries():
    catalog, _inject, _reset = load_fault_modules()
    return catalog.load_catalog().faults


def write_default_nginx_conf() -> None:
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "demo" / "ops-lab" / "nginx" / "render.py"), "8080"],
        cwd=REPO_ROOT,
        check=True,
    )


def compose_up() -> None:
    write_default_nginx_conf()
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            COMPOSE_PROJECT,
            "up",
            "-d",
            "--build",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def compose_down() -> None:
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", COMPOSE_PROJECT, "down"],
        cwd=REPO_ROOT,
        check=True,
    )


def wait_until_healthy(verifier_module, *, timeout: float = HEALTH_WAIT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = verifier_module.verify(verifier_module.live_deps(), wait=True)
        if last.healthy():
            return
        time.sleep(HEALTH_POLL_INTERVAL)
    detail = last.model_dump() if last is not None else "no verifier result"
    pytest.fail(f"ops-lab did not become healthy within {timeout}s: {detail}")


def run_verify(verifier_module):
    return verifier_module.verify(verifier_module.live_deps(), wait=True)


def assert_healthy(verifier_module) -> None:
    result = run_verify(verifier_module)
    assert result.healthy(), result.model_dump()


def assert_matches_expected(result, expected) -> None:
    assert result.model_dump() == expected.model_dump()


def wait_for_verifier_expected(
    verifier_module,
    expected,
    *,
    timeout: float = 15.0,
):
    deadline = time.monotonic() + timeout
    last = None
    expected_dump = expected.model_dump()
    while time.monotonic() < deadline:
        last = run_verify(verifier_module)
        if last.model_dump() == expected_dump:
            return last
        time.sleep(0.5)
    detail = last.model_dump() if last is not None else "no verifier result"
    pytest.fail(
        f"timed out waiting for verifier expected {expected_dump}, last={detail}",
    )
