"""Model gateway errors."""

from __future__ import annotations

from skillforge.domain.errors import SkillForgeError


class ModelError(SkillForgeError):
    """Base error for model invocation."""


class ModelInvocationError(ModelError):
    """HTTP or transport failure talking to a model endpoint."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class ModelScriptExhaustedError(ModelError):
    """Fake adapter has no scripted responses left."""

    def __init__(self) -> None:
        super().__init__("fake model script exhausted: no more scripted responses")
