"""Punctuation transformation between Chinese conventions.

Traditional Chinese (zh-TW / zh-HK / zh-Hant) typically uses corner brackets
「」『』 for quotation, while Simplified Chinese (zh-CN / zh-Hans) uses the
full-width curly quotes ""''. OpenCC does not change these, so books mostly
end up with mismatched conventions after a script-only conversion.

Maps are character-for-character; we only touch the Unicode points that have
unambiguous open/close semantics so we don't have to track quote state.
"""
from __future__ import annotations

# Full-width curly quotes (zh-Hans convention) -> corner brackets (zh-Hant convention)
TRAD_QUOTE_MAP: dict[str, str] = {
    "“": "「",  # " -> 「
    "”": "」",  # " -> 」
    "‘": "『",  # ' -> 『
    "’": "』",  # ' -> 』
}

SIMP_QUOTE_MAP: dict[str, str] = {v: k for k, v in TRAD_QUOTE_MAP.items()}

_TRAD_LANGS = frozenset({"zh-TW", "zh-HK", "zh-Hant"})
_SIMP_LANGS = frozenset({"zh-CN", "zh-Hans"})


def punctuation_map_for(target_lang: str) -> dict[str, str] | None:
    """Return the quote-mark map for ``target_lang``, or ``None`` if no mapping applies."""
    if target_lang in _TRAD_LANGS:
        return TRAD_QUOTE_MAP
    if target_lang in _SIMP_LANGS:
        return SIMP_QUOTE_MAP
    return None


def convert_punctuation(text: str, mapping: dict[str, str]) -> str:
    if not text or not mapping:
        return text
    return text.translate(str.maketrans(mapping))
