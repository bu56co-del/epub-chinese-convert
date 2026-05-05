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
