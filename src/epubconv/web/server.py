"""FastAPI server for browser-based EPUB conversion + skill export + summary + image gen.

Runs locally; no auth, no persistence. Designed to be opened by
double-clicking ``launch.command`` (which runs ``epubconv serve --reload``).

Tabs: Convert / Diff / Skill / Summary / Image. A header "Update" button
runs ``git pull`` and (with --reload) auto-restarts the server.

Optional dependency: install with ``pip install epubconv[web]``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "fastapi is required. Install with: pip install epubconv[web]"
    ) from exc

from ..converters.writing_mode import WRITING_MODES
from ..diff import build_diff_report
from ..engines.registry import get_engine, list_engines
from ..image.client import edit_image, generate_image
from ..pipeline import convert_epub
from ..skill.exporter import export_skill
from ..summarize import summarise_epub

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>epubconv</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 720px; margin: 1.5em auto; padding: 0 1em; }
  h1 { margin-bottom: 0.2em; }
  header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 0.5em; }
  .tabs { display: flex; flex-wrap: wrap; gap: 0.25em; border-bottom: 2px solid #ddd; margin-bottom: 1em; }
  .tab { background: none; border: 0; padding: 0.5em 1em; cursor: pointer; color: #555; border-bottom: 2px solid transparent; margin-bottom: -2px; font-size: 0.95em; }
  .tab:hover { color: #2563eb; }
  .tab.active { color: #2563eb; border-bottom-color: #2563eb; font-weight: 600; }
  .panel { display: none; }
  .panel.active { display: block; }
  form { display: grid; gap: 0.75em; padding: 1em; border: 1px solid #ddd; border-radius: 8px; }
  label { display: grid; gap: 0.25em; font-size: 0.9em; }
  input[type=file], input[type=text], input[type=number], select, button, textarea { padding: 0.5em; font-size: 1em; font-family: inherit; }
  textarea { resize: vertical; min-height: 4em; }
  button { background: #2563eb; color: white; border: 0; border-radius: 6px; cursor: pointer; }
  button:hover { background: #1d4ed8; }
  button.secondary { background: #f3f4f6; color: #111; border: 1px solid #d1d5db; }
  button.secondary:hover { background: #e5e7eb; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75em; }
  .muted { color: #666; font-size: 0.85em; }
  pre.result { white-space: pre-wrap; background: #f9fafb; padding: 0.75em; border-radius: 6px; max-height: 24em; overflow-y: auto; }
  .summary-md { background: #f9fafb; padding: 1em; border-radius: 6px; line-height: 1.6; }
  .summary-md h2 { margin-top: 1em; }
  img.output { max-width: 100%; border-radius: 6px; border: 1px solid #ddd; }
  #update-status { font-size: 0.85em; color: #555; }
  .ref-thumb { max-width: 120px; max-height: 120px; border-radius: 4px; border: 1px solid #ddd; vertical-align: middle; }
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
  <button class="tab" data-tab="image">Image Gen</button>
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
  <p class="muted">Sends the book's text through an LLM (banana2556) and returns a structured summary.
    Requires <code>BANANA2556_API_KEY</code> in the environment.</p>
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

<section id="t-image" class="panel">
<form id="f-image" enctype="multipart/form-data">
  <h3>Image generation (banana2556)</h3>
  <p class="muted">Text-to-image, or image-to-image when you provide a reference.
    Requires <code>BANANA2556_API_KEY</code>.</p>
  <label>Reference image (optional — triggers image-to-image)
    <input type="file" name="reference" accept="image/*" id="img-ref">
  </label>
  <div id="img-ref-preview" style="display:none">Ref: <img id="img-ref-thumb" class="ref-thumb" alt=""></div>
  <label>Prompt
    <textarea name="prompt" placeholder="A retro pixel-art castle on a hill, sunset" required></textarea>
  </label>
  <div class="row">
    <label>Model <select name="model" id="img-model">
      <option value="dall-e-3">dall-e-3 (text-to-image only)</option>
      <option value="gpt-image-1">gpt-image-1 (supports refs)</option>
      <option value="flux-kontext">flux-kontext (supports refs)</option>
    </select></label>
    <label>Size <select name="size">
      <option>1024x1024</option><option>1024x1792</option><option>1792x1024</option>
      <option>512x512</option>
    </select></label>
  </div>
  <div class="row">
    <label>Quality (dall-e-3) <select name="quality">
      <option>standard</option><option>hd</option>
    </select></label>
    <label>Output filename <input type="text" name="filename" value="image.png"></label>
  </div>
  <button type="button" id="btn-image">Generate image</button>
  <div id="img-status" class="muted"></div>
  <div id="img-output" style="display:none">
    <img id="img-output-tag" class="output" alt="generated image"/>
    <div style="margin-top:0.5em">
      <button type="button" id="btn-img-download" class="secondary">Download</button>
      <button type="button" id="btn-img-use-as-ref" class="secondary">Use as reference</button>
    </div>
  </div>
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
    });
  });

  // -------- Update (git pull) --------
  const updateBtn = document.getElementById("btn-update");
  const updateStatus = document.getElementById("update-status");
  updateBtn.addEventListener("click", async () => {
    updateBtn.disabled = true;
    updateStatus.textContent = "Pulling…";
    try {
      const r = await fetch("/update", { method: "POST" });
      const data = await r.json();
      if (!r.ok) {
        updateStatus.textContent = "Error: " + (data.detail || r.statusText);
        return;
      }
      const summary = data.changed
        ? `Updated to ${data.head.slice(0, 7)} (${data.files} files). Server reloading…`
        : "Already up to date.";
      updateStatus.textContent = summary;
    } catch (e) {
      updateStatus.textContent = "Error: " + e;
    } finally {
      updateBtn.disabled = false;
    }
  });

  // -------- Skill (download / install) --------
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

  // -------- Image gen --------
  const imageForm = document.getElementById("f-image");
  const imgStatus = document.getElementById("img-status");
  const imgOutput = document.getElementById("img-output");
  const imgOutputTag = document.getElementById("img-output-tag");
  const imgRefInput = document.getElementById("img-ref");
  const imgRefPreview = document.getElementById("img-ref-preview");
  const imgRefThumb = document.getElementById("img-ref-thumb");
  const imgModel = document.getElementById("img-model");
  let lastBlob = null;

  imgRefInput.addEventListener("change", () => {
    const f = imgRefInput.files[0];
    if (!f) { imgRefPreview.style.display = "none"; return; }
    imgRefThumb.src = URL.createObjectURL(f);
    imgRefPreview.style.display = "block";
    // If model is dall-e-3 (no ref support) and a ref is provided, hint switch.
    if (imgModel.value === "dall-e-3") {
      imgModel.value = "gpt-image-1";
    }
  });

  document.getElementById("btn-image").addEventListener("click", async () => {
    imgStatus.textContent = "Generating image (can take 20-60s)…";
    imgOutput.style.display = "none";
    const r = await fetch("/generate-image", { method: "POST", body: new FormData(imageForm) });
    if (!r.ok) {
      const data = await r.json().catch(() => null);
      imgStatus.textContent = "Error: " + (data ? data.detail : r.statusText);
      return;
    }
    lastBlob = await r.blob();
    imgOutputTag.src = URL.createObjectURL(lastBlob);
    imgOutput.style.display = "block";
    imgStatus.textContent = `Generated (${(lastBlob.size / 1024).toFixed(0)} KB).`;
  });

  document.getElementById("btn-img-download").addEventListener("click", () => {
    if (!lastBlob) return;
    const fname = imageForm.elements.filename.value || "image.png";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(lastBlob);
    a.download = fname; a.click();
  });

  document.getElementById("btn-img-use-as-ref").addEventListener("click", () => {
    if (!lastBlob) return;
    const file = new File([lastBlob], "previous.png", { type: "image/png" });
    const dt = new DataTransfer();
    dt.items.add(file);
    imgRefInput.files = dt.files;
    imgRefInput.dispatchEvent(new Event("change"));
    imgStatus.textContent = "Loaded previous output as reference. Edit the prompt and regenerate.";
  });

  // Tiny inline markdown renderer (h2, h3, bold, em, code, lists, paragraphs).
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

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        opts = "\n".join(f"<option>{name}</option>" for name in list_engines())
        return INDEX_HTML.replace("__ENGINE_OPTIONS__", opts)

    @app.post("/update")
    def update_endpoint() -> JSONResponse:
        """Run `git pull --ff-only` in the repo, return summary.

        With the server launched as ``epubconv serve --reload``, file changes
        from the pull trigger an automatic restart, so the user never has to
        touch the terminal. If the repo isn't a git checkout (e.g. installed
        from a wheel), we surface a 400 with a clear error.
        """
        if not (repo_root / ".git").exists():
            raise HTTPException(status_code=400, detail=f"{repo_root} is not a git working tree")
        rc, out, err = _git("pull", "--ff-only", cwd=repo_root)
        if rc != 0:
            raise HTTPException(status_code=500, detail=err or out or "git pull failed")
        rc2, head, _ = _git("rev-parse", "HEAD", cwd=repo_root)
        # Count files changed in the pull, if any.
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

    @app.post("/generate-image")
    async def generate_image_endpoint(
        prompt: str = Form(...),
        model: str = Form("dall-e-3"),
        size: str = Form("1024x1024"),
        quality: str = Form("standard"),
        reference: UploadFile | None = File(None),
    ) -> Response:
        api_key = os.environ.get("BANANA2556_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="BANANA2556_API_KEY env var not set")

        try:
            if reference is not None and reference.filename:
                ref_bytes = await reference.read()
                if not ref_bytes:
                    raise ValueError("empty reference image")
                png = edit_image(
                    prompt=prompt,
                    reference_image=ref_bytes,
                    reference_filename=reference.filename or "reference.png",
                    api_key=api_key,
                    model=model,
                    size=size,
                )
            else:
                png = generate_image(
                    prompt=prompt,
                    api_key=api_key,
                    model=model,
                    size=size,
                    quality=quality,
                )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        return Response(content=png, media_type="image/png")

    return app


app = create_app()
