"""C5.8: service recovery runbook keeps Appendix B on its own page."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from skillforge.ingestion.structured import parse_pdf

_ROOT = Path(__file__).resolve().parents[3]
_DOCS = _ROOT / "demo" / "docs"
_MARKDOWN = _DOCS / "service-recovery-runbook.md"
_PDF = _DOCS / "service-recovery-runbook.pdf"
_APPENDIX = "## Appendix B: Reverse Proxy Troubleshooting"
_MAIN_HEADINGS = ("## Service Down", "## 502 from proxy")
_APPENDIX_PHRASES = (
    "nginx reload failed / upstream mismatch",
    "502",
    "upstream",
    "nginx -t",
    "server backend:8080;",
    "server backend:8081;",
    "this_is_not_valid_nginx;",
)


def test_markdown_splits_appendix_b() -> None:
    text = _MARKDOWN.read_text(encoding="utf-8")
    head, appendix = text.split(_APPENDIX, maxsplit=1)
    for heading in _MAIN_HEADINGS:
        assert heading in head
    assert "nginx -t" not in head
    assert "this_is_not_valid_nginx" not in head
    for phrase in _APPENDIX_PHRASES:
        assert phrase in appendix


def test_pdf_keeps_appendix_on_the_last_page() -> None:
    parsed = parse_pdf(_PDF.read_bytes())
    assert len(parsed.segments) == 2
    earlier = "\n".join(segment.text for segment in parsed.segments[:-1])
    last = parsed.segments[-1].text
    assert "nginx -t" not in earlier
    assert "Appendix B" in last
    assert "nginx -t" in last


def test_committed_pdf_matches_renderer(tmp_path: Path) -> None:
    renderer = _load_renderer()
    markdown = _MARKDOWN.read_text(encoding="utf-8")
    rendered = tmp_path / "service-recovery-runbook.pdf"
    rendered.write_bytes(renderer.render_runbook_pdf(markdown))
    committed = [segment.text for segment in parse_pdf(_PDF.read_bytes()).segments]
    fresh = [segment.text for segment in parse_pdf(rendered.read_bytes()).segments]
    assert fresh == committed


def _load_renderer():
    path = _DOCS / "render_runbook_pdf.py"
    spec = importlib.util.spec_from_file_location("render_runbook_pdf", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
