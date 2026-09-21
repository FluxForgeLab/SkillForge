"""Load ops-lab fault catalog. Host-side; shared by inject, incident, and evaluator."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

VERIFIER_RESULT_FIELDS = frozenset(
    {
        "http_status",
        "backend_running",
        "nginx_config_valid",
        "upstream_port_matches",
        "db_running",
    }
)

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.yaml"


class VerifierExpectation(BaseModel):
    http_status: int
    backend_running: bool
    nginx_config_valid: bool
    upstream_port_matches: bool
    db_running: bool


class IncidentTemplate(BaseModel):
    title: str
    summary: str
    symptoms: list[str] = Field(min_length=1)


class FaultEntry(BaseModel):
    id: str
    fixture: str
    label: str
    description: str
    expected_after_inject: VerifierExpectation
    incident: IncidentTemplate

    @model_validator(mode="after")
    def fixture_matches_id(self) -> FaultEntry:
        if self.fixture != self.id:
            raise ValueError(f"fixture {self.fixture!r} must match id {self.id!r}")
        return self


class CatalogReset(BaseModel):
    command: str = "reset"


class FaultCatalog(BaseModel):
    version: int
    project: str
    health_url: str
    faults: list[FaultEntry]
    reset: CatalogReset = Field(default_factory=CatalogReset)

    @model_validator(mode="after")
    def unique_fault_ids(self) -> FaultCatalog:
        ids = [fault.id for fault in self.faults]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate fault id in catalog")
        fixtures = [fault.fixture for fault in self.faults]
        if len(fixtures) != len(set(fixtures)):
            raise ValueError("duplicate fixture in catalog")
        return self


def load_catalog(path: Path | None = None) -> FaultCatalog:
    catalog_path = path or CATALOG_PATH
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog = FaultCatalog.model_validate(raw)
    for fault in catalog.faults:
        keys = set(fault.expected_after_inject.model_dump())
        if keys != VERIFIER_RESULT_FIELDS:
            raise ValueError(
                f"fault {fault.id!r} expected_after_inject keys {sorted(keys)} "
                f"!= verifier fields {sorted(VERIFIER_RESULT_FIELDS)}"
            )
    return catalog


@lru_cache(maxsize=1)
def cached_catalog() -> FaultCatalog:
    return load_catalog()


def fault_ids(*, catalog: FaultCatalog | None = None) -> tuple[str, ...]:
    cat = catalog or cached_catalog()
    return tuple(fault.id for fault in cat.faults)


def get_fault(fault_id: str, *, catalog: FaultCatalog | None = None) -> FaultEntry:
    cat = catalog or cached_catalog()
    for fault in cat.faults:
        if fault.id == fault_id:
            return fault
    raise KeyError(f"unknown fault_id {fault_id!r}")


def require_fault(fault_id: str, *, catalog: FaultCatalog | None = None) -> FaultEntry:
    try:
        return get_fault(fault_id, catalog=catalog)
    except KeyError as exc:
        known = ", ".join(fault_ids(catalog=catalog))
        raise ValueError(f"unknown fault_id {fault_id!r}; known: {known}") from exc
