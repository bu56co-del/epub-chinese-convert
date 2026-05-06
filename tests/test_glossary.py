from __future__ import annotations

from pathlib import Path

import pytest

from epubconv.engines.base import Engine
from epubconv.engines.glossary_engine import GlossaryEngine
from epubconv.engines.opencc_engine import OpenCCEngine
from epubconv.glossary import Glossary


class FakeEngine(Engine):
    """Engine that uppercases ASCII letters and records what it saw."""

    name = "fake"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def convert(self, text: str) -> str:
        self.seen.append(text)
        return text.upper()


def test_empty_glossary_is_identity() -> None:
    g = Glossary.empty()
    assert g.is_empty()
    text, restore = g.apply_pre("hello")
    assert text == "hello"
    assert restore == {}
    assert g.apply_post("hello", restore) == "hello"


def test_protect_keeps_token_through_engine() -> None:
    g = Glossary(protect=("Force",))
    fake = FakeEngine()
    eng = GlossaryEngine(fake, g)
    out = eng.convert("the Force is strong")
    assert "Force" in out
    assert "FORCE" not in out
    # Engine saw a placeholder, not the original token.
    assert "Force" not in fake.seen[0]


def test_pre_replace_runs_before_engine() -> None:
    g = Glossary(pre=(("teh", "the"),))
    fake = FakeEngine()
    out = GlossaryEngine(fake, g).convert("teh quick fox")
    assert out == "THE QUICK FOX"


def test_post_replace_overrides_engine_output() -> None:
    g = Glossary(post=(("FOX", "wolf"),))
    fake = FakeEngine()
    out = GlossaryEngine(fake, g).convert("the fox")
    assert out == "THE wolf"


def test_protect_then_post_does_not_double_apply() -> None:
    # Protected token should be restored *before* post-rules run; if the post-rule
    # matches the restored token it's the user's intent and should still apply.
    g = Glossary(protect=("Yoda",), post=(("Yoda", "Master Yoda"),))
    fake = FakeEngine()
    out = GlossaryEngine(fake, g).convert("hello Yoda")
    assert out == "HELLO Master Yoda"


def test_longer_protect_token_wins_over_shorter() -> None:
    g = Glossary(protect=("New York", "York"))
    fake = FakeEngine()
    out = GlossaryEngine(fake, g).convert("from New York")
    # "New York" must be protected as a whole, not split by "York".
    assert "New York" in out
    assert out == "FROM New York"


def test_glossary_with_real_opencc_engine() -> None:
    g = Glossary(post=(("軟體", "軟件"),))  # force HK term
    base = OpenCCEngine("zh-CN", "zh-TW")
    eng = GlossaryEngine(base, g)
    # "软件" → opencc s2twp normally produces "軟體" (TW); glossary forces "軟件".
    out = eng.convert("软件更新")
    assert "軟件" in out
    assert "軟體" not in out


def test_from_yaml_mapping(tmp_path: Path) -> None:
    p = tmp_path / "g.yaml"
    p.write_text(
        """
protect:
  - 原力
  - 哈利波特
pre:
  teh: the
post:
  軟體: 軟件
""",
        encoding="utf-8",
    )
    g = Glossary.from_yaml(p)
    assert g.protect == ("原力", "哈利波特")
    assert g.pre == (("teh", "the"),)
    assert g.post == (("軟體", "軟件"),)


def test_from_yaml_ordered_list(tmp_path: Path) -> None:
    # List-of-single-pair-mappings is the way to guarantee order across YAML libs.
    p = tmp_path / "g.yaml"
    p.write_text(
        """
post:
  - a: b
  - c: d
""",
        encoding="utf-8",
    )
    g = Glossary.from_yaml(p)
    assert g.post == (("a", "b"), ("c", "d"))


def test_from_yaml_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "g.yaml"
    p.write_text("", encoding="utf-8")
    g = Glossary.from_yaml(p)
    assert g.is_empty()


def test_from_yaml_rejects_bad_shape(tmp_path: Path) -> None:
    p = tmp_path / "g.yaml"
    p.write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Glossary.from_yaml(p)


def test_from_yaml_rejects_non_string_values(tmp_path: Path) -> None:
    p = tmp_path / "g.yaml"
    p.write_text("protect:\n  - 123\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Glossary.from_yaml(p)
