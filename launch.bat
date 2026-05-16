@echo off
rem launch.bat — double-click to start the epubconv web UI on Windows.
rem
rem Mirrors launch.command's job on macOS:
rem   1. Sets the working directory to wherever this file lives.
rem   2. Creates .venv on first run.
rem   3. Ensures the [web,llm] dependency set is installed every launch
rem      (cheap when already up to date; auto-recovers if pyproject grows
rem      a new optional dep).
rem   4. Opens http://127.0.0.1:8000 in the default browser.
rem   5. Runs `epubconv serve --reload` so /update (git pull) hot-reloads.

setlocal
cd /d "%~dp0"

if not exist .venv (
    echo First run: creating .venv ^(one-time^)...
    py -3 -m venv .venv 2>nul
    if errorlevel 1 (
        python -m venv .venv
        if errorlevel 1 (
            echo Failed to create venv. Install Python 3.10+ first.
            pause
            exit /b 1
        )
    )
)

call .venv\Scripts\activate.bat

echo Checking dependencies (fast when nothing changed)...
python -m pip install --upgrade --quiet pip
python -m pip install --quiet -e ".[web,llm]"

start "" "http://127.0.0.1:8000"
epubconv serve --reload
