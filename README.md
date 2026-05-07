# epubconv

Convert EPUB books between Chinese variants (zh-CN ↔ zh-TW ↔ zh-HK ↔ zh-Hant ↔ zh-Hans).

OpenCC under the hood, plus a stack of opt-in features for things OpenCC alone won't do: protect/override term lists, quote-mark conversion, vertical writing mode, MOBI output, batch conversion with resume, an LLM fallback for ambiguous characters, a side-by-side diff preview, and a tiny web UI.

```
zh-CN: 软件更新与原力
zh-TW: 軟體更新與原力        ← OpenCC default
zh-HK: 軟件更新與原力        ← with --series sw glossary forcing 軟件
```

---

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/bu56co-del/epub-chinese-convert
cd epub-chinese-convert

python3 -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate

pip install -e .                  # core only
pip install -e ".[web]"           # + web UI
pip install -e ".[llm]"           # + LLM fallback
pip install -e ".[web,llm,dev]"   # everything + tests
```

---

## CLI

### Convert one book

```bash
epubconv convert book.epub --from zh-CN --to zh-TW
# default output: book.zh-TW.epub
```

Options worth knowing:

| Flag | Effect |
|---|---|
| `-f / --from` | Source language (`zh-CN`, `zh-Hans`, `zh-TW`, `zh-Hant`, `zh-HK`) |
| `-t / --to` | Target language (same set) |
| `-g / --glossary <path>` | YAML rules for protect / pre / post replacements |
| `-s / --series <name>` | Named series glossary (see below) |
| `--punctuation / --no-punctuation` | `""''` ↔ 「」『』 (default: on) |
| `-w / --writing-mode` | `preserve` (default) / `horizontal` / `vertical` |
| `-F / --format` | `epub` (default) or `mobi` (needs Calibre `ebook-convert`) |
| `--llm <provider>` | `gemini` or `banana2556` — only invoked for ambiguous characters |
| `-v / --verbose` | Show pipeline step logs |

### Diff preview (no output EPUB)

```bash
epubconv diff book.epub --from zh-CN --to zh-TW -o report.html
open report.html
```

### Batch + resume

```bash
epubconv batch ./my-books ./out --to zh-TW
# resume after a crash: same command again, "done" files are skipped
```

State lives in `out/.epubconv-batch.json`. Pass `--no-resume` to force re-conversion.

### Suggest proper-noun candidates

Heuristic name extraction so you don't have to scan a whole book by hand:

```bash
epubconv extract-names book.epub -o names.yaml
# review and prune names.yaml, then:
epubconv convert book.epub --glossary names.yaml
```

### Web UI

```bash
pip install -e ".[web]"
epubconv serve
# open http://127.0.0.1:8000
```

Drag-drop EPUB, pick variant, get back the converted file or a diff report.

---

## Glossary YAML

Three sections, all optional:

```yaml
# Tokens passed through unchanged. Engine sees a placeholder.
protect:
  - 哈利波特
  - 鄧不利多

# search → replace, applied to the source text *before* the engine.
# Useful for fixing typos in the source.
pre:
  哈利伯特: 哈利波特

# search → replace, applied *after* the engine. Useful for overriding the
# engine's choice — for example forcing HK terminology over the TW default.
post:
  軟體: 軟件
```

`pre`/`post` also accept an ordered-list form if you need guaranteed order across YAML libraries:

```yaml
post:
  - 軟體: 軟件
  - 紐約: 紐約
```

### Series glossaries (cross-book)

Save shared term lists once and reuse across a whole series:

```bash
mkdir -p ~/.config/epubconv/series
$EDITOR ~/.config/epubconv/series/harry-potter.yaml
```

Then any conversion can pick it up:

```bash
epubconv convert book1.epub --series harry-potter
epubconv convert book2.epub --series harry-potter --glossary book2-extras.yaml
```

When both `--series` and `--glossary` are given the series rules apply first; the per-book glossary then runs on top and can override.

```bash
epubconv series list           # show all known series
epubconv series path <name>    # print resolved YAML path
```

The directory is overridable with `EPUBCONV_CONFIG_DIR`.

---

## LLM fallback

OpenCC sometimes picks the wrong glyph for context-dependent characters (`后/发/只/表/干/里/面/...`). Turning on `--llm` routes only the snippets that contain those characters to a chat-completions API; everything else stays on OpenCC. Results are cached on disk by `sha256(text) | target_lang | model`, so repeat runs are free.

Both supported providers expose an OpenAI-compatible endpoint:

```bash
# Direct Gemini
export GEMINI_API_KEY=...
epubconv convert book.epub --llm gemini

# banana2556 aggregator (can route to GPT, Claude, Gemini, ...)
export BANANA2556_API_KEY=sk-...
epubconv convert book.epub --llm banana2556 --llm-model claude-3-5-sonnet-20241022
```

| Provider | Default model | Env var |
|---|---|---|
| `gemini` | `gemini-1.5-pro` | `GEMINI_API_KEY` |
| `banana2556` | `gpt-4o-mini` | `BANANA2556_API_KEY` |

`--llm-cache <path>` overrides the default `~/.cache/epubconv/llm.json`.

---

## GitHub Action

Use this repo as an action in any workflow:

```yaml
- uses: bu56co-del/epub-chinese-convert@v1   # or a commit SHA
  with:
    src: book.epub
    dst: book.zh-TW.epub
    to: zh-TW
    series: harry-potter
    llm: banana2556
  env:
    BANANA2556_API_KEY: ${{ secrets.BANANA2556_API_KEY }}
```

`src` accepts either an EPUB or a directory; the action picks `convert` or `batch` accordingly.

`.github/workflows/convert-release-epubs.yml` in this repo is a worked example: when a release is published, every attached EPUB is converted to zh-TW and zh-HK and uploaded back to the release.

---

## Pluggable engines

Third parties can register new engines under the `epubconv.engines` entry-point group:

```toml
# my-plugin's pyproject.toml
[project.entry-points."epubconv.engines"]
fanhuaji = "myplugin.fanhuaji:make_engine"
```

Factory signature: `(source: str, target: str, **kwargs) -> Engine`.

Once installed alongside epubconv, the plugin is automatically picked up:

```bash
epubconv list-engines
epubconv convert book.epub --engine fanhuaji
```

The base `Engine` class lives in `epubconv.engines.base` and only requires implementing `convert(text: str) -> str`.

---

## What this won't do (yet)

- **Fixed-layout EPUBs** (manga, picture books) — not tested
- **Embedded font subsetting** — fonts pass through untouched, which means a zh-Hans font may render zh-Hant output with missing glyphs depending on the reader
- **Page-list (`<pageList>`) round-trip** — internal anchors should survive but this isn't validated end-to-end
- **`epubcheck` integration** — output isn't auto-validated against the EPUB spec

A real-EPUB testing pass is the obvious next thing if you depend on any of the above.

---

## Development

```bash
pip install -e ".[dev,llm,web]"
pytest                            # 90 tests
```

CI runs the suite on Python 3.10 / 3.11 / 3.12 (`.github/workflows/ci.yml`).

---

## License

Apache-2.0.
