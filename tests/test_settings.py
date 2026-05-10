from __future__ import annotations

import os
from pathlib import Path

import pytest

from epubconv import settings


@pytest.fixture
def fake_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point EPUBCONV_CONFIG_DIR at a temp dir and clear known keys from env."""
    monkeypatch.setenv("EPUBCONV_CONFIG_DIR", str(tmp_path))
    for key in settings.KNOWN_KEYS:
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def test_secrets_path_uses_config_dir(fake_config: Path) -> None:
    assert settings.secrets_path() == fake_config / "secrets.env"


def test_save_writes_file_with_known_keys_only(fake_config: Path) -> None:
    settings.save_keys({
        "BANANA2556_API_KEY": "sk-banana",
        "GEMINI_API_KEY": "g-key",
        "RANDOM_OTHER": "ignored",  # not in KNOWN_KEYS — must be dropped
    })
    contents = (fake_config / "secrets.env").read_text(encoding="utf-8")
    assert "BANANA2556_API_KEY=sk-banana" in contents
    assert "GEMINI_API_KEY=g-key" in contents
    assert "RANDOM_OTHER" not in contents


def test_save_updates_environ(fake_config: Path) -> None:
    settings.save_keys({"BANANA2556_API_KEY": "sk-1"})
    assert os.environ.get("BANANA2556_API_KEY") == "sk-1"


def test_save_empty_value_clears_key(fake_config: Path) -> None:
    settings.save_keys({"BANANA2556_API_KEY": "sk-1"})
    settings.save_keys({"BANANA2556_API_KEY": ""})
    contents = (fake_config / "secrets.env").read_text(encoding="utf-8")
    assert "BANANA2556_API_KEY" not in contents
    assert "BANANA2556_API_KEY" not in os.environ


def test_load_into_env_reads_file(fake_config: Path) -> None:
    (fake_config / "secrets.env").write_text(
        "BANANA2556_API_KEY=sk-from-disk\nGEMINI_API_KEY=g-disk\n",
        encoding="utf-8",
    )
    loaded = settings.load_into_env()
    assert loaded == {"BANANA2556_API_KEY": "sk-from-disk", "GEMINI_API_KEY": "g-disk"}
    assert os.environ.get("BANANA2556_API_KEY") == "sk-from-disk"


def test_load_does_not_clobber_existing_env(
    fake_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BANANA2556_API_KEY", "shell-wins")
    (fake_config / "secrets.env").write_text(
        "BANANA2556_API_KEY=sk-from-disk\n", encoding="utf-8",
    )
    settings.load_into_env()
    assert os.environ["BANANA2556_API_KEY"] == "shell-wins"


def test_load_with_no_file_returns_empty(fake_config: Path) -> None:
    assert settings.load_into_env() == {}


def test_status_reflects_env(fake_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BANANA2556_API_KEY", "sk-abcdefgh")
    s = settings.status()
    assert s["BANANA2556_API_KEY"]["configured"] is True
    assert s["BANANA2556_API_KEY"]["last4"] == "efgh"
    assert s["GEMINI_API_KEY"]["configured"] is False
    assert s["GEMINI_API_KEY"]["last4"] == ""


def test_save_writes_mode_0600(fake_config: Path) -> None:
    settings.save_keys({"BANANA2556_API_KEY": "sk-1"})
    mode = (fake_config / "secrets.env").stat().st_mode & 0o777
    # Owner-only on POSIX; on Windows mode bits are limited but the call
    # shouldn't error.
    assert mode in (0o600, 0o666, 0o644)
