from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from epubconv.web.server import create_app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def skill_epub(tmp_path: Path) -> Path:
    """An EPUB rich enough to pass the 200-char content filter used by export-skill."""
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf"'
        ' media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="b">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="b">urn:uuid:web</dc:identifier>'
        '<dc:title>测试小说</dc:title><dc:creator>张三</dc:creator>'
        '<dc:language>zh-CN</dc:language>'
        '<dc:description>测试。</dc:description></metadata>'
        '<manifest>'
        '<item id="ch1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '</manifest>'
        '<spine><itemref idref="ch1"/></spine></package>'
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<head><title>目录</title></head><body><nav epub:type="toc"><ol>'
        '<li><a href="chapter1.xhtml">第一章 开始</a></li></ol></nav></body></html>'
    )
    body = "故事就此展开，主角踏上未知的旅途。" * 30
    chapter = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        '<head><title>第一章</title></head>'
        f'<body><h1>第一章 开始</h1><p>{body}</p></body></html>'
    )
    epub_path = tmp_path / "novel.epub"
    with zipfile.ZipFile(epub_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/chapter1.xhtml", chapter)
        zf.writestr("OEBPS/nav.xhtml", nav)
    return epub_path


def test_index_serves_html_with_engine_options(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>epubconv</title>" in r.text
    assert "<option>opencc</option>" in r.text  # builtin registered via entry-point


def test_convert_roundtrips_epub(client: TestClient, sample_epub: Path) -> None:
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/convert",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"source_lang": "zh-CN", "target_lang": "zh-TW", "writing_mode": "preserve"},
        )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/epub+zip"
    assert r.content[:4] == b"PK\x03\x04"  # ZIP magic
    assert "sample.zh-TW.epub" in r.headers.get("content-disposition", "")


def test_convert_rejects_bad_writing_mode(client: TestClient, sample_epub: Path) -> None:
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/convert",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"writing_mode": "sideways"},
        )
    assert r.status_code == 400


def test_convert_rejects_unknown_engine(client: TestClient, sample_epub: Path) -> None:
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/convert",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"engine_name": "no-such-engine"},
        )
    assert r.status_code == 400


def test_index_includes_skill_section(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Export Claude Skill" in r.text
    assert "Download ZIP" in r.text
    assert "Install to ~/.claude/skills/" in r.text


def test_export_skill_returns_zip(client: TestClient, skill_epub: Path) -> None:
    with skill_epub.open("rb") as fh:
        r = client.post(
            "/export-skill",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"target_lang": "zh-TW", "chunk_size": "1500"},
        )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    cd = r.headers.get("content-disposition", "")
    assert ".zip" in cd

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    # Skill folder name ends with .zip in disposition; entries are <slug>/SKILL.md etc.
    assert any(n.endswith("/SKILL.md") for n in names)
    assert any(n.endswith("/data.jsonl") for n in names)
    assert any(n.endswith("/index.json") for n in names)
    assert any(n.endswith("/manifest.json") for n in names)


def test_export_skill_rejects_unparseable_epub(client: TestClient, sample_epub: Path) -> None:
    # The conftest.sample_epub is too small (single chapter <200 chars) — exporter
    # should respond with 400 from our HTTPException, not crash.
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/export-skill",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
        )
    assert r.status_code == 400


def test_install_skill_writes_to_home_claude_skills(
    client: TestClient,
    skill_epub: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    with skill_epub.open("rb") as fh:
        r = client.post(
            "/install-skill",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"target_lang": "zh-TW"},
        )
    assert r.status_code == 200
    payload = r.json()
    assert payload["chunks"] >= 1

    installed = Path(payload["path"])
    assert installed.is_dir()
    assert installed.is_relative_to(tmp_path / ".claude" / "skills")
    assert (installed / "SKILL.md").exists()
    assert (installed / "data.jsonl").exists()


def test_install_skill_overwrites_existing(
    client: TestClient,
    skill_epub: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    payload = {"target_lang": "zh-TW"}
    for _ in range(2):
        with skill_epub.open("rb") as fh:
            r = client.post(
                "/install-skill",
                files={"file": ("novel.epub", fh, "application/epub+zip")},
                data=payload,
            )
        assert r.status_code == 200


def test_diff_returns_html(client: TestClient, sample_epub: Path) -> None:
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/diff",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"source_lang": "zh-CN", "target_lang": "zh-TW"},
        )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "epubconv diff" in r.text
