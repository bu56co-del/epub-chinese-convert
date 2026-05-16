# pages/ — Cloudflare Pages landing site

Static landing page + bootstrap installer for [epubconv][repo]. Hosted on
Cloudflare Pages so anyone can install the local-first app with a single
copy-paste, while the actual processing stays on the user's Mac.

## Deploy

1. Sign in at <https://dash.cloudflare.com/> → **Workers & Pages** →
   **Create application** → **Pages** → **Connect to Git**.
2. Pick the `bu56co-del/epub-chinese-convert` repo.
3. Production branch: whichever branch you want to ship (typically
   `claude/ebook-chinese-translator-mcmy8`).
4. Build settings:
   - **Framework preset**: None
   - **Build command**: *(leave blank)*
   - **Build output directory**: `pages`
5. Deploy. You get a `*.pages.dev` URL.
6. Optional: add a custom domain in **Custom domains**.

## Files

| File | Role |
|---|---|
| `index.html` | Landing page (dark theme, vanilla JS). Detects the deployed origin and renders the right `curl` command. |
| `style.css` | Matches the app's web UI palette. |
| `install.sh` | Bash bootstrap: Homebrew check → Python → optional Calibre → clone repo → venv → `pip install -e ".[web,llm]"` → open `launch.command`. Idempotent. |
| `uninstall.sh` | Removes `~/Apps/epubconv`. Pass `--purge` to also wipe `~/.config/epubconv` (cache + saved settings). |
| `_headers` | Forces `text/x-shellscript` on the scripts so `curl … \| bash` is unambiguous. |

## What hits Cloudflare

Only the landing page assets + the install / uninstall script downloads.
Every API call the app makes (banana2556 / Gemini for the Summary tab)
goes **direct from the user's Mac to the provider** — Cloudflare never
sees the LLM traffic.

[repo]: https://github.com/bu56co-del/epub-chinese-convert
