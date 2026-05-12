"""Format conversion via Calibre's ``ebook-convert`` binary.

Calibre is intentionally a runtime-only dependency: it's a system install,
not a pip package. We shell out and surface a clear error if the binary
isn't on PATH.

We rely on Calibre's auto-detection from the file extension for both
source and destination formats, so the matrix of supported pairs is:

  in : .epub .mobi .azw3 .azw
  out: .epub .mobi .azw3 .azw

Only the *extension* of ``dst`` controls the output format.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from loguru import logger

EBOOK_CONVERT = "ebook-convert"

# Output formats exposed in the UI / CLI. Calibre supports more (pdf, txt,
# fb2, lit, ...) but these are the ones the user asked for.
OUTPUT_FORMATS: tuple[str, ...] = ("epub", "mobi", "azw3")
INPUT_FORMATS: tuple[str, ...] = ("epub", "mobi", "azw3", "azw")

# Calibre needs the output extension to match the format. Map any aliases
# the UI might present back to the canonical extension we hand to
# ebook-convert.
_FORMAT_TO_EXT: dict[str, str] = {
    "epub": ".epub",
    "mobi": ".mobi",
    "azw3": ".azw3",
    "azw": ".azw3",  # 'azw' in UI maps to azw3 — Calibre's modern Kindle format
}


def have_calibre() -> bool:
    return shutil.which(EBOOK_CONVERT) is not None


class CalibreNotFoundError(RuntimeError):
    """Raised when ``ebook-convert`` is not on PATH."""


def detect_format(path: Path) -> str:
    """Return the canonical format name for ``path``'s extension."""
    ext = path.suffix.lower().lstrip(".")
    if ext == "azw":
        return "azw3"  # treat as the modern variant
    if ext in OUTPUT_FORMATS:
        return ext
    raise ValueError(
        f"unsupported ebook extension {path.suffix!r} for {path.name}; "
        f"supported: {INPUT_FORMATS}"
    )


def output_path_for(src: Path, fmt: str, suffix: str = "") -> Path:
    """Build a destination path next to ``src`` with the right extension.

    ``suffix`` lets callers tag the converted file, e.g. ``".zh-TW"``.
    """
    if fmt not in _FORMAT_TO_EXT:
        raise ValueError(f"unsupported output format: {fmt!r}; expected {OUTPUT_FORMATS}")
    return src.with_name(f"{src.stem}{suffix}{_FORMAT_TO_EXT[fmt]}")


def ebook_convert(src: Path, dst: Path) -> Path:
    """Run ``ebook-convert <src> <dst>``. Returns the output path.

    Format is determined by Calibre from the source + destination file
    extensions; no flags are passed beyond the two paths.

    Raises :class:`CalibreNotFoundError` if Calibre is not installed.
    Raises ``subprocess.CalledProcessError`` on conversion failure.
    """
    if not have_calibre():
        raise CalibreNotFoundError(
            f"{EBOOK_CONVERT!r} not found on PATH. Install Calibre "
            "(https://calibre-ebook.com) to enable cross-format conversion."
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"calibre: {EBOOK_CONVERT} {src.name} -> {dst.name}")
    subprocess.run(
        [EBOOK_CONVERT, str(src), str(dst)],
        check=True,
        capture_output=True,
    )
    return dst


# Backward-compat shim — old callers still imported `epub_to_mobi`.
def epub_to_mobi(epub: Path, mobi: Path) -> Path:
    return ebook_convert(epub, mobi)
