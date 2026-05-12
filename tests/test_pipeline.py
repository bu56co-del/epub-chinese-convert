import subprocess
import zipfile
from pathlib import Path

import pytest

from epubconv.engines.opencc_engine import OpenCCEngine
from epubconv.formats import calibre
from epubconv.pipeline import convert_ebook, convert_epub


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


def test_convert_ebook_epub_to_epub_skips_calibre(
    sample_epub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both ends are EPUB we never touch ebook-convert."""
    monkeypatch.setattr(
        calibre, "ebook_convert",
        lambda *a, **kw: pytest.fail("ebook_convert should not be called for EPUB→EPUB"),
    )
    out = tmp_path / "out.epub"
    convert_ebook(sample_epub, out, OpenCCEngine("zh-CN", "zh-TW"), "zh-TW", output_format="epub")
    assert out.exists()


def test_convert_ebook_epub_to_mobi_runs_calibre_once(
    sample_epub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EPUB → MOBI converts content, then wraps via Calibre once at the end."""
    calls: list[tuple[Path, Path]] = []

    def fake_run(cmd, check, capture_output):
        Path(cmd[2]).write_bytes(b"FAKE-MOBI")
        calls.append((Path(cmd[1]), Path(cmd[2])))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(calibre.shutil, "which", lambda n: "/usr/bin/ebook-convert")
    monkeypatch.setattr(calibre.subprocess, "run", fake_run)

    out = tmp_path / "book.zh-TW.mobi"
    convert_ebook(
        sample_epub, out, OpenCCEngine("zh-CN", "zh-TW"), "zh-TW", output_format="mobi",
    )
    assert out.exists()
    # Exactly one Calibre invocation: the final EPUB → MOBI wrap.
    assert len(calls) == 1
    assert calls[0][1].suffix == ".mobi"


def test_convert_ebook_mobi_input_runs_calibre_twice(
    sample_epub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MOBI → AZW3 needs Calibre on the way in and on the way out."""
    # Pretend the user uploaded a .mobi by renaming the EPUB fixture.
    fake_mobi = tmp_path / "input.mobi"
    fake_mobi.write_bytes(sample_epub.read_bytes())

    calls: list[tuple[Path, Path]] = []

    def fake_run(cmd, check, capture_output):
        out_path = Path(cmd[2])
        if out_path.suffix == ".epub":
            # Calibre is asked to produce an EPUB from MOBI; hand it our
            # real fixture EPUB so the next stage has valid content.
            out_path.write_bytes(sample_epub.read_bytes())
        else:
            out_path.write_bytes(b"FAKE-AZW3")
        calls.append((Path(cmd[1]).suffix, out_path.suffix))
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(calibre.shutil, "which", lambda n: "/usr/bin/ebook-convert")
    monkeypatch.setattr(calibre.subprocess, "run", fake_run)

    out = tmp_path / "out.azw3"
    convert_ebook(
        fake_mobi, out, OpenCCEngine("zh-CN", "zh-TW"), "zh-TW", output_format="azw3",
    )
    assert out.read_bytes() == b"FAKE-AZW3"
    # First MOBI→EPUB, then EPUB→AZW3.
    assert calls == [(".mobi", ".epub"), (".epub", ".azw3")]


def test_convert_ebook_rejects_unknown_extension(
    sample_epub: Path, tmp_path: Path,
) -> None:
    junk = tmp_path / "file.pdf"
    junk.write_bytes(b"")
    with pytest.raises(ValueError, match="unsupported"):
        convert_ebook(
            junk, tmp_path / "out.epub", OpenCCEngine("zh-CN", "zh-TW"), "zh-TW",
        )
