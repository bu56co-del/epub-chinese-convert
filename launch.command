#!/usr/bin/env bash
# launch.command — double-click to start the epubconv web UI.
#
# What this does:
#   1. cds into the directory this file lives in.
#   2. Creates .venv on first run.
#   3. Ensures the [web,llm] dependency set is installed every launch
#      (cheap when already up to date; auto-recovers if pyproject grows
#      a new optional dep).
#   4. Opens http://127.0.0.1:8000 in the default browser.
#   5. Runs `epubconv serve --reload` so /update (git pull) hot-reloads.
#
# To enable double-click on macOS:
#   chmod +x launch.command

set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "First run: creating .venv (one-time)..."
  python3 -m venv .venv
fi

source .venv/bin/activate

# Idempotent — pip skips already-satisfied requirements quickly. Logs
# stay quiet on the steady-state path; only print on the rare slow case
# (new dep / fresh venv).
echo "Checking dependencies (this is fast when nothing changed)..."
python -m pip install --upgrade --quiet pip
python -m pip install --quiet -e ".[web,llm]"

(sleep 2 && open http://127.0.0.1:8000) &

exec epubconv serve --reload
