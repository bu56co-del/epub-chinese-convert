"""OpenAI-compatible client used for both Gemini and banana2556.

Both providers expose an OpenAI-compatible chat completions endpoint, so we
keep one client implementation and select the provider via base_url + api_key:

* ``gemini``     -> https://generativelanguage.googleapis.com/v1beta/openai/
                    + GEMINI_API_KEY    (default model: gemini-1.5-pro)
* ``banana2556`` -> https://api.banana2556.com/v1
                    + BANANA2556_API_KEY (default model: gpt-4o-mini)

The ``openai`` package is an optional dependency; install with
``pip install epubconv[llm]``. Importing this module without it fails with a
clear hint.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

PROVIDERS = ("gemini", "banana2556")

_DEFAULTS: dict[str, tuple[str, str, str]] = {
    # provider -> (base_url, env_var, default_model)
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "GEMINI_API_KEY",
        "gemini-1.5-pro",
    ),
    "banana2556": (
        "https://api.banana2556.com/v1",
        "BANANA2556_API_KEY",
        "gpt-4o-mini",
    ),
}


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def for_provider(cls, name: str, model: str | None = None, api_key: str | None = None) -> "LLMConfig":
        if name not in _DEFAULTS:
            raise ValueError(f"unknown LLM provider: {name!r}; expected one of {PROVIDERS}")
        base_url, env_var, default_model = _DEFAULTS[name]
        key = api_key or os.environ.get(env_var)
        if not key:
            raise ValueError(
                f"LLM provider {name!r} requires API key. Set ${env_var} or pass api_key=."
            )
        return cls(base_url=base_url, api_key=key, model=model or default_model)


SYSTEM_PROMPT = (
    "You are a Chinese script converter. Translate the user's text into the "
    "requested target Chinese variant (one of zh-TW, zh-Hant, zh-HK, zh-CN, "
    "zh-Hans). Preserve every character that doesn't need to change, including "
    "punctuation, numbers, and any non-Chinese tokens. Do not add commentary. "
    "Return ONLY the converted text."
)


class LLMClient:
    """Thin wrapper around the OpenAI SDK pinned to chat completions."""

    def __init__(self, cfg: LLMConfig) -> None:
        try:
            from openai import OpenAI  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "openai package is required. Install with: pip install epubconv[llm]"
            ) from exc

        from openai import OpenAI

        self.cfg = cfg
        self._client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

    def translate(self, text: str, target_lang: str) -> str:
        return self.complete(
            system=SYSTEM_PROMPT,
            user=f"Target: {target_lang}\n\n{text}",
        )

    def complete(self, system: str, user: str, *, temperature: float = 0.0) -> str:
        """Generic chat completion. Returns the assistant message content."""
        resp = self._client.chat.completions.create(
            model=self.cfg.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        choice = resp.choices[0]
        return (choice.message.content or "").strip()
