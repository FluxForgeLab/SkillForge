"""C5.7: skillforge index rebuild."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from skillforge.cli import main
from skillforge.config import Settings
from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.chunks import insert_chunks
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.source_documents import insert_source_document
from skillforge.domain.entities import Chunk, Project, SourceDocument


def test_index_rebuild_prints_project(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "app.sqlite"
    _seed(db_path)
    monkeypatch.setattr(
        "skillforge.cli.get_settings",
        lambda: Settings(_env_file=None, sqlite_path=db_path),
    )
    code = main(["index", "rebuild", "--project", "proj_1"])
    assert code == 0
    assert "rebuilt\tproj_1" in capsys.readouterr().out


def test_index_rebuild_unknown_project_exits_2(tmp_path: Path, monkeypatch, capsys) -> None:
    db_path = tmp_path / "app.sqlite"
    initialize_database(db_path)
    monkeypatch.setattr(
        "skillforge.cli.get_settings",
        lambda: Settings(_env_file=None, sqlite_path=db_path),
    )
    code = main(["index", "rebuild", "--project", "missing"])
    assert code == 2
    assert "unknown project" in capsys.readouterr().err


def _seed(db_path: Path) -> None:
    initialize_database(db_path)
    now = datetime.now(UTC)
    with connection(db_path) as conn:
        insert_project(conn, Project(id="proj_1", name="lab", created_at=now))
        insert_source_document(
            conn,
            SourceDocument(
                id="doc_1",
                project_id="proj_1",
                filename="notes.md",
                sha256="abc",
                version="1",
                parser="markdown",
                created_at=now,
            ),
        )
        insert_chunks(
            conn,
            [
                Chunk(
                    id="chunk_1",
                    document_id="doc_1",
                    project_id="proj_1",
                    ordinal=0,
                    text="Title body",
                    title="Title",
                    line_start=1,
                    line_end=1,
                )
            ],
        )
