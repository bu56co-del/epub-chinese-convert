"""End-to-end orchestration for ``epubconv export-skill``.

Pipeline (called by the CLI command):

1. Hash the source EPUB (``source_sha256``) for provenance.
2. Extract the EPUB into a temp directory.
3. Read book metadata + TOC.
4. Chunk each TOC entry into one or more :class:`Chunk` records.
5. Run each chunk's text through the conversion engine to the target variant.
6. Write four files into ``out_dir/<slug>``:
   * ``data.jsonl``      – one record per line, UTF-8, no BOM
   * ``index.json``      – id → byte offset, chapter_title → [ids]
   * ``manifest.json``   – source hash, book metadata, generation timestamp
   * ``SKILL.md``        – YAML frontmatter + how-to-query body

The output is deterministic: same input + same engine → identical bytes.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from ..engines.base import Engine
from ..engines.opencc_engine import OpenCCEngine
from ..epub import extract_epub
from ..names import extract_candidates
from .chunk import DEFAULT_CHUNK_SIZE, Chunk, chunk_book
from .description import build_description
from .extract import is_content_file, read_toc

SLUG_FALLBACK = "epub-skill"


@dataclass
class ExportResult:
    out_dir: Path
    chunks: int
    skill_md: Path
    data_jsonl: Path
    index_json: Path
    manifest_json: Path
    description: str = field(default="")


def export_skill(
    epub: Path,
    out_dir: Path,
    *,
    target_lang: str = "zh-TW",
    name: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    description_override: str | None = None,
    keep_footnotes: bool = False,
    engine: Engine | None = None,
) -> ExportResult:
    """Export an EPUB as a Claude Skill directory. Returns paths to the artefacts."""
    sha = _sha256_file(epub)

    with tempfile.TemporaryDirectory(prefix="epubconv-skill-") as tmp:
        pkg = extract_epub(epub, Path(tmp))
        metadata = pkg.metadata()
        toc = [e for e in read_toc(pkg) if is_content_file(e.src)]
        if not toc:
            raise ValueError(f"no content found in {epub}")

        chunks = chunk_book(toc, chunk_size=chunk_size, keep_footnotes=keep_footnotes)
        if not chunks:
            raise ValueError(f"no text extracted from {epub}")

        source_lang = _first_str(metadata.get("language", "")) or "zh-CN"
        engine = engine or _default_engine(source_lang, target_lang)
        for c in chunks:
            c.text = engine.convert(c.text)

        # Convert metadata + name candidates to the target script too, so the
        # SKILL.md frontmatter and slug match the JSONL content.
        metadata = _convert_metadata(metadata, engine)
        top = [
            engine.convert(t)
            for t, _ in extract_candidates(epub, min_occurrences=3)[:5]
        ]

        slug = _slugify(name or _first_str(metadata.get("title", "")) or SLUG_FALLBACK)
        skill_dir = out_dir / slug
        skill_dir.mkdir(parents=True, exist_ok=True)

        data_path = skill_dir / "data.jsonl"
        index_path = skill_dir / "index.json"
        manifest_path = skill_dir / "manifest.json"
        skill_md_path = skill_dir / "SKILL.md"

        offsets = _write_jsonl(data_path, chunks, sha)
        _write_index(index_path, chunks, offsets)
        _write_manifest(manifest_path, sha, metadata, len(chunks), target_lang)

        description = build_description(
            metadata,
            top_names=top,
            override=description_override,
        )
        _write_skill_md(skill_md_path, slug, description, metadata)

        logger.info(f"export-skill: {len(chunks)} chunks -> {skill_dir}")

        return ExportResult(
            out_dir=skill_dir,
            chunks=len(chunks),
            skill_md=skill_md_path,
            data_jsonl=data_path,
            index_json=index_path,
            manifest_json=manifest_path,
            description=description,
        )


def _convert_metadata(metadata: dict, engine: Engine) -> dict:
    """Run every string value through the engine so SKILL.md matches JSONL script."""
    out: dict = {}
    for k, v in metadata.items():
        if isinstance(v, str):
            out[k] = engine.convert(v)
        elif isinstance(v, list):
            out[k] = [engine.convert(item) if isinstance(item, str) else item for item in v]
        else:
            out[k] = v
    return out


def _default_engine(source_lang: str, target_lang: str) -> Engine:
    if source_lang == target_lang:
        return _IdentityEngine()
    try:
        return OpenCCEngine(source_lang, target_lang)
    except ValueError:
        # Source/target combination has no OpenCC config; pass through unchanged.
        logger.warning(f"no OpenCC config for {source_lang} -> {target_lang}; skipping conversion")
        return _IdentityEngine()


class _IdentityEngine(Engine):
    name = "identity"

    def convert(self, text: str) -> str:
        return text


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(64 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _write_jsonl(path: Path, chunks: list[Chunk], sha: str) -> dict[str, int]:
    """Write JSONL and return ``{id: byte_offset}``."""
    offsets: dict[str, int] = {}
    with path.open("wb") as fh:
        for c in chunks:
            offsets[c.id] = fh.tell()
            line = json.dumps(c.as_record(sha), ensure_ascii=False)
            fh.write(line.encode("utf-8"))
            fh.write(b"\n")
    return offsets


def _write_index(path: Path, chunks: list[Chunk], offsets: dict[str, int]) -> None:
    chapter_to_ids: dict[str, list[str]] = {}
    for c in chunks:
        chapter_to_ids.setdefault(c.chapter_title, []).append(c.id)
    payload = {
        "offsets": offsets,
        "chapters": chapter_to_ids,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_manifest(
    path: Path,
    sha: str,
    metadata: dict,
    chunk_count: int,
    target_lang: str,
) -> None:
    payload = {
        "source_sha256": sha,
        "target_language": target_lang,
        "chunk_count": chunk_count,
        "generated_at": int(time.time()),
        "book": {k: v for k, v in metadata.items()},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_skill_md(path: Path, name: str, description: str, metadata: dict) -> None:
    title = _first_str(metadata.get("title", "")) or name
    blurb = _first_str(metadata.get("description", "")).strip()

    # Emit YAML frontmatter using a literal block scalar to handle multi-line
    # descriptions cleanly. Indented two spaces inside the block.
    desc_block = description.replace("\n", " ").strip()
    body_intro = f"# {title}\n"
    if blurb:
        body_intro += f"\n{blurb}\n"

    body = body_intro + (
        "\n## How to query this skill\n\n"
        "The knowledge base is at `${CLAUDE_SKILL_DIR}/data.jsonl` (one JSON\n"
        "record per line). The `${CLAUDE_SKILL_DIR}/index.json` maps record\n"
        "IDs to byte offsets and chapter titles to record IDs.\n\n"
        "Useful patterns:\n"
        "- Free-text search: `grep -n \"TERM\" ${CLAUDE_SKILL_DIR}/data.jsonl`\n"
        "- Read by ID: open `index.json`, look up `offsets[<id>]`, then\n"
        "  `sed -n \"<line>p\" data.jsonl` (note: offsets are byte positions;\n"
        "  to read a single line use `awk 'NR==N' data.jsonl` after counting).\n"
        "- List chapters: `jq -r '.chapter_title' data.jsonl | sort -u`\n\n"
        "Always ground answers in records you actually read; cite the\n"
        "`chapter_title` and `chapter_num` fields when quoting.\n"
    )

    frontmatter = f"---\nname: {name}\ndescription: |\n  {desc_block}\n---\n\n"
    path.write_text(frontmatter + body, encoding="utf-8")


def _first_str(value) -> str:
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value or "")


_SLUG_BAD = re.compile(r"[^a-z0-9一-鿿-]+")


def _slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = _SLUG_BAD.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or SLUG_FALLBACK
