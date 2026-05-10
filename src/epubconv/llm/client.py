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
import time
from dataclasses import dataclass

PROVIDERS = ("gemini", "banana2556")

# Long-context summary requests can take well over a minute on busy upstreams.
# Default OpenAI SDK timeout (10 min) is fine, but we set explicitly so it's
# obvious. Banana2556 sometimes drops the upstream connection mid-stream
# (HTTP 408 "stream disconnected"); we retry those with back-off.
DEFAULT_TIMEOUT = 600.0
RETRY_STATUS = (408, 429, 500, 502, 503, 504)
MAX_ATTEMPTS = 3

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

    def __init__(self, cfg: LLMConfig, *, timeout: float = DEFAULT_TIMEOUT) -> None:
        try:
            from openai import OpenAI  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "openai package is required. Install with: pip install epubconv[llm]"
            ) from exc

        from openai import OpenAI

        self.cfg = cfg
        self._client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=timeout)

    def translate(self, text: str, target_lang: str) -> str:
        return self.complete(
            system=SYSTEM_PROMPT,
            user=f"Target: {target_lang}\n\n{text}",
        )

    def complete(self, system: str, user: str, *, temperature: float = 0.0) -> str:
        """Generic chat completion with retry on transient errors.

        Banana2556 occasionally returns 408 ("stream disconnected before
        completion") for long requests where the upstream provider drops
        mid-stream. We retry such errors plus 429 / 5xx with exponential
        back-off (5, 10, 20s) up to ``MAX_ATTEMPTS`` total attempts.
        """
        last_err: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
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
            except Exception as exc:
                if not _is_retryable(exc) or attempt == MAX_ATTEMPTS - 1:
                    raise
                last_err = exc
                wait = (2 ** attempt) * 5  # 5, 10, 20s
                time.sleep(wait)
        # Defensive — the loop should always raise or return.
        raise RuntimeError(f"unexpected: {last_err}")


def _is_retryable(exc: Exception) -> bool:
    """Treat 408 / 429 / 5xx and connection drops as retryable."""
    status = getattr(exc, "status_code", None)
    if status in RETRY_STATUS:
        return True
    # APIStatusError on newer openai SDKs exposes .status_code; older builds
    # carry it inside the response. Inspect the message as a final fallback
    # for the banana2556-specific "stream disconnected before completion".
    message = str(exc).lower()
    if "stream disconnected" in message or "stream closed" in message:
        return True
    if "timeout" in message or "connection" in message and "reset" in message:
        return True
    return False
