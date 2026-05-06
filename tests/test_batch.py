from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from epubconv.batch import (
    MANIFEST_NAME,
    BatchResult,
    Manifest,
    find_epubs,
    run_batch,
)


def _make_epub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-epub")


def test_find_epubs_recursive(tmp_path: Path) -> None:
    _make_epub(tmp_path / "a.epub")
    _make_epub(tmp_path / "sub" / "b.epub")
    (tmp_path / "not-an-epub.txt").write_text("x")
    assert find_epubs(tmp_path) == [tmp_path / "a.epub", tmp_path / "sub" / "b.epub"]


def test_run_batch_calls_convert_for_each(tmp_path: Path) -> None:
    inp, out = tmp_path / "in", tmp_path / "out"
    _make_epub(inp / "x.epub")
    _make_epub(inp / "y.epub")

    seen: list[tuple[Path, Path]] = []

    def fake(src: Path, dst: Path) -> Path:
        seen.append((src, dst))
        dst.write_bytes(b"converted")
        return dst

    result = run_batch(inp, out, fake)
    assert len(seen) == 2
    assert sorted(s.name for s, _ in seen) == ["x.epub", "y.epub"]
    assert result.done and not result.errored and not result.skipped


def test_run_batch_records_errors_and_continues(tmp_path: Path) -> None:
    inp, out = tmp_path / "in", tmp_path / "out"
    _make_epub(inp / "ok.epub")
    _make_epub(inp / "bad.epub")

    def fake(src: Path, dst: Path) -> Path:
        if src.name == "bad.epub":
            raise RuntimeError("boom")
        dst.write_bytes(b"")
        return dst

    result = run_batch(inp, out, fake)
    assert [s.name for s in result.done] == ["ok.epub"]
    assert [s.name for s, _ in result.errored] == ["bad.epub"]


def test_resume_skips_done_files(tmp_path: Path) -> None:
    inp, out = tmp_path / "in", tmp_path / "out"
    _make_epub(inp / "a.epub")

    calls = {"n": 0}

    def fake(src: Path, dst: Path) -> Path:
        calls["n"] += 1
        dst.write_bytes(b"")
        return dst

    run_batch(inp, out, fake)
    assert calls["n"] == 1

    # Second run resumes -> should skip.
    result = run_batch(inp, out, fake)
    assert calls["n"] == 1
    assert [s.name for s in result.skipped] == ["a.epub"]


def test_no_resume_reconverts(tmp_path: Path) -> None:
    inp, out = tmp_path / "in", tmp_path / "out"
    _make_epub(inp / "a.epub")

    calls = {"n": 0}

    def fake(src: Path, dst: Path) -> Path:
        calls["n"] += 1
        dst.write_bytes(b"")
        return dst

    run_batch(inp, out, fake)
    run_batch(inp, out, fake, resume=False)
    assert calls["n"] == 2


def test_resume_retries_errored(tmp_path: Path) -> None:
    inp, out = tmp_path / "in", tmp_path / "out"
    _make_epub(inp / "flaky.epub")

    state = {"first": True}

    def fake(src: Path, dst: Path) -> Path:
        if state["first"]:
            state["first"] = False
            raise RuntimeError("transient")
        dst.write_bytes(b"")
        return dst

    r1 = run_batch(inp, out, fake)
    assert r1.errored and not r1.done
    r2 = run_batch(inp, out, fake)  # resume retries error rows
    assert r2.done and not r2.errored


def test_manifest_persisted_and_human_readable(tmp_path: Path) -> None:
    inp, out = tmp_path / "in", tmp_path / "out"
    _make_epub(inp / "中文書.epub")  # non-ASCII filename round-trips
    run_batch(inp, out, lambda s, d: (d.write_bytes(b""), d)[1])

    manifest = out / MANIFEST_NAME
    assert manifest.exists()
    text = manifest.read_text(encoding="utf-8")
    assert "中文書.epub" in text  # ensure_ascii=False
    data = json.loads(text)
    assert data["files"]["中文書.epub"]["status"] == "done"


def test_run_batch_rejects_non_directory(tmp_path: Path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("")
    with pytest.raises(NotADirectoryError):
        run_batch(f, tmp_path / "o", lambda s, d: d)
