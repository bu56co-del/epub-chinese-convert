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


def test_update_runs_pip_and_touches_init_when_changed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the pull moves HEAD we install deps and touch __init__.py
    so uvicorn --reload notices and restarts."""
    from epubconv.web import server as srv

    pull_output = (
        "Updating abc1234..def5678\n"
        "Fast-forward\n"
        " 3 files changed, 10 insertions(+)\n"
    )

    def fake_git(*args, cwd):
        if args[0] == "pull":
            return 0, pull_output, ""
        if args[0] == "rev-parse":
            return 0, "def567890abcdef", ""
        return 0, "", ""

    pip_calls: list = []
    def fake_refresh(repo_root):
        pip_calls.append(repo_root)
        return "ok"

    init_path = srv.Path(__file__).resolve().parents[1] / "src" / "epubconv" / "__init__.py"
    init_path.touch()  # ensure exists
    before_mtime = init_path.stat().st_mtime

    monkeypatch.setattr(srv, "_git", fake_git)
    monkeypatch.setattr(srv, "_refresh_dependencies", fake_refresh)

    import time as _t
    _t.sleep(0.01)  # ensure mtime can change

    r = client.post("/update")
    assert r.status_code == 200
    payload = r.json()
    assert payload["changed"] is True
    assert payload["files"] == 3
    assert payload["pip"] == "ok"
    assert pip_calls == [srv.Path(__file__).resolve().parents[1]]
    assert init_path.stat().st_mtime > before_mtime


def _parse_sse_events(body: str) -> list[dict]:
    """Yield JSON objects from a `data: {...}\\n\\n` stream."""
    out: list[dict] = []
    for chunk in body.split("\n\n"):
        line = chunk.strip()
        if not line.startswith("data:"):
            continue
        out.append(json.loads(line[5:].strip()))
    return out


def _wait_for_done(client: TestClient, timeout: float = 5.0) -> list[dict]:
    """POST /summarize returns immediately. Poll /summarize-status until the
    run finishes, then fetch the replay via /summarize-stream."""
    import time as _t
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        s = client.get("/summarize-status").json()
        if not s["active"]:
            break
        _t.sleep(0.05)
    r = client.get("/summarize-stream")
    return _parse_sse_events(r.text)


def test_index_has_pdf_download_and_print_container(client: TestClient) -> None:
    text = client.get("/").text
    assert "Download PDF" in text
    assert 'id="print-container"' in text
    assert 'id="print-title"' in text
    assert "@media print" in text


def test_summarize_endpoint_starts_task_and_streams_done(
    client: TestClient,
    skill_epub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /summarize starts a detached task and returns 200 with
    {started: true}. The events come via GET /summarize-stream."""
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
    assert r.json()["started"] is True

    events = _wait_for_done(client)
    stages = [e["stage"] for e in events]
    assert stages[0] == "extracting"
    assert "extracted" in stages
    assert "batch_start" in stages
    assert "batch_done" in stages
    assert stages[-1] == "done"
    # `extracted` carries title + creator so the UI can show them
    # alongside the progress bar before the run finishes.
    extracted = next(e for e in events if e["stage"] == "extracted")
    assert extracted["title"] == "测试小说"
    assert extracted["creator"] == "张三"
    final = events[-1]
    assert "一句話總結" in final["text"]
    assert final["title"] == "测试小说"
    assert final["creator"] == "张三"


def test_summarize_status_reflects_run_state(
    client: TestClient,
    skill_epub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/summarize-status lets the page-load reconnect logic decide whether
    to auto-attach without opening an SSE stream."""
    from epubconv import summarize as sm

    class FakeClient:
        def complete(self, system, user, **kw): return "## 一句話總結\n測"

    monkeypatch.setattr(sm, "LLMClient", lambda cfg: FakeClient())
    monkeypatch.setattr(sm, "LLMConfig",
                        type("Cfg", (), {"for_provider": staticmethod(lambda *a, **kw: object())}))

    # No run yet.
    s = client.get("/summarize-status").json()
    assert s["active"] is False
    assert s["event_count"] == 0

    with skill_epub.open("rb") as fh:
        client.post(
            "/summarize",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"max_chars": "5000"},
        )
    _wait_for_done(client)
    s = client.get("/summarize-status").json()
    assert s["active"] is False
    assert s["has_result"] is True
    assert s["latest_stage"] == "done"


def test_cancel_endpoint_stops_in_flight_run(
    client: TestClient,
    skill_epub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /summarize-cancel sets the cancel event; the worker checks it
    between LLM calls and emits a final `cancelled` event."""
    from epubconv import summarize as sm
    import time as _t

    class SlowClient:
        def complete(self, system, user, **kw):
            _t.sleep(0.2)
            return "### 內容\n- ok"

    monkeypatch.setattr(sm, "LLMClient", lambda cfg: SlowClient())
    monkeypatch.setattr(sm, "LLMConfig",
                        type("Cfg", (), {"for_provider": staticmethod(lambda *a, **kw: object())}))

    with skill_epub.open("rb") as fh:
        r1 = client.post(
            "/summarize",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"max_chars": "5000", "per_call_budget": "300"},
        )
    assert r1.status_code == 200

    # Give the worker a moment to enter the first LLM call.
    _t.sleep(0.1)
    cancel = client.post("/summarize-cancel")
    assert cancel.status_code == 200
    assert cancel.json()["cancel_requested"] is True

    events = _wait_for_done(client, timeout=10.0)
    assert events[-1]["stage"] == "cancelled"


