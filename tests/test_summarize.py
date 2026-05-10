from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from epubconv import summarize


def _build_book(tmp_path: Path) -> Path:
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="b">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="b">urn:test</dc:identifier>'
        '<dc:title>測試</dc:title><dc:language>zh-TW</dc:language></metadata>'
        '<manifest>'
        '<item id="ch1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="ch2" href="c2.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '</manifest>'
        '<spine><itemref idref="ch1"/><itemref idref="ch2"/></spine></package>'
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<head><title>目錄</title></head><body><nav epub:type="toc"><ol>'
        '<li><a href="c1.xhtml">第一章</a></li>'
        '<li><a href="c2.xhtml">第二章</a></li></ol></nav></body></html>'
    )
    body1 = "第一章內容。" * 60
    body2 = "第二章內容。" * 60
    epub = tmp_path / "b.epub"
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)
        zf.writestr("OEBPS/c1.xhtml", f"<html><body><p>{body1}</p></body></html>")
        zf.writestr("OEBPS/c2.xhtml", f"<html><body><p>{body2}</p></body></html>")
    return epub


def test_book_text_returns_chapters_in_order(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    text, chapters = summarize.book_text(epub, max_chars=100_000)
    assert chapters == 2
    # Order matters: chapter 1 appears before chapter 2.
    assert text.index("第一章") < text.index("第二章")


def test_book_text_truncates_to_max_chars(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    text, _ = summarize.book_text(epub, max_chars=200)
    assert len(text) <= 200


def test_summarise_epub_calls_llm_with_truncated_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epub = _build_book(tmp_path)
    seen: dict = {}

    class FakeClient:
        def complete(self, system: str, user: str, **kw) -> str:
            seen["system"] = system
            seen["user"] = user
            return "## 一句話總結\n測。"

    result = summarize.summarise_epub(epub, max_chars=500, client=FakeClient())
    assert result.text.startswith("## 一句話總結")
    assert result.chapters_used >= 1
    assert result.chars_used <= 500
    assert "請按以下結構撮要" in seen["user"]
    assert "繁體中文" in seen["system"]


def test_summarise_epub_raises_on_empty_book(tmp_path: Path) -> None:
    # Build an epub with no chunkable content (only a nav file).
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/c.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="b">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="b">urn:e</dc:identifier><dc:title>e</dc:title>'
        '<dc:language>zh-CN</dc:language></metadata>'
        '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>'
        '<spine/></package>'
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<body><nav epub:type="toc"><ol/></nav></body></html>'
    )
    epub = tmp_path / "empty.epub"
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/c.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)

    with pytest.raises(ValueError, match="no readable text"):
        summarize.summarise_epub(epub, client=object())  # client never called
