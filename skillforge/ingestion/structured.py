"""PDF, YAML, JSON, and OpenAPI parsers."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import yaml
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from skillforge.ingestion.errors import IngestError
from skillforge.ingestion.text import ParsedDocument, ParsedSegment

_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")


def parse_pdf(data: bytes) -> ParsedDocument:
    """One segment per page. ``page`` is 1-based."""
    try:
        reader = PdfReader(BytesIO(data))
        segments = [
            ParsedSegment(text=page.extract_text() or "", page=number)
            for number, page in enumerate(reader.pages, start=1)
        ]
    except PdfReadError as exc:
        raise IngestError("pdf could not be parsed") from exc
    if not segments:
        raise IngestError("pdf has no pages")
    return ParsedDocument(parser="pdf", segments=segments)


def classify_structured(filename: str, text: str) -> str:
    """Return ``yaml``, ``json``, or ``openapi`` after the text parses."""
    suffix = Path(filename).suffix.lower()
    loaded = _load(text, suffix)
    if _is_openapi(loaded):
        return "openapi"
    if suffix == ".json":
        return "json"
    return "yaml"


def parse_structured(text: str, parser: str, filename: str) -> ParsedDocument:
    """Re-parse a stored YAML, JSON, or OpenAPI document."""
    suffix = Path(filename).suffix.lower()
    if parser == "openapi":
        loaded = _load(text, suffix)
        if not _is_openapi(loaded):
            raise IngestError("stored openapi document has no paths")
        return ParsedDocument(parser="openapi", segments=_operations(loaded))
    if parser in {"yaml", "json"}:
        _load(text, ".json" if parser == "json" else ".yaml")
        return ParsedDocument(parser=parser, segments=[_whole(text)])
    raise IngestError(f"unsupported parser {parser!r}")


def _load(text: str, suffix: str) -> object:
    try:
        if suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise IngestError("structured source could not be parsed") from exc


def _is_openapi(loaded: object) -> bool:
    if not isinstance(loaded, dict):
        return False
    if "openapi" not in loaded and "swagger" not in loaded:
        return False
    return isinstance(loaded.get("paths"), dict)


def _operations(loaded: dict[str, object]) -> list[ParsedSegment]:
    paths = loaded["paths"]
    if not isinstance(paths, dict):
        return []
    segments: list[ParsedSegment] = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in _METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            lines = [f"{method.upper()} {path}"]
            operation_id = operation.get("operationId")
            if isinstance(operation_id, str) and operation_id:
                lines.append(f"operationId: {operation_id}")
            summary = operation.get("summary")
            if isinstance(summary, str) and summary:
                lines.append(f"summary: {summary}")
            segments.append(ParsedSegment(text="\n".join(lines)))
    return segments


def _whole(text: str) -> ParsedSegment:
    count = len(text.splitlines())
    return ParsedSegment(text=text, line_start=1, line_end=count)
