from __future__ import annotations

from ..converters.punctuation import convert_punctuation
from .base import Engine


class PunctuationEngine(Engine):
    """Wraps a base engine and rewrites quote marks on the engine's output.

    Composition order matters: when stacked inside a ``GlossaryEngine``, the
    punctuation pass runs *after* the base engine but *before* glossary
    post-rules, so users can still override punctuation choices via their
    glossary.
    """

    def __init__(self, base: Engine, mapping: dict[str, str]) -> None:
        self.base = base
        self.mapping = mapping
        self.name = base.name

    def convert(self, text: str) -> str:
        if not text:
            return text
        return convert_punctuation(self.base.convert(text), self.mapping)
