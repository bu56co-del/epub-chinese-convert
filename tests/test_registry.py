from __future__ import annotations

import importlib.metadata as md
from types import SimpleNamespace

import pytest

from epubconv.engines.base import Engine
from epubconv.engines.opencc_engine import OpenCCEngine
from epubconv.engines.registry import EntryPointGroup, get_engine, list_engines


class FakeEngine(Engine):
    name = "fake"

    def __init__(self, source: str, target: str, **kwargs) -> None:
        self.source = source
        self.target = target
        self.kwargs = kwargs

    def convert(self, text: str) -> str:
        return text


def _factory(source: str, target: str, **kwargs) -> Engine:
    return FakeEngine(source, target, **kwargs)


class _FakeEP:
    """Minimal entry-point shim sufficient for the registry."""

    def __init__(self, name: str, target) -> None:
        self.name = name
        self._target = target

    def load(self):
        return self._target


def test_builtin_opencc_resolves() -> None:
    engine = get_engine("opencc", "zh-CN", "zh-TW")
    assert isinstance(engine, OpenCCEngine)


def test_unknown_engine_raises() -> None:
    with pytest.raises(ValueError, match="unknown engine"):
        get_engine("nope", "zh-CN", "zh-TW")


def test_plugin_engine_resolved_via_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    eps = [_FakeEP("fake", _factory)]

    def fake_entry_points(group: str | None = None, **_: object):
        assert group == EntryPointGroup
        return eps

    monkeypatch.setattr(md, "entry_points", fake_entry_points)

    engine = get_engine("fake", "zh-CN", "zh-TW", opencc_config="ignored")
    assert isinstance(engine, FakeEngine)
    assert engine.source == "zh-CN"
    assert engine.target == "zh-TW"
    assert engine.kwargs == {"opencc_config": "ignored"}


def test_list_engines_includes_builtin_and_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    eps = [_FakeEP("fanhuaji", _factory), _FakeEP("zhconv", _factory)]
    monkeypatch.setattr(md, "entry_points", lambda **_: eps)

    names = list_engines()
    assert "opencc" in names
    assert "fanhuaji" in names
    assert "zhconv" in names
    assert names == sorted(names)


def test_plugin_factory_must_be_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    eps = [_FakeEP("broken", "not-a-callable")]
    monkeypatch.setattr(md, "entry_points", lambda **_: eps)
    with pytest.raises(TypeError):
        get_engine("broken", "zh-CN", "zh-TW")
