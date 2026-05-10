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


def test_index_includes_all_tabs(client: TestClient) -> None:
    r = client.get("/")
    text = r.text
    for label in ["Convert", "Diff", "Export Skill", "Summary", "Settings"]:
        assert label in text
    assert "btn-update" in text
    # Image gen has been removed.
    assert "generate-image" not in text
    assert "Image Gen" not in text


def test_update_endpoint_runs_git_pull(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint resolves the repo root via Path; we monkey-patch the
    git wrapper so we don't depend on a live remote."""
    from epubconv.web import server as srv

    calls: list[tuple] = []

    def fake_git(*args: str, cwd: Path) -> tuple[int, str, str]:
        calls.append((args, cwd))
        if args[0] == "pull":
            return 0, "Already up to date.", ""
        if args[0] == "rev-parse":
            return 0, "abc123def4567890", ""
        return 0, "", ""

    monkeypatch.setattr(srv, "_git", fake_git)
    r = client.post("/update")
    assert r.status_code == 200
    payload = r.json()
    assert payload["changed"] is False
    assert payload["head"] == "abc123def4567890"
    assert calls and calls[0][0][0] == "pull"


def test_update_endpoint_reports_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from epubconv.web import server as srv
    monkeypatch.setattr(srv, "_git", lambda *args, cwd: (1, "", "fatal: not a git repo"))
    r = client.post("/update")
    assert r.status_code == 500
    assert "fatal" in r.json()["detail"]


def test_summarize_endpoint(
    client: TestClient,
    skill_epub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock LLMClient so we don't hit the network."""
    from epubconv import summarize as sm

    class FakeClient:
        def complete(self, system: str, user: str, **kwargs) -> str:
            return "## 一句話總結\n測試小說。\n\n## 主要人物\n- 主角"

    monkeypatch.setattr(sm, "LLMClient", lambda cfg: FakeClient())
    monkeypatch.setattr(sm, "LLMConfig",
                        type("Cfg", (), {"for_provider": staticmethod(lambda *a, **kw: object())}))

    with skill_epub.open("rb") as fh:
        r = client.post(
            "/summarize",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"provider": "banana2556", "model": "gpt-5", "max_chars": "5000"},
        )
    assert r.status_code == 200
    payload = r.json()
    assert "一句話總結" in payload["text"]
    assert payload["chapters_used"] >= 1
    assert payload["chars_used"] > 0


def test_summarize_endpoint_handles_empty_book(
    client: TestClient,
    sample_epub: Path,
) -> None:
    # Conftest sample is too short → summarize raises ValueError → 400.
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/summarize",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"max_chars": "5000"},
        )
    assert r.status_code == 400


def test_settings_get_reflects_environment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BANANA2556_API_KEY", "sk-test1234")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = client.get("/settings")
    assert r.status_code == 200
    data = r.json()
    assert data["BANANA2556_API_KEY"]["configured"] is True
    assert data["BANANA2556_API_KEY"]["last4"] == "1234"
    assert data["GEMINI_API_KEY"]["configured"] is False


def test_settings_post_saves_and_updates_env(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EPUBCONV_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("BANANA2556_API_KEY", raising=False)

    r = client.post("/settings", json={"BANANA2556_API_KEY": "sk-saved"})
    assert r.status_code == 200
    assert r.json()["BANANA2556_API_KEY"]["last4"] == "aved"

    # File written and key in env.
    contents = (tmp_path / "secrets.env").read_text(encoding="utf-8")
    assert "BANANA2556_API_KEY=sk-saved" in contents
    import os
    assert os.environ.get("BANANA2556_API_KEY") == "sk-saved"


def test_settings_post_rejects_unknown_key(client: TestClient) -> None:
    r = client.post("/settings", json={"FOO_BAR": "x"})
    assert r.status_code == 400
    assert "unknown" in r.json()["detail"].lower()


def test_settings_reload_endpoint(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EPUBCONV_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("BANANA2556_API_KEY", raising=False)
    (tmp_path / "secrets.env").write_text(
        "BANANA2556_API_KEY=sk-reloaded\n", encoding="utf-8",
    )
    r = client.post("/settings/reload")
    assert r.status_code == 200
    # Subsequent /settings should reflect the loaded value.
    r2 = client.get("/settings")
    assert r2.json()["BANANA2556_API_KEY"]["configured"] is True


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
