"""Split a parsed document into source-located chunks stored in SQLite."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.chunks import delete_chunks_by_document, insert_chunks
from skillforge.domain.entities import Chunk, SourceDocument
from skillforge.ingestion.text import ParsedDocument, ParsedLine, ParsedSegment

_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*))?$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def chunk_document(
    db_path: Path,
    document: SourceDocument,
    parsed: ParsedDocument,
) -> list[Chunk]:
    """Replace this document's chunks. Does not touch a retrieval index."""
    chunks = _chunks(document, parsed)
    initialize_database(db_path)
    with connection(db_path) as conn:
        delete_chunks_by_document(conn, document.id)
        if chunks:
            insert_chunks(conn, chunks)
    return chunks


def _chunks(document: SourceDocument, parsed: ParsedDocument) -> list[Chunk]:
    if parsed.parser == "markdown":
        return _from_markdown(document, parsed.lines)
    if parsed.parser == "text":
        return _from_lines(document, parsed.lines, title=None)
    if parsed.parser == "pdf":
        return [
            _segment_chunk(document, ordinal, segment, title=None)
            for ordinal, segment in enumerate(parsed.segments)
        ]
    if parsed.parser in {"yaml", "json"}:
        if not parsed.segments:
            return []
        return [_segment_chunk(document, 0, parsed.segments[0], title=None)]
    if parsed.parser == "openapi":
        return [
            _segment_chunk(document, ordinal, segment, title=_first_line(segment.text))
            for ordinal, segment in enumerate(parsed.segments)
        ]
    return []


def _from_markdown(document: SourceDocument, lines: list[ParsedLine]) -> list[Chunk]:
    sections: list[tuple[str | None, list[ParsedLine]]] = []
    current_title: str | None = None
    current: list[ParsedLine] = []
    fence: str | None = None
    started = False
    for line in lines:
        if fence is not None:
            current.append(line)
            if _closes_fence(line.text, fence):
                fence = None
            continue
        opened = _open_fence(line.text)
        if opened is not None:
            current.append(line)
            fence = opened
            continue
        heading = _heading_title(line.text)
        if heading is None:
            current.append(line)
            continue
        if current:
            sections.append((current_title, current))
        elif started:
            sections.append((current_title, []))
        started = True
        current_title = heading
        current = [line]
    if current or (started and not sections):
        sections.append((current_title, current))
    built = [
        _line_chunk(document, ordinal, title, section)
        for ordinal, (title, section) in enumerate(sections)
        if section
    ]
    return built


def _from_lines(
    document: SourceDocument,
    lines: list[ParsedLine],
    title: str | None,
) -> list[Chunk]:
    if not lines:
        return []
    return [_line_chunk(document, 0, title, lines)]


def _line_chunk(
    document: SourceDocument,
    ordinal: int,
    title: str | None,
    lines: list[ParsedLine],
) -> Chunk:
    return Chunk(
        id=f"chunk_{uuid4().hex}",
        document_id=document.id,
        project_id=document.project_id,
        ordinal=ordinal,
        text="\n".join(line.text for line in lines),
        title=title,
        line_start=lines[0].number,
        line_end=lines[-1].number,
    )


def _segment_chunk(
    document: SourceDocument,
    ordinal: int,
    segment: ParsedSegment,
    title: str | None,
) -> Chunk:
    return Chunk(
        id=f"chunk_{uuid4().hex}",
        document_id=document.id,
        project_id=document.project_id,
        ordinal=ordinal,
        text=segment.text,
        title=title,
        page=segment.page,
        line_start=segment.line_start,
        line_end=segment.line_end,
    )


def _heading_title(line: str) -> str | None:
    match = _ATX.match(line)
    if match is None:
        return None
    body = match.group(2) or ""
    body = re.sub(r"\s+#+\s*$", "", body).strip()
    return body


def _open_fence(line: str) -> str | None:
    match = _FENCE.match(line)
    if match is None:
        return None
    return match.group(1)[0] * 3


def _closes_fence(line: str, marker: str) -> bool:
    stripped = line.strip()
    char = marker[0]
    return len(stripped) >= 3 and stripped.startswith(marker) and set(stripped) == {char}


def _first_line(text: str) -> str | None:
    lines = text.splitlines()
    if not lines:
        return None
    return lines[0]
