"""Load evals.json and map each fixture onto the ops-lab fault catalog."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from skillforge.domain.entities import EvalCase
from skillforge.evaluator.errors import EvalLoadError

# Same names as demo/ops-lab/verifier/verify.py RESULT_FIELDS.
_VERIFIER_FIELDS = frozenset(
    {
        "http_status",
        "backend_running",
        "nginx_config_valid",
        "upstream_port_matches",
        "db_running",
    }
)
_DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "faults" / "catalog.yaml"
)


class LoadedEvalCase(BaseModel):
    """One eval case plus the catalog fault id its fixture resolved to."""

    model_config = ConfigDict(extra="forbid")

    case: EvalCase
    fault_id: str


def load_eval_cases(
    skill_path: str | Path,
    catalog_path: str | Path | None = None,
) -> list[LoadedEvalCase]:
    """Read eval cases and attach each fixture's fault id from the catalog."""
    evals_path = _evals_path(Path(skill_path))
    cases = _parse_cases(evals_path)
    fixtures = _fixture_index(Path(catalog_path) if catalog_path is not None else _DEFAULT_CATALOG)
    loaded: list[LoadedEvalCase] = []
    for case in cases:
        fault_id = fixtures.get(case.fixture)
        if fault_id is None:
            known = ", ".join(sorted(fixtures))
            raise EvalLoadError(f"unknown fixture {case.fixture!r}; known: {known}")
        loaded.append(LoadedEvalCase(case=case, fault_id=fault_id))
    return loaded


def _evals_path(skill_path: Path) -> Path:
    if skill_path.is_file():
        if skill_path.name != "evals.json":
            raise EvalLoadError(f"skill path must be a skill directory or evals.json: {skill_path}")
        return skill_path
    candidate = skill_path / "evals" / "evals.json"
    if not candidate.is_file():
        raise EvalLoadError(f"evals.json not found: {candidate}")
    return candidate


def _parse_cases(evals_path: Path) -> list[EvalCase]:
    try:
        raw = json.loads(evals_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalLoadError(f"evals.json is not valid JSON: {evals_path}") from exc
    if not isinstance(raw, list):
        raise EvalLoadError(f"evals.json root must be a list: {evals_path}")
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        try:
            case = EvalCase.model_validate(item)
        except ValidationError as exc:
            raise EvalLoadError(f"eval case at index {index} is invalid: {exc}") from exc
        if case.id in seen:
            raise EvalLoadError(f"duplicate eval case id {case.id!r}")
        seen.add(case.id)
        unknown = set(case.expected) - _VERIFIER_FIELDS
        if unknown:
            allowed = ", ".join(sorted(_VERIFIER_FIELDS))
            keys = ", ".join(sorted(unknown))
            raise EvalLoadError(
                f"eval case {case.id!r} unexpected expected keys: {keys}; allowed: {allowed}"
            )
        cases.append(case)
    return cases


def _fixture_index(catalog_path: Path) -> dict[str, str]:
    if not catalog_path.is_file():
        raise EvalLoadError(f"catalog not found: {catalog_path}")
    try:
        loaded = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise EvalLoadError(f"catalog is not valid YAML: {catalog_path}") from exc
    faults = loaded.get("faults") if isinstance(loaded, dict) else None
    if not isinstance(faults, list):
        raise EvalLoadError(f"catalog faults must be a list: {catalog_path}")
    index: dict[str, str] = {}
    for item in faults:
        if not isinstance(item, dict):
            raise EvalLoadError(f"catalog fault must be a mapping: {catalog_path}")
        fixture = item.get("fixture")
        fault_id = item.get("id")
        if not isinstance(fixture, str) or not isinstance(fault_id, str):
            raise EvalLoadError(f"catalog fault requires string id and fixture: {catalog_path}")
        if fixture in index:
            raise EvalLoadError(f"duplicate fixture {fixture!r}")
        index[fixture] = fault_id
    return index
