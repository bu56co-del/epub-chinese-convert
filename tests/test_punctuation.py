from __future__ import annotations

from epubconv.converters.punctuation import (
    SIMP_QUOTE_MAP,
    TRAD_QUOTE_MAP,
    convert_punctuation,
    punctuation_map_for,
)
from epubconv.engines.glossary_engine import GlossaryEngine
from epubconv.engines.opencc_engine import OpenCCEngine
from epubconv.engines.punctuation_engine import PunctuationEngine
from epubconv.glossary import Glossary


def test_trad_quote_map_pairs() -> None:
    assert TRAD_QUOTE_MAP["“"] == "「"
    assert TRAD_QUOTE_MAP["”"] == "」"
    assert TRAD_QUOTE_MAP["‘"] == "『"
    assert TRAD_QUOTE_MAP["’"] == "』"


def test_simp_map_is_inverse_of_trad_map() -> None:
    assert SIMP_QUOTE_MAP == {v: k for k, v in TRAD_QUOTE_MAP.items()}


def test_punctuation_map_for_known_targets() -> None:
    assert punctuation_map_for("zh-TW") is TRAD_QUOTE_MAP
    assert punctuation_map_for("zh-HK") is TRAD_QUOTE_MAP
    assert punctuation_map_for("zh-Hant") is TRAD_QUOTE_MAP
    assert punctuation_map_for("zh-CN") is SIMP_QUOTE_MAP
    assert punctuation_map_for("zh-Hans") is SIMP_QUOTE_MAP


def test_punctuation_map_for_unknown_returns_none() -> None:
    assert punctuation_map_for("en") is None
    assert punctuation_map_for("ja") is None


def test_convert_punctuation_basic() -> None:
    assert convert_punctuation("“你好”", TRAD_QUOTE_MAP) == "「你好」"
    assert convert_punctuation("‘內’", TRAD_QUOTE_MAP) == "『內』"


def test_convert_punctuation_leaves_other_chars_alone() -> None:
    text = "她说“你好”，code: \"x\""
    out = convert_punctuation(text, TRAD_QUOTE_MAP)
    assert out == "她说「你好」，code: \"x\""  # ASCII quotes untouched


def test_convert_punctuation_empty_inputs() -> None:
    assert convert_punctuation("", TRAD_QUOTE_MAP) == ""
    assert convert_punctuation("hi", {}) == "hi"


def test_punctuation_engine_with_opencc() -> None:
    base = OpenCCEngine("zh-CN", "zh-TW")
    eng = PunctuationEngine(base, TRAD_QUOTE_MAP)
    out = eng.convert("她说“你好世界”")
    assert "「" in out and "」" in out
    assert "“" not in out and "”" not in out


def test_punctuation_then_glossary_post_can_override() -> None:
    # Punctuation runs before glossary post; user glossary should still win.
    base = OpenCCEngine("zh-CN", "zh-TW")
    eng = PunctuationEngine(base, TRAD_QUOTE_MAP)
    eng = GlossaryEngine(eng, Glossary(post=(("「", "“"), ("」", "”"))))
    out = eng.convert("她说“你好”")
    assert "“" in out and "”" in out  # glossary forced curly quotes back


def test_round_trip_trad_to_simp() -> None:
    trad = "「你好」『內』"
    simp = convert_punctuation(trad, SIMP_QUOTE_MAP)
    assert simp == "“你好”‘內’"
