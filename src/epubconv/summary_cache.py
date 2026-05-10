"""Disk cache for partial summary results so a failed run can resume.

Each successful LLM call (per-batch chunk note, or final combine output)
is hashed by its input text and saved as a UTF-8 file under
``$EPUBCONV_CONFIG_DIR/cache/summary/<book_sha>/``. On a re-run we look up
the same hash and short-circuit the LLM call — saving both wall-clock
time and per-token API costs after a partial failure.

Layout:

    <book_sha>/
    ├── batch_<sha[:16]>.txt   ← per-batch chunk note
    └── combine_<sha[:16]>.txt ← combined final summary

Keying by content hash means the cache is robust to different chunkings
of the same source: as long as the same exact batch text is sent, the
result is reused.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from .series import config_dir


def _cache_root() -> Path:
    return config_dir() / "cache" / "summary"


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_text(text: str) -> str:
    return hash_bytes(text.encode("utf-8"))


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class SummaryCache:
    """Per-book cache. ``book_id`` is typically ``hash_file(epub_path)``."""

    def __init__(self, book_id: str, *, root: Path | None = None) -> None:
        self.book_id = book_id
        self.root = (root or _cache_root()) / book_id

    def _path(self, kind: str, key: str) -> Path:
        return self.root / f"{kind}_{key[:16]}.txt"

    def get(self, kind: str, key: str) -> str | None:
        p = self._path(kind, key)
        if not p.exists():
            return None
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return None

    def set(self, kind: str, key: str, value: str) -> None:
        p = self._path(kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + rename so a crash mid-write doesn't
        # leave a partial entry.
        fd, tmpname = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(value)
            os.replace(tmpname, p)
        except Exception:
            try:
                os.unlink(tmpname)
            except OSError:
                pass
            raise

    def keys(self, kind: str) -> list[str]:
        if not self.root.is_dir():
            return []
        prefix = f"{kind}_"
        return sorted(
            p.stem[len(prefix):] for p in self.root.iterdir()
            if p.is_file() and p.stem.startswith(prefix)
        )

    def clear(self) -> int:
        if not self.root.is_dir():
            return 0
        n = 0
        for p in self.root.iterdir():
            if p.is_file():
                p.unlink()
                n += 1
        try:
            self.root.rmdir()
        except OSError:
            pass
        return n
