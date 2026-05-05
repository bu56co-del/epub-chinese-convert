"""MOBI output via Calibre's ``ebook-convert`` binary.

Calibre is intentionally a runtime-only dependency: it's a system install,
not a pip package. We shell out and surface a clear error if the binary
isn't on PATH.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from loguru import logger

EBOOK_CONVERT = "ebook-convert"


class CalibreNotFoundError(RuntimeError):
    """Raised when ``ebook-convert`` is not on PATH."""


def have_calibre() -> bool:
    return shutil.which(EBOOK_CONVERT) is not None


def epub_to_mobi(epub: Path, mobi: Path) -> Path:
    """Run ``ebook-convert <epub> <mobi>``. Returns the output path.

    Raises ``CalibreNotFoundError`` if Calibre is not installed.
    Raises ``subprocess.CalledProcessError`` on conversion failure.
    """
    if not have_calibre():
        raise CalibreNotFoundError(
            f"{EBOOK_CONVERT!r} not found on PATH. Install Calibre "
            "(https://calibre-ebook.com) to enable MOBI output."
        )
    mobi.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"mobi: {EBOOK_CONVERT} {epub.name} -> {mobi.name}")
    subprocess.run(
        [EBOOK_CONVERT, str(epub), str(mobi)],
        check=True,
        capture_output=True,
    )
    return mobi
