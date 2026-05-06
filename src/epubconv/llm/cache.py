"""On-disk JSON cache keyed by (sha256(text), target_lang, model).

Tiny, simple, write-through. Atomic on save (write-then-rename). One file
per cache, no locking — assumes a single process at a time, which matches
the CLI use case.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_CACHE_PATH = Path("~/.cache/epubconv/llm.json").expanduser()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _key(text: str, target_lang: str, model: str) -> str:
    return f"{_hash(text)}|{target_lang}|{model}"


class Cache:
    def __init__(self, path: Path = DEFAULT_CACHE_PATH) -> None:
        self.path = path
        self._data: dict[str, str] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, text: str, target_lang: str, model: str) -> str | None:
        return self._data.get(_key(text, target_lang, model))

    def set(self, text: str, target_lang: str, model: str, value: str) -> None:
        self._data[_key(text, target_lang, model)] = value
        self._flush()

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._data)
