"""FastAPI server for browser-based EPUB conversion + diff preview.

Runs locally; no auth, no persistence. Drag an EPUB into the page, pick the
target variant, get back the converted file or a diff report. Uploads are
held in a temp dir for the lifetime of the request.

Optional dependency: install with ``pip install epubconv[web]``.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "fastapi is required. Install with: pip install epubconv[web]"
    ) from exc

from ..converters.writing_mode import WRITING_MODES
from ..diff import build_diff_report
from ..engines.registry import get_engine, list_engines
from ..pipeline import convert_epub

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
</body>
</html>
"""


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
