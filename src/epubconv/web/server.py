"""FastAPI server for browser-based EPUB conversion + skill export + summary.

Runs locally; no auth, no persistence. Designed to be opened by
double-clicking ``launch.command`` (which runs ``epubconv serve --reload``).

Tabs: Convert / Diff / Skill / Summary / Settings. A header "Update"
button runs ``git pull`` and (with --reload) auto-restarts the server.

Optional dependency: install with ``pip install epubconv[web]``.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "fastapi is required. Install with: pip install epubconv[web]"
    ) from exc

from ..converters.writing_mode import WRITING_MODES
from ..diff import build_diff_report
from ..engines.registry import get_engine, list_engines
from ..pipeline import convert_epub
from ..settings import KNOWN_KEYS, load_into_env, save_keys, status as settings_status
from ..skill.exporter import export_skill
from ..summarize import summarise_epub

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>epubconv</title>
<style>
  :root {
    --bg: #0f172a;
    --bg-raised: #1e293b;
    --bg-hover: #334155;
    --border: #334155;
    --text: #e2e8f0;
    --text-muted: #94a3b8;
    --text-strong: #f1f5f9;
    --accent: #60a5fa;
    --accent-hover: #93c5fd;
    --ok: #34d399;
    --error: #f87171;
    --code-bg: #0b1120;
  }
  * { box-sizing: border-box; }
  html, body { background: var(--bg); color: var(--text); }
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 720px; margin: 1.5em auto; padding: 0 1em; }
  a { color: var(--accent); }
  h1, h2, h3 { color: var(--text-strong); }
  h1 { margin-bottom: 0.2em; }
  code { background: var(--code-bg); padding: 0 0.3em; border-radius: 3px; font-size: 0.9em; }
  header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 0.5em; }
  .tabs { display: flex; flex-wrap: wrap; gap: 0.25em; border-bottom: 2px solid var(--border); margin-bottom: 1em; }
  .tab { background: none; border: 0; padding: 0.5em 1em; cursor: pointer; color: var(--text-muted); border-bottom: 2px solid transparent; margin-bottom: -2px; font-size: 0.95em; }
  .tab:hover { color: var(--accent-hover); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
  .panel { display: none; }
  .panel.active { display: block; }
  form { display: grid; gap: 0.75em; padding: 1em; background: var(--bg-raised); border: 1px solid var(--border); border-radius: 8px; }
  label { display: grid; gap: 0.25em; font-size: 0.9em; color: var(--text-muted); }
  input[type=file], input[type=text], input[type=password], input[type=number], select, button, textarea {
    padding: 0.5em; font-size: 1em; font-family: inherit; border-radius: 6px;
  }
  input[type=text], input[type=password], input[type=number], select, textarea {
    background: var(--bg); color: var(--text); border: 1px solid var(--border);
  }
  input:focus, select:focus, textarea:focus {
    outline: none; border-color: var(--accent);
  }
  input[type=file] { color: var(--text); }
  input[type=file]::file-selector-button {
    background: var(--bg-hover); color: var(--text); border: 1px solid var(--border);
    border-radius: 4px; padding: 0.3em 0.7em; cursor: pointer; margin-right: 0.5em;
  }
  button { background: var(--accent); color: #0f172a; font-weight: 600; border: 0; cursor: pointer; }
  button:hover { background: var(--accent-hover); }
  button:disabled { background: var(--bg-hover); color: var(--text-muted); cursor: not-allowed; }
  button.secondary { background: var(--bg-hover); color: var(--text); border: 1px solid var(--border); font-weight: 400; }
  button.secondary:hover { background: var(--border); color: var(--text-strong); }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75em; }
  .muted { color: var(--text-muted); font-size: 0.85em; }
  pre.result { white-space: pre-wrap; background: var(--code-bg); color: var(--text); padding: 0.75em; border-radius: 6px; max-height: 24em; overflow-y: auto; border: 1px solid var(--border); }
  .summary-md { background: var(--bg); color: var(--text); padding: 1em; border-radius: 6px; line-height: 1.6; border: 1px solid var(--border); }
  .summary-md h2, .summary-md h3 { color: var(--text-strong); margin-top: 1em; }
  .summary-md code { background: var(--code-bg); }
  .key-status { font-family: monospace; }
  .ok { color: var(--ok); }
  .missing { color: var(--error); }
  #update-status { font-size: 0.85em; color: var(--text-muted); }
  ::selection { background: var(--accent); color: #0f172a; }
</style>
</head>
<body>
<header>
  <h1>epubconv</h1>
  <div>
    <button id="btn-update" class="secondary">↻ Update (git pull)</button>
    <span id="update-status"></span>
  </div>
</header>

<div class="tabs">
  <button class="tab active" data-tab="convert">Convert</button>
  <button class="tab" data-tab="diff">Diff</button>
  <button class="tab" data-tab="skill">Export Skill</button>
  <button class="tab" data-tab="summary">Summary</button>
  <button class="tab" data-tab="settings">⚙ Settings</button>
</div>

<section id="t-convert" class="panel active">
<form id="f-convert" enctype="multipart/form-data" action="/convert" method="post">
  <h3>Convert EPUB between Chinese variants</h3>
  <label>EPUB <input type="file" name="file" accept=".epub" required></label>
  <div class="row">
    <label>From <select name="source_lang">
      <option>zh-CN</option><option>zh-Hans</option><option>zh-TW</option><option>zh-HK</option><option>zh-Hant</option>
    </select></label>
    <label>To <select name="target_lang">
      <option>zh-TW</option><option>zh-HK</option><option>zh-Hant</option><option>zh-CN</option><option>zh-Hans</option>
    </select></label>
  </div>
  <div class="row">
    <label>Writing mode <select name="writing_mode">
      <option>preserve</option><option>horizontal</option><option>vertical</option>
    </select></label>
    <label>Engine <select name="engine_name">__ENGINE_OPTIONS__</select></label>
  </div>
  <button type="submit">Convert &rarr; download</button>
</form>
</section>

<section id="t-diff" class="panel">
<form id="f-diff" enctype="multipart/form-data" action="/diff" method="post">
  <h3>Side-by-side diff preview</h3>
  <label>EPUB <input type="file" name="file" accept=".epub" required></label>
  <div class="row">
    <label>From <select name="source_lang">
      <option>zh-CN</option><option>zh-Hans</option><option>zh-TW</option><option>zh-HK</option><option>zh-Hant</option>
    </select></label>
    <label>To <select name="target_lang">
      <option>zh-TW</option><option>zh-HK</option><option>zh-Hant</option><option>zh-CN</option><option>zh-Hans</option>
    </select></label>
  </div>
  <button type="submit">Render diff</button>
</form>
</section>

<section id="t-skill" class="panel">
<form id="f-skill" enctype="multipart/form-data">
  <h3>Export Claude Skill</h3>
  <p class="muted">Bundle the book as a Claude Skill folder (SKILL.md + JSONL knowledge base).
    "Download" sends a ZIP; "Install" writes directly to <code>~/.claude/skills/</code>.</p>
  <label>EPUB <input type="file" name="file" accept=".epub" required></label>
  <div class="row">
    <label>To <select name="target_lang">
      <option>zh-TW</option><option>zh-HK</option><option>zh-Hant</option><option>zh-CN</option><option>zh-Hans</option>
    </select></label>
    <label>Chunk size <input type="number" name="chunk_size" value="1500" min="200" max="10000"></label>
  </div>
  <label>Skill name (optional, slug override) <input type="text" name="name" placeholder="auto from <dc:title>"></label>
  <label>Description (optional) <input type="text" name="description" placeholder="auto from metadata"></label>
  <div class="row">
    <button type="button" id="btn-skill-download">Download ZIP</button>
    <button type="button" id="btn-skill-install">Install to ~/.claude/skills/</button>
  </div>
  <pre id="skill-result" class="muted result" style="display:none"></pre>
</form>
</section>

<section id="t-summary" class="panel">
<form id="f-summary" enctype="multipart/form-data">
  <h3>One-click book summary</h3>
  <p class="muted">Sends the book's text through an LLM and returns a structured summary.
    Set your provider key in the <strong>Settings</strong> tab first.</p>
  <label>EPUB <input type="file" name="file" accept=".epub" required></label>
  <div class="row">
    <label>Provider <select name="provider">
      <option value="banana2556">banana2556</option>
      <option value="gemini">gemini</option>
    </select></label>
    <label>Model <input type="text" name="model" value="gpt-5" placeholder="gpt-5 / gpt-4o / claude-3-5-sonnet-20241022 / gemini-1.5-pro"></label>
  </div>
  <label>Max source chars <input type="number" name="max_chars" value="80000" min="2000" max="500000"></label>
  <button type="button" id="btn-summary">Generate summary</button>
  <div id="summary-status" class="muted"></div>
  <div id="summary-out" class="summary-md" style="display:none"></div>
</form>
</section>

<section id="t-settings" class="panel">
<form id="f-settings">
  <h3>API keys</h3>
  <p class="muted">Saved to <code>~/.config/epubconv/secrets.env</code> with mode 0600.
    Loaded into the server's environment at startup so other tabs can use them.
    A value already exported in your shell takes precedence over what's saved here.</p>

  <label>BANANA2556_API_KEY
    <span class="key-status muted" id="status-banana2556">…</span>
    <input type="password" name="BANANA2556_API_KEY" placeholder="sk-...">
  </label>

  <label>GEMINI_API_KEY
    <span class="key-status muted" id="status-gemini">…</span>
    <input type="password" name="GEMINI_API_KEY" placeholder="AIza...">
  </label>

  <div class="row">
    <button type="button" id="btn-settings-save">Save</button>
    <button type="button" id="btn-settings-reload" class="secondary">Reload from disk</button>
  </div>
  <div id="settings-status" class="muted"></div>
</form>
</section>

<script>
(function() {
  // -------- Tabs --------
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("t-" + btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "settings") refreshSettings();
    });
  });

  // -------- Update --------
  const updateBtn = document.getElementById("btn-update");
  const updateStatus = document.getElementById("update-status");
  updateBtn.addEventListener("click", async () => {
    updateBtn.disabled = true;
    updateStatus.textContent = "Pulling…";
    try {
      const r = await fetch("/update", { method: "POST" });
      const data = await r.json();
      if (!r.ok) { updateStatus.textContent = "Error: " + (data.detail || r.statusText); return; }
      updateStatus.textContent = data.changed
        ? `Updated to ${data.head.slice(0,7)} (${data.files} files). Server reloading…`
        : "Already up to date.";
    } catch (e) {
      updateStatus.textContent = "Error: " + e;
    } finally {
      updateBtn.disabled = false;
    }
  });

  // -------- Skill --------
  const skillForm = document.getElementById("f-skill");
  const skillResult = document.getElementById("skill-result");
  function showSkill(text, isErr) {
    skillResult.style.display = "block";
    skillResult.textContent = text;
    skillResult.style.color = isErr ? "#b00" : "#070";
  }
  document.getElementById("btn-skill-download").addEventListener("click", async () => {
    showSkill("Generating skill…", false);
    const r = await fetch("/export-skill", { method: "POST", body: new FormData(skillForm) });
    if (!r.ok) { showSkill("Error: " + (await r.text()), true); return; }
    const blob = await r.blob();
    const cd = r.headers.get("content-disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    const fname = m ? m[1] : "skill.zip";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = fname; a.click();
    URL.revokeObjectURL(url);
    showSkill("Downloaded " + fname, false);
  });
  document.getElementById("btn-skill-install").addEventListener("click", async () => {
    showSkill("Installing to ~/.claude/skills/ …", false);
    const r = await fetch("/install-skill", { method: "POST", body: new FormData(skillForm) });
    const data = await r.json().catch(() => null);
    if (!r.ok) { showSkill("Error: " + (data ? data.detail : r.statusText), true); return; }
    showSkill(
      "Installed!\\nPath: " + data.path + "\\nChunks: " + data.chunks +
      "\\n\\nRestart Claude Code (or open a new session) to pick up the skill.",
      false
    );
  });

  // -------- Summary --------
  const summaryForm = document.getElementById("f-summary");
  const summaryStatus = document.getElementById("summary-status");
  const summaryOut = document.getElementById("summary-out");
  document.getElementById("btn-summary").addEventListener("click", async () => {
    summaryStatus.textContent = "Reading EPUB and querying the LLM (this can take 30-60s)…";
    summaryOut.style.display = "none";
    const r = await fetch("/summarize", { method: "POST", body: new FormData(summaryForm) });
    const data = await r.json().catch(() => null);
    if (!r.ok) {
      summaryStatus.textContent = "Error: " + (data ? data.detail : r.statusText);
      return;
    }
    summaryStatus.textContent =
      `Summarised ${data.chapters_used} chapters (${data.chars_used.toLocaleString()} chars).`;
    summaryOut.style.display = "block";
    summaryOut.innerHTML = simpleMarkdown(data.text);
  });

  // -------- Settings --------
  const settingsForm = document.getElementById("f-settings");
  const settingsStatus = document.getElementById("settings-status");

  async function refreshSettings() {
    const r = await fetch("/settings");
    if (!r.ok) { settingsStatus.textContent = "Error: " + r.statusText; return; }
    const data = await r.json();
    for (const [key, info] of Object.entries(data)) {
      const span = document.getElementById("status-" + key.toLowerCase().replace(/_api_key$/, ""));
      if (!span) continue;
      span.classList.remove("ok", "missing");
      if (info.configured) {
        span.classList.add("ok");
        span.textContent = `set (••••${info.last4})`;
      } else {
        span.classList.add("missing");
        span.textContent = "not set";
      }
    }
  }

  document.getElementById("btn-settings-save").addEventListener("click", async () => {
    settingsStatus.textContent = "Saving…";
    const fd = new FormData(settingsForm);
    // Drop empty fields so blank inputs don't clear an existing key.
    const payload = {};
    for (const [k, v] of fd.entries()) {
      if (typeof v === "string" && v.trim()) payload[k] = v.trim();
    }
    const r = await fetch("/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => null);
      settingsStatus.textContent = "Error: " + (d ? d.detail : r.statusText);
      return;
    }
    // Clear input values after save so the masked indicator is the source of truth.
    for (const inp of settingsForm.querySelectorAll("input[type=password]")) inp.value = "";
    settingsStatus.textContent = "Saved.";
    refreshSettings();
  });

  document.getElementById("btn-settings-reload").addEventListener("click", async () => {
    settingsStatus.textContent = "Reloading from disk…";
    const r = await fetch("/settings/reload", { method: "POST" });
    if (!r.ok) { settingsStatus.textContent = "Error: " + r.statusText; return; }
    settingsStatus.textContent = "Reloaded.";
    refreshSettings();
  });

  // initial load
  refreshSettings();

  // -------- Tiny inline markdown renderer --------
  function simpleMarkdown(s) {
    function esc(t) { return t.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c])); }
    const lines = s.split(/\\r?\\n/);
    const out = [];
    let inUl = false;
    for (let raw of lines) {
      const line = raw.trimEnd();
      if (line.startsWith("## ")) {
        if (inUl) { out.push("</ul>"); inUl = false; }
        out.push("<h2>" + inline(esc(line.slice(3))) + "</h2>");
      } else if (line.startsWith("# ")) {
        if (inUl) { out.push("</ul>"); inUl = false; }
        out.push("<h3>" + inline(esc(line.slice(2))) + "</h3>");
      } else if (line.startsWith("- ") || line.startsWith("* ")) {
        if (!inUl) { out.push("<ul>"); inUl = true; }
        out.push("<li>" + inline(esc(line.slice(2))) + "</li>");
      } else if (line === "") {
        if (inUl) { out.push("</ul>"); inUl = false; }
      } else {
        if (inUl) { out.push("</ul>"); inUl = false; }
        out.push("<p>" + inline(esc(line)) + "</p>");
      }
    }
    if (inUl) out.push("</ul>");
    return out.join("\\n");
  }
  function inline(s) {
    return s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>")
      .replace(/\\*([^*]+)\\*/g, "<em>$1</em>");
  }
})();
</script>
</body>
</html>
"""


