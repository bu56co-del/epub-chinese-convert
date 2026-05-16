from __future__ import annotations

import tempfile
from pathlib import Path

import chardet
from loguru import logger

from .converters.content import convert_xhtml
from .converters.opf import update_opf
from .converters.writing_mode import apply_writing_mode
from .engines.base import Engine
from .epub import extract_epub, pack_epub
from .formats.calibre import (
    CalibreNotFoundError,
    OUTPUT_FORMATS,
    detect_format,
    ebook_convert,
    output_path_for,
)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        guess = chardet.detect(raw)
        encoding = guess.get("encoding") or "utf-8"
        logger.warning(f"{path.name}: not UTF-8, falling back to {encoding}")
        return raw.decode(encoding, errors="replace")


def convert_epub(
    src: Path,
    dst: Path,
    engine: Engine,
    target_lang: str,
    writing_mode: str = "preserve",
) -> Path:
    """Convert an EPUB end-to-end. Returns the output path."""
    with tempfile.TemporaryDirectory(prefix="epubconv-") as tmp:
        work = Path(tmp)
        logger.info(f"extract: {src.name} -> {work}")
        pkg = extract_epub(src, work)

        files = pkg.content_files
        logger.info(f"convert: {len(files)} content file(s) using engine={engine.name}")
        for path in files:
            text = _read_text(path)
            converted = convert_xhtml(text, engine)
            path.write_text(converted, encoding="utf-8")

        logger.info(f"opf: {pkg.opf_path.relative_to(work)}")
        update_opf(pkg.opf_path, engine, target_lang)

        if writing_mode != "preserve":
            logger.info(f"writing-mode: {writing_mode}")
            apply_writing_mode(pkg, writing_mode)

        logger.info(f"pack: -> {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        pack_epub(work, dst)

    return dst


def convert_ebook(
    src: Path,
    dst: Path,
    engine: Engine,
    target_lang: str,
    *,
    writing_mode: str = "preserve",
    output_format: str | None = None,
) -> Path:
    """Convert any supported ebook format end-to-end via the EPUB pipeline.

    Pipeline:
      1. If ``src`` is not already EPUB, run it through Calibre to
         produce a temporary EPUB.
      2. Run the existing Chinese-variant conversion on that EPUB.
      3. If the resolved output format is not EPUB, run Calibre again
         to wrap the result in the target container.

    Both Calibre legs are skipped when source and target are already
    EPUB, so existing EPUB → EPUB callers pay no extra cost.

    Returns the final output path.
    """
    src_fmt = detect_format(src)
    if output_format is None:
        output_format = detect_format(dst)
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"unsupported output_format: {output_format!r}; expected {OUTPUT_FORMATS}")

    with tempfile.TemporaryDirectory(prefix="epubconv-fmt-") as tmp:
        work = Path(tmp)

        # Step 1: source → EPUB (skip if already EPUB).
        if src_fmt == "epub":
            epub_in = src
        else:
            epub_in = work / f"{src.stem}.epub"
            logger.info(f"convert_ebook: {src_fmt} -> epub via Calibre ({src.name})")
            try:
                ebook_convert(src, epub_in)
            except CalibreNotFoundError:
                raise

        # Step 2: Chinese variant conversion (always EPUB → EPUB).
        if output_format == "epub":
            return convert_epub(epub_in, dst, engine, target_lang, writing_mode=writing_mode)

        epub_out = work / f"{src.stem}.{target_lang}.epub"
        convert_epub(epub_in, epub_out, engine, target_lang, writing_mode=writing_mode)

        # Step 3: EPUB → target format via Calibre.
        logger.info(f"convert_ebook: epub -> {output_format} via Calibre ({dst.name})")
        try:
            ebook_convert(epub_out, dst)
        except CalibreNotFoundError:
            raise

    return dst
