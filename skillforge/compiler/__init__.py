"""Skill compiler. C6.1 validates SkillSpec before any generation pass."""

from skillforge.compiler.spec import SkillSpecError, load_skill_spec, validate_skill_spec

__all__ = [
    "SkillSpecError",
    "load_skill_spec",
    "validate_skill_spec",
]
