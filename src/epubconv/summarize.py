"""Summarise an EPUB using an OpenAI-compatible LLM.

Reads the book's body text in spine order (skipping cover / TOC / colophon)
and asks the LLM for a structured markdown summary
(主旨、主角、主題、章節摘要、每章啟發、寫作風格).

For long books (>= ``_PER_CALL_CHAR_BUDGET``) we map-reduce: split by
chapter boundaries into context-sized batches, have the LLM extract
per-batch notes, then a final pass combines those notes into the
structured summary. This avoids "Input too long" 502s on books that
exceed the model's context window.

Optional dependency: ``epubconv[llm]`` for the OpenAI SDK that
``LLMClient`` wraps. Both ``banana2556`` and direct ``gemini`` providers
work because they both expose chat-completions.
"""
from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .epub import extract_epub
from .llm.client import LLMClient, LLMConfig
from .pipeline import _read_text
from .skill.extract import clean_text, is_content_file, read_toc

logger = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 800_000  # large; relies on long-context models like Haiku 4.5
DEFAULT_PROVIDER = "banana2556"
DEFAULT_MODEL = "claude-haiku-4.5-as"  # banana2556 alias

# How many source characters we send in one chat-completions call.
# 150K chars ≈ 100K-150K tokens for Chinese/English mix — leaves headroom
# for system prompt + structured output inside a 200K-token window.
_PER_CALL_CHAR_BUDGET = 150_000

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

## 每章嘅啟發 / 諗法 / 得著
（依書中順序，每章用 H3 開頭：### 第 N 章 — <章節標題>
然後列出最少 3 點 bullet：每點係讀完呢章之後嘅 idea / 諗法 / 得著
唔係單純複述劇情，要係讀者可以帶走嘅觀察、教訓、或進一步思考嘅問題）

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


_CHUNK_TEMPLATE = """以下係本書嘅其中一段（可能包含多章）。請只係抽取以下資料，
唔好寫總結 — 後面有另一個步驟會將呢啲筆記整合：

### 出現嘅人物
- 列舉，每個一行：姓名 — 一句描述

### 章節事件 / 內容
（依章節順序，每章 1-3 句寫低發生咗咩）

### 主題 / 觀察
（呢段見到嘅主題或重要 motif，bullet form）

### 每章嘅啟發 / 諗法 / 得著
（每章用 H4 開頭：#### 第 N 章 — <章節標題>
然後最少 3 點 bullet：讀完呢章 take away 嘅 idea / 觀察 / 教訓 / 進一步思考嘅問題
唔係單純複述劇情）

### 寫作風格觀察
（一行 bullet，描述呢段嘅語氣、節奏、敘事視角）

---

{body}
"""


_COMBINE_TEMPLATE = """以下係本書按章節順序拆成幾段嘅筆記。
請整合成一個完整撮要，照住下面嘅結構（同章節順序）：

## 一句話總結
（一句話講出本書嘅核心主題）

## 主要人物
（最多 5 個，每個一行：姓名 — 一句描述。合併重複人物）

## 主要主題
（3-5 個 bullet points，summarise 跨段嘅 motif）

## 章節摘要
（每章 1-2 句，依書中順序，合併拆段資料）

## 每章嘅啟發 / 諗法 / 得著
（依書中順序，每章用 H3 開頭：### 第 N 章 — <章節標題>
然後列出最少 3 點 bullet，由筆記抽出最值得嘅 takeaway，
唔係單純複述劇情，要係讀者可以帶走嘅觀察、教訓、或進一步思考嘅問題）

## 寫作風格 / 體裁
（一段，整合各段觀察，描述語氣、節奏、敘事視角）

---

{notes}
"""


def summarise_epub(
    epub_path: Path,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    api_key: str | None = None,
    client: LLMClient | None = None,
    per_call_budget: int = _PER_CALL_CHAR_BUDGET,
) -> Summary:
    """Top-level entry: extract → (chunk if long) → ask LLM → return :class:`Summary`."""
    body, chapters = book_text(epub_path, max_chars=max_chars)
    if not body:
        raise ValueError(f"no readable text in {epub_path}")

    if client is None:
        cfg = LLMConfig.for_provider(provider, model=model or DEFAULT_MODEL, api_key=api_key)
        client = LLMClient(cfg)

    if len(body) <= per_call_budget:
        prompt = _USER_TEMPLATE.format(max_chars=max_chars, body=body)
        text = client.complete(system=_SYSTEM_PROMPT, user=prompt)
    else:
        text = _summarise_long(body, client=client, per_call_budget=per_call_budget)

    return Summary(text=text, chars_used=len(body), chapters_used=chapters)


def _summarise_long(body: str, *, client: LLMClient, per_call_budget: int) -> str:
    """Map-reduce: split body by chapter boundaries, summarise each batch,
    then combine the partial notes into the final structured summary."""
    batches = _split_into_batches(body, per_call_budget)
    logger.info("summarise: long book — %d batches of ~%d chars each", len(batches), per_call_budget)

    notes: list[str] = []
    for i, batch in enumerate(batches, start=1):
        logger.info("summarise: batch %d/%d (%d chars)", i, len(batches), len(batch))
        prompt = _CHUNK_TEMPLATE.format(body=batch)
        out = client.complete(system=_SYSTEM_PROMPT, user=prompt)
        notes.append(f"## 段 {i}（共 {len(batches)} 段）\n\n{out}")

    merged = "\n\n".join(notes)
    logger.info("summarise: combining %d batches of notes (%d chars total)", len(batches), len(merged))
    final_prompt = _COMBINE_TEMPLATE.format(notes=merged)
    return client.complete(system=_SYSTEM_PROMPT, user=final_prompt)


def _split_into_batches(body: str, budget: int) -> list[str]:
    """Pack chapter blocks into <= budget-char batches.

    ``body`` is shaped as ``## <title>\\n<text>\\n\\n## <title>\\n<text>...``
    by :func:`book_text`. We split on the chapter delimiter, then greedily
    pack chapters into batches without exceeding ``budget``. A single
    chapter larger than ``budget`` is hard-split as a last resort.
    """
    if not body:
        return []
    # Split on the heading delimiter while keeping the heading prefix.
    raw_chapters = body.split("\n\n## ")
    chapters: list[str] = []
    for i, ch in enumerate(raw_chapters):
        if i == 0:
            chapters.append(ch)  # already starts with "## " from book_text
        else:
            chapters.append("## " + ch)

    batches: list[str] = []
    current: list[str] = []
    current_len = 0
    for ch in chapters:
        ch_len = len(ch)
        if ch_len > budget:
            # Flush current, then hard-split the oversize chapter.
            if current:
                batches.append("\n\n".join(current))
                current, current_len = [], 0
            for i in range(0, ch_len, budget):
                batches.append(ch[i : i + budget])
            continue
        glue = 2 if current else 0
        if current_len + glue + ch_len > budget:
            batches.append("\n\n".join(current))
            current, current_len = [ch], ch_len
        else:
            current.append(ch)
            current_len += glue + ch_len
    if current:
        batches.append("\n\n".join(current))
    return batches
