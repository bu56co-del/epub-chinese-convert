"""Backwards-compat re-exports for the old ``formats.mobi`` module.

The actual implementation lives in :mod:`epubconv.formats.calibre` now
since we support MOBI / AZW3 plus reverse conversions.
"""
from __future__ import annotations

from .calibre import (
    CalibreNotFoundError,
    EBOOK_CONVERT,
    ebook_convert,
    epub_to_mobi,
    have_calibre,
)

__all__ = [
    "CalibreNotFoundError",
    "EBOOK_CONVERT",
    "ebook_convert",
    "epub_to_mobi",
    "have_calibre",
]
