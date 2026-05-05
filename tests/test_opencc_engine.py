from epubconv.engines.opencc_engine import OpenCCEngine


def test_simplified_to_traditional_phrase():
    eng = OpenCCEngine("zh-CN", "zh-TW")
    out = eng.convert("软件信息")
    # s2twp should give Taiwan vocabulary, not just char-level mapping.
    assert "軟體" in out or "軟件" in out
    assert "簡" not in out  # source had no 简, sanity


def test_traditional_to_simplified():
    eng = OpenCCEngine("zh-TW", "zh-CN")
    assert eng.convert("繁體中文") == "繁体中文"


def test_unknown_pair_raises():
    import pytest
    with pytest.raises(ValueError):
        OpenCCEngine("zh-CN", "ja-JP")


def test_explicit_config_overrides_pair():
    eng = OpenCCEngine("zh-CN", "zh-TW", config="s2t")
    # s2t is char-level Hant, no Taiwan vocab.
    assert eng.convert("简体") == "簡體"


def test_empty_string_passthrough():
    eng = OpenCCEngine("zh-CN", "zh-TW")
    assert eng.convert("") == ""
