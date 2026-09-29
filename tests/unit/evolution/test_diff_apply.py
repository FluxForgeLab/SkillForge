"""Unified diffs apply when the hunk text is unique but the line number is off."""

from pathlib import Path

import pytest

from skillforge.evolution.diff_apply import apply_unified_diff

_SKILL = """\
## Never do


## Verification

HTTP 200 means the service recovered.
"""


def test_off_by_one_hunk_applies_at_the_matching_context(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(_SKILL, encoding="utf-8")
    diff = """\
--- a/SKILL.md
+++ b/SKILL.md
@@ -1,3 +1,4 @@
 ## Verification
 
 HTTP 200 means the service recovered.
+ins_04 Run nginx -t before nginx.reload.
"""
    apply_unified_diff(skill, diff)
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert "ins_04 Run nginx -t before nginx.reload." in text
    assert text.index("## Verification") < text.index("ins_04")


def test_exact_line_number_still_applies(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("alpha\nbeta\n", encoding="utf-8")
    diff = """\
--- a/SKILL.md
+++ b/SKILL.md
@@ -2,1 +2,1 @@
-beta
+gamma
"""
    apply_unified_diff(skill, diff)
    assert (skill / "SKILL.md").read_text(encoding="utf-8") == "alpha\ngamma\n"


def test_missing_context_still_fails(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("only this line\n", encoding="utf-8")
    diff = """\
--- a/SKILL.md
+++ b/SKILL.md
@@ -4,1 +4,1 @@
-missing line
+replacement
"""
    with pytest.raises(ValueError, match="hunk context mismatch"):
        apply_unified_diff(skill, diff)


def test_repeated_context_is_not_guessed(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("same\nsame\n", encoding="utf-8")
    diff = """\
--- a/SKILL.md
+++ b/SKILL.md
@@ -9,1 +9,1 @@
-same
+other
"""
    with pytest.raises(ValueError, match="matched 2 places"):
        apply_unified_diff(skill, diff)
