#!/usr/bin/env bash
# epubconv uninstaller.
#
# Removes the cloned repo + venv. Leaves Calibre / Homebrew / Python
# alone (other apps depend on them). Leaves cached LLM responses and
# saved API keys alone too — pass --purge to wipe those.
#
# Usage:
#   curl -fsSL https://<your-project>.pages.dev/uninstall.sh | bash
#   curl -fsSL https://<your-project>.pages.dev/uninstall.sh | bash -s -- --purge

set -euo pipefail

INSTALL_DIR="${EPUBCONV_INSTALL_DIR:-$HOME/Apps/epubconv}"
CACHE_DIR="${EPUBCONV_CONFIG_DIR:-$HOME/.config/epubconv}"
PURGE=false

for arg in "$@"; do
    [[ "$arg" == "--purge" ]] && PURGE=true
done

red()    { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }
green()  { printf '\033[1;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }

if [[ -d "$INSTALL_DIR" ]]; then
    yellow "Removing $INSTALL_DIR…"
    rm -rf "$INSTALL_DIR"
else
    green "No install directory at $INSTALL_DIR — already gone."
fi

if [[ "$PURGE" == "true" ]]; then
    if [[ -d "$CACHE_DIR" ]]; then
        yellow "Purging cache + saved settings at $CACHE_DIR…"
        rm -rf "$CACHE_DIR"
    fi
else
    if [[ -d "$CACHE_DIR" ]]; then
        green "Cache and saved settings preserved at $CACHE_DIR"
        echo  "  (pass --purge to delete them too)"
    fi
fi

green "Done."
