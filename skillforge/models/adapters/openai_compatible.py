"""OpenAI-compatible chat completions adapter (httpx)."""

from __future__ import annotations

from typing import Any

import httpx

from skillforge.models.errors import ModelInvocationError
from skillforge.models.types import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    TokenUsage,
    ToolCall,
)


class OpenAICompatibleAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        default_model: str,
        default_temperature: float = 0.0,
        default_seed: int | None = None,
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._default_model = default_model
        self._default_temperature = default_temperature
        self._default_seed = default_seed
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )
        self._api_key = api_key

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def generate(self, request: ModelRequest) -> ModelResponse:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body: dict[str, Any] = {
            "model": request.model or self._default_model,
            "messages": [_message_to_api(message) for message in request.messages],
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self._default_temperature
            ),
        }
        seed = request.seed if request.seed is not None else self._default_seed
        if seed is not None:
            body["seed"] = seed
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]

        try:
            response = await self._client.post(
                "/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ModelInvocationError(
                f"model HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelInvocationError(str(exc)) from exc

        return _parse_chat_response(response.json())


def _message_to_api(message: ChatMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role}
    if message.role == "tool":
        payload["content"] = message.content or ""
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        return payload

    if message.content is not None:
        payload["content"] = message.content
    elif message.role == "assistant" and message.tool_calls:
        payload["content"] = None

    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    return payload


def _parse_chat_response(data: dict[str, Any]) -> ModelResponse:
    choices = data.get("choices") or []
    if not choices:
        raise ModelInvocationError("model response missing choices")

    message = choices[0].get("message") or {}
    tool_calls_raw = message.get("tool_calls") or []
    tool_calls = [
        ToolCall(
            id=item.get("id") or "",
            name=(item.get("function") or {}).get("name") or "",
            arguments=(item.get("function") or {}).get("arguments") or "{}",
        )
        for item in tool_calls_raw
    ]

    usage_raw = data.get("usage") or {}
    usage = TokenUsage(
        prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
        completion_tokens=int(usage_raw.get("completion_tokens") or 0),
        total_tokens=int(usage_raw.get("total_tokens") or 0),
    )

    return ModelResponse(
        content=message.get("content"),
        tool_calls=tool_calls,
        finish_reason=choices[0].get("finish_reason"),
        usage=usage,
        model=data.get("model"),
    )
