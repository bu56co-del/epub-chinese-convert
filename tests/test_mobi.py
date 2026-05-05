from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from epubconv.formats import mobi as mobi_mod
from epubconv.formats.mobi import CalibreNotFoundError, epub_to_mobi


def test_have_calibre_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mobi_mod.shutil, "which", lambda name: None)
    assert mobi_mod.have_calibre() is False


def test_have_calibre_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mobi_mod.shutil, "which", lambda name: "/usr/bin/ebook-convert")
    assert mobi_mod.have_calibre() is True


def test_epub_to_mobi_raises_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mobi_mod.shutil, "which", lambda name: None)
    with pytest.raises(CalibreNotFoundError):
        epub_to_mobi(tmp_path / "in.epub", tmp_path / "out.mobi")


def test_epub_to_mobi_invokes_calibre(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epub = tmp_path / "in.epub"
    epub.write_bytes(b"")
    out = tmp_path / "subdir" / "out.mobi"

    calls: list[list[str]] = []

    def fake_run(cmd, check, capture_output):
        calls.append(list(cmd))
        # Simulate Calibre creating the file.
        Path(cmd[2]).write_bytes(b"FAKE-MOBI")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(mobi_mod.shutil, "which", lambda name: "/usr/bin/ebook-convert")
    monkeypatch.setattr(mobi_mod.subprocess, "run", fake_run)

    result = epub_to_mobi(epub, out)
    assert result == out
    assert out.read_bytes() == b"FAKE-MOBI"
    assert calls == [["ebook-convert", str(epub), str(out)]]
    assert out.parent.exists()  # parent created