def test_cancel_endpoint_when_idle_is_noop(client: TestClient) -> None:
    r = client.post("/summarize-cancel")
    assert r.status_code == 200
    assert r.json()["cancel_requested"] is False


def test_summarize_returns_409_when_run_already_active(
    client: TestClient,
    skill_epub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second POST while the first is in flight returns 409 so the
    browser knows to attach instead of starting a new run."""
    from epubconv import summarize as sm
    import time as _t

    class SlowClient:
        def complete(self, system, user, **kw):
            _t.sleep(0.3)
            return "### 內容\n- ok"

    monkeypatch.setattr(sm, "LLMClient", lambda cfg: SlowClient())
    monkeypatch.setattr(sm, "LLMConfig",
                        type("Cfg", (), {"for_provider": staticmethod(lambda *a, **kw: object())}))

    with skill_epub.open("rb") as fh:
        r1 = client.post(
            "/summarize",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"max_chars": "5000"},
        )
    assert r1.status_code == 200
    with skill_epub.open("rb") as fh:
        r2 = client.post(
            "/summarize",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"max_chars": "5000"},
        )
    assert r2.status_code == 409
    assert "running" in r2.json()["detail"].lower()
    # Drain the in-flight run so subsequent tests start clean.
    _wait_for_done(client)


def test_summarize_stream_replays_for_late_subscribers(
    client: TestClient,
    skill_epub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second GET /summarize-stream after the run finishes still gets
    the full event sequence — the basis of "refresh and reconnect"."""
    from epubconv import summarize as sm

    class FakeClient:
        def complete(self, system, user, **kw): return "## 一句話總結\n測"

    monkeypatch.setattr(sm, "LLMClient", lambda cfg: FakeClient())
    monkeypatch.setattr(sm, "LLMConfig",
                        type("Cfg", (), {"for_provider": staticmethod(lambda *a, **kw: object())}))

    with skill_epub.open("rb") as fh:
        client.post(
            "/summarize",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"max_chars": "5000"},
        )
    _wait_for_done(client)

    # Open the stream a second time; should still get the buffered events.
    second = _parse_sse_events(client.get("/summarize-stream").text)
    assert any(e["stage"] == "extracting" for e in second)
    assert second[-1]["stage"] == "done"


def test_summarize_endpoint_handles_empty_book(
    client: TestClient,
    sample_epub: Path,
) -> None:
    # Conftest sample is too short → summarize raises ValueError → final
    # event is `{"stage": "error", "status": 400}` on the stream.
    with sample_epub.open("rb") as fh:
        r = client.post(
            "/summarize",
            files={"file": ("sample.epub", fh, "application/epub+zip")},
            data={"max_chars": "5000"},
        )
    assert r.status_code == 200
    events = _wait_for_done(client)
    final = events[-1]
    assert final["stage"] == "error"
    assert final["status"] == 400


