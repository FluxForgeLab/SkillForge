"""C5.2: pdf pages, yaml/json documents, and OpenAPI operations."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from skillforge.db.connection import connection
from skillforge.db.init import initialize_database
from skillforge.db.repositories.projects import insert_project
from skillforge.db.repositories.source_documents import list_source_documents
from skillforge.domain.entities import Project
from skillforge.ingestion import IngestError, parse_stored, store_upload

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ingestion"


def test_pdf_page_text(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    project_id = _seed(db_path)
    document = store_upload(db_path, project_id, "manual.pdf", _hello_pdf(), root=root)
    parsed = parse_stored(document, root)
    assert document.parser == "pdf"
    assert len(parsed.segments) == 1
    assert parsed.segments[0].page == 1
    assert "Hello" in parsed.segments[0].text
    assert parsed.lines == []


def test_yaml_and_json_are_one_segment(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    project_id = _seed(db_path)
    yaml_bytes = (_FIXTURES / "sample.yaml").read_bytes()
    json_bytes = (_FIXTURES / "sample.json").read_bytes()
    yaml_doc = store_upload(db_path, project_id, "sample.yaml", yaml_bytes, root=root)
    json_doc = store_upload(db_path, project_id, "sample.json", json_bytes, root=root)
    yaml_parsed = parse_stored(yaml_doc, root)
    json_parsed = parse_stored(json_doc, root)
    assert yaml_doc.parser == "yaml"
    assert json_doc.parser == "json"
    assert yaml_parsed.segments[0].text == yaml_bytes.decode("utf-8")
    assert yaml_parsed.segments[0].line_start == 1
    assert yaml_parsed.segments[0].line_end == len(yaml_bytes.decode("utf-8").splitlines())
    assert json_parsed.segments[0].text == json_bytes.decode("utf-8")
    assert len(yaml_parsed.segments) == 1
    assert len(json_parsed.segments) == 1


def test_openapi_operations_keep_path_order(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    project_id = _seed(db_path)
    data = (_FIXTURES / "openapi.yaml").read_bytes()
    document = store_upload(db_path, project_id, "openapi.yaml", data, root=root)
    parsed = parse_stored(document, root)
    assert document.parser == "openapi"
    assert [segment.text for segment in parsed.segments] == [
        "GET /health\noperationId: getHealth\nsummary: Liveness",
        "POST /restart\noperationId: restart",
    ]


def test_invalid_yaml_and_pdf_are_not_stored(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"
    root = tmp_path / "sources"
    project_id = _seed(db_path)
    with pytest.raises(IngestError):
        store_upload(db_path, project_id, "broken.yaml", b": [", root=root)
    with pytest.raises(IngestError):
        store_upload(db_path, project_id, "broken.pdf", b"%PDF", root=root)
    with connection(db_path) as conn:
        assert list_source_documents(conn, project_id) == []


def _hello_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = font
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 24 Tf 100 700 Td (Hello) Tj ET")
    page[NameObject("/Contents")] = content
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _seed(db_path: Path) -> str:
    initialize_database(db_path)
    project_id = "proj_1"
    with connection(db_path) as conn:
        insert_project(
            conn,
            Project(id=project_id, name="lab", created_at=datetime.now(UTC)),
        )
    return project_id
