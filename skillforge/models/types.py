"""Model request/response types and trace payload helpers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ChatRole = Literal["system", "user", "assistant", "tool"]

_TRACE_CONTENT_LIMIT = 2000


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str = "{}"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class ToolDefinition(BaseModel):
    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelRequest(BaseModel):
    run_id: str
    messages: list[ChatMessage]
    tools: list[ToolDefinition] = Field(default_factory=list)
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    stage: str | None = None


class ModelResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str | None = None


def _truncate(text: str | None, limit: int = _TRACE_CONTENT_LIMIT) -> str | None:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def request_trace_payload(request: ModelRequest) -> dict[str, Any]:
    return {
        "model": request.model,
        "message_count": len(request.messages),
        "messages": [
            {
                "role": message.role,
                "content": _truncate(message.content),
                "tool_call_id": message.tool_call_id,
                "tool_call_names": [call.name for call in message.tool_calls],
            }
            for message in request.messages
        ],
        "tools": [tool.name for tool in request.tools],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "seed": request.seed,
    }


def response_trace_payload(response: ModelResponse) -> dict[str, Any]:
    return {
        "model": response.model,
        "content": _truncate(response.content),
        "finish_reason": response.finish_reason,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": _truncate(call.arguments, 500)}
            for call in response.tool_calls
        ],
        "usage": response.usage.model_dump(),
    }