def test_summarize_endpoint_passes_per_call_budget_through(
    client: TestClient,
    skill_epub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Per-call budget UI input lets users dodge proxy-specific
    'Single message too long' caps. The endpoint must pass it through
    unchanged to summarise_epub."""
    captured: dict = {}
    from epubconv.web import server as srv

    def fake_summarise(path, **kwargs):
        captured.update(kwargs)
        from epubconv.summarize import Summary
        return Summary(text="ok", chars_used=1, chapters_used=1)

    monkeypatch.setattr(srv, "summarise_epub", fake_summarise)
    with skill_epub.open("rb") as fh:
        r = client.post(
            "/summarize",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"per_call_budget": "8000"},
        )
    assert r.status_code == 200
    assert captured["per_call_budget"] == 8000


def test_summary_form_has_per_call_budget_input(client: TestClient) -> None:
    text = client.get("/").text
    assert 'name="per_call_budget"' in text
    assert "Per-call budget" in text


def test_summarize_endpoint_emits_error_event_with_batch_context(
    client: TestClient,
    skill_epub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SummaryError surfaces as a final stream event with status=502 and
    the detail string naming the stage and char count."""
    from epubconv import summarize as sm

    def boom(*a, **kw):
        raise sm.SummaryError(
            "batch-3/14: LLM rejected 49823 input chars after 12.4s: "
            "Upstream error: Input too long"
        )

    monkeypatch.setattr("epubconv.web.server.summarise_epub", boom)
    with skill_epub.open("rb") as fh:
        r = client.post(
            "/summarize",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
        )
    assert r.status_code == 200
    events = _wait_for_done(client)
    final = events[-1]
    assert final["stage"] == "error"
    assert final["status"] == 502
    assert "batch-3/14" in final["detail"]
    assert "49823" in final["detail"]
    assert "Input too long" in final["detail"]


def test_no_server_side_settings_endpoints(client: TestClient) -> None:
    """API keys live in browser localStorage now; no server endpoints."""
    assert client.get("/settings").status_code == 404
    assert client.post("/settings", json={"BANANA2556_API_KEY": "x"}).status_code == 404
    assert client.post("/settings/reload").status_code == 404


def test_summarize_accepts_api_key_form_field(
    client: TestClient,
    skill_epub: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The browser sends the localStorage key as a form param. The server
    should pass it through to summarise_epub instead of looking at env."""
    monkeypatch.delenv("BANANA2556_API_KEY", raising=False)

    captured: dict = {}
    from epubconv.web import server as srv

    def fake_summarise(path, **kwargs):
        captured.update(kwargs)
        from epubconv.summarize import Summary
        return Summary(text="ok", chars_used=1, chapters_used=1)

    monkeypatch.setattr(srv, "summarise_epub", fake_summarise)

    with skill_epub.open("rb") as fh:
        r = client.post(
            "/summarize",
            files={"file": ("novel.epub", fh, "application/epub+zip")},
            data={"provider": "banana2556", "api_key": "sk-from-browser"},
        )
    assert r.status_code == 200
    assert captured["api_key"] == "sk-from-browser"


def test_settings_tab_uses_localstorage_in_html(client: TestClient) -> None:
    text = client.get("/").text
    # The tab still exists, but the JS reads/writes localStorage rather
    # than calling /settings.
    assert "Save to browser" in text
    assert "localStorage" in text
    assert 'localStorage.setItem("epubconv:"' in text
    assert "BANANA2556_API_KEY" in text  # appears in KEY_NAMES array
    assert "GEMINI_API_KEY" in text


def test_test_key_endpoint_calls_provider_models(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The button hits /test-key, which probes GET <base_url>/models."""
    from epubconv.web import server as srv

    captured: dict = {}

    def fake_check(provider, api_key, **kwargs):
        captured["provider"] = provider
        captured["api_key"] = api_key
        return {"ok": True, "status": 200, "model_count": 17, "message": "OK — 17 models"}

    monkeypatch.setattr(srv, "_check_key", fake_check)
    r = client.post("/test-key", data={"provider": "banana2556", "api_key": "sk-xyz"})
    assert r.status_code == 200
    payload = r.json()
    assert payload["ok"] is True
    assert payload["model_count"] == 17
    assert captured == {"provider": "banana2556", "api_key": "sk-xyz"}


def test_test_key_endpoint_returns_401_detail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from epubconv.web import server as srv
    monkeypatch.setattr(
        srv, "_check_key",
        lambda p, k, **kw: {"ok": False, "status": 401, "model_count": 0, "message": "auth_unavailable"},
    )
    r = client.post("/test-key", data={"provider": "banana2556", "api_key": "sk-bad"})
    assert r.status_code == 200  # the *probe* succeeded; the *upstream* didn't
    d = r.json()
    assert d["ok"] is False
    assert d["status"] == 401
    assert "auth_unavailable" in d["message"]


def test_test_key_endpoint_rejects_unknown_provider(client: TestClient) -> None:
    r = client.post("/test-key", data={"provider": "openai", "api_key": "sk-x"})
    assert r.status_code == 400


def test_test_key_endpoint_rejects_blank_key(client: TestClient) -> None:
    r = client.post("/test-key", data={"provider": "banana2556", "api_key": "   "})
    assert r.status_code == 400


def test_settings_tab_has_test_button(client: TestClient) -> None:
    text = client.get("/").text
    assert "Test connection" in text
    assert "btn-settings-test" in text


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
