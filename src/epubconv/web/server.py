"""FastAPI server for browser-based EPUB conversion + diff preview.

Runs locally; no auth, no persistence. Drag an EPUB into the page, pick the
target variant, get back the converted file or a diff report. Uploads are
held in a temp dir for the lifetime of the request.

Optional dependency: install with ``pip install epubconv[web]``.
"""
from __future__ import annotations

import shutil
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
from ..skill.exporter import export_skill

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>epubconv</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 640px; margin: 2em auto; padding: 0 1em; }
  h1 { margin-bottom: 0.2em; }
  form { display: grid; gap: 0.75em; padding: 1em; border: 1px solid #ddd; border-radius: 8px; }
  label { display: grid; gap: 0.25em; font-size: 0.9em; }
  input[type=file], select, button { padding: 0.5em; font-size: 1em; }
  button { background: #2563eb; color: white; border: 0; border-radius: 6px; cursor: pointer; }
  button:hover { background: #1d4ed8; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75em; }
  .muted { color: #666; font-size: 0.85em; }
</style>
</head>
<body>
<h1>epubconv</h1>
<p class="muted">Convert an EPUB between Chinese variants, or preview a diff.</p>

<form id="f-convert" enctype="multipart/form-data" action="/convert" method="post">
  <h3>Convert</h3>
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

<br>

<form id="f-diff" enctype="multipart/form-data" action="/diff" method="post">
  <h3>Diff preview</h3>
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

<br>

<form id="f-skill" enctype="multipart/form-data">
  <h3>Export Claude Skill</h3>
  <p class="muted">
    Bundle the book as a Claude Skill folder (SKILL.md + JSONL knowledge base).
    "Download" sends a ZIP; "Install" writes directly to <code>~/.claude/skills/</code>.
  </p>
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
  <pre id="skill-result" class="muted" style="white-space:pre-wrap;display:none"></pre>
</form>

<script>
(function() {
  const form = document.getElementById("f-skill");
  const result = document.getElementById("skill-result");

  function buildFormData() {
    return new FormData(form);
  }

  function showResult(text, isError) {
    result.style.display = "block";
    result.textContent = text;
    result.style.color = isError ? "#b00" : "#070";
  }

  document.getElementById("btn-skill-download").addEventListener("click", async () => {
    showResult("Generating skill...", false);
    const r = await fetch("/export-skill", { method: "POST", body: buildFormData() });
    if (!r.ok) {
      showResult("Error: " + (await r.text()), true);
      return;
    }
    const blob = await r.blob();
    const cd = r.headers.get("content-disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    const fname = m ? m[1] : "skill.zip";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = fname; a.click();
    URL.revokeObjectURL(url);
    showResult("Downloaded " + fname, false);
  });

  document.getElementById("btn-skill-install").addEventListener("click", async () => {
    showResult("Installing to ~/.claude/skills/ ...", false);
    const r = await fetch("/install-skill", { method: "POST", body: buildFormData() });
    const data = await r.json().catch(() => null);
    if (!r.ok) {
      showResult("Error: " + (data ? data.detail : r.statusText), true);
      return;
    }
    showResult(
      "Installed!\nPath: " + data.path + "\nChunks: " + data.chunks +
      "\n\nRestart Claude Code (or open a new session) to pick up the skill.",
      false
    );
  });
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
    """Save the upload, run export_skill, and return (skill_dir, tmp_dir).

    The caller is responsible for any further work (zip / copytree); the
    tmp_dir lives until the response is finished. We deliberately use
    ``mkdtemp`` (not a context manager) because FastAPI streams the
    FileResponse back after this coroutine returns.
    """
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


def create_app() -> FastAPI:
    app = FastAPI(title="epubconv", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        opts = "\n".join(f"<option>{name}</option>" for name in list_engines())
        return INDEX_HTML.replace("__ENGINE_OPTIONS__", opts)

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

    return app


app = create_app()
