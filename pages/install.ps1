# epubconv installer for Windows 10 / 11.
#
# Usage from the landing page (PowerShell):
#   iwr -useb https://<your-project>.pages.dev/install.ps1 | iex
#
# What it does:
#   1. Checks for winget (Windows Package Manager, built into Win10 1809+ /
#      Win11). If missing, points the user at the Microsoft Store page.
#   2. Installs Git + Python 3.11 via winget if either is missing.
#   3. Optionally installs Calibre (needed for MOBI / AZW3 conversion).
#   4. Clones epub-chinese-convert into $env:USERPROFILE\Apps\epubconv.
#   5. Creates a venv + installs the [web,llm] extras.
#   6. Opens launch.bat so the server starts in a Command Prompt window
#      and the default browser jumps to http://127.0.0.1:8000.
#
# Re-runnable: a second run updates the checkout to the latest commit and
# refreshes any new dependencies. Cache + API keys (stored in localStorage)
# are untouched.

$ErrorActionPreference = "Stop"

# ---- configurable ----
$RepoUrl     = if ($env:EPUBCONV_REPO_URL) { $env:EPUBCONV_REPO_URL } else { "https://github.com/bu56co-del/epub-chinese-convert" }
$Branch      = if ($env:EPUBCONV_BRANCH)   { $env:EPUBCONV_BRANCH }   else { "claude/ebook-chinese-translator-mcmy8" }
$InstallDir  = if ($env:EPUBCONV_INSTALL_DIR) { $env:EPUBCONV_INSTALL_DIR } else { Join-Path $env:USERPROFILE "Apps\epubconv" }

# ---- helpers ----
function Write-Step($msg)   { Write-Host "▶ $msg" -ForegroundColor Blue }
function Write-Ok($msg)     { Write-Host "✅ $msg" -ForegroundColor Green }
function Write-Note($msg)   { Write-Host $msg -ForegroundColor Yellow }
function Write-Err($msg)    { Write-Host $msg -ForegroundColor Red }

function Ask-YesNo($prompt, $default = "N") {
    $reply = Read-Host -Prompt $prompt
    if ([string]::IsNullOrWhiteSpace($reply)) { $reply = $default }
    return ($reply -match '^[Yy]')
}

function Test-Cmd($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Refresh-Path() {
    # Pull the latest PATH from registry so freshly-winget-installed tools
    # show up without restarting PowerShell.
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH", "User")
}

# ---- preflight ----
Write-Host ""
Write-Host "epubconv Windows installer" -ForegroundColor Cyan
Write-Host "Install dir: $InstallDir"
Write-Host ""

if (-not (Test-Cmd "winget")) {
    Write-Err "winget (Windows Package Manager) is not installed."
    Write-Note "Install it from the Microsoft Store: 'App Installer'"
    Write-Note "  ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1"
    Write-Note "Then re-run this installer."
    exit 1
}
Write-Step "winget is available."

# 1. Git
if (-not (Test-Cmd "git")) {
    Write-Step "Installing Git via winget…"
    winget install --silent --accept-source-agreements --accept-package-agreements -e --id Git.Git
    Refresh-Path
    if (-not (Test-Cmd "git")) {
        Write-Err "git not on PATH after install. Open a new PowerShell window and re-run."
        exit 1
    }
}
Write-Step "git $(git --version) is installed."

# 2. Python 3.11
$pythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    if (Test-Cmd $candidate) {
        $verStr = & $candidate -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
        if ($verStr) {
            $parts = $verStr.Trim().Split(".")
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
                $pythonExe = $candidate
                Write-Step "$candidate $verStr is installed."
                break
            }
        }
    }
}
if (-not $pythonExe) {
    Write-Step "Installing Python 3.11 via winget…"
    winget install --silent --accept-source-agreements --accept-package-agreements -e --id Python.Python.3.11
    Refresh-Path
    if (Test-Cmd "python") { $pythonExe = "python" }
    elseif (Test-Cmd "py") { $pythonExe = "py" }
    if (-not $pythonExe) {
        Write-Err "Python install finished but isn't on PATH yet."
        Write-Note "Open a new PowerShell window and re-run this installer."
        exit 1
    }
}

# 3. Calibre (optional)
if (Test-Cmd "ebook-convert") {
    Write-Step "Calibre (ebook-convert) is already installed — MOBI / AZW3 enabled."
} else {
    Write-Note "Calibre is not installed."
    Write-Host "  → Without it, epubconv can still do EPUB ↔ EPUB Chinese-variant conversion."
    Write-Host "  → With it, you get MOBI / AZW3 input + output (Kindle formats)."
    if (Ask-YesNo "Install Calibre now via winget? [y/N]") {
        Write-Step "Installing Calibre…"
        winget install --silent --accept-source-agreements --accept-package-agreements -e --id calibre.calibre
        Refresh-Path
    } else {
        Write-Note "Skipping Calibre. Install later with: winget install -e --id calibre.calibre"
    }
}

# 4. Clone or update
$parent = Split-Path -Parent $InstallDir
if (-not (Test-Path $parent)) {
    New-Item -ItemType Directory -Path $parent | Out-Null
}

if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Step "Updating existing checkout at $InstallDir…"
    Push-Location $InstallDir
    git fetch origin
    git checkout $Branch
    git reset --hard "origin/$Branch"
    Pop-Location
} else {
    Write-Step "Cloning $RepoUrl → $InstallDir…"
    git clone --branch $Branch --single-branch $RepoUrl $InstallDir
}

Push-Location $InstallDir

# 5. venv + dependencies
if (-not (Test-Path ".venv")) {
    Write-Step "Creating .venv…"
    & $pythonExe -m venv .venv
}

Write-Step "Installing/refreshing Python dependencies (takes ~1-2 min the first time)…"
$pip = Join-Path ".venv\Scripts" "python.exe"
& $pip -m pip install --upgrade --quiet pip
& $pip -m pip install --quiet -e ".[web,llm]"

Pop-Location

# 6. Friendly summary
Write-Host ""
Write-Ok "epubconv is installed at $InstallDir"
Write-Host ""
Write-Host "To start the app whenever you want:"
Write-Host "  - Double-click  $InstallDir\launch.bat  in Explorer, OR"
Write-Host "  - Run:  $InstallDir\launch.bat"
Write-Host ""
Write-Host "Both will open http://127.0.0.1:8000 in your browser."
Write-Host ""

if (Ask-YesNo "Start it now? [Y/n]" "Y") {
    Write-Step "Launching…"
    Start-Process (Join-Path $InstallDir "launch.bat")
}
