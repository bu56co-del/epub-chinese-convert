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

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from .epub import extract_epub
from .llm.client import LLMClient, LLMConfig
from .pipeline import _read_text
from .skill.extract import clean_text, is_content_file, read_toc

DEFAULT_MAX_CHARS = 800_000  # large; relies on long-context models like Haiku 4.5
DEFAULT_PROVIDER = "banana2556"
DEFAULT_MODEL = "claude-haiku-4.5-as"  # banana2556 alias

# How many source characters we send in one chat-completions call.
# Empirical floor — banana2556's claude-haiku-4.5-as alias rejects messages
# above ~30K chars even though Claude Haiku 4.5's underlying context is
# 200K tokens. Different proxies / aliases cap at different points, so
# the user can override this via the UI / form / function arg if they
# know their provider's limit. The map-reduce path also auto-halves on
# "too long" errors, so this is just the *starting* budget.
_PER_CALL_CHAR_BUDGET = 20_000

# Hard floor for the adaptive halving loop. If the upstream still
# rejects a request this small, something is genuinely wrong (auth,
# outage, etc.) and we surface the original error instead of looping.
# Tests monkey-patch this down so they don't need >1500-char fixtures.
_MIN_BATCH_BUDGET = 1500

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


class SummaryError(RuntimeError):
    """Raised when the LLM fails on a specific stage; ``__cause__`` carries
    the original exception. The message includes which stage / batch /
    char count produced the error so the user can see it in the UI."""


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

    logger.info(
        "summarise: book has {chars} chars across {chapters} chapters (budget per call: {budget})",
        chars=len(body), chapters=chapters, budget=per_call_budget,
    )

    if len(body) <= per_call_budget:
        logger.info("summarise: single-call path (body fits in one request)")
        prompt = _USER_TEMPLATE.format(max_chars=max_chars, body=body)
        text = _call(client, "single", _SYSTEM_PROMPT, prompt, batch_chars=len(body))
    else:
        text = _summarise_long(body, client=client, per_call_budget=per_call_budget)

    return Summary(text=text, chars_used=len(body), chapters_used=chapters)


def _summarise_long(body: str, *, client: LLMClient, per_call_budget: int) -> str:
    """Map-reduce with adaptive batch sizing.

    The proxy / model behind a banana2556 alias often caps per-message
    size well below the model's nominal context (e.g. claude-haiku-4.5-as
    rejects ~19K-char messages even though Haiku 4.5's true context is
    200K tokens). When that happens the user shouldn't have to keep
    halving the budget by hand — we halve it ourselves, on the fly:

    1. Try the next batch at ``current_budget`` chars.
    2. On a "too long" / "context" / "max_tokens" error, halve
       ``current_budget`` and re-try the same body region. Successful
       batches are kept; we never re-do work.
    3. Floor at 1500 chars; below that we surface the original error.

    This costs at most one wasted call per halving event (i.e. O(log n)
    extra calls), not one per batch, and the user only ever sees the
    fast path once the budget settles.
    """
    notes: list[str] = []
    body_remaining = body
    current_budget = per_call_budget
    min_budget = _MIN_BATCH_BUDGET
    batch_no = 0

    logger.info(
        "summarise: map-reduce starting at budget {budget} chars (body {n} chars)",
        budget=current_budget, n=len(body),
    )

    while body_remaining.strip():
        # Take the *first* batch under the current budget. We don't
        # pre-split everything because future budgets may shrink.
        first_batch = _split_into_batches(body_remaining, current_budget)[0]
        batch_no += 1
        stage = f"batch-{batch_no}@{current_budget}"
        prompt = _CHUNK_TEMPLATE.format(body=first_batch)
        try:
            out = _call(client, stage, _SYSTEM_PROMPT, prompt, batch_chars=len(first_batch))
        except SummaryError as exc:
            if not _looks_too_long(exc):
                raise
            new_budget = current_budget // 2
            if new_budget < min_budget:
                logger.error(
                    "summarise: floor reached ({floor} chars), upstream still rejects — giving up",
                    floor=min_budget,
                )
                raise
            logger.warning(
                "summarise[{stage}]: 'too long' — halving budget {old}→{new} and retrying same region",
                stage=stage, old=current_budget, new=new_budget,
            )
            current_budget = new_budget
            batch_no -= 1  # don't count the failed attempt
            continue

        notes.append(f"## 段 {len(notes) + 1}\n\n{out}")
        # Advance past the consumed batch (preserve a clean delimiter).
        body_remaining = body_remaining[len(first_batch):].lstrip("\n")

    merged = "\n\n".join(notes)
    final_prompt = _COMBINE_TEMPLATE.format(notes=merged)
    return _call(client, "combine", _SYSTEM_PROMPT, final_prompt, batch_chars=len(merged))


_TOO_LONG_MARKERS = (
    "too long", "context", "max_tokens", "context_length",
    "single message too long", "input too long",
)


def _looks_too_long(exc: BaseException) -> bool:
    """Return True if the wrapped error looks like a per-message size limit."""
    msg = str(exc).lower()
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        msg += " " + str(cause).lower()
    return any(marker in msg for marker in _TOO_LONG_MARKERS)


def _call(client: LLMClient, stage: str, system: str, user: str, *, batch_chars: int) -> str:
    """Wrap an LLM call with timing + a SummaryError that names the stage
    and char count when the upstream request fails."""
    started = time.time()
    logger.info("summarise[{stage}]: sending {chars} chars", stage=stage, chars=batch_chars)
    try:
        out = client.complete(system=system, user=user)
    except Exception as exc:
        elapsed = time.time() - started
        logger.error(
            "summarise[{stage}]: failed after {sec:.1f}s with {chars} input chars: {exc}",
            stage=stage, sec=elapsed, chars=batch_chars, exc=exc,
        )
        raise SummaryError(
            f"{stage}: LLM rejected {batch_chars} input chars after {elapsed:.1f}s: {exc}"
        ) from exc
    elapsed = time.time() - started
    logger.info(
        "summarise[{stage}]: ok in {sec:.1f}s, response {out_chars} chars",
        stage=stage, sec=elapsed, out_chars=len(out),
    )
    return out


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
