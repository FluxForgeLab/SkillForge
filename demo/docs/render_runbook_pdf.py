"""Render the service recovery runbook markdown into a two-page PDF."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

_APPENDIX = "## Appendix B:"
_WIDTH = 80
_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_FONT_SIZE = 11
_LEADING = 14
_MARGIN_X = 72
_START_Y = 750


def render_runbook_pdf(markdown: str) -> bytes:
    """Put the main chapters on page 1 and Appendix B on page 2."""
    pages = _split_pages(markdown)
    writer = PdfWriter()
    for page_text in pages:
        _add_page(writer, page_text)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _split_pages(markdown: str) -> list[str]:
    marker = f"\n{_APPENDIX}"
    if marker not in markdown:
        raise ValueError("runbook is missing Appendix B")
    head, tail = markdown.split(marker, 1)
    return [head.rstrip() + "\n", f"{_APPENDIX}{tail}"]


def _add_page(writer: PdfWriter, text: str) -> None:
    page = writer.add_blank_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = font
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources
    lines = _wrap_page(text)
    content = DecodedStreamObject()
    content.set_data(_content_stream(lines))
    page[NameObject("/Contents")] = content


def _wrap_page(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        lines.extend(_wrap_line(raw))
    return lines


def _wrap_line(text: str) -> list[str]:
    if text == "":
        return [""]
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if current == "" else f"{current} {word}"
        if len(candidate) <= _WIDTH:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current or not lines:
        lines.append(current)
    return lines


def _content_stream(lines: list[str]) -> bytes:
    parts = [
        b"BT\n",
        f"/F1 {_FONT_SIZE} Tf\n".encode("ascii"),
        f"{_LEADING} TL\n".encode("ascii"),
        f"{_MARGIN_X} {_START_Y} Td\n".encode("ascii"),
    ]
    for line in lines:
        parts.append(_pdf_literal(line))
        parts.append(b" Tj T*\n")
    parts.append(b"ET\n")
    return b"".join(parts)


def _pdf_literal(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return b"(" + escaped.encode("ascii") + b")"


def main() -> None:
    root = Path(__file__).resolve().parent
    markdown = (root / "service-recovery-runbook.md").read_text(encoding="utf-8")
    (root / "service-recovery-runbook.pdf").write_bytes(render_runbook_pdf(markdown))


if __name__ == "__main__":
    main()
