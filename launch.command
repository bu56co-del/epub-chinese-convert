#!/usr/bin/env bash
# launch.command — double-click to start the epubconv web UI.
#
# What this does:
#   1. Sets the working directory to wherever this file lives.
#   2. Activates .venv (or creates one + installs deps the first time).
#   3. Opens http://127.0.0.1:8000 in the default browser.
#   4. Runs `epubconv serve --reload` so /update (git pull) hot-reloads.
#
# To enable double-click on macOS:
#   chmod +x launch.command

set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "First run: creating .venv and installing dependencies (one-time, ~1-2 min)..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -e ".[web,llm]"
else
  source .venv/bin/activate
fi

(sleep 2 && open http://127.0.0.1:8000) &

exec epubconv serve --reload
