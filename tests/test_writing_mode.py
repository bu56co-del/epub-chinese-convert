from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from lxml import etree

from epubconv.converters.writing_mode import WRITING_MODES, apply_writing_mode
from epubconv.engines.opencc_engine import OpenCCEngine
from epubconv.epub import extract_epub
from epubconv.pipeline import convert_epub


CSS_BODY = "body { font-family: serif; }\n"


def _build_epub_with_css(tmp_path: Path) -> Path:
    epub = tmp_path / "book.epub"
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="b">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="b">x</dc:identifier><dc:title>t</dc:title><dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>
    <item id="c" href="c.xhtml" media-type="application/xhtml+xml"/>
    <item id="s" href="style.css" media-type="text/css"/>
  </manifest>
  <spine><itemref idref="c"/></spine>
</package>"""
    chapter = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><link rel="stylesheet" href="style.css"/></head>
<body><p>正文</p></body></html>"""
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/c.xhtml", chapter)
        zf.writestr("OEBPS/style.css", CSS_BODY)
    return epub


def _build_epub_without_css(tmp_path: Path) -> Path:
    epub = tmp_path / "book2.epub"
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="b">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="b">x</dc:identifier><dc:title>t</dc:title><dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>
    <item id="c" href="c.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c"/></spine>
</package>"""
    chapter = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head/><body><p>正文</p></body></html>"""
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/c.xhtml", chapter)
    return epub


def test_preserve_is_noop(tmp_path: Path) -> None:
    epub = _build_epub_with_css(tmp_path)
    pkg = extract_epub(epub, tmp_path / "ext")
    css_before = pkg.css_files[0].read_text()
    apply_writing_mode(pkg, "preserve")
    assert pkg.css_files[0].read_text() == css_before


def test_unknown_mode_raises(tmp_path: Path) -> None:
    epub = _build_epub_with_css(tmp_path)
    pkg = extract_epub(epub, tmp_path / "ext")
    with pytest.raises(ValueError):
        apply_writing_mode(pkg, "sideways")


def test_vertical_appends_css_and_sets_rtl(tmp_path: Path) -> None:
    epub = _build_epub_with_css(tmp_path)
    pkg = extract_epub(epub, tmp_path / "ext")
    apply_writing_mode(pkg, "vertical")

    css = pkg.css_files[0].read_text()
    assert "vertical-rl" in css
    assert "writing-mode" in css
    # Original content preserved.
    assert CSS_BODY.strip() in css

    tree = etree.parse(str(pkg.opf_path))
    spine = tree.getroot().find("{http://www.idpf.org/2007/opf}spine")
    assert spine.get("page-progression-direction") == "rtl"


def test_horizontal_sets_ltr(tmp_path: Path) -> None:
    epub = _build_epub_with_css(tmp_path)
    pkg = extract_epub(epub, tmp_path / "ext")
    apply_writing_mode(pkg, "horizontal")

    tree = etree.parse(str(pkg.opf_path))
    spine = tree.getroot().find("{http://www.idpf.org/2007/opf}spine")
    assert spine.get("page-progression-direction") == "ltr"
    assert "horizontal-tb" in pkg.css_files[0].read_text()


def test_no_css_in_package_creates_one(tmp_path: Path) -> None:
    epub = _build_epub_without_css(tmp_path)
    pkg = extract_epub(epub, tmp_path / "ext")
    assert pkg.css_files == []
    apply_writing_mode(pkg, "vertical")

    css_files = list(pkg.root.rglob("epubconv-writing-mode.css"))
    assert len(css_files) == 1
    assert "vertical-rl" in css_files[0].read_text()

    # Manifest got a new CSS item.
    tree = etree.parse(str(pkg.opf_path))
    items = tree.getroot().findall(".//{http://www.idpf.org/2007/opf}item")
    assert any(i.get("media-type") == "text/css" for i in items)

    # XHTML head got a <link>.
    chapter = (pkg.root / "OEBPS" / "c.xhtml").read_text()
    assert "epubconv-writing-mode.css" in chapter


def test_pipeline_applies_writing_mode_end_to_end(tmp_path: Path) -> None:
    epub = _build_epub_with_css(tmp_path)
    out = tmp_path / "out.epub"
    convert_epub(epub, out, OpenCCEngine("zh-CN", "zh-TW"), "zh-TW", writing_mode="vertical")
    with zipfile.ZipFile(out) as zf:
        assert "vertical-rl" in zf.read("OEBPS/style.css").decode()
        assert b'page-progression-direction="rtl"' in zf.read("OEBPS/content.opf")


def test_writing_modes_const_complete() -> None:
    assert set(WRITING_MODES) == {"preserve", "horizontal", "vertical"}
