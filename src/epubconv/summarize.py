"""Summarise an EPUB using an OpenAI-compatible LLM.

Reads the book's body text in spine order (skipping cover / TOC / colophon),
truncates to a context-budget, and asks the LLM for a structured summary
(主旨、主角、主題、章節摘要).

Optional dependency: ``epubconv[llm]`` for the OpenAI SDK that
``LLMClient`` wraps. Both ``banana2556`` and direct ``gemini`` providers
work because they both expose chat-completions.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .epub import extract_epub
from .llm.client import LLMClient, LLMConfig
from .pipeline import _read_text
from .skill.extract import clean_text, is_content_file, read_toc

DEFAULT_MAX_CHARS = 80_000  # well under GPT-5 / Gemini 1.5 context budgets
DEFAULT_PROVIDER = "banana2556"
DEFAULT_MODEL = "gpt-5"  # banana2556 routes to OpenAI's latest

_SYSTEM_PROMPT = (
    "你係一個書籍分析助手。用繁體中文（zh-TW）回答，"
    "唔好加任何免責聲明。輸出 markdown 格式。"
)

_USER_TEMPLATE = """以下係一本書嘅原文（已 truncate 到首 {max_chars} 字）。

請按以下結構撮要：

## 一句話總結
（一句話講出本書嘅核心主題）

## 主要人物
（最多 5 個，每個一行：姓名 — 一句描述）

## 主要主題
（3-5 個 bullet points）

## 章節摘要
（每章 1-2 句，依書中順序）

## 寫作風格 / 體裁
（一段，描述語氣、節奏、敘事視角）

---

{body}
"""


@dataclass
class Summary:
    text: str          # markdown
    chars_used: int    # how many chars of source we sent
    chapters_used: int


def book_text(epub_path: Path, *, max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, int]:
    """Concatenate visible chapter text in TOC order, capped at ``max_chars``.

    Returns ``(text, chapter_count)``.
    """
    with tempfile.TemporaryDirectory(prefix="epubconv-summary-") as tmp:
        pkg = extract_epub(epub_path, Path(tmp))
        toc = [e for e in read_toc(pkg) if is_content_file(e.src)]

        parts: list[str] = []
        total = 0  # includes glue ("\n\n") that will be inserted between blocks
        used = 0
        for entry in toc:
            try:
                raw = _read_text(entry.src)
            except (FileNotFoundError, OSError):
                continue
            text = clean_text(raw)
            if not text:
                continue
            header = f"## {entry.title}"
            block = f"{header}\n{text}"
            glue = 2 if parts else 0  # the "\n\n" we'll add before this block
            remaining = max_chars - total - glue
            if remaining <= 0:
                break
            if len(block) > remaining:
                block = block[:remaining]
            parts.append(block)
            total += len(block) + glue
            used += 1
        return "\n\n".join(parts), used


def summarise_epub(
    epub_path: Path,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    api_key: str | None = None,
    client: LLMClient | None = None,
) -> Summary:
    """Top-level entry: extract → truncate → ask LLM → return :class:`Summary`."""
    body, chapters = book_text(epub_path, max_chars=max_chars)
    if not body:
        raise ValueError(f"no readable text in {epub_path}")

    if client is None:
        cfg = LLMConfig.for_provider(provider, model=model or DEFAULT_MODEL, api_key=api_key)
        client = LLMClient(cfg)

    prompt = _USER_TEMPLATE.format(max_chars=max_chars, body=body)
    text = client.complete(system=_SYSTEM_PROMPT, user=prompt)
    return Summary(text=text, chars_used=len(body), chapters_used=chapters)
