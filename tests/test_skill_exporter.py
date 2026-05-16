from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from epubconv.skill.exporter import _slugify, export_skill


CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def _build_book(tmp_path: Path) -> Path:
    long_para = "故事就此展开，主角踏上了未知的旅途。" * 30  # zh-Hans, exceeds 200 char filter
    chapter_template = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\">"
        "<head><title>{title}</title></head>"
        "<body><h1>{title}</h1><p>{body}</p></body></html>"
    )
    cover_xhtml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\">"
        "<head><title>封面</title></head><body epub:type=\"cover\"><h1>封面</h1></body></html>"
    )
    nav_xhtml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\">"
        "<head><title>目录</title></head><body><nav epub:type=\"toc\"><ol>"
        "<li><a href=\"chapter1.xhtml\">第一章 开始</a></li>"
        "<li><a href=\"chapter2.xhtml\">第二章 旅途</a></li>"
        "</ol></nav></body></html>"
    )
    opf = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<package xmlns=\"http://www.idpf.org/2007/opf\" version=\"3.0\" unique-identifier=\"b\">"
        "<metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\">"
        "<dc:identifier id=\"b\">urn:uuid:test</dc:identifier>"
        "<dc:title>测试小说</dc:title>"
        "<dc:creator>张三</dc:creator>"
        "<dc:language>zh-CN</dc:language>"
        "<dc:description>一本简体中文测试小说。</dc:description>"
        "</metadata>"
        "<manifest>"
        "<item id=\"cover\" href=\"cover.xhtml\" media-type=\"application/xhtml+xml\"/>"
        "<item id=\"ch1\" href=\"chapter1.xhtml\" media-type=\"application/xhtml+xml\"/>"
        "<item id=\"ch2\" href=\"chapter2.xhtml\" media-type=\"application/xhtml+xml\"/>"
        "<item id=\"nav\" href=\"nav.xhtml\" media-type=\"application/xhtml+xml\" properties=\"nav\"/>"
        "</manifest>"
        "<spine>"
        "<itemref idref=\"cover\"/>"
        "<itemref idref=\"ch1\"/>"
        "<itemref idref=\"ch2\"/>"
        "</spine></package>"
    )

    epub = tmp_path / "novel.epub"
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/cover.xhtml", cover_xhtml)
        zf.writestr("OEBPS/chapter1.xhtml", chapter_template.format(title="第一章 开始", body=long_para))
        zf.writestr("OEBPS/chapter2.xhtml", chapter_template.format(title="第二章 旅途", body=long_para))
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
    return epub


def test_export_writes_four_files(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    out = tmp_path / "out"
    result = export_skill(epub, out, target_lang="zh-TW")

    expected = {"SKILL.md", "data.jsonl", "index.json", "manifest.json"}
    actual = {p.name for p in result.out_dir.iterdir()}
    assert expected <= actual

    assert result.chunks >= 2  # at least chapter 1 and chapter 2


def test_jsonl_one_record_per_line_in_target_script(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    out = tmp_path / "out"
    result = export_skill(epub, out, target_lang="zh-TW")

    lines = result.data_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == result.chunks
    records = [json.loads(line) for line in lines]

    # Source said "开始" (zh-CN); target should be "開始" (zh-TW).
    titles = {r["chapter_title"] for r in records}
    assert "第一章 開始" in titles or "第一章 开始" in titles  # OpenCC s2twp output

    # Each record has the schema we promised.
    for r in records:
        assert {"id", "chapter_index", "chapter_num", "chapter_title",
                "heading_path", "section_index", "text", "char_count",
                "source_sha256"} <= r.keys()


def test_index_json_offsets_resolve_to_correct_lines(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    out = tmp_path / "out"
    result = export_skill(epub, out, target_lang="zh-TW")

    index = json.loads(result.index_json.read_text(encoding="utf-8"))
    assert "offsets" in index and "chapters" in index

    raw = result.data_jsonl.read_bytes()
    for record_id, offset in index["offsets"].items():
        # The byte at `offset` is the first char of the JSON line.
        end = raw.find(b"\n", offset)
        assert end != -1
        record = json.loads(raw[offset:end].decode("utf-8"))
        assert record["id"] == record_id


def test_manifest_has_source_hash_and_metadata(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    out = tmp_path / "out"
    result = export_skill(epub, out, target_lang="zh-TW")

    manifest = json.loads(result.manifest_json.read_text(encoding="utf-8"))
    assert manifest["source_sha256"]  # 64 hex chars
    assert len(manifest["source_sha256"]) == 64
    assert manifest["target_language"] == "zh-TW"
    assert manifest["chunk_count"] == result.chunks
    # Title was zh-CN "测试小说"; manifest stores the converted zh-TW form.
    assert manifest["book"]["title"] == "測試小說"
    # `language` records the source script declared in the OPF, untouched.
    assert manifest["book"]["language"] == "zh-CN"


def test_skill_md_has_frontmatter_with_name_and_description(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    out = tmp_path / "out"
    result = export_skill(epub, out, target_lang="zh-TW")

    md = result.skill_md.read_text(encoding="utf-8")
    assert md.startswith("---\n")
    assert "name:" in md
    assert "description:" in md
    assert "${CLAUDE_SKILL_DIR}/data.jsonl" in md


def test_description_override_used_verbatim(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    out = tmp_path / "out"
    result = export_skill(epub, out, target_lang="zh-TW", description_override="custom test desc")
    md = result.skill_md.read_text(encoding="utf-8")
    assert "custom test desc" in md


def test_export_is_deterministic(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    r1 = export_skill(epub, tmp_path / "out1", target_lang="zh-TW")
    r2 = export_skill(epub, tmp_path / "out2", target_lang="zh-TW")
    # data.jsonl bytes should be identical (same hash, same chunks, same convert).
    assert r1.data_jsonl.read_bytes() == r2.data_jsonl.read_bytes()


def test_name_override_changes_slug(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    out = tmp_path / "out"
    result = export_skill(epub, out, target_lang="zh-TW", name="my-novel")
    assert result.out_dir.name == "my-novel"


def test_slugify_handles_chinese_and_punctuation() -> None:
    assert _slugify("Harry Potter") == "harry-potter"
    assert _slugify("哈利波特：神秘的魔法石") == "哈利波特-神秘的魔法石"
    assert _slugify("   ") == "epub-skill"
