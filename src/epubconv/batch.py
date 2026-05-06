"""Batch convert a directory of EPUB files with resume support.

State is stored next to the input directory (or a user-supplied path) in a
small JSON manifest, keyed by relative path. Each entry records status
(``done`` / ``error``) and the output path or error message. On rerun,
``done`` files are skipped, ``error`` files are retried.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable

from loguru import logger

MANIFEST_NAME = ".epubconv-batch.json"


@dataclass
class FileStatus:
    status: str  # "done" | "error"
    output: str | None = None
    error: str | None = None
    finished_at: float = 0.0


@dataclass
class Manifest:
    version: int = 1
    files: dict[str, FileStatus] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            version=data.get("version", 1),
            files={k: FileStatus(**v) for k, v in data.get("files", {}).items()},
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = {
            "version": self.version,
            "files": {k: asdict(v) for k, v in self.files.items()},
        }
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


@dataclass
class BatchResult:
    done: list[Path]
    skipped: list[Path]
    errored: list[tuple[Path, str]]


def find_epubs(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.epub") if p.is_file())


def run_batch(
    inputs: Path,
    outputs: Path,
    convert: Callable[[Path, Path], Path],
    *,
    manifest_path: Path | None = None,
    resume: bool = True,
) -> BatchResult:
    """Convert every ``*.epub`` under ``inputs`` into ``outputs``.

    ``convert(src, dst)`` performs the actual conversion. On exception, the
    file is recorded as errored and processing continues. Output filenames
    mirror the input layout under ``outputs``.
    """
    if not inputs.is_dir():
        raise NotADirectoryError(f"input must be a directory: {inputs}")
    outputs.mkdir(parents=True, exist_ok=True)

    manifest_path = manifest_path or (outputs / MANIFEST_NAME)
    manifest = Manifest.load(manifest_path)

    epubs = find_epubs(inputs)
    logger.info(f"batch: {len(epubs)} epub(s) under {inputs}")

    done: list[Path] = []
    skipped: list[Path] = []
    errored: list[tuple[Path, str]] = []

    for src in epubs:
        rel = src.relative_to(inputs).as_posix()
        existing = manifest.files.get(rel)
        if resume and existing and existing.status == "done":
            existing_out = Path(existing.output) if existing.output else None
            if existing_out and existing_out.exists():
                logger.info(f"skip (already done): {rel}")
                skipped.append(src)
                continue

        dst = outputs / src.relative_to(inputs)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            convert(src, dst)
            manifest.files[rel] = FileStatus(status="done", output=str(dst), finished_at=time.time())
            done.append(src)
            logger.info(f"done: {rel}")
        except Exception as exc:
            manifest.files[rel] = FileStatus(status="error", error=str(exc), finished_at=time.time())
            errored.append((src, str(exc)))
            logger.error(f"error: {rel}: {exc}")
        finally:
            manifest.save(manifest_path)

    return BatchResult(done=done, skipped=skipped, errored=errored)
