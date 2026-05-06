"""Engine wrapper that routes ambiguous-character snippets to an LLM.

Strategy:
1. The base engine (typically OpenCC) converts every text node by default.
2. If the *source* text contains any character whose Hans->Hant mapping is
   ambiguous in context (后/发/只/表/干/里/面/...), we hand the *whole text
   node* to the LLM instead, then cache the result.

This keeps LLM calls bounded: a chapter usually has a few hundred text
nodes, of which only a fraction contain ambiguous characters. Cache key is
``sha256(text) | target_lang | model``, so re-running the same chapter is
free after the first pass.
"""
from __future__ import annotations

from .base import Engine
from ..llm.cache import Cache
from ..llm.client import LLMClient

# Source-side characters where OpenCC s2t* mappings are most often wrong.
# These are zh-Hans glyphs that map to multiple zh-Hant glyphs depending
# on context. A snippet containing any of these gets the LLM treatment.
DEFAULT_AMBIGUOUS_HANS: frozenset[str] = frozenset(
    "后发只表干里面板丑斗范胡复几扑准价处涂"
)


class LLMFallbackEngine(Engine):
    def __init__(
        self,
        base: Engine,
        llm: LLMClient,
        target_lang: str,
        cache: Cache,
        ambiguous: frozenset[str] = DEFAULT_AMBIGUOUS_HANS,
        min_length: int = 4,
    ) -> None:
        self.base = base
        self.llm = llm
        self.target_lang = target_lang
        self.cache = cache
        self.ambiguous = ambiguous
        self.min_length = min_length
        self.name = base.name
        # exposed for tests / observability
        self.calls = 0
        self.cache_hits = 0

    def convert(self, text: str) -> str:
        if not text or len(text) < self.min_length:
            return self.base.convert(text)
        if not any(c in text for c in self.ambiguous):
            return self.base.convert(text)

        cached = self.cache.get(text, self.target_lang, self.llm.cfg.model)
        if cached is not None:
            self.cache_hits += 1
            return cached

        result = self.llm.translate(text, self.target_lang)
        self.calls += 1
        self.cache.set(text, self.target_lang, self.llm.cfg.model, result)
        return result
