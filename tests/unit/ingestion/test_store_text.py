"""C5.1: content-addressed uploads and line-preserving markdown/text parse."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.source_documents import list_source_documents
from skillforge.domain.entities import Project
from skillforge.ingestion import IngestError, parse_stored, store_upload

_MARKDOWN = b"# Title\n\nbody\n"


def test_markdown_keeps_blank_line_numbers(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    project_id = _seed(db_path)
    document = store_upload(db_path, project_id, "runbook.md", _MARKDOWN, root=root)
    parsed = parse_stored(document, root)
    assert document.parser == "markdown"
    assert document.version == "1"
    assert document.sha256 == hashlib.sha256(_MARKDOWN).hexdigest()
    assert [(line.number, line.text) for line in parsed.lines] == [
        (1, "# Title"),
        (2, ""),
        (3, "body"),
    ]
    blob = root / project_id / document.sha256 / "source"
    assert blob.read_bytes() == _MARKDOWN


def test_same_bytes_keep_one_version(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    project_id = _seed(db_path)
    first = store_upload(db_path, project_id, "runbook.md", _MARKDOWN, root=root)
    second = store_upload(db_path, project_id, "runbook.md", _MARKDOWN, root=root)
    assert second.id == first.id
    assert second.version == "1"
    with connection(db_path) as conn:
        rows = list_source_documents(conn, project_id)
    assert len(rows) == 1


def test_new_bytes_increment_version_and_keep_old_blob(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    project_id = _seed(db_path)
    first = store_upload(db_path, project_id, "runbook.md", _MARKDOWN, root=root)
    updated = b"# Title\n\nbody changed\n"
    second = store_upload(db_path, project_id, "runbook.md", updated, root=root)
    assert second.version == "2"
    assert second.sha256 != first.sha256
    assert (root / project_id / first.sha256 / "source").read_bytes() == _MARKDOWN
    assert (root / project_id / second.sha256 / "source").read_bytes() == updated
    with connection(db_path) as conn:
        assert len(list_source_documents(conn, project_id)) == 2


def test_txt_parser_and_rejections(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    project_id = _seed(db_path)
    document = store_upload(db_path, project_id, "notes.TXT", b"line\n", root=root)
    assert document.parser == "text"
    assert parse_stored(document, root).lines[0].text == "line"
    with pytest.raises(IngestError):
        store_upload(db_path, project_id, "manual.pdf", b"%PDF", root=root)
    with pytest.raises(IngestError):
        store_upload(db_path, project_id, "../secret.md", _MARKDOWN, root=root)
    with pytest.raises(IngestError):
        store_upload(db_path, project_id, "bad.md", b"\xff", root=root)


def _seed(db_path: Path) -> str:
    initialize_database(db_path)
    project_id = "proj_1"
    with connection(db_path) as conn:
        insert_project(
            conn,
            Project(id=project_id, name="lab", created_at=datetime.now(UTC)),
        )
    return project_id
