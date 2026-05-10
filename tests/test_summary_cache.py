from __future__ import annotations

from pathlib import Path

import pytest

from epubconv.summary_cache import SummaryCache, hash_text


def test_set_then_get_roundtrips(tmp_path: Path) -> None:
    c = SummaryCache(book_id="abc", root=tmp_path)
    c.set("batch", hash_text("hello"), "result-payload")
    assert c.get("batch", hash_text("hello")) == "result-payload"


def test_get_missing_returns_none(tmp_path: Path) -> None:
    c = SummaryCache(book_id="abc", root=tmp_path)
    assert c.get("batch", hash_text("nope")) is None


def test_keys_segregated_by_kind(tmp_path: Path) -> None:
    c = SummaryCache(book_id="x", root=tmp_path)
    c.set("batch", hash_text("a"), "A")
    c.set("combine", hash_text("a"), "B")
    assert c.get("batch", hash_text("a")) == "A"
    assert c.get("combine", hash_text("a")) == "B"


def test_set_is_atomic_temp_file_cleaned(tmp_path: Path) -> None:
    c = SummaryCache(book_id="x", root=tmp_path)
    c.set("batch", hash_text("k"), "v")
    files = list((tmp_path / "x").iterdir())
    # No leftover .tmp files.
    assert all(not f.name.endswith(".tmp") for f in files), files


def test_keys_listing(tmp_path: Path) -> None:
    c = SummaryCache(book_id="x", root=tmp_path)
    c.set("batch", "a" * 16, "1")
    c.set("batch", "b" * 16, "2")
    c.set("combine", "c" * 16, "3")
    assert c.keys("batch") == ["a" * 16, "b" * 16]
    assert c.keys("combine") == ["c" * 16]


def test_clear_removes_book_directory(tmp_path: Path) -> None:
    c = SummaryCache(book_id="x", root=tmp_path)
    c.set("batch", hash_text("k"), "v")
    n = c.clear()
    assert n == 1
    assert not (tmp_path / "x").exists()


def test_clear_when_empty_returns_zero(tmp_path: Path) -> None:
    c = SummaryCache(book_id="x", root=tmp_path)
    assert c.clear() == 0


def test_book_dirs_isolated(tmp_path: Path) -> None:
    a = SummaryCache(book_id="A", root=tmp_path)
    b = SummaryCache(book_id="B", root=tmp_path)
    a.set("batch", hash_text("k"), "from-A")
    b.set("batch", hash_text("k"), "from-B")
    assert a.get("batch", hash_text("k")) == "from-A"
    assert b.get("batch", hash_text("k")) == "from-B"
