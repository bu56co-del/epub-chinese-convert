from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag

from ..engines.base import Engine

# Tags whose text content should never be converted.
SKIP_TAGS: frozenset[str] = frozenset({
    "code", "pre", "script", "style", "kbd", "samp", "var",
})

# Attributes carrying user-visible text that should be converted.
TEXT_ATTRS: frozenset[str] = frozenset({"alt", "title"})


def convert_xhtml(xml: str, engine: Engine) -> str:
    """Convert text content of an XHTML/NCX document, preserving markup.

    Skips `<code>`, `<pre>`, `<script>`, `<style>` and similar code-like tags.
    Converts `alt` / `title` attributes since those surface in readers.
    """
    soup = BeautifulSoup(xml, "lxml-xml")
    _walk(soup, engine)
    return str(soup)


def _walk(node, engine: Engine) -> None:
    for child in list(getattr(node, "children", [])):
        if isinstance(child, NavigableString):
            text = str(child)
            if text and text.strip():
                converted = engine.convert(text)
                if converted != text:
                    child.replace_with(converted)
        elif isinstance(child, Tag):
            if child.name in SKIP_TAGS:
                continue
            for attr in TEXT_ATTRS:
                val = child.get(attr)
                if isinstance(val, str) and val.strip():
                    child[attr] = engine.convert(val)
            _walk(child, engine)
