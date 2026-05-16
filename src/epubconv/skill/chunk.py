"""Chunk an EPUB into JSONL records using TOC entries.

For each :class:`TocEntry` resolved by ``read_toc``, we read the visible
text of the referenced file (or the fragment within it, if the entry has
an anchor and the previous entry pointed at the same file), then break
the result into one or more :class:`Chunk` records bounded by
``chunk_size`` characters. Splits land on paragraph boundaries — never
mid-paragraph — so a section longer than the budget produces several
contiguous records sharing the same chapter / TOC metadata.

Out: a flat list of :class:`Chunk` ready to be JSON-serialised by
``epubconv.skill.exporter``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from bs4 import BeautifulSoup

from ..pipeline import _read_text
from .extract import TocEntry, clean_text

DEFAULT_CHUNK_SIZE = 1500

_CHAPTER_NUM_RE = re.compile(
    r"(?:第\s*([零〇一二三四五六七八九十百千两兩\d]+)\s*[章回節节卷篇]|chapter\s*(\d+))",
    re.IGNORECASE,
)

_CN_NUM_MAP = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3,
    "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


@dataclass
class Chunk:
    """One JSONL record."""

    id: str
    chapter_index: int
    chapter_num: int | None
    chapter_title: str
    heading_path: list[str]
    section_index: int
    text: str
    char_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.char_count = len(self.text)

    def as_record(self, source_sha256: str) -> dict:
        d = asdict(self)
        d["source_sha256"] = source_sha256
        return d


def chunk_book(
    toc: list[TocEntry],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    keep_footnotes: bool = False,
) -> list[Chunk]:
    """Walk TOC entries in order and produce a flat list of chunks."""
    chunks: list[Chunk] = []
    chapter_idx = 0

    for entry in toc:
        text = _read_entry_text(entry, keep_footnotes=keep_footnotes)
        if not text:
            continue
        chapter_idx += 1
        chapter_num = _normalise_chapter_num(entry.title)

        sections = _split_to_sections(text, chunk_size)
        for s_idx, section_text in enumerate(sections, start=1):
            cid = f"ch{chapter_idx:02d}.s{s_idx:02d}"
            chunks.append(Chunk(
                id=cid,
                chapter_index=chapter_idx,
                chapter_num=chapter_num,
                chapter_title=entry.title,
                heading_path=list(entry.heading_path) or [entry.title],
                section_index=s_idx,
                text=section_text,
            ))

    return chunks


def _read_entry_text(entry: TocEntry, *, keep_footnotes: bool) -> str:
    """Read visible text for a TOC entry, scoped to its fragment if present."""
    try:
        raw = _read_text(entry.src)
    except (FileNotFoundError, OSError):
        return ""

    if entry.fragment:
        scoped = _slice_to_fragment(raw, entry.fragment)
        if scoped is not None:
            return clean_text(scoped, keep_footnotes=keep_footnotes)

    return clean_text(raw, keep_footnotes=keep_footnotes)


def _slice_to_fragment(xml: str, fragment: str) -> str | None:
    """Return the subtree of ``xml`` rooted at the element whose id == fragment."""
    soup = BeautifulSoup(xml, "lxml-xml")
    target = soup.find(attrs={"id": fragment})
    if target is None:
        return None
    return str(target)


def _split_to_sections(text: str, chunk_size: int) -> list[str]:
    """Pack paragraphs into <= chunk_size pieces.

    Paragraphs come from any whitespace-separated block in the cleaned text;
    we treat any run of 2+ consecutive whitespace chars as a paragraph break,
    falling back to single newlines if that yields nothing.
    """
    if len(text) <= chunk_size:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"(?:\s*\n\s*){2,}", text) if p.strip()]
    if not paragraphs:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        # No internal breaks — hard-split on chunk_size as a last resort.
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    sections: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for para in paragraphs:
        # If a single paragraph exceeds chunk_size, split it on sentence boundaries.
        if len(para) > chunk_size:
            if buf:
                sections.append(" ".join(buf))
                buf, buf_len = [], 0
            sections.extend(_hard_split(para, chunk_size))
            continue
        if buf and buf_len + 1 + len(para) > chunk_size:
            sections.append(" ".join(buf))
            buf, buf_len = [para], len(para)
        else:
            buf.append(para)
            buf_len += len(para) + (1 if buf_len else 0)
    if buf:
        sections.append(" ".join(buf))
    return sections


def _hard_split(text: str, chunk_size: int) -> list[str]:
    sentences = re.split(r"(?<=[。！？!?])\s*", text)
    out: list[str] = []
    buf = ""
    for s in sentences:
        if not s:
            continue
        if len(buf) + len(s) > chunk_size and buf:
            out.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        out.append(buf)
    # Any remaining over-sized pieces (e.g. text with no sentence boundaries
    # at all, or a single sentence longer than the budget) get hard-cut.
    final: list[str] = []
    for piece in out:
        if len(piece) <= chunk_size:
            final.append(piece)
        else:
            final.extend(piece[i : i + chunk_size] for i in range(0, len(piece), chunk_size))
    return final or [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _normalise_chapter_num(title: str) -> int | None:
    if not title:
        return None
    m = _CHAPTER_NUM_RE.search(title)
    if not m:
        return None
    cn, en = m.group(1), m.group(2)
    if en is not None and en.isdigit():
        return int(en)
    if cn is not None:
        return _cn_to_int(cn)
    return None


def _cn_to_int(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    # Strip leading 零/〇 placeholders so 一百零二 -> 一百 + 零二 -> 100 + 2.
    s = s.lstrip("零〇")
    # Handle compact forms: 十 = 10, 二十 = 20, 二十三 = 23, 一百零二 = 102.
    if "百" in s:
        h, _, rest = s.partition("百")
        h_val = _CN_NUM_MAP.get(h, 1) if h else 1
        # rest may itself start with 零, e.g. "零二" -> 2.
        rest_clean = rest.lstrip("零〇")
        if not rest_clean:
            rest_val = 0
        elif "十" in rest_clean:
            rest_val = _cn_to_int(rest_clean) or 0
        elif len(rest_clean) == 1 and rest_clean in _CN_NUM_MAP:
            rest_val = _CN_NUM_MAP[rest_clean]
        else:
            rest_val = _cn_to_int(rest_clean) or 0
        return h_val * 100 + rest_val
    if "十" in s:
        l, _, r = s.partition("十")
        l_val = _CN_NUM_MAP.get(l, 1) if l else 1
        r_val = _CN_NUM_MAP.get(r, 0) if r else 0
        return l_val * 10 + r_val
    if len(s) == 1 and s in _CN_NUM_MAP:
        return _CN_NUM_MAP[s]
    return None
