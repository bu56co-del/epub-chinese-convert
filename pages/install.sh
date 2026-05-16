#!/usr/bin/env bash
# epubconv installer for macOS (Linux best-effort).
#
# Usage from the landing page:
#   curl -fsSL https://<your-project>.pages.dev/install.sh | bash
#
# What it does:
#   1. Verifies Homebrew + Python 3.10+ on macOS (installs Python via brew if missing).
#   2. Optionally installs Calibre (needed for MOBI / AZW3 conversion).
#   3. Clones epub-chinese-convert into $EPUBCONV_INSTALL_DIR (default ~/Apps/epubconv).
#   4. Creates a venv + installs the [web,llm] extras.
#   5. Opens launch.command so the server starts in a Terminal window and the
#      default browser jumps to http://127.0.0.1:8000.
#
# Re-runnable: a second run updates the checkout to the latest commit and
# refreshes any new dependencies. Cache + API keys (stored in localStorage)
# are untouched.

set -euo pipefail

# ---- configurable ----
REPO_URL="${EPUBCONV_REPO_URL:-https://github.com/bu56co-del/epub-chinese-convert}"
BRANCH="${EPUBCONV_BRANCH:-claude/ebook-chinese-translator-mcmy8}"
INSTALL_DIR="${EPUBCONV_INSTALL_DIR:-$HOME/Apps/epubconv}"

# ---- helpers ----
red()    { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }
green()  { printf '\033[1;32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }
step()   { printf '\033[1;34m▶\033[0m %s\n' "$*"; }

ask_yes_no() {
    # Read from /dev/tty so the prompt works inside `curl | bash`.
    local prompt="$1"
    local default="${2:-N}"
    local reply
    if [[ ! -t 0 ]] && [[ -e /dev/tty ]]; then
        printf '%s ' "$prompt" > /dev/tty
        read -r reply < /dev/tty
    else
        read -rp "$prompt " reply
    fi
    reply="${reply:-$default}"
    [[ "$reply" =~ ^[Yy] ]]
}

# ---- preflight ----
OS="$(uname -s)"
case "$OS" in
    Darwin) green "macOS detected." ;;
    Linux)  yellow "Linux detected — best-effort install (Calibre step is manual)." ;;
    *)      red "Unsupported OS: $OS"; exit 1 ;;
esac

# 1. Homebrew (macOS only)
if [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew >/dev/null 2>&1; then
        yellow "Homebrew is not installed."
        if ask_yes_no "Install Homebrew now (the official one-liner)? [Y/n]" "Y"; then
            step "Running Homebrew's official installer… (takes ~5 min, will ask for your password)"
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            # Pick the right prefix per architecture and bring brew onto PATH
            # for the rest of this script.
            if [[ "$(uname -m)" == "arm64" ]]; then
                BREW_PREFIX="/opt/homebrew"
            else
                BREW_PREFIX="/usr/local"
            fi
            if [[ -x "$BREW_PREFIX/bin/brew" ]]; then
                eval "$($BREW_PREFIX/bin/brew shellenv)"
            fi
            if ! command -v brew >/dev/null 2>&1; then
                red "Homebrew install finished but 'brew' isn't on PATH."
                echo  "Open a new Terminal window and re-run this installer."
                exit 1
            fi
            green "Homebrew is installed."
        else
            red "Aborting — Homebrew is required on macOS."
            echo  "You can install it manually later:"
            echo  '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
            exit 1
        fi
    else
        step "Homebrew is installed."
    fi
fi

# 2. Python 3.10+
need_python_install=false
if command -v python3 >/dev/null 2>&1; then
    PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
    PY_MAJOR="${PY_VER%%.*}"
    PY_MINOR="${PY_VER##*.}"
    if (( PY_MAJOR < 3 )) || { (( PY_MAJOR == 3 )) && (( PY_MINOR < 10 )); }; then
        yellow "Found python3 $PY_VER — need 3.10+."
        need_python_install=true
    else
        step "python3 $PY_VER is installed."
    fi
else
    need_python_install=true
fi

if [[ "$need_python_install" == "true" ]]; then
    if [[ "$OS" == "Darwin" ]]; then
        step "Installing python@3.11 via Homebrew…"
        brew install python@3.11
    else
        red "Install Python 3.10+ manually and re-run."
        exit 1
    fi
fi

# 3. Calibre (optional)
if command -v ebook-convert >/dev/null 2>&1; then
    step "Calibre (ebook-convert) is already installed — MOBI / AZW3 conversion enabled."
else
    yellow "Calibre is not installed."
    echo  "  → Without it, epubconv can still do EPUB ↔ EPUB Chinese-variant conversion."
    echo  "  → With it, you get MOBI / AZW3 input + output (Kindle formats)."
    if [[ "$OS" == "Darwin" ]] && ask_yes_no "Install Calibre now via Homebrew? [y/N]"; then
        step "Installing Calibre cask…"
        brew install --cask calibre
    elif [[ "$OS" == "Linux" ]]; then
        yellow "On Linux, install Calibre manually: https://calibre-ebook.com"
    else
        yellow "Skipping Calibre. You can install it later with: brew install --cask calibre"
    fi
fi

# 4. Clone or update
mkdir -p "$(dirname "$INSTALL_DIR")"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    step "Updating existing checkout at $INSTALL_DIR…"
    git -C "$INSTALL_DIR" fetch origin
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
    step "Cloning $REPO_URL → $INSTALL_DIR…"
    git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# 5. venv + dependencies
if [[ ! -d ".venv" ]]; then
    step "Creating .venv…"
    python3 -m venv .venv
fi

step "Installing/refreshing Python dependencies (this takes ~1-2 min the first time)…"
# shellcheck source=/dev/null
source .venv/bin/activate
python -m pip install --upgrade --quiet pip
python -m pip install --quiet -e ".[web,llm]"
deactivate

# 6. Make launcher executable
chmod +x launch.command

# 7. Friendly summary
green ""
green "✅ epubconv is installed at $INSTALL_DIR"
green ""
echo  "To start the app whenever you want:"
echo  "  • Double-click  $INSTALL_DIR/launch.command  in Finder, OR"
echo  "  • Run:  $INSTALL_DIR/launch.command"
echo  ""
echo  "Both will open http://127.0.0.1:8000 in your browser."
echo  ""

if [[ "$OS" == "Darwin" ]] && ask_yes_no "Start it now? [Y/n]" "Y"; then
    step "Launching…"
    open "$INSTALL_DIR/launch.command"
fi
