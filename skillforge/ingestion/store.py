"""Content-addressed upload storage for source documents."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from skillforge.config import get_settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.projects import get_project
from skillforge.db.repositories.source_documents import (
    insert_source_document,
    list_source_documents_by_filename,
)
from skillforge.domain.entities import SourceDocument
from skillforge.ingestion.errors import IngestError

_MARKDOWN = {".md", ".markdown"}
_TEXT = {".txt"}


def store_upload(
    db_path: Path,
    project_id: str,
    filename: str,
    data: bytes,
    *,
    root: Path | None = None,
) -> SourceDocument:
    """Store raw bytes under ``root/<project>/<sha256>/source`` and record a version.

    Re-uploading the same bytes for the same filename returns the existing row.
    A new byte string for that filename opens a new sha directory and increments version.
    """
    name = _plain_name(filename, field="filename")
    _plain_name(project_id, field="project_id")
    parser = _parser_for(name)
    _require_utf8(data)
    digest = hashlib.sha256(data).hexdigest()
    storage = root if root is not None else get_settings().data_dir / "sources"
    initialize_database(db_path)
    with connection(db_path) as conn:
        if get_project(conn, project_id) is None:
            raise IngestError(f"unknown project {project_id!r}")
        previous = list_source_documents_by_filename(conn, project_id, name)
        match = next((item for item in previous if item.sha256 == digest), None)
        if match is not None:
            _write_blob(storage, project_id, digest, data)
            return match
        version = "1" if not previous else str(max(int(item.version) for item in previous) + 1)
        document = SourceDocument(
            id=f"doc_{uuid4().hex}",
            project_id=project_id,
            filename=name,
            sha256=digest,
            version=version,
            parser=parser,
            created_at=datetime.now(UTC),
        )
        _write_blob(storage, project_id, digest, data)
        insert_source_document(conn, document)
        return document


def _plain_name(value: str, *, field: str) -> str:
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise IngestError(f"{field} must be a single path segment: {value!r}")
    return value


def _parser_for(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in _MARKDOWN:
        return "markdown"
    if suffix in _TEXT:
        return "text"
    raise IngestError(f"unsupported source type {suffix or filename!r}")


def _require_utf8(data: bytes) -> None:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError("upload is not valid UTF-8") from exc


def _write_blob(root: Path, project_id: str, digest: str, data: bytes) -> None:
    path = root / project_id / digest / "source"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() != data:
        raise IngestError(f"sha directory already holds different bytes: {digest}")
    if not path.is_file():
        path.write_bytes(data)
