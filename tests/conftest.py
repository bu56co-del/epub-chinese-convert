from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

# Make src/ importable without an editable install.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

CONTENT_OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:test-1</dc:identifier>
    <dc:title>简体中文测试书</dc:title>
    <dc:creator>张三</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:description>这是一本用于测试的简体中文电子书。</dc:description>
  </metadata>
  <manifest>
    <item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>
"""

CHAPTER_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>第一章</title></head>
<body>
  <h1>第一章 简体测试</h1>
  <p>这是一段简体中文，软件和信息应该被转换成繁体用语。</p>
  <p>她说：&quot;你好世界&quot;。</p>
  <pre><code>print("不应该转换：简体")</code></pre>
  <p><img src="cover.jpg" alt="封面图片" title="书的封面"/></p>
</body>
</html>
"""

NAV_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>目录</title></head>
<body>
  <nav epub:type="toc"><ol><li><a href="chapter1.xhtml">第一章</a></li></ol></nav>
</body>
</html>
"""


@pytest.fixture
def sample_epub(tmp_path: Path) -> Path:
    """Build a minimal valid EPUB on disk and return its path."""
    epub_path = tmp_path / "sample.epub"
    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", CONTENT_OPF)
        zf.writestr("OEBPS/chapter1.xhtml", CHAPTER_XHTML)
        zf.writestr("OEBPS/nav.xhtml", NAV_XHTML)
    return epub_path
