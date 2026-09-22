"""System prompt for the agent loop. Skill text is added in C3.7."""

from __future__ import annotations

_BARE_PROMPT = (
    "You are the service recovery agent. Use the provided tools to handle the task. "
    "When the task is finished, reply with text and do not call tools."
)


def system_prompt(skill_path: str | None) -> str:
    del skill_path
    return _BARE_PROMPT
