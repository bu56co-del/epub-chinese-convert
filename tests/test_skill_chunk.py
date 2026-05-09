from __future__ import annotations

from pathlib import Path

from epubconv.skill.chunk import (
    Chunk,
    DEFAULT_CHUNK_SIZE,
    _hard_split,
    _normalise_chapter_num,
    _split_to_sections,
    chunk_book,
)
from epubconv.skill.extract import TocEntry


# ---- chapter number normalisation ----


def test_normalise_arabic() -> None:
    assert _normalise_chapter_num("Chapter 12") == 12
    assert _normalise_chapter_num("第12章") == 12


def test_normalise_chinese_basic() -> None:
    assert _normalise_chapter_num("第一章") == 1
    assert _normalise_chapter_num("第十章") == 10
    assert _normalise_chapter_num("第十二章") == 12
    assert _normalise_chapter_num("第二十三章") == 23


def test_normalise_chinese_hundreds() -> None:
    assert _normalise_chapter_num("第一百回") == 100
    assert _normalise_chapter_num("第一百零二回") == 102
    assert _normalise_chapter_num("第二百五十六回") == 256


def test_normalise_simplified_unit() -> None:
    assert _normalise_chapter_num("第二节") == 2
    assert _normalise_chapter_num("第三卷") == 3
    assert _normalise_chapter_num("第四篇") == 4


def test_normalise_returns_none_for_unparseable() -> None:
    assert _normalise_chapter_num("Prologue") is None
    assert _normalise_chapter_num("") is None
    assert _normalise_chapter_num("無章節編號") is None


# ---- chunk packing ----


def test_split_short_text_returns_single_section() -> None:
    text = "短文本"
    sections = _split_to_sections(text, chunk_size=100)
    assert sections == ["短文本"]


def test_split_packs_paragraphs_to_chunk_size() -> None:
    paragraphs = ["A" * 60, "B" * 60, "C" * 60]
    text = "\n\n".join(paragraphs)
    sections = _split_to_sections(text, chunk_size=130)
    # Should produce 2 sections: [A+B] and [C].
    assert len(sections) == 2
    assert "A" * 60 in sections[0] and "B" * 60 in sections[0]
    assert sections[1] == "C" * 60


def test_split_never_breaks_mid_paragraph_when_possible() -> None:
    paragraphs = ["A" * 100, "B" * 100]
    text = "\n\n".join(paragraphs)
    sections = _split_to_sections(text, chunk_size=120)
    assert len(sections) == 2
    assert sections[0] == "A" * 100
    assert sections[1] == "B" * 100


def test_hard_split_falls_back_when_no_sentence_boundaries() -> None:
    text = "x" * 250
    out = _hard_split(text, chunk_size=100)
    assert sum(len(s) for s in out) == 250
    assert all(len(s) <= 100 for s in out)


def test_hard_split_prefers_sentence_boundaries() -> None:
    text = "甲句子很長很長很長。乙句子很長很長很長！丙句子也很長很長很長？"
    out = _hard_split(text, chunk_size=20)
    # Each segment should end on a terminator and not exceed chunk_size by much.
    for s in out:
        assert s.rstrip()[-1:] in "。！？"


# ---- chunk_book ----


def test_chunk_book_assigns_sequential_ids(tmp_path: Path) -> None:
    f1 = tmp_path / "c1.xhtml"
    f1.write_text(
        "<html><body><p>" + ("第一章內容。" * 30) + "</p></body></html>",
        encoding="utf-8",
    )
    f2 = tmp_path / "c2.xhtml"
    f2.write_text(
        "<html><body><p>" + ("第二章內容。" * 30) + "</p></body></html>",
        encoding="utf-8",
    )
    toc = [
        TocEntry(title="第一章", src=f1, heading_path=["第一章"]),
        TocEntry(title="第二章", src=f2, heading_path=["第二章"]),
    ]
    chunks = chunk_book(toc, chunk_size=10_000)
    assert [c.id for c in chunks] == ["ch01.s01", "ch02.s01"]
    assert chunks[0].chapter_num == 1
    assert chunks[1].chapter_num == 2


def test_chunk_book_splits_long_section(tmp_path: Path) -> None:
    f = tmp_path / "long.xhtml"
    paragraphs = ["<p>" + ("段落。" * 200) + "</p>" for _ in range(5)]
    f.write_text("<html><body>" + "\n".join(paragraphs) + "</body></html>", encoding="utf-8")
    toc = [TocEntry(title="第一章", src=f, heading_path=["第一章"])]
    chunks = chunk_book(toc, chunk_size=500)
    assert len(chunks) > 1
    assert {c.chapter_index for c in chunks} == {1}
    assert [c.section_index for c in chunks] == list(range(1, len(chunks) + 1))
    for c in chunks:
        assert c.char_count <= 500 + 200  # paragraph budget can overshoot slightly when joining


def test_chunk_skips_missing_files(tmp_path: Path) -> None:
    toc = [TocEntry(title="第一章", src=tmp_path / "nope.xhtml")]
    assert chunk_book(toc) == []


def test_chunk_default_size_constant() -> None:
    assert DEFAULT_CHUNK_SIZE == 1500


def test_chunk_record_includes_source_sha(tmp_path: Path) -> None:
    f = tmp_path / "c.xhtml"
    f.write_text(
        "<html><body><p>" + ("第一章。" * 100) + "</p></body></html>",
        encoding="utf-8",
    )
    chunks = chunk_book(
        [TocEntry(title="第一章", src=f, heading_path=["第一章"])],
        chunk_size=10_000,
    )
    assert chunks[0].as_record("abc123")["source_sha256"] == "abc123"
    assert chunks[0].as_record("abc123")["chapter_title"] == "第一章"
