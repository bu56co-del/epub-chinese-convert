from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from epubconv.formats import calibre


def test_have_calibre_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calibre.shutil, "which", lambda name: None)
    assert calibre.have_calibre() is False


def test_have_calibre_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calibre.shutil, "which", lambda name: "/usr/bin/ebook-convert")
    assert calibre.have_calibre() is True


def test_ebook_convert_raises_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calibre.shutil, "which", lambda name: None)
    with pytest.raises(calibre.CalibreNotFoundError):
        calibre.ebook_convert(tmp_path / "in.epub", tmp_path / "out.mobi")


def test_ebook_convert_invokes_calibre(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "in.epub"
    src.write_bytes(b"")
    dst = tmp_path / "subdir" / "out.azw3"

    calls: list[list[str]] = []

    def fake_run(cmd, check, capture_output):
        calls.append(list(cmd))
        Path(cmd[2]).write_bytes(b"FAKE-OUTPUT")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(calibre.shutil, "which", lambda name: "/usr/bin/ebook-convert")
    monkeypatch.setattr(calibre.subprocess, "run", fake_run)

    out = calibre.ebook_convert(src, dst)
    assert out == dst
    assert dst.read_bytes() == b"FAKE-OUTPUT"
    assert calls == [["ebook-convert", str(src), str(dst)]]
    assert dst.parent.exists()


def test_epub_to_mobi_compat_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Old callers still importing epub_to_mobi keep working."""
    monkeypatch.setattr(calibre.shutil, "which", lambda name: "/usr/bin/ebook-convert")
    monkeypatch.setattr(
        calibre.subprocess, "run",
        lambda cmd, check, capture_output: subprocess.CompletedProcess(cmd, 0, b"", b""),
    )
    src = tmp_path / "in.epub"
    src.write_bytes(b"")
    out = calibre.epub_to_mobi(src, tmp_path / "out.mobi")
    assert out == tmp_path / "out.mobi"


def test_detect_format_from_extension(tmp_path: Path) -> None:
    assert calibre.detect_format(tmp_path / "x.epub") == "epub"
    assert calibre.detect_format(tmp_path / "x.mobi") == "mobi"
    assert calibre.detect_format(tmp_path / "x.azw3") == "azw3"
    assert calibre.detect_format(tmp_path / "x.azw") == "azw3"  # alias
    assert calibre.detect_format(tmp_path / "X.EPUB") == "epub"  # case insensitive


def test_detect_format_rejects_unknown(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        calibre.detect_format(tmp_path / "x.pdf")


def test_output_path_for_keeps_stem_adds_suffix(tmp_path: Path) -> None:
    src = tmp_path / "book.epub"
    assert calibre.output_path_for(src, "mobi") == tmp_path / "book.mobi"
    assert calibre.output_path_for(src, "azw3", ".zh-TW") == tmp_path / "book.zh-TW.azw3"
    # 'azw' alias maps to .azw3 extension.
    assert calibre.output_path_for(src, "azw") == tmp_path / "book.azw3"


def test_supported_format_constants() -> None:
    assert set(calibre.OUTPUT_FORMATS) == {"epub", "mobi", "azw3"}
    assert "azw" in calibre.INPUT_FORMATS  # accept Kindle's older extension on input
