"""Domain-level errors."""

from __future__ import annotations

from typing import Literal


class SkillForgeError(Exception):
    """Base error for SkillForge application logic."""


class InvalidStateTransition(SkillForgeError):
    """Raised when a state machine transition is not allowed."""

    def __init__(
        self,
        *,
        machine: Literal["pipeline", "skill_version"],
        current: str,
        target: str,
    ) -> None:
        self.machine = machine
        self.current = current
        self.target = target
        super().__init__(
            f"{machine} state transition not allowed: {current!r} -> {target!r}",
        )
