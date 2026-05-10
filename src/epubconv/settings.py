"""Read/write the API-key secrets file used by the web UI.

Path: ``$EPUBCONV_CONFIG_DIR/secrets.env`` (defaults to
``~/.config/epubconv/secrets.env``). Format: simple ``KEY=value`` lines,
no shell escaping, no comments — written and read by us only.

On import, ``load_into_env()`` is called by the server's startup hook so
keys saved by the user persist across server restarts (and across the
``--reload`` hot-restart triggered by /update).
"""
from __future__ import annotations

import os
from pathlib import Path

from .series import config_dir

# Keys we expose in the UI. Add to this list (and the UI form) when wiring
# new providers.
KNOWN_KEYS = ("BANANA2556_API_KEY", "GEMINI_API_KEY")


def secrets_path() -> Path:
    return config_dir() / "secrets.env"


def load_into_env() -> dict[str, str]:
    """Read the secrets file into ``os.environ`` for known keys.

    Existing env vars take precedence, so a value already set in the shell
    overrides the saved file. Returns the dict that was loaded (for tests
    and the /settings GET endpoint).
    """
    path = secrets_path()
    if not path.exists():
        return {}
    loaded: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key in KNOWN_KEYS and value:
            loaded[key] = value
            os.environ.setdefault(key, value)
    return loaded


def save_keys(updates: dict[str, str]) -> None:
    """Merge ``updates`` into the secrets file and ``os.environ``.

    A value of ``""`` in ``updates`` removes the key. Keys not in
    :data:`KNOWN_KEYS` are silently ignored to keep the file tidy.
    """
    path = secrets_path()
    existing = _read_raw(path)
    for key, value in updates.items():
        if key not in KNOWN_KEYS:
            continue
        if value:
            existing[key] = value
            os.environ[key] = value
        else:
            existing.pop(key, None)
            os.environ.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{k}={v}\n" for k, v in existing.items()),
        encoding="utf-8",
    )
    # tighten file mode — avoid accidental world-readability of secrets
    try:
        path.chmod(0o600)
    except OSError:
        pass


def status() -> dict[str, dict[str, str | bool]]:
    """Return ``{KEY: {configured: bool, last4: str}}`` for each known key."""
    out: dict[str, dict[str, str | bool]] = {}
    for key in KNOWN_KEYS:
        value = os.environ.get(key, "")
        out[key] = {
            "configured": bool(value),
            "last4": value[-4:] if value else "",
        }
    return out


def _read_raw(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out
