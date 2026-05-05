import zipfile
from pathlib import Path

from epubconv.engines.opencc_engine import OpenCCEngine
from epubconv.pipeline import convert_epub


def test_full_pipeline_produces_valid_epub(sample_epub: Path, tmp_path: Path):
    out = tmp_path / "out.epub"
    engine = OpenCCEngine("zh-CN", "zh-TW", config="s2t")

    convert_epub(sample_epub, out, engine, "zh-TW")

    assert out.exists() and out.stat().st_size > 0

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        # mimetype must be the first entry per EPUB spec.
        assert names[0] == "mimetype"
        info = zf.getinfo("mimetype")
        assert info.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"

        chapter = zf.read("OEBPS/chapter1.xhtml").decode("utf-8")
        assert "簡體" in chapter
        assert "<code>print(\"不应该转换：简体\")</code>" in chapter

        opf = zf.read("OEBPS/content.opf").decode("utf-8")
        assert "<dc:language>zh-TW</dc:language>" in opf
        assert "簡體中文測試書" in opf
