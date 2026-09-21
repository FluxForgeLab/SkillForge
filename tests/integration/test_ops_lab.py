"""Integration tests: inject → verify → reset for each catalog fault."""

from __future__ import annotations

import pytest

from tests.integration.support_ops_lab import (
    assert_healthy,
    catalog_fault_entries,
    wait_for_verifier_expected,
    wait_until_healthy,
)


@pytest.fixture(autouse=True)
def _reset_ops_lab_after_each_test(ops_lab, ops_lab_faults) -> None:
    yield
    _catalog, _inject, reset = ops_lab_faults
    try:
        reset.reset()
    except Exception:
        pass


@pytest.mark.integration
def test_ops_lab_starts_healthy(ops_lab, ops_lab_verifier) -> None:
    assert_healthy(ops_lab_verifier)


@pytest.mark.integration
@pytest.mark.parametrize(
    "fault_entry",
    catalog_fault_entries(),
    ids=lambda fault: fault.id,
)
def test_inject_verify_reset_cycle(
    ops_lab,
    ops_lab_verifier,
    ops_lab_faults,
    fault_entry,
) -> None:
    _catalog, inject, reset = ops_lab_faults
    reset.reset()
    wait_until_healthy(ops_lab_verifier, timeout=30.0)
    assert_healthy(ops_lab_verifier)

    inject.inject(fault_entry.id)
    after_inject = wait_for_verifier_expected(
        ops_lab_verifier,
        fault_entry.expected_after_inject,
    )
    assert not after_inject.healthy(), after_inject.model_dump()

    reset.reset()
    wait_until_healthy(ops_lab_verifier, timeout=30.0)
    assert_healthy(ops_lab_verifier)
