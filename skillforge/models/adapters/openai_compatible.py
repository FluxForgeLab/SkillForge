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
        local_names = [tool.name for tool in request.tools]
        api_to_local = {_api_tool_name(name): name for name in local_names}
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": _api_tool_name(tool.name),
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
        body["messages"] = [_message_to_api(message, local_names) for message in request.messages]

        try:
            response = await self._client.post(
                "/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise ModelInvocationError(
                f"model HTTP {exc.response.status_code}: {detail}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelInvocationError(str(exc)) from exc

        return _parse_chat_response(response.json(), api_to_local)


def _api_tool_name(name: str) -> str:
    return name.replace(".", "_")


def _message_to_api(message: ChatMessage, local_names: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role}
    content = _rewrite_tool_names(message.content, local_names)
    if message.role == "tool":
        payload["content"] = content or ""
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        return payload

    if content is not None:
        payload["content"] = content
    elif message.role == "assistant" and message.tool_calls:
        payload["content"] = None

    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": _api_tool_name(call.name),
                    "arguments": call.arguments,
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _rewrite_tool_names(content: str | None, local_names: list[str]) -> str | None:
    if content is None:
        return None
    rewritten = content
    for name in sorted(local_names, key=len, reverse=True):
        rewritten = rewritten.replace(name, _api_tool_name(name))
    return rewritten


def _tool_call_from_api(item: dict[str, Any], api_to_local: dict[str, str]) -> ToolCall:
    function = item.get("function") or {}
    api_name = function.get("name") or ""
    return ToolCall(
        id=item.get("id") or "",
        name=api_to_local.get(api_name) or api_name,
        arguments=function.get("arguments") or "{}",
    )


def _parse_chat_response(data: dict[str, Any], api_to_local: dict[str, str]) -> ModelResponse:
    choices = data.get("choices") or []
    if not choices:
        raise ModelInvocationError("model response missing choices")

    message = choices[0].get("message") or {}
    tool_calls_raw = message.get("tool_calls") or []
    tool_calls = [_tool_call_from_api(item, api_to_local) for item in tool_calls_raw]

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
