from __future__ import annotations

from pathlib import Path

import pytest

from epubconv.glossary import Glossary
from epubconv.series import (
    ENV_VAR,
    config_dir,
    list_series,
    load_series,
    series_dir,
    series_path,
)


@pytest.fixture
def fake_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    (tmp_path / "series").mkdir()
    return tmp_path


def test_env_var_overrides_config_dir(fake_config: Path) -> None:
    assert config_dir() == fake_config
    assert series_dir() == fake_config / "series"


def test_series_path_rejects_unsafe_names(fake_config: Path) -> None:
    with pytest.raises(ValueError):
        series_path("../etc")
    with pytest.raises(ValueError):
        series_path("a/b")
    with pytest.raises(ValueError):
        series_path(".hidden")
    with pytest.raises(ValueError):
        series_path("")


def test_load_series_missing_raises(fake_config: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_series("nope")


def test_load_series_returns_glossary(fake_config: Path) -> None:
    p = fake_config / "series" / "harry-potter.yaml"
    p.write_text(
        "protect:\n  - 哈利波特\npost:\n  魔法部: 魔法部\n",
        encoding="utf-8",
    )
    g = load_series("harry-potter")
    assert g.protect == ("哈利波特",)
    assert g.post == (("魔法部", "魔法部"),)


def test_list_series_sorted(fake_config: Path) -> None:
    (fake_config / "series" / "b.yaml").write_text("protect: []\n")
    (fake_config / "series" / "a.yaml").write_text("protect: []\n")
    (fake_config / "series" / "c.txt").write_text("ignored")
    assert list_series() == ["a", "b"]


def test_list_series_empty_when_dir_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    # No 'series' subdir created.
    assert list_series() == []


def test_glossary_merge_concat_and_order() -> None:
    a = Glossary(protect=("X",), pre=(("a", "b"),), post=(("p", "q"),))
    b = Glossary(protect=("Y",), pre=(("c", "d"),), post=(("p", "Q"),))  # b overrides a's post
    merged = a.merge(b)
    assert merged.protect == ("X", "Y")
    assert merged.pre == (("a", "b"), ("c", "d"))
    assert merged.post == (("p", "q"), ("p", "Q"))


def test_merged_glossary_b_overrides_a_in_engine() -> None:
    from epubconv.engines.glossary_engine import GlossaryEngine
    from epubconv.engines.opencc_engine import OpenCCEngine

    series = Glossary(post=(("軟體", "軟件"),))      # series rule: HK term
    explicit = Glossary(post=(("軟件", "App軟件"),))  # per-book: prefix it
    merged = series.merge(explicit)

    eng = GlossaryEngine(OpenCCEngine("zh-CN", "zh-TW"), merged)
    out = eng.convert("软件更新")
    # series rewrote 軟體->軟件, explicit then prefixed it.
    assert "App軟件" in out
