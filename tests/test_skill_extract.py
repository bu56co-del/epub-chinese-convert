from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from epubconv.epub import extract_epub
from epubconv.skill.extract import (
    TocEntry,
    clean_text,
    is_content_file,
    read_toc,
)


CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def _build_book(tmp_path: Path, *, with_nav: bool = True, with_ncx: bool = False) -> Path:
    """Build a multi-chapter EPUB whose chapters each exceed the 200-char filter."""
    long_para = "故事就此展開，主角踏上了未知的旅途。" * 20
    chapter_template = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\">"
        "<head><title>{title}</title></head>"
        "<body><h1>{title}</h1><p>{body}</p></body></html>"
    )
    cover_xhtml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\">"
        "<head><title>封面</title></head><body epub:type=\"cover\"><h1>封面</h1></body></html>"
    )
    nav_xhtml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\">"
        "<head><title>目錄</title></head><body><nav epub:type=\"toc\"><ol>"
        "<li><a href=\"chapter1.xhtml\">第一章 開始</a></li>"
        "<li><a href=\"chapter2.xhtml\">第二章 旅途</a><ol>"
        "<li><a href=\"chapter2.xhtml#sub\">第二節 同伴</a></li>"
        "</ol></li>"
        "</ol></nav></body></html>"
    )

    spine = "<itemref idref=\"cover\"/><itemref idref=\"ch1\"/><itemref idref=\"ch2\"/>"
    manifest = (
        "<item id=\"cover\" href=\"cover.xhtml\" media-type=\"application/xhtml+xml\"/>"
        "<item id=\"ch1\" href=\"chapter1.xhtml\" media-type=\"application/xhtml+xml\"/>"
        "<item id=\"ch2\" href=\"chapter2.xhtml\" media-type=\"application/xhtml+xml\"/>"
    )
    if with_nav:
        manifest += (
            "<item id=\"nav\" href=\"nav.xhtml\" media-type=\"application/xhtml+xml\""
            " properties=\"nav\"/>"
        )
    if with_ncx:
        manifest += "<item id=\"ncx\" href=\"toc.ncx\" media-type=\"application/x-dtbncx+xml\"/>"

    opf = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<package xmlns=\"http://www.idpf.org/2007/opf\" version=\"3.0\" unique-identifier=\"b\">"
        "<metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\">"
        "<dc:identifier id=\"b\">urn:uuid:test</dc:identifier>"
        "<dc:title>測試書</dc:title>"
        "<dc:creator>作者</dc:creator>"
        "<dc:language>zh-TW</dc:language>"
        "<dc:description>這是一本測試書</dc:description>"
        "</metadata>"
        f"<manifest>{manifest}</manifest>"
        f"<spine>{spine}</spine>"
        "</package>"
    )

    ncx_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<ncx xmlns=\"http://www.daisy.org/z3986/2005/ncx/\" version=\"2005-1\">"
        "<head/><docTitle><text>測試書</text></docTitle><navMap>"
        "<navPoint id=\"n1\" playOrder=\"1\"><navLabel><text>第一章 開始</text></navLabel>"
        "<content src=\"chapter1.xhtml\"/></navPoint>"
        "<navPoint id=\"n2\" playOrder=\"2\"><navLabel><text>第二章 旅途</text></navLabel>"
        "<content src=\"chapter2.xhtml\"/></navPoint>"
        "</navMap></ncx>"
    )

    epub = tmp_path / "book.epub"
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/cover.xhtml", cover_xhtml)
        zf.writestr("OEBPS/chapter1.xhtml", chapter_template.format(title="第一章 開始", body=long_para))
        zf.writestr(
            "OEBPS/chapter2.xhtml",
            chapter_template.format(title="第二章 旅途", body=long_para + "<span id=\"sub\">同伴章節</span>"),
        )
        if with_nav:
            zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        if with_ncx:
            zf.writestr("OEBPS/toc.ncx", ncx_xml)
    return epub


# ---- clean_text ----


def test_clean_text_strips_script_style_code_pre() -> None:
    xml = (
        "<html><body><p>正文</p>"
        "<script>alert(1)</script>"
        "<style>p{color:red}</style>"
        "<pre><code>print('x')</code></pre>"
        "</body></html>"
    )
    assert clean_text(xml) == "正文"


