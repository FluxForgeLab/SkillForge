"""Model gateway and adapters."""

from skillforge.models.adapters import FakeModelAdapter, OpenAICompatibleAdapter
from skillforge.models.errors import (
    ModelError,
    ModelInvocationError,
    ModelScriptExhaustedError,
)
from skillforge.models.gateway import (
    ModelGateway,
    build_adapter,
    fake_adapter_from_script,
    get_model_gateway,
    load_fake_script,
)
from skillforge.models.types import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

__all__ = [
    "ChatMessage",
    "FakeModelAdapter",
    "ModelError",
    "ModelGateway",
    "ModelInvocationError",
    "ModelRequest",
    "ModelResponse",
    "ModelScriptExhaustedError",
    "OpenAICompatibleAdapter",
    "TokenUsage",
    "ToolCall",
    "ToolDefinition",
    "build_adapter",
    "fake_adapter_from_script",
    "get_model_gateway",
    "load_fake_script",
]
