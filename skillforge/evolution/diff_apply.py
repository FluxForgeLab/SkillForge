"""Minimal unified-diff apply using only the stdlib (no ``patch`` / unidiff)."""

from __future__ import annotations

import re
from pathlib import Path

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_FILE_HEADER_RE = re.compile(r"^(---|\+\+\+) ([^\t\n]+)")


def normalize_diff_path(raw: str) -> str:
    """Strip ``a/`` / ``b/`` prefixes and ``/dev/null`` → empty."""
    path = raw.strip().strip('"')
    if path in {"/dev/null", "dev/null"}:
        return ""
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path.replace("\\", "/")


def iter_diff_paths(diff_text: str) -> list[str]:
    """Return relative paths touched by a unified diff (empty string for /dev/null)."""
    paths: list[str] = []
    seen: set[str] = set()
    for line in diff_text.splitlines():
        match = _FILE_HEADER_RE.match(line)
        if match is None:
            continue
        normalized = normalize_diff_path(match.group(2))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        paths.append(normalized)
    return paths


def touches_evals(diff_text: str) -> bool:
    """True when any path in the diff is under ``evals/``."""
    for path in iter_diff_paths(diff_text):
        if path == "evals" or path.startswith("evals/"):
            return True
    return False


def apply_unified_diff(root: Path, diff_text: str) -> list[str]:
    """Apply a unified diff under ``root``. Returns relative paths that changed."""
    root = Path(root)
    changed: list[str] = []
    for old_path, new_path, hunks in _parse_files(diff_text):
        target_rel = new_path or old_path
        if not target_rel:
            raise ValueError("unified diff file has neither old nor new path")
        target = root / target_rel
        if new_path == "" and old_path:
            # deleted file
            old_file = root / old_path
            if old_file.is_file():
                old_file.unlink()
            changed.append(old_path)
            continue
        if old_path and (root / old_path).is_file():
            original = (root / old_path).read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            original = []
        patched = _apply_hunks(original, hunks)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(patched), encoding="utf-8")
        changed.append(target_rel)
    return changed


def _parse_files(
    diff_text: str,
) -> list[tuple[str, str, list[tuple[int, int, list[str]]]]]:
    lines = diff_text.splitlines(keepends=True)
    files: list[tuple[str, str, list[tuple[int, int, list[str]]]]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("--- "):
            i += 1
            continue
        old_raw = line[4:].split("\t", 1)[0].rstrip("\r\n")
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise ValueError("unified diff missing +++ header after ---")
        new_raw = lines[i][4:].split("\t", 1)[0].rstrip("\r\n")
        i += 1
        old_path = normalize_diff_path(old_raw)
        new_path = normalize_diff_path(new_raw)
        hunks: list[tuple[int, int, list[str]]] = []
        while i < len(lines) and lines[i].startswith("@@ "):
            match = _HUNK_RE.match(lines[i].rstrip("\r\n"))
            if match is None:
                raise ValueError(f"invalid hunk header: {lines[i]!r}")
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            i += 1
            body: list[str] = []
            while i < len(lines):
                body_line = lines[i]
                if body_line.startswith("--- ") or body_line.startswith("@@ "):
                    break
                if body_line.startswith("\\"):  # "\ No newline at end of file"
                    i += 1
                    continue
                if body_line[:1] in {" ", "+", "-", "\n"} or body_line.startswith("\r"):
                    body.append(
                        body_line if body_line.endswith(("\n", "\r\n")) else body_line + "\n"
                    )
                    i += 1
                    continue
                break
            hunks.append((old_start, old_count, body))
        files.append((old_path, new_path, hunks))
    if not files:
        raise ValueError("unified diff contains no file headers")
    return files


def _apply_hunks(
    original: list[str],
    hunks: list[tuple[int, int, list[str]]],
) -> list[str]:
    result = list(original)
    # Apply from bottom to top so line numbers stay valid.
    for old_start, old_count, body in reversed(hunks):
        start = max(old_start - 1, 0)
        old_lines: list[str] = []
        new_lines: list[str] = []
        for raw in body:
            tag = raw[:1]
            content = raw[1:] if tag in {" ", "+", "-"} else raw
            if not content.endswith("\n") and tag in {" ", "+", "-"}:
                content = content + "\n"
            if tag == " ":
                old_lines.append(content)
                new_lines.append(content)
            elif tag == "-":
                old_lines.append(content)
            elif tag == "+":
                new_lines.append(content)
            elif tag == "\n" or raw.strip() == "":
                # rare empty context line without prefix
                old_lines.append("\n")
                new_lines.append("\n")
            else:
                raise ValueError(f"invalid hunk line: {raw!r}")
        end = start + len(old_lines)
        if old_count == 0:
            end = start
        expected = result[start:end]
        if expected != old_lines:
            raise ValueError(
                f"hunk context mismatch at line {old_start}: "
                f"expected {old_lines!r} got {expected!r}"
            )
        result[start:end] = new_lines
    return result