async def _build_skill(
    file: UploadFile,
    target_lang: str,
    chunk_size: int,
    name: str,
    description: str,
) -> tuple[Path, Path]:
    """Save the upload, run export_skill, and return (skill_dir, tmp_dir)."""
    upload_name = file.filename or "input.epub"
    tmp_dir = Path(tempfile.mkdtemp(prefix="epubconv-skill-"))
    src = tmp_dir / upload_name
    src.write_bytes(await file.read())
    out_dir = tmp_dir / "skill"
    try:
        result = export_skill(
            src,
            out_dir,
            target_lang=target_lang,
            name=name or None,
            chunk_size=chunk_size,
            description_override=description or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result.out_dir, tmp_dir


def _zip_dir(src_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src_dir.rglob("*"):
            if path.is_file():
                zf.write(path, src_dir.name + "/" + path.relative_to(src_dir).as_posix())


def _git(*args: str, cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def create_app() -> FastAPI:
    app = FastAPI(title="epubconv", docs_url=None, redoc_url=None)
    repo_root = Path(__file__).resolve().parents[3]

    # Pull saved API keys into os.environ on startup so /summarize and any
    # future LLM features can find them without the user re-exporting in
    # the shell after each --reload.
    load_into_env()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        opts = "\n".join(f"<option>{name}</option>" for name in list_engines())
        return INDEX_HTML.replace("__ENGINE_OPTIONS__", opts)

    @app.post("/update")
    def update_endpoint() -> JSONResponse:
        if not (repo_root / ".git").exists():
            raise HTTPException(status_code=400, detail=f"{repo_root} is not a git working tree")
        rc, out, err = _git("pull", "--ff-only", cwd=repo_root)
        if rc != 0:
            raise HTTPException(status_code=500, detail=err or out or "git pull failed")
        rc2, head, _ = _git("rev-parse", "HEAD", cwd=repo_root)
        changed = "Already up to date." not in out
        files = 0
        if changed:
            for line in out.splitlines():
                stripped = line.strip()
                if "file" in stripped and "changed" in stripped:
                    parts = stripped.split()
                    try:
                        files = int(parts[0])
                    except (ValueError, IndexError):
                        pass
        return JSONResponse({
            "changed": changed,
            "head": head if rc2 == 0 else "",
            "files": files,
            "stdout": out,
        })

    @app.get("/settings")
    def settings_get() -> JSONResponse:
        return JSONResponse(settings_status())

    @app.post("/settings")
    async def settings_post(payload: dict) -> JSONResponse:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")
        unknown = [k for k in payload if k not in KNOWN_KEYS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown keys: {unknown}")
        save_keys({k: str(v) for k, v in payload.items()})
        return JSONResponse(settings_status())

    @app.post("/settings/reload")
    def settings_reload() -> JSONResponse:
        load_into_env()
        return JSONResponse(settings_status())

    @app.post("/convert")
    async def convert_endpoint(
        file: UploadFile = File(...),
        source_lang: str = Form("zh-CN"),
        target_lang: str = Form("zh-TW"),
        writing_mode: str = Form("preserve"),
        engine_name: str = Form("opencc"),
    ) -> FileResponse:
        if writing_mode not in WRITING_MODES:
            raise HTTPException(status_code=400, detail=f"writing_mode must be one of {WRITING_MODES}")

        upload_name = file.filename or "input.epub"
        tmp_dir = Path(tempfile.mkdtemp(prefix="epubconv-web-"))
        src = tmp_dir / upload_name
        src.write_bytes(await file.read())
        dst = tmp_dir / f"{Path(upload_name).stem}.{target_lang}.epub"

        try:
            engine = get_engine(engine_name, source_lang, target_lang)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        convert_epub(src, dst, engine, target_lang, writing_mode=writing_mode)
        return FileResponse(
            path=dst,
            media_type="application/epub+zip",
            filename=dst.name,
        )

    @app.post("/export-skill")
    async def export_skill_endpoint(
        file: UploadFile = File(...),
        target_lang: str = Form("zh-TW"),
        chunk_size: int = Form(1500),
        name: str = Form(""),
        description: str = Form(""),
    ) -> FileResponse:
        skill_dir, tmp_dir = await _build_skill(file, target_lang, chunk_size, name, description)
        zip_path = tmp_dir / f"{skill_dir.name}.zip"
        _zip_dir(skill_dir, zip_path)
        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=zip_path.name,
        )

    @app.post("/install-skill")
    async def install_skill_endpoint(
        file: UploadFile = File(...),
        target_lang: str = Form("zh-TW"),
        chunk_size: int = Form(1500),
        name: str = Form(""),
        description: str = Form(""),
    ) -> JSONResponse:
        skill_dir, _tmp = await _build_skill(file, target_lang, chunk_size, name, description)
        target = Path("~/.claude/skills").expanduser() / skill_dir.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(skill_dir, target)
        chunks = sum(1 for _ in (target / "data.jsonl").open("rb"))
        return JSONResponse({
            "path": str(target),
            "chunks": chunks,
            "name": skill_dir.name,
        })

    @app.post("/diff", response_class=HTMLResponse)
    async def diff_endpoint(
        file: UploadFile = File(...),
        source_lang: str = Form("zh-CN"),
        target_lang: str = Form("zh-TW"),
        engine_name: str = Form("opencc"),
    ) -> str:
        upload_name = file.filename or "input.epub"
        tmp_dir = Path(tempfile.mkdtemp(prefix="epubconv-web-"))
        src = tmp_dir / upload_name
        src.write_bytes(await file.read())
        report = tmp_dir / "report.html"

        try:
            engine = get_engine(engine_name, source_lang, target_lang)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        build_diff_report(src, engine, report)
        return report.read_text(encoding="utf-8")

    @app.post("/summarize")
    async def summarize_endpoint(
        file: UploadFile = File(...),
        provider: str = Form("banana2556"),
        model: str = Form(""),
        max_chars: int = Form(80_000),
    ) -> JSONResponse:
        upload_name = file.filename or "input.epub"
        tmp_dir = Path(tempfile.mkdtemp(prefix="epubconv-summary-"))
        src = tmp_dir / upload_name
        src.write_bytes(await file.read())
        try:
            result = summarise_epub(
                src,
                max_chars=max_chars,
                provider=provider,
                model=model or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
        return JSONResponse({
            "text": result.text,
            "chars_used": result.chars_used,
            "chapters_used": result.chapters_used,
        })

    return app


app = create_app()
