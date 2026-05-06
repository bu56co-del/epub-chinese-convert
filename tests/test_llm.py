from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from epubconv.engines.base import Engine
from epubconv.engines.llm_fallback_engine import (
    DEFAULT_AMBIGUOUS_HANS,
    LLMFallbackEngine,
)
from epubconv.llm.cache import Cache
from epubconv.llm.client import LLMConfig, PROVIDERS


# ---------- LLMConfig ----------


def test_provider_defaults_known() -> None:
    assert set(PROVIDERS) == {"gemini", "banana2556"}


def test_for_provider_uses_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    cfg = LLMConfig.for_provider("gemini")
    assert cfg.api_key == "g-key"
    assert "googleapis.com" in cfg.base_url
    assert cfg.model.startswith("gemini")


def test_for_provider_banana(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BANANA2556_API_KEY", "sk-banana")
    cfg = LLMConfig.for_provider("banana2556", model="claude-3-5-sonnet-20241022")
    assert cfg.api_key == "sk-banana"
    assert cfg.base_url == "https://api.banana2556.com/v1"
    assert cfg.model == "claude-3-5-sonnet-20241022"


def test_for_provider_explicit_key_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    cfg = LLMConfig.for_provider("gemini", api_key="explicit")
    assert cfg.api_key == "explicit"


def test_for_provider_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        LLMConfig.for_provider("gemini")


def test_for_provider_unknown_raises() -> None:
    with pytest.raises(ValueError):
        LLMConfig.for_provider("not-a-provider")


# ---------- Cache ----------


def test_cache_roundtrip(tmp_path: Path) -> None:
    c = Cache(tmp_path / "c.json")
    assert c.get("hi", "zh-TW", "m") is None
    c.set("hi", "zh-TW", "m", "您好")
    assert c.get("hi", "zh-TW", "m") == "您好"

    # Reload from disk.
    c2 = Cache(tmp_path / "c.json")
    assert c2.get("hi", "zh-TW", "m") == "您好"
    assert len(c2) == 1


def test_cache_keyed_by_lang_and_model(tmp_path: Path) -> None:
    c = Cache(tmp_path / "c.json")
    c.set("hi", "zh-TW", "m1", "A")
    assert c.get("hi", "zh-CN", "m1") is None
    assert c.get("hi", "zh-TW", "m2") is None


def test_cache_corrupt_file_recovers(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text("not-json")
    c = Cache(p)
    assert len(c) == 0
    c.set("a", "zh-TW", "m", "B")
    assert c.get("a", "zh-TW", "m") == "B"


# ---------- LLMFallbackEngine ----------


class FakeBase(Engine):
    name = "fake"
    def __init__(self) -> None:
        self.calls = 0
    def convert(self, text: str) -> str:
        self.calls += 1
        return f"[base]{text}"


class FakeLLM:
    def __init__(self, response: str = "[llm-result]") -> None:
        self.cfg = SimpleNamespace(model="fake-model")
        self.response = response
        self.calls: list[tuple[str, str]] = []
    def translate(self, text: str, target_lang: str) -> str:
        self.calls.append((text, target_lang))
        return self.response


def test_short_text_skips_llm(tmp_path: Path) -> None:
    base, llm = FakeBase(), FakeLLM()
    eng = LLMFallbackEngine(base, llm, "zh-TW", Cache(tmp_path / "c.json"))
    out = eng.convert("后")  # contains ambiguous char but below min_length
    assert out == "[base]后"
    assert llm.calls == []


def test_no_ambiguous_skips_llm(tmp_path: Path) -> None:
    base, llm = FakeBase(), FakeLLM()
    eng = LLMFallbackEngine(base, llm, "zh-TW", Cache(tmp_path / "c.json"))
    out = eng.convert("普通普通的句子沒有疑")
    assert out.startswith("[base]")
    assert llm.calls == []


def test_ambiguous_routes_to_llm_and_caches(tmp_path: Path) -> None:
    base, llm = FakeBase(), FakeLLM(response="皇后下令")
    cache_path = tmp_path / "c.json"
    eng = LLMFallbackEngine(base, llm, "zh-TW", Cache(cache_path))

    src = "皇后下令把发书"  # contains 后 and 发
    out = eng.convert(src)
    assert out == "皇后下令"
    assert len(llm.calls) == 1
    assert eng.calls == 1

    # Second call with same input -> cache hit, no new LLM call.
    out2 = eng.convert(src)
    assert out2 == "皇后下令"
    assert len(llm.calls) == 1
    assert eng.cache_hits == 1


def test_default_ambiguous_set_includes_known_pitfalls() -> None:
    for ch in "后发只表干里":
        assert ch in DEFAULT_AMBIGUOUS_HANS
