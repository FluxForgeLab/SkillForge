"""Line-preserving parsers for markdown and plain text."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from skillforge.domain.entities import SourceDocument
from skillforge.ingestion.errors import IngestError

TextParser = Literal["markdown", "text"]


class ParsedLine(BaseModel):
    """One source line. ``number`` is 1-based."""

    model_config = ConfigDict(extra="forbid")

    number: int
    text: str


class ParsedDocument(BaseModel):
    """Full text split into lines. Headings stay as text for a later chunker."""

    model_config = ConfigDict(extra="forbid")

    parser: TextParser
    lines: list[ParsedLine]


def parse_markdown(text: str) -> ParsedDocument:
    """Split markdown on lines without dropping blank lines or heading marks."""
    return _split(text, "markdown")


def parse_text(text: str) -> ParsedDocument:
    """Split plain text on lines without dropping blank lines."""
    return _split(text, "text")


def parse_stored(document: SourceDocument, root: Path) -> ParsedDocument:
    """Read a stored blob and parse it with the recorded parser name."""
    path = root / document.project_id / document.sha256 / "source"
    if not path.is_file():
        raise IngestError(f"stored source missing: {path}")
    text = path.read_text(encoding="utf-8")
    if document.parser == "markdown":
        return parse_markdown(text)
    if document.parser == "text":
        return parse_text(text)
    raise IngestError(f"unsupported parser {document.parser!r}")


def _split(text: str, parser: TextParser) -> ParsedDocument:
    lines = [
        ParsedLine(number=number, text=line)
        for number, line in enumerate(text.splitlines(), start=1)
    ]
    return ParsedDocument(parser=parser, lines=lines)
