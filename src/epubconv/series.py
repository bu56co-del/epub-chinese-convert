"""Cross-book glossary lookup.

Glossaries can live in a config directory keyed by series name, so users can
share term lists across an entire book series:

    ~/.config/epubconv/series/harry-potter.yaml

The ``--series harry-potter`` flag resolves the file via this module. The
config directory can be overridden with the ``EPUBCONV_CONFIG_DIR`` env var
(useful for testing or per-project config).
"""
from __future__ import annotations

import os
from pathlib import Path

from .glossary import Glossary

ENV_VAR = "EPUBCONV_CONFIG_DIR"
_DEFAULT_DIR = Path("~/.config/epubconv").expanduser()


def config_dir() -> Path:
    override = os.environ.get(ENV_VAR)
    return Path(override).expanduser() if override else _DEFAULT_DIR


def series_dir() -> Path:
    return config_dir() / "series"


def series_path(name: str) -> Path:
    """Resolve a series name to its YAML path. Does not check existence."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(f"invalid series name: {name!r}")
    return series_dir() / f"{name}.yaml"


def load_series(name: str) -> Glossary:
    """Load the named series glossary.

    Raises ``FileNotFoundError`` if the file is missing, with a message that
    points at the resolved path so users can see where we looked.
    """
    path = series_path(name)
    if not path.exists():
        raise FileNotFoundError(
            f"series glossary {name!r} not found at {path}. "
            f"Set {ENV_VAR} or create the file."
        )
    return Glossary.from_yaml(path)


def list_series() -> list[str]:
    """Return sorted names of available series glossaries (without extension)."""
    d = series_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml") if p.is_file())
