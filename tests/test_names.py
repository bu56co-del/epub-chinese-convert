from __future__ import annotations

import zipfile
from pathlib import Path

from epubconv.names import extract_candidates


CHAPTER_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>"""


def _build_epub(tmp_path: Path, body: str) -> Path:
    epub = tmp_path / "n.epub"
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="b">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="b">x</dc:identifier><dc:title>t</dc:title><dc:language>zh-CN</dc:language>
  </metadata>
  <manifest><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest>
  <spine><itemref idref="c"/></spine>
</package>"""
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/c.xhtml", CHAPTER_TEMPLATE.format(body=body))
    return epub


def test_quoted_tokens_score_high(tmp_path: Path) -> None:
    body = (
        "<p>「哈利」走進了房間。</p>"
        "<p>「哈利」笑了。</p>"
        "<p>「哈利」說：你好。</p>"
        "<p>普通普通普通普通的句子。</p>"
    )
    epub = _build_epub(tmp_path, body)
    cands = extract_candidates(epub, min_occurrences=3)
    tokens = [t for t, _ in cands]
    assert "哈利" in tokens
    # 哈利 should rank higher than any 2-gram fragment of the noise.
    assert tokens[0] == "哈利"


def test_min_occurrences_filters(tmp_path: Path) -> None:
    body = "<p>李四只出現一次。</p><p>王五也只出現一次。</p>"
    epub = _build_epub(tmp_path, body)
    cands = extract_candidates(epub, min_occurrences=2)
    assert all(count >= 2 for _, count in cands)


def test_returns_sorted_by_count_desc(tmp_path: Path) -> None:
    body = "<p>" + ("阿明說 " * 10) + ("小華說 " * 5) + "</p>"
    epub = _build_epub(tmp_path, body)
    cands = extract_candidates(epub, min_occurrences=3)
    counts = [c for _, c in cands]
    assert counts == sorted(counts, reverse=True)


def test_skips_code_pre_tags(tmp_path: Path) -> None:
    body = "<p>正常段落。</p>" + "<pre>不应入选不应入选不应入选</pre>" * 3
    epub = _build_epub(tmp_path, body)
    cands = extract_candidates(epub, min_occurrences=3)
    tokens = [t for t, _ in cands]
    assert "不应" not in tokens
    assert "应入选" not in tokens
