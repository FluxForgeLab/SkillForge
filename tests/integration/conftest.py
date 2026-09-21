"""Fixtures for ops-lab integration tests."""

from __future__ import annotations

import pytest

from tests.integration.support_ops_lab import (
    compose_down,
    compose_up,
    load_fault_modules,
    load_verifier_module,
    wait_until_healthy,
)


@pytest.fixture(scope="session")
def docker_available() -> None:
    import docker

    try:
        docker.from_env().ping()
    except Exception as exc:
        pytest.skip(f"Docker not available: {exc}")


@pytest.fixture(scope="session")
def ops_lab_verifier(docker_available):
    return load_verifier_module()


@pytest.fixture(scope="session")
def ops_lab_faults(docker_available):
    return load_fault_modules()


@pytest.fixture(scope="session")
def ops_lab(docker_available, ops_lab_verifier):
    compose_up()
    try:
        _catalog, _inject, reset = load_fault_modules()
        try:
            reset.reset()
        except Exception:
            pass
        wait_until_healthy(ops_lab_verifier)
        yield
    finally:
        _catalog, _inject, reset = load_fault_modules()
        try:
            reset.reset()
        except Exception:
            pass
        compose_down()
