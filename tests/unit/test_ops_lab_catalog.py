from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "faults" / "catalog.yaml"
_FAULTS_DIR = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "faults"
_VERIFY_PATH = Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "verifier" / "verify.py"


def _load_catalog_module():
    if str(_FAULTS_DIR) not in sys.path:
        sys.path.insert(0, str(_FAULTS_DIR))
    sys.modules.pop("catalog", None)
    return importlib.import_module("catalog")


def _load_inject_module():
    if str(_FAULTS_DIR) not in sys.path:
        sys.path.insert(0, str(_FAULTS_DIR))
    for name in ("dockerutil", "nginxfault", "catalog", "inject"):
        sys.modules.pop(name, None)
    return importlib.import_module("inject")


def _verifier_result_fields() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location("ops_lab_verifier", _VERIFY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return frozenset(module.RESULT_FIELDS)


def test_catalog_loads_three_faults() -> None:
    catalog = _load_catalog_module()
    cat = catalog.load_catalog(_CATALOG_PATH)
    assert cat.version == 1
    assert cat.project == "skillforge-lab"
    assert len(cat.faults) == 3
    assert catalog.fault_ids(catalog=cat) == (
        "backend_stopped",
        "nginx_wrong_upstream",
        "nginx_bad_config_reload",
    )


def test_catalog_expected_keys_match_verifier_fields() -> None:
    catalog = _load_catalog_module()
    cat = catalog.load_catalog(_CATALOG_PATH)
    assert catalog.VERIFIER_RESULT_FIELDS == _verifier_result_fields()
    for fault in cat.faults:
        assert set(fault.expected_after_inject.model_dump()) == catalog.VERIFIER_RESULT_FIELDS


def test_get_fault_unknown_raises() -> None:
    catalog = _load_catalog_module()
    with pytest.raises(KeyError, match="unknown fault_id"):
        catalog.get_fault("not-a-fault", catalog=catalog.load_catalog(_CATALOG_PATH))


def test_require_fault_lists_known_ids() -> None:
    catalog = _load_catalog_module()
    with pytest.raises(ValueError, match="known: backend_stopped"):
        catalog.require_fault("missing", catalog=catalog.load_catalog(_CATALOG_PATH))


def test_inject_fault_ids_match_catalog() -> None:
    catalog = _load_catalog_module()
    inject = _load_inject_module()
    cat = catalog.load_catalog(_CATALOG_PATH)
    catalog_ids = set(catalog.fault_ids(catalog=cat))
    inject_ids = {
        inject.FAULT_BACKEND_STOPPED,
        inject.FAULT_NGINX_WRONG_UPSTREAM,
        inject.FAULT_NGINX_BAD_CONFIG_RELOAD,
    }
    assert inject_ids == catalog_ids
