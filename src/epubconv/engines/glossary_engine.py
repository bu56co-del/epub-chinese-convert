from __future__ import annotations

from ..glossary import Glossary
from .base import Engine


class GlossaryEngine(Engine):
    """Wraps a base engine with user glossary rules.

    Order per ``convert(text)`` call:
    1. ``glossary.pre`` search/replace on source
    2. protect tokens swapped for placeholders
    3. base engine converts the text
    4. placeholders restored to original tokens
    5. ``glossary.post`` search/replace on output
    """

    def __init__(self, base: Engine, glossary: Glossary) -> None:
        self.base = base
        self.glossary = glossary
        self.name = base.name

    def convert(self, text: str) -> str:
        if not text:
            return text
        prepared, restore = self.glossary.apply_pre(text)
        converted = self.base.convert(prepared)
        return self.glossary.apply_post(converted, restore)