def test_clean_text_strips_ruby_pronunciation() -> None:
    xml = "<html><body><p>漢<ruby><rb>字</rb><rt>jì</rt></ruby></p></body></html>"
    out = clean_text(xml)
    assert "字" in out
    assert "jì" not in out


def test_clean_text_drops_footnote_aside_by_default() -> None:
    xml = (
        "<html xmlns:epub=\"http://www.idpf.org/2007/ops\">"
        "<body><p>正文</p>"
        "<aside epub:type=\"footnote\">這是註腳</aside>"
        "</body></html>"
    )
    assert "註腳" not in clean_text(xml)


def test_clean_text_keeps_footnote_when_requested() -> None:
    xml = (
        "<html xmlns:epub=\"http://www.idpf.org/2007/ops\">"
        "<body><p>正文</p>"
        "<aside epub:type=\"footnote\">這是註腳</aside>"
        "</body></html>"
    )
    out = clean_text(xml, keep_footnotes=True)
    assert "註腳" in out


def test_clean_text_collapses_whitespace() -> None:
    xml = "<p>a\n\n\n  b\t\tc</p>"
    assert clean_text(xml) == "a b c"


# ---- is_content_file ----


def test_is_content_file_drops_cover_by_epub_type(tmp_path: Path) -> None:
    cover = tmp_path / "cover.xhtml"
    cover.write_text(
        "<?xml version=\"1.0\"?><html xmlns=\"http://www.w3.org/1999/xhtml\""
        " xmlns:epub=\"http://www.idpf.org/2007/ops\">"
        "<body epub:type=\"cover\">封面文字封面文字封面文字封面文字封面文字封面文字"
        "封面文字封面文字封面文字封面文字封面文字</body></html>"
    )
    assert not is_content_file(cover)


def test_is_content_file_drops_short_files(tmp_path: Path) -> None:
    p = tmp_path / "chapter1.xhtml"
    p.write_text("<html><body><p>太短</p></body></html>")
    assert not is_content_file(p)


def test_is_content_file_accepts_long_chapter(tmp_path: Path) -> None:
    p = tmp_path / "chapter1.xhtml"
    p.write_text("<html><body><p>" + ("正文" * 200) + "</p></body></html>")
    assert is_content_file(p)


def test_is_content_file_drops_by_filename(tmp_path: Path) -> None:
    p = tmp_path / "colophon.xhtml"
    p.write_text("<html><body><p>" + ("版權頁" * 200) + "</p></body></html>")
    assert not is_content_file(p)


# ---- read_toc ----


def test_read_toc_prefers_nav_xhtml(tmp_path: Path) -> None:
    epub = _build_book(tmp_path, with_nav=True, with_ncx=True)
    pkg = extract_epub(epub, tmp_path / "ext")
    entries = read_toc(pkg)
    titles = [e.title for e in entries]
    assert "第一章 開始" in titles
    assert "第二章 旅途" in titles
    assert any(e.heading_path == ["第二章 旅途", "第二節 同伴"] for e in entries)


def test_read_toc_falls_back_to_ncx_when_no_nav(tmp_path: Path) -> None:
    epub = _build_book(tmp_path, with_nav=False, with_ncx=True)
    pkg = extract_epub(epub, tmp_path / "ext")
    entries = read_toc(pkg)
    assert [e.title for e in entries] == ["第一章 開始", "第二章 旅途"]


def test_read_toc_falls_back_to_spine_when_no_toc(tmp_path: Path) -> None:
    epub = _build_book(tmp_path, with_nav=False, with_ncx=False)
    pkg = extract_epub(epub, tmp_path / "ext")
    entries = read_toc(pkg)
    # Cover has epub:type=cover and is excluded; chapters 1 and 2 remain.
    titles = [e.title for e in entries]
    assert "第一章 開始" in titles
    assert "第二章 旅途" in titles


def test_toc_entry_resolves_to_real_files(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    pkg = extract_epub(epub, tmp_path / "ext")
    for e in read_toc(pkg):
        assert e.src.exists(), f"missing TOC target: {e.src}"
