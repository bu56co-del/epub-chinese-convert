"""FastAPI server for browser-based EPUB conversion + skill export + summary.

Runs locally; no auth, no persistence. Designed to be opened by
double-clicking ``launch.command`` (which runs ``epubconv serve --reload``).

Tabs: Convert / Diff / Skill / Summary / Settings. A header "Update &
Relaunch" button runs ``git pull`` + ``pip install`` and triggers the
``--reload`` watcher to restart the server with the new code; the
browser tab refreshes itself on completion.

Optional dependency: install with ``pip install epubconv[web]``.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "fastapi is required. Install with: pip install epubconv[web]"
    ) from exc

from loguru import logger

from ..converters.writing_mode import WRITING_MODES
from ..diff import build_diff_report
from ..engines.registry import get_engine, list_engines
from ..llm.client import PROVIDERS, provider_base_url
from ..pipeline import convert_epub
from ..skill.exporter import export_skill
from ..summarize import SummaryCancelled, SummaryError, summarise_epub

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
  progress { -webkit-appearance: none; appearance: none; border: 0; }
  progress::-webkit-progress-bar { background: var(--bg); border-radius: 4px; }
  progress::-webkit-progress-value { background: var(--accent); border-radius: 4px; transition: width 0.2s; }
  progress::-moz-progress-bar { background: var(--accent); border-radius: 4px; }
  .summary-header { margin-top: 1.5em; padding-bottom: 0.5em; border-bottom: 1px solid var(--border); }
  .summary-header h2 { margin: 0; color: var(--text-strong); }
  .summary-header .creator { color: var(--text-muted); font-size: 0.9em; margin-top: 0.25em; }
  .print-only { display: none; }
  @media print {
    /* Hide everything except the print container, then unhide it. */
    body > * { display: none !important; }
    body > #print-container { display: block !important; }
    #print-container { color: #000; background: #fff; padding: 0; max-width: 100%; }
    #print-container h1, #print-container h2, #print-container h3 { color: #000; }
    #print-container .creator { color: #555; font-size: 0.95em; margin-bottom: 1em; }
    #print-container .summary-md { background: transparent; border: 0; padding: 0; }
    #print-container code { background: #f0f0f0; }
  }
</style>
</head>
<body>
<header>
  <h1>epubconv</h1>
  <div>
    <button id="btn-update" class="secondary">↻ Update &amp; Relaunch</button>
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
    The API key from the <strong>⚙ Settings</strong> tab (browser localStorage) is sent
    along with each request.</p>
  <label>EPUB <input type="file" name="file" accept=".epub" required></label>
  <div class="row">
    <label>Provider <select name="provider">
      <option value="banana2556">banana2556</option>
      <option value="gemini">gemini</option>
    </select></label>
    <label>Model <input type="text" name="model" value="claude-haiku-4.5-as" placeholder="claude-haiku-4.5-as / gpt-5 / claude-3-5-sonnet-20241022 / gemini-1.5-pro"></label>
  </div>
  <div class="row">
    <label>Max source chars <input type="number" name="max_chars" value="800000" min="2000" max="2000000"></label>
    <label>Per-call budget (chars)
      <input type="number" name="per_call_budget" value="20000" min="2000" max="200000">
    </label>
  </div>
  <p class="muted">Long books are split into batches of <em>per-call budget</em> chars, summarised
    separately, then merged. Lower the budget if you see "Single message too long" / "Input too long"
    upstream errors; raise it on long-context models to use fewer calls.</p>
  <div class="row">
    <button type="button" id="btn-summary">Generate summary</button>
    <button type="button" id="btn-summary-cancel" class="secondary" style="display:none">Cancel</button>
  </div>
  <div id="summary-progress" style="display:none">
    <progress id="summary-bar" value="0" max="100" style="width:100%; height:0.6em"></progress>
    <div id="summary-progress-text" class="muted" style="font-family:monospace; font-size:0.85em"></div>
  </div>
  <div id="summary-status" class="muted"></div>
  <div id="summary-header" class="summary-header" style="display:none">
    <h2 id="summary-title"></h2>
    <div id="summary-creator" class="creator"></div>
    <div style="margin-top:0.5em">
      <button type="button" id="btn-summary-pdf" class="secondary">📄 Download PDF</button>
    </div>
  </div>
  <div id="summary-out" class="summary-md" style="display:none"></div>
</form>
</section>

<!-- Hidden container shown only during print; populated by the PDF button. -->
<div id="print-container" class="print-only">
  <h1 id="print-title"></h1>
  <div id="print-creator" class="creator"></div>
  <div id="print-summary" class="summary-md"></div>
</div>

<section id="t-settings" class="panel">
<form id="f-settings">
  <h3>API keys</h3>
  <p class="muted">Saved in <strong>your browser's localStorage</strong> only —
    never written to the server's filesystem. Sent with each request that
    needs an LLM. A shell-exported env var on the server takes precedence
    if you also have one set there.</p>

  <label>BANANA2556_API_KEY
    <span class="key-status muted" id="status-banana2556">…</span>
    <input type="password" name="BANANA2556_API_KEY" placeholder="sk-...">
  </label>

  <label>GEMINI_API_KEY
    <span class="key-status muted" id="status-gemini">…</span>
    <input type="password" name="GEMINI_API_KEY" placeholder="AIza...">
  </label>

  <div class="row">
    <button type="button" id="btn-settings-save">Save to browser</button>
    <button type="button" id="btn-settings-clear" class="secondary">Clear stored keys</button>
  </div>
  <button type="button" id="btn-settings-test" class="secondary">Test connection</button>
  <pre id="settings-status" class="muted result" style="display:none"></pre>
</form>
</section>

<script>
(function() {
  // -------- Local API-key storage --------
  const KEY_NAMES = ["BANANA2556_API_KEY", "GEMINI_API_KEY"];
  function getKey(name) { return localStorage.getItem("epubconv:" + name) || ""; }
  function setKey(name, value) {
    if (value) localStorage.setItem("epubconv:" + name, value);
    else localStorage.removeItem("epubconv:" + name);
  }

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

  // -------- Update & Relaunch --------
  const updateBtn = document.getElementById("btn-update");
  const updateStatus = document.getElementById("update-status");

  async function waitForServerBack(timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const r = await fetch("/", { cache: "no-store" });
        if (r.ok) return true;
      } catch (e) { /* server still restarting */ }
      await new Promise(res => setTimeout(res, 500));
    }
    return false;
  }

  updateBtn.addEventListener("click", async () => {
    updateBtn.disabled = true;
    updateStatus.textContent = "Pulling…";
    let data;
    try {
      const r = await fetch("/update", { method: "POST" });
      data = await r.json();
      if (!r.ok) {
        updateStatus.textContent = "Error: " + (data.detail || r.statusText);
        updateBtn.disabled = false;
        return;
      }
    } catch (e) {
      updateStatus.textContent = "Error: " + e;
      updateBtn.disabled = false;
      return;
    }

    if (!data.changed) {
      updateStatus.textContent = "Already up to date.";
      updateBtn.disabled = false;
      return;
    }

    updateStatus.textContent =
      `Pulled ${data.head.slice(0,7)} (${data.files} files, pip: ${data.pip}). ` +
      `Restarting server…`;
    // Give uvicorn time to notice the file change and start the new process.
    await new Promise(res => setTimeout(res, 1500));
    const back = await waitForServerBack(20000);
    if (back) {
      updateStatus.textContent = "Reloading browser…";
      location.reload();
    } else {
      updateStatus.textContent =
        "Server didn't come back in 20s — check the terminal and refresh manually.";
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

  // -------- Summary (detached background task with reconnect) --------
  const summaryForm = document.getElementById("f-summary");
  const summaryStatus = document.getElementById("summary-status");
  const summaryOut = document.getElementById("summary-out");
  const summaryProgress = document.getElementById("summary-progress");
  const summaryBar = document.getElementById("summary-bar");
  const summaryProgressText = document.getElementById("summary-progress-text");
  const cancelBtn = document.getElementById("btn-summary-cancel");
  const summaryHeader = document.getElementById("summary-header");
  const summaryTitle = document.getElementById("summary-title");
  const summaryCreator = document.getElementById("summary-creator");
  const pdfBtn = document.getElementById("btn-summary-pdf");
  let currentTitle = "";
  let currentCreator = "";

  pdfBtn.addEventListener("click", () => {
    // Populate the print container with the current summary, then trigger
    // the browser's print dialog so the user can pick "Save as PDF".
    document.getElementById("print-title").textContent =
      currentTitle || "Book summary";
    document.getElementById("print-creator").textContent =
      currentCreator ? `作者：${currentCreator}` : "";
    document.getElementById("print-summary").innerHTML = summaryOut.innerHTML;
    window.print();
  });

  cancelBtn.addEventListener("click", async () => {
    if (!confirm("Cancel the current summarisation? Cached batches will be preserved, so you can resume by clicking Generate summary again.")) return;
    cancelBtn.disabled = true;
    cancelBtn.textContent = "Cancelling…";
    try {
      await fetch("/summarize-cancel", { method: "POST" });
    } catch (e) {
      summaryStatus.textContent = "Cancel request failed: " + e;
    }
  });

  function fmt(n) { return n.toLocaleString(); }

  function handleSummaryEvent(ev) {
    const total = ev.chars_total || 0;
    const done = ev.chars_processed || 0;
    const pct = total > 0 ? Math.min(99, Math.round((done * 100) / total)) : 0;

    if (ev.stage === "extracting") {
      summaryProgressText.textContent = "Reading EPUB…";
    } else if (ev.stage === "extracted") {
      if (ev.title) currentTitle = ev.title;
      if (ev.creator) currentCreator = ev.creator;
      const titleLabel = ev.title
        ? `《${ev.title}》${ev.creator ? "（" + ev.creator + "）" : ""} — `
        : "";
      summaryProgressText.textContent =
        `${titleLabel}Found ${ev.chapters} chapters, ${fmt(total)} chars to process.`;
    } else if (ev.stage === "batch_start") {
      summaryBar.value = pct;
      summaryProgressText.textContent =
        `Batch ${ev.batch_no} (budget ${fmt(ev.budget)} chars, sending ${fmt(ev.batch_chars)})… ${pct}%`;
    } else if (ev.stage === "batch_done") {
      summaryBar.value = pct;
      const sec = (ev.elapsed_ms / 1000).toFixed(1);
      summaryProgressText.textContent =
        `Batch ${ev.batch_no} ok (${sec}s) — ${fmt(done)}/${fmt(total)} (${pct}%)`;
    } else if (ev.stage === "halve") {
      summaryProgressText.textContent =
        `Upstream "too long" — halving budget ${fmt(ev.old_budget)}→${fmt(ev.new_budget)} and retrying…`;
    } else if (ev.stage === "combine_start") {
      summaryBar.value = 99;
      summaryProgressText.textContent =
        `All batches done. Combining ${fmt(ev.notes_chars)} chars of notes into final summary…`;
    } else if (ev.stage === "combine_split") {
      const groups = ev.groups_out;
      const groupsLabel = groups ? ` into ${groups} groups` : "";
      const budgetLabel = ev.budget ? ` (group budget ${fmt(ev.budget)} chars)` : "";
      summaryProgressText.textContent =
        `Combine round ${ev.depth + 1}: ${ev.notes_in} notes (${fmt(ev.notes_chars)} chars) ` +
        `won't fit in one call — packing${groupsLabel}${budgetLabel}…`;
    } else if (ev.stage === "combine_done") {
      summaryBar.value = 100;
    } else if (ev.stage === "done") {
      summaryBar.value = 100;
      summaryStatus.textContent =
        `Summarised ${ev.chapters_used} chapters (${fmt(ev.chars_used)} chars).`;
      if (ev.title) currentTitle = ev.title;
      if (ev.creator) currentCreator = ev.creator;
      if (currentTitle) {
        summaryTitle.textContent = `《${currentTitle}》`;
        summaryCreator.textContent = currentCreator ? `作者：${currentCreator}` : "";
        summaryHeader.style.display = "block";
      } else {
        summaryHeader.style.display = "none";
      }
      summaryOut.style.display = "block";
      summaryOut.innerHTML = simpleMarkdown(ev.text);
      cancelBtn.style.display = "none";
    } else if (ev.stage === "cancelled") {
      summaryStatus.textContent =
        "Cancelled. " + (ev.note || "") + " Click Generate summary again to resume.";
      cancelBtn.style.display = "none";
    } else if (ev.stage === "error") {
      let msg = "Error: " + ev.detail;
      if (typeof ev.detail === "string") {
        if (ev.detail.includes("API key")) {
          msg += " — open the Settings tab and paste your key.";
        } else if (/too long|context|max_tokens/i.test(ev.detail)) {
          msg += " — try lowering Per-call budget (e.g. halve it) and resubmit.";
        }
      }
      summaryStatus.textContent = msg;
    }
  }

  async function attachSummaryStream() {
    summaryProgress.style.display = "block";
    let reconnectDelay = 1000;
    while (true) {
      let r;
      try {
        r = await fetch("/summarize-stream", { cache: "no-store" });
      } catch (e) {
        // Network error — back off and retry.
        summaryProgressText.textContent =
          `Disconnected (${e}). Reconnecting in ${reconnectDelay/1000}s…`;
        await new Promise(res => setTimeout(res, reconnectDelay));
        reconnectDelay = Math.min(reconnectDelay * 2, 8000);
        continue;
      }
      if (!r.ok) {
        summaryStatus.textContent = "Stream error: HTTP " + r.status;
        return;
      }
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let terminalSeen = false;
      while (true) {
        let chunk;
        try {
          chunk = await reader.read();
        } catch (e) {
          // Reader broke mid-stream — reconnect.
          summaryProgressText.textContent =
            `Stream dropped (${e}). Reconnecting…`;
          break;
        }
        if (chunk.done) break;
        buf += decoder.decode(chunk.value, { stream: true });
        let parts = buf.split("\\n\\n");
        buf = parts.pop();
        for (const part of parts) {
          const line = part.trim();
          if (!line || line.startsWith(":")) continue;  // keepalive
          if (!line.startsWith("data:")) continue;
          try {
            const ev = JSON.parse(line.slice(5).trim());
            handleSummaryEvent(ev);
            if (ev.stage === "done" || ev.stage === "error") {
              terminalSeen = true;
            }
          } catch (e) {
            console.warn("bad SSE event:", line, e);
          }
        }
      }
      if (terminalSeen) return;
      // Otherwise: reconnect to pick up where we left off.
      reconnectDelay = 1000;
    }
  }

  document.getElementById("btn-summary").addEventListener("click", async () => {
    summaryStatus.textContent = "";
    summaryOut.style.display = "none";
    summaryHeader.style.display = "none";
    currentTitle = "";
    currentCreator = "";
    summaryProgress.style.display = "block";
    summaryBar.value = 0;
    summaryProgressText.textContent = "Starting…";
    cancelBtn.disabled = false;
    cancelBtn.textContent = "Cancel";
    cancelBtn.style.display = "inline-block";

    const fd = new FormData(summaryForm);
    const provider = fd.get("provider");
    const keyName = provider === "gemini" ? "GEMINI_API_KEY" : "BANANA2556_API_KEY";
    const stored = getKey(keyName);
    if (stored) fd.set("api_key", stored);

    let r;
    try {
      r = await fetch("/summarize", { method: "POST", body: fd });
    } catch (e) {
      summaryStatus.textContent = "Network error: " + e;
      summaryProgress.style.display = "none";
      return;
    }
    if (r.status === 409) {
      // A run is already going — just attach.
      summaryProgressText.textContent =
        "A summarisation is already running — attaching to its stream…";
      attachSummaryStream();
      return;
    }
    if (!r.ok) {
      const text = await r.text();
      summaryStatus.textContent = "Error " + r.status + ": " + text.slice(0, 240);
      summaryProgress.style.display = "none";
      return;
    }
    attachSummaryStream();
  });

  // On page load, peek at server status — if a run is in progress (or
  // just finished and we never saw the result), auto-attach to replay.
  (async () => {
    try {
      const r = await fetch("/summarize-status", { cache: "no-store" });
      if (!r.ok) return;
      const s = await r.json();
      if (s.active || s.has_result) {
        summaryProgressText.textContent = s.active
          ? "Reattaching to in-progress summarisation…"
          : "Replaying the last summarisation…";
        summaryProgress.style.display = "block";
        if (s.active) {
          cancelBtn.disabled = false;
          cancelBtn.textContent = "Cancel";
          cancelBtn.style.display = "inline-block";
        }
        attachSummaryStream();
      }
    } catch (e) { /* offline; nothing to do */ }
  })();

  // -------- Settings (localStorage only) --------
  const settingsForm = document.getElementById("f-settings");
  const settingsStatus = document.getElementById("settings-status");

  function refreshSettings() {
    for (const name of KEY_NAMES) {
      const value = getKey(name);
      const span = document.getElementById(
        "status-" + name.toLowerCase().replace(/_api_key$/, "")
      );
      if (!span) continue;
      span.classList.remove("ok", "missing");
      if (value) {
        span.classList.add("ok");
        span.textContent = `set (••••${value.slice(-4)})`;
      } else {
        span.classList.add("missing");
        span.textContent = "not set";
      }
    }
  }

  document.getElementById("btn-settings-save").addEventListener("click", () => {
    const fd = new FormData(settingsForm);
    let saved = 0;
    for (const name of KEY_NAMES) {
      const value = (fd.get(name) || "").toString().trim();
      // Empty input leaves the existing value alone (use Clear to remove).
      if (value) { setKey(name, value); saved++; }
    }
    for (const inp of settingsForm.querySelectorAll("input[type=password]")) inp.value = "";
    showSettings(saved
      ? `Saved ${saved} key${saved === 1 ? "" : "s"} to browser localStorage.`
      : "Nothing to save (inputs were empty).");
    refreshSettings();
  });

  document.getElementById("btn-settings-clear").addEventListener("click", () => {
    if (!confirm("Remove all saved API keys from this browser?")) return;
    for (const name of KEY_NAMES) setKey(name, "");
    for (const inp of settingsForm.querySelectorAll("input[type=password]")) inp.value = "";
    showSettings("Cleared.");
    refreshSettings();
  });

  document.getElementById("btn-settings-test").addEventListener("click", async () => {
    showSettings("Testing…");
    const lines = [];
    for (const name of KEY_NAMES) {
      const provider = name === "GEMINI_API_KEY" ? "gemini" : "banana2556";
      const key = getKey(name);
      if (!key) { lines.push(`${provider}: no key saved — skip`); continue; }
      const fd = new FormData();
      fd.append("provider", provider);
      fd.append("api_key", key);
      try {
        const r = await fetch("/test-key", { method: "POST", body: fd });
        const d = await r.json();
        if (d.ok) {
          lines.push(`${provider}: ✓ ${d.message}`);
        } else {
          lines.push(`${provider}: ✗ HTTP ${d.status} — ${d.message.slice(0, 240)}`);
        }
      } catch (e) {
        lines.push(`${provider}: ✗ network error: ${e}`);
      }
    }
    showSettings(lines.join("\\n"));
  });

  function showSettings(text) {
    settingsStatus.style.display = "block";
    settingsStatus.textContent = text;
  }

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


def _check_key(provider: str, api_key: str, *, timeout: float = 15.0) -> dict:
    """Hit GET <base_url>/models with the given key. Returns a dict that the
    /test-key endpoint can JSON-encode."""
    base = provider_base_url(provider).rstrip("/")
    url = f"{base}/models"
    req = Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "epubconv/test-key",
            "Accept": "application/json",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            payload = json.loads(raw.decode("utf-8"))
            models = payload.get("data") or payload.get("models") or []
            return {
                "ok": True,
                "status": resp.status,
                "model_count": len(models) if isinstance(models, list) else 0,
                "message": f"OK — {len(models) if isinstance(models, list) else '?'} models available",
            }
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return {"ok": False, "status": e.code, "model_count": 0, "message": body}
    except (URLError, OSError, json.JSONDecodeError) as e:
        return {"ok": False, "status": 0, "model_count": 0, "message": f"{type(e).__name__}: {e}"}


def _refresh_dependencies(repo_root: Path) -> str:
    """Run ``pip install -e .[web,llm]`` quietly. Idempotent; ~1-2s when
    nothing changed. Returns a short log line for the response."""
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-e", f"{repo_root}[web,llm]"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode == 0:
        return "ok"
    # Don't fail the whole update on pip errors — surface the message but
    # let the user see the new code is live.
    return f"pip exited {proc.returncode}: {proc.stderr.strip()[:200]}"


def create_app() -> FastAPI:
    app = FastAPI(title="epubconv", docs_url=None, redoc_url=None)
    repo_root = Path(__file__).resolve().parents[3]

    # On every server start, log the git HEAD so the user can confirm
    # they're actually running the version they just pulled — diagnoses
    # "I updated but it's still broken" reports in seconds.
    try:
        rc, head, _ = _git("rev-parse", "--short", "HEAD", cwd=repo_root)
        head_label = head if rc == 0 else "unknown"
    except Exception:
        head_label = "no-git"
    logger.info(f"epubconv server starting on git HEAD = {head_label}")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        opts = "\n".join(f"<option>{name}</option>" for name in list_engines())
        return INDEX_HTML.replace("__ENGINE_OPTIONS__", opts)

    @app.post("/update")
    def update_endpoint() -> JSONResponse:
        """Pull latest code, refresh deps, and trigger a reload.

        With ``epubconv serve --reload`` (which ``launch.command`` always
        uses), uvicorn watches the source tree and restarts on file
        changes. The browser polls / and refreshes itself when it comes
        back. We also re-run ``pip install -e ".[web,llm]"`` so a pull
        that adds an optional dep doesn't leave the server importing a
        missing package on next request.
        """
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

        pip_log = ""
        if changed:
            pip_log = _refresh_dependencies(repo_root)

        # Touching a watched file forces uvicorn's reloader to restart even
        # if the pull only changed templates / static assets it doesn't
        # naturally watch. (When code under src/epubconv/ changed, this is
        # redundant but harmless.)
        if changed:
            (repo_root / "src" / "epubconv" / "__init__.py").touch()

        return JSONResponse({
            "changed": changed,
            "head": head if rc2 == 0 else "",
            "files": files,
            "stdout": out,
            "pip": pip_log,
        })

    @app.post("/test-key")
    async def test_key_endpoint(
        provider: str = Form("banana2556"),
        api_key: str = Form(...),
    ) -> JSONResponse:
        """Hit ``GET <base_url>/models`` with the given key as a quick
        health probe. The Settings tab calls this to give immediate
        ✓ / ✗ feedback so the user doesn't have to launch a Summary to
        find out the key is bad."""
        if provider not in PROVIDERS:
            raise HTTPException(status_code=400, detail=f"unknown provider: {provider}")
        if not api_key.strip():
            raise HTTPException(status_code=400, detail="api_key is required")
        result = _check_key(provider, api_key.strip())
        return JSONResponse(result)

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

    # --- detached summarisation task ----------------------------------
    # Only one run at a time. Survives browser disconnects so users can
    # close the tab / refresh and reconnect without losing progress.
    summary_run: dict[str, object] = {
        "active": False,
        "events": [],            # list of dicts emitted so far (replay buffer)
        "subscribers": [],       # list of (asyncio.Queue, asyncio.AbstractEventLoop)
        "started_at": 0.0,
        "cancel_event": None,    # threading.Event for the current run, or None
    }

    def _emit_summary_event(event: dict) -> None:
        """Called from the worker thread; bridges into each subscriber's loop."""
        summary_run["events"].append(event)
        for q, loop in list(summary_run["subscribers"]):
            try:
                asyncio.run_coroutine_threadsafe(q.put(event), loop)
            except RuntimeError:
                pass  # loop closed; subscriber will be cleaned up on its end

    def _summary_worker(src: Path, **kwargs) -> None:
        try:
            def progress(stage: str, data) -> None:
                _emit_summary_event({"stage": stage, **dict(data)})
            result = summarise_epub(src, progress=progress, **kwargs)
            _emit_summary_event({
                "stage": "done",
                "text": result.text,
                "chars_used": result.chars_used,
                "chapters_used": result.chapters_used,
                "title": result.title,
                "creator": result.creator,
            })
        except SummaryCancelled as exc:
            logger.info("summarize task: cancelled — {exc}", exc=exc)
            _emit_summary_event({
                "stage": "cancelled",
                "message": str(exc),
                "note": "Cached batches and sub-summaries preserved. "
                        "Re-click Generate summary to resume from where you stopped.",
            })
        except ValueError as exc:
            logger.warning("summarize task: 400 {exc}", exc=exc)
            _emit_summary_event({"stage": "error", "status": 400, "detail": str(exc)})
        except SummaryError as exc:
            logger.error("summarize task: 502 {exc}", exc=exc)
            _emit_summary_event({"stage": "error", "status": 502, "detail": str(exc)})
        except Exception as exc:
            logger.exception("summarize task: unexpected error")
            _emit_summary_event({"stage": "error", "status": 500, "detail": f"{type(exc).__name__}: {exc}"})
        finally:
            summary_run["active"] = False

    @app.post("/summarize")
    async def summarize_endpoint(
        file: UploadFile = File(...),
        provider: str = Form("banana2556"),
        model: str = Form(""),
        max_chars: int = Form(800_000),
        per_call_budget: int = Form(20_000),
        api_key: str = Form(""),
    ) -> JSONResponse:
        """Start a detached summarisation task and return immediately.

        The browser then opens GET /summarize-stream to receive progress
        events. The run survives browser disconnects, so closing the tab,
        refreshing, or losing network briefly does NOT cancel it — just
        re-attach to /summarize-stream and the buffered events replay.

        If a run is already in flight, returns 409 with a hint to attach
        to the existing stream rather than start a new one.
        """
        if summary_run["active"]:
            raise HTTPException(
                status_code=409,
                detail="A summarisation is already running — attach to /summarize-stream to follow it.",
            )

        upload_name = file.filename or "input.epub"
        tmp_dir = Path(tempfile.mkdtemp(prefix="epubconv-summary-"))
        src = tmp_dir / upload_name
        src.write_bytes(await file.read())
        logger.info(
            "summarize endpoint: file={name} provider={provider} model={model} max_chars={mc} per_call={pb}",
            name=upload_name, provider=provider, model=model or "<default>",
            mc=max_chars, pb=per_call_budget,
        )

        # Reset replay buffer for this new run.
        cancel_event = threading.Event()
        summary_run["active"] = True
        summary_run["events"] = []
        summary_run["subscribers"] = []
        summary_run["started_at"] = __import__("time").time()
        summary_run["cancel_event"] = cancel_event

        threading.Thread(
            target=_summary_worker,
            args=(src,),
            kwargs=dict(
                max_chars=max_chars,
                per_call_budget=per_call_budget,
                provider=provider,
                model=model or None,
                api_key=api_key or None,
                cancel_event=cancel_event,
            ),
            daemon=True,
        ).start()
        return JSONResponse({"started": True, "started_at": summary_run["started_at"]})

    @app.post("/summarize-cancel")
    def summarize_cancel_endpoint() -> JSONResponse:
        """Politely ask the in-flight summarisation to stop.

        The worker only checks the cancel flag *between* LLM calls, so an
        already-in-flight chat-completions request will finish (≤ 30-60s
        typically). Cached results are untouched — re-clicking Generate
        summary picks up exactly where the cancel landed.
        """
        if not summary_run.get("active"):
            return JSONResponse({"cancel_requested": False, "reason": "no active run"})
        event = summary_run.get("cancel_event")
        if event is not None and not event.is_set():
            event.set()
            logger.info("summarize: cancel requested")
        return JSONResponse({"cancel_requested": True})

    @app.get("/summarize-stream")
    async def summarize_stream() -> StreamingResponse:
        """Attach to the in-flight summary task (or the just-finished one).

        Replays every event from the start of the current run, then streams
        new ones as they arrive. Multiple browsers can attach; closing one
        does not cancel the run.
        """
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        subscriber = (queue, loop)
        summary_run["subscribers"].append(subscriber)

        async def stream():
            try:
                # Replay buffered events first.
                replayed_terminal = False
                for ev in list(summary_run["events"]):
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    if ev.get("stage") in ("done", "error"):
                        replayed_terminal = True
                if replayed_terminal:
                    return

                # Stream new events.
                while True:
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        # Keepalive comment so reverse proxies / browsers
                        # don't close the idle connection during slow LLM calls.
                        yield ": keepalive\n\n"
                        if not summary_run["active"]:
                            return
                        continue
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    if ev.get("stage") in ("done", "error"):
                        return
            finally:
                try:
                    summary_run["subscribers"].remove(subscriber)
                except ValueError:
                    pass

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/summarize-status")
    def summarize_status() -> JSONResponse:
        """Lightweight peek for page-load reconnect logic."""
        events = summary_run["events"]
        latest = events[-1] if events else None
        return JSONResponse({
            "active": bool(summary_run["active"]),
            "started_at": summary_run["started_at"],
            "event_count": len(events),
            "latest_stage": latest.get("stage") if latest else None,
            "has_result": any(e.get("stage") == "done" for e in events),
        })

    return app


app = create_app()
