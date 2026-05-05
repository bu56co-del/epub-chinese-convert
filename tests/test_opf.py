from pathlib import Path

from lxml import etree

from epubconv.converters.opf import update_opf
from epubconv.engines.opencc_engine import OpenCCEngine

DC_NS = {"dc": "http://purl.org/dc/elements/1.1/"}


OPF_SRC = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:x</dc:identifier>
    <dc:title>简体测试</dc:title>
    <dc:creator>张三</dc:creator>
    <dc:language>zh-CN</dc:language>
  </metadata>
  <manifest/>
  <spine/>
</package>
"""


def test_update_opf_rewrites_language_and_title(tmp_path: Path):
    opf = tmp_path / "content.opf"
    opf.write_text(OPF_SRC, encoding="utf-8")

    engine = OpenCCEngine("zh-CN", "zh-TW", config="s2t")
    update_opf(opf, engine, "zh-TW")

    tree = etree.parse(str(opf))
    lang = tree.find(".//dc:language", DC_NS)
    title = tree.find(".//dc:title", DC_NS)
    creator = tree.find(".//dc:creator", DC_NS)

    assert lang.text == "zh-TW"
    assert title.text == "簡體測試"
    assert creator.text == "張三"
