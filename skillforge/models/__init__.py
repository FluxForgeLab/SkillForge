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
from skillforge.models.structured import (
    StructuredOutputError,
    build_schema_instruction,
    extract_json,
    generate_structured,
    parse_structured_content,
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
    "StructuredOutputError",
    "TokenUsage",
    "ToolCall",
    "ToolDefinition",
    "build_schema_instruction",
    "build_adapter",
    "extract_json",
    "generate_structured",
    "parse_structured_content",
    "fake_adapter_from_script",
    "get_model_gateway",
    "load_fake_script",
]
