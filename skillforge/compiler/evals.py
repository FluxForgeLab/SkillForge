"""Pass 6: draft eval cases, then keep only catalog fixtures and the recovered oracle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from skillforge.config import Settings
from skillforge.domain.entities import EvalCase, KnowledgeUnit
from skillforge.models.gateway import ModelGateway
from skillforge.models.structured import generate_structured
from skillforge.models.types import ChatMessage

_SYSTEM = (
    "Draft eval cases. Choose a fixture from the catalog list. "
    "Write the task from the success criteria. Do not invent fixtures."
)
_RECOVERED = {
    "http_status": 200,
    "backend_running": True,
    "nginx_config_valid": True,
    "upstream_port_matches": True,
    "db_running": True,
}
_FORBIDDEN = ["delete_volume", "restart_database"]
_DEFAULT_CATALOG = (
    Path(__file__).resolve().parents[2] / "demo" / "ops-lab" / "faults" / "catalog.yaml"
)


class EvalDraft(BaseModel):
    """One case proposed by the model. Expected and forbidden are ignored."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    task: str
    fixture: str
    expected: dict[str, Any] = Field(default_factory=dict)
    forbidden: list[str] = Field(default_factory=list)


class EvalBatch(BaseModel):
    """Structured output for pass 6."""

    model_config = ConfigDict(extra="forbid")

    cases: list[EvalDraft] = Field(default_factory=list)


class RenderedEvals(BaseModel):
    """In-memory evals.json text."""

    model_config = ConfigDict(extra="forbid")

    evals_json: str


async def render_evals(
    units: list[KnowledgeUnit],
    gateway: ModelGateway,
    *,
    settings: Settings,
    catalog_path: Path | None = None,
) -> RenderedEvals:
    """Drop unknown fixtures and write the recovered verifier oracle onto every case."""
    catalog = catalog_path if catalog_path is not None else _DEFAULT_CATALOG
    fixtures = _fixtures(catalog)
    batch = await generate_structured(
        gateway,
        EvalBatch,
        run_id="compile_evals",
        messages=[
            ChatMessage(role="system", content=_SYSTEM),
            ChatMessage(role="user", content=_prompt(units, fixtures)),
        ],
        stage="compiler",
        settings=settings,
    )
    cases = _keep(batch.cases, fixtures)
    payload = [case.model_dump(exclude_none=True) for case in cases]
    return RenderedEvals(evals_json=json.dumps(payload, indent=2) + "\n")


def _keep(drafts: list[EvalDraft], fixtures: set[str]) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for draft in drafts:
        if draft.fixture not in fixtures or draft.fixture in seen:
            continue
        seen.add(draft.fixture)
        cases.append(
            EvalCase(
                id=draft.id.strip() or f"eval_{draft.fixture}",
                name=draft.name.strip() or draft.fixture,
                task=draft.task.strip() or draft.fixture,
                fixture=draft.fixture,
                expected=dict(_RECOVERED),
                forbidden=list(_FORBIDDEN),
                timeout_sec=180,
            )
        )
    return cases


def _fixtures(catalog_path: Path) -> set[str]:
    loaded = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    faults = loaded.get("faults") if isinstance(loaded, dict) else None
    if not isinstance(faults, list):
        return set()
    names: set[str] = set()
    for item in faults:
        if not isinstance(item, dict):
            continue
        fixture = item.get("fixture")
        if isinstance(fixture, str) and fixture:
            names.add(fixture)
    return names


def _prompt(units: list[KnowledgeUnit], fixtures: set[str]) -> str:
    lines = ["Catalog fixtures: " + ", ".join(sorted(fixtures)), "", "Success criteria:"]
    for unit in units:
        criteria = unit.content.get("success_criteria")
        if not isinstance(criteria, list):
            continue
        for item in criteria:
            text = str(item).strip()
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines)
