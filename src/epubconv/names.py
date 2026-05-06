"""Heuristic proper-noun candidate extraction from EPUB content.

This is intentionally a *suggestion* tool: rule-based, fast, no ML/LLM. It
gives users a sorted list of probable names/places that they can review and
copy into a glossary's ``protect`` list. Recall > precision; user prunes.

Heuristics:

1. Tokens appearing inside Chinese quotation marks 「」/『』/""/''. Quoted
   spans are strong signals for names, especially in dialogue.
2. Tokens following honorific / title prefixes (老/小/阿/大/老 + name char).
3. CJK n-grams (length 2-4) that occur >= ``min_occurrences`` times across
   the book and don't consist entirely of common stop characters.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from .epub import extract_epub
from .pipeline import _read_text

# Common single-char Chinese tokens that aren't names. Rough; user reviews output.
_STOP_CHARS = set(
    "的了在是和也都就要不沒這那有著一个個我你他她它們什麼那這個那個還"
    "及與或所以因為所所為與及又並而但也但是然後然而所以對於關於對"
    "上下中內外前後左右這裡那裡這樣那樣怎麼這麼那麼"
    "說道想看見聽到知道明白覺得感覺以為認為相信"
    "可以可能應該必須會能會兒一些一個一些一點點"
)

_QUOTE_PAIRS = [("「", "」"), ("『", "』"), ("“", "”"), ("‘", "’")]
_HONORIFICS = ("老", "小", "阿", "大")
_CJK_RE = re.compile(r"[一-鿿]+")


def _xhtml_text(path: Path) -> str:
    soup = BeautifulSoup(_read_text(path), "lxml-xml")
    for tag in soup.find_all(["script", "style", "code", "pre"]):
        tag.decompose()
    return soup.get_text(" ")


def extract_candidates(epub: Path, *, min_occurrences: int = 3, max_len: int = 4) -> list[tuple[str, int]]:
    """Return ``(token, count)`` pairs sorted by count desc, then token asc."""
    import tempfile

    quoted_counter: Counter[str] = Counter()
    honorific_counter: Counter[str] = Counter()
    ngram_counter: Counter[str] = Counter()

    with tempfile.TemporaryDirectory(prefix="epubconv-names-") as tmp:
        pkg = extract_epub(epub, Path(tmp))
        for path in pkg.content_files:
            if path.suffix.lower() not in {".xhtml", ".html", ".htm"}:
                continue
            text = _xhtml_text(path)

            for opener, closer in _QUOTE_PAIRS:
                pattern = re.compile(f"{re.escape(opener)}([^{re.escape(opener)}{re.escape(closer)}]{{1,{max_len}}}){re.escape(closer)}")
                for match in pattern.finditer(text):
                    token = match.group(1).strip()
                    if 2 <= len(token) <= max_len and _is_cjk_only(token):
                        quoted_counter[token] += 1

            for hon in _HONORIFICS:
                for match in re.finditer(f"{hon}([一-鿿]{{1,{max_len - 1}}})", text):
                    candidate = hon + match.group(1)
                    if 2 <= len(candidate) <= max_len:
                        honorific_counter[candidate] += 1

            for run in _CJK_RE.findall(text):
                for n in range(2, max_len + 1):
                    for i in range(len(run) - n + 1):
                        ng = run[i : i + n]
                        if not _is_plausible_name(ng):
                            continue
                        ngram_counter[ng] += 1

    combined: Counter[str] = Counter()
    # Quoted hits are weighted higher: a quoted occurrence is worth 3 ngram occurrences.
    for token, n in quoted_counter.items():
        combined[token] += n * 3
    for token, n in honorific_counter.items():
        combined[token] += n * 2
    for token, n in ngram_counter.items():
        combined[token] += n

    return sorted(
        ((tok, count) for tok, count in combined.items() if count >= min_occurrences),
        key=lambda kv: (-kv[1], kv[0]),
    )


def _is_cjk_only(s: str) -> bool:
    return bool(s) and all("一" <= ch <= "鿿" for ch in s)


def _is_plausible_name(token: str) -> bool:
    if not _is_cjk_only(token):
        return False
    if all(ch in _STOP_CHARS for ch in token):
        return False
    # If the token is mostly stop chars, drop it.
    stop_ratio = sum(1 for ch in token if ch in _STOP_CHARS) / len(token)
    return stop_ratio < 0.5
