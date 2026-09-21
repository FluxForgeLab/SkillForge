"""Structured JSON output via ModelGateway with schema validation and retries."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ValidationError

from skillforge.config import Settings, get_settings
from skillforge.models.errors import ModelError
from skillforge.models.gateway import ModelGateway
from skillforge.models.types import ChatMessage, ModelRequest

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)


class StructuredOutputError(ModelError):
    """Structured output could not be parsed after all retry attempts."""

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        last_error: str,
        last_raw: str | None = None,
    ) -> None:
        self.attempts = attempts
        self.last_error = last_error
        self.last_raw = last_raw
        super().__init__(message)


def extract_json(text: str) -> str:
    """Return JSON payload text, stripping optional markdown fences."""
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def build_schema_instruction(schema: type[BaseModel], *, schema_title: str | None = None) -> str:
    json_schema = schema.model_json_schema(mode="validation")
    name = schema_title or schema.__name__
    return (
        "Respond with a single JSON object only (no markdown fences, no commentary) "
        f"that validates against the JSON Schema for {name}:\n"
        f"{json.dumps(json_schema, ensure_ascii=False)}"
    )


def build_retry_instruction(
    error: str,
    schema: type[BaseModel],
    *,
    schema_title: str | None = None,
) -> str:
    json_schema = schema.model_json_schema(mode="validation")
    name = schema_title or schema.__name__
    return (
        f"Your previous response was invalid: {error}\n"
        "Respond with JSON only (no markdown fences, no commentary) matching this schema "
        f"for {name}:\n"
        f"{json.dumps(json_schema, ensure_ascii=False)}"
    )


def parse_structured_content[T: BaseModel](content: str | None, schema: type[T]) -> T:
    if content is None or not content.strip():
        msg = "empty model content"
        raise ValueError(msg)

    raw = extract_json(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc

    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"schema validation failed: {exc}") from exc


def _copy_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [message.model_copy(deep=True) for message in messages]


async def generate_structured[T: BaseModel](
    gateway: ModelGateway,
    schema: type[T],
    *,
    run_id: str,
    messages: list[ChatMessage],
    stage: str | None = None,
    max_retries: int | None = None,
    temperature: float | None = None,
    schema_title: str | None = None,
    settings: Settings | None = None,
) -> T:
    resolved_settings = settings if settings is not None else get_settings()
    max_attempts = (
        max_retries if max_retries is not None else resolved_settings.structured_output_max_retries
    )
    if max_attempts < 1:
        msg = "max_retries must be at least 1"
        raise ValueError(msg)

    attempt_messages = _copy_messages(messages) + [
        ChatMessage(
            role="user",
            content=build_schema_instruction(schema, schema_title=schema_title),
        ),
    ]

    last_error = ""
    last_raw: str | None = None

    for attempt in range(max_attempts):
        response = await gateway.generate(
            ModelRequest(
                run_id=run_id,
                messages=attempt_messages,
                stage=stage,
                temperature=temperature,
            ),
        )
        last_raw = response.content
        try:
            return parse_structured_content(response.content, schema)
        except ValueError as exc:
            last_error = str(exc)
            if attempt + 1 >= max_attempts:
                break
            attempt_messages = attempt_messages + [
                ChatMessage(role="assistant", content=response.content or ""),
                ChatMessage(
                    role="user",
                    content=build_retry_instruction(
                        last_error,
                        schema,
                        schema_title=schema_title,
                    ),
                ),
            ]

    raise StructuredOutputError(
        f"structured output failed after {max_attempts} attempt(s): {last_error}",
        attempts=max_attempts,
        last_error=last_error,
        last_raw=last_raw,
    )
