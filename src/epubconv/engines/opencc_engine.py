from __future__ import annotations

from opencc import OpenCC

from .base import Engine

OPENCC_CONFIGS: dict[tuple[str, str], str] = {
    ("zh-CN", "zh-TW"): "s2twp",
    ("zh-CN", "zh-HK"): "s2hk",
    ("zh-CN", "zh-Hant"): "s2t",
    ("zh-Hans", "zh-TW"): "s2twp",
    ("zh-Hans", "zh-HK"): "s2hk",
    ("zh-Hans", "zh-Hant"): "s2t",
    ("zh-TW", "zh-CN"): "tw2sp",
    ("zh-HK", "zh-CN"): "hk2s",
    ("zh-Hant", "zh-CN"): "t2s",
    ("zh-Hant", "zh-Hans"): "t2s",
    ("zh-TW", "zh-Hans"): "tw2sp",
    ("zh-HK", "zh-Hans"): "hk2s",
    ("zh-TW", "zh-HK"): "tw2hk",
    ("zh-HK", "zh-TW"): "hk2tw",
    ("zh-Hant", "zh-TW"): "t2tw",
    ("zh-Hant", "zh-HK"): "t2hk",
}


class OpenCCEngine(Engine):
    name = "opencc"

    def __init__(self, source: str, target: str, config: str | None = None) -> None:
        if config is None:
            config = OPENCC_CONFIGS.get((source, target))
            if config is None:
                raise ValueError(
                    f"No OpenCC config for {source} -> {target}. "
                    f"Pass config= explicitly or pick from {sorted({c for c in OPENCC_CONFIGS.values()})}."
                )
        self.config = config
        self._cc = OpenCC(config)

    def convert(self, text: str) -> str:
        if not text:
            return text
        return self._cc.convert(text)
