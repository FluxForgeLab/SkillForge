"""C5.3: heading-aware chunks keep line numbers that slice back to the source."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.chunks import list_chunks_by_document
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.source_documents import insert_source_document
from skillforge.domain.entities import Project, SourceDocument
from skillforge.ingestion.chunking import chunk_document
from skillforge.ingestion.text import ParsedDocument, ParsedSegment, parse_markdown

_MARKDOWN = """\
intro

# Service Down

stop the backend

```
# not a heading
```

## Check

look at logs
"""


def test_markdown_line_numbers_slice_back_to_source(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    document = _seed(db_path)
    parsed = parse_markdown(_MARKDOWN)
    chunks = chunk_document(db_path, document, parsed)
    source = _MARKDOWN.splitlines()
    assert [chunk.title for chunk in chunks] == [None, "Service Down", "Check"]
    for chunk in chunks:
        assert chunk.line_start is not None and chunk.line_end is not None
        sliced = "\n".join(source[chunk.line_start - 1 : chunk.line_end])
        assert sliced == chunk.text
    assert "# not a heading" in chunks[1].text
    assert chunks[1].title == "Service Down"
    assert [chunk.ordinal for chunk in chunks] == [0, 1, 2]


def test_pdf_pages_and_openapi_titles(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    document = _seed(db_path, document_id="doc_pdf", parser="pdf")
    pdf = ParsedDocument(
        parser="pdf",
        segments=[
            ParsedSegment(text="page one", page=1),
            ParsedSegment(text="page two", page=2),
        ],
    )
    pages = chunk_document(db_path, document, pdf)
    assert [(chunk.page, chunk.line_start, chunk.text) for chunk in pages] == [
        (1, None, "page one"),
        (2, None, "page two"),
    ]

    operations = ParsedDocument(
        parser="openapi",
        segments=[
            ParsedSegment(text="GET /health\noperationId: getHealth"),
            ParsedSegment(text="POST /restart\noperationId: restart"),
        ],
    )
    api_doc = _seed(db_path, document_id="doc_api", parser="openapi", filename="openapi.yaml")
    ops = chunk_document(db_path, api_doc, operations)
    assert [chunk.title for chunk in ops] == ["GET /health", "POST /restart"]
    assert all(chunk.line_start is None and chunk.page is None for chunk in ops)


def test_rechunk_replaces_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    document = _seed(db_path)
    parsed = parse_markdown(_MARKDOWN)
    first = chunk_document(db_path, document, parsed)
    second = chunk_document(db_path, document, parsed)
    with connection(db_path) as conn:
        stored = list_chunks_by_document(conn, document.id)
    assert len(first) == len(second) == len(stored) == 3
    assert [chunk.ordinal for chunk in stored] == [0, 1, 2]


def _seed(
    db_path: Path,
    *,
    document_id: str = "doc_1",
    parser: str = "markdown",
    filename: str = "runbook.md",
) -> SourceDocument:
    initialize_database(db_path)
    now = datetime.now(UTC)
    document = SourceDocument(
        id=document_id,
        project_id="proj_1",
        filename=filename,
        sha256="abc",
        version="1",
        parser=parser,
        created_at=now,
    )
    with connection(db_path) as conn:
        if conn.execute("SELECT 1 FROM projects WHERE id = ?", ("proj_1",)).fetchone() is None:
            insert_project(conn, Project(id="proj_1", name="lab", created_at=now))
        insert_source_document(conn, document)
    return document
