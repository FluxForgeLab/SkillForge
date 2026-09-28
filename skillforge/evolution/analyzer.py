"""Classify a failed agent run into a structured Failure."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from skillforge.config import Settings, get_settings
from skillforge.domain.entities import Failure, TraceEvent
from skillforge.domain.enums import FailureClass
from skillforge.evaluator.assertions import AssertionResult
from skillforge.models.gateway import ModelGateway
from skillforge.models.structured import generate_structured
from skillforge.models.types import ChatMessage

_SYSTEM = (
    "You classify why an agent skill run failed. "
    "Pick exactly one FailureClass value. "
    "evidence must be verbatim substrings copied from the supplied trace payloads "
    "or verifier JSON — never invent or paraphrase evidence. "
    "Do not fill source_support; leave evidence retrieval to a later step."
)


class FailureDraft(BaseModel):
    """Model-proposed failure fields. Evidence is filtered before becoming Failure."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    failure_class: FailureClass = Field(alias="class")
    symptom: str
    failed_assertion: str | None = None
    evidence: list[str] = Field(default_factory=list)
    suspected_skill_gap: str | None = None


class FailureAnalyzer:
    """Turn trace + assertion + verifier into a domain Failure via structured model output."""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._gateway = gateway
        self._settings = settings if settings is not None else get_settings()

    async def analyze(
        self,
        *,
        run_id: str,
        events: Sequence[TraceEvent],
        assertion: AssertionResult,
        verifier: Mapping[str, Any],
    ) -> Failure:
        corpus = _evidence_corpus(events, verifier)
        draft = await generate_structured(
            self._gateway,
            FailureDraft,
            run_id=run_id,
            messages=[
                ChatMessage(role="system", content=_SYSTEM),
                ChatMessage(
                    role="user",
                    content=_user_prompt(events, assertion, verifier),
                ),
            ],
            stage="evolution",
            settings=self._settings,
        )
        return Failure(
            run_id=run_id,
            failure_class=draft.failure_class,
            symptom=draft.symptom,
            failed_assertion=draft.failed_assertion,
            evidence=_filter_evidence(draft.evidence, corpus),
            suspected_skill_gap=draft.suspected_skill_gap,
            source_support=[],
        )


def _user_prompt(
    events: Sequence[TraceEvent],
    assertion: AssertionResult,
    verifier: Mapping[str, Any],
) -> str:
    payload = {
        "assertion": assertion.model_dump(),
        "verifier": dict(verifier),
        "events": [
            {
                "type": event.type.value,
                "name": event.name,
                "input": event.input,
                "output": event.output,
            }
            for event in events
        ],
    }
    return (
        "Classify this failed run. Copy evidence strings verbatim from event "
        f"payloads or verifier JSON.\n\n{json.dumps(payload, ensure_ascii=False, default=str)}"
    )


def _evidence_corpus(events: Sequence[TraceEvent], verifier: Mapping[str, Any]) -> str:
    """Join payload text so evidence can match raw strings or JSON fragments."""
    parts: list[str] = []
    _collect_strings(dict(verifier), parts)
    parts.append(json.dumps(dict(verifier), ensure_ascii=False, default=str))
    for event in events:
        if event.name:
            parts.append(event.name)
        _collect_strings(event.input, parts)
        _collect_strings(event.output, parts)
        parts.append(json.dumps(event.input, ensure_ascii=False, default=str))
        parts.append(json.dumps(event.output, ensure_ascii=False, default=str))
    return "\n".join(parts)


def _collect_strings(value: Any, parts: list[str]) -> None:
    if isinstance(value, str):
        parts.append(value)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_strings(item, parts)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _collect_strings(item, parts)


def _filter_evidence(candidates: Sequence[str], corpus: str) -> list[str]:
    kept: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if not item or item in seen:
            continue
        if item not in corpus:
            continue
        seen.add(item)
        kept.append(item)
    return kept
