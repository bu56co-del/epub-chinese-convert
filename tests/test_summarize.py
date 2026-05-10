from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from epubconv import summarize


def _build_book(tmp_path: Path) -> Path:
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="b">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="b">urn:test</dc:identifier>'
        '<dc:title>測試</dc:title><dc:language>zh-TW</dc:language></metadata>'
        '<manifest>'
        '<item id="ch1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="ch2" href="c2.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '</manifest>'
        '<spine><itemref idref="ch1"/><itemref idref="ch2"/></spine></package>'
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<head><title>目錄</title></head><body><nav epub:type="toc"><ol>'
        '<li><a href="c1.xhtml">第一章</a></li>'
        '<li><a href="c2.xhtml">第二章</a></li></ol></nav></body></html>'
    )
    body1 = "第一章內容。" * 60
    body2 = "第二章內容。" * 60
    epub = tmp_path / "b.epub"
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)
        zf.writestr("OEBPS/c1.xhtml", f"<html><body><p>{body1}</p></body></html>")
        zf.writestr("OEBPS/c2.xhtml", f"<html><body><p>{body2}</p></body></html>")
    return epub


def test_book_text_returns_chapters_in_order(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    text, chapters = summarize.book_text(epub, max_chars=100_000)
    assert chapters == 2
    # Order matters: chapter 1 appears before chapter 2.
    assert text.index("第一章") < text.index("第二章")


def test_book_text_truncates_to_max_chars(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    text, _ = summarize.book_text(epub, max_chars=200)
    assert len(text) <= 200


def test_summarise_epub_calls_llm_with_truncated_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epub = _build_book(tmp_path)
    seen: dict = {}

    class FakeClient:
        def complete(self, system: str, user: str, **kw) -> str:
            seen["system"] = system
            seen["user"] = user
            return "## 一句話總結\n測。"

    result = summarize.summarise_epub(epub, max_chars=500, client=FakeClient())
    assert result.text.startswith("## 一句話總結")
    assert result.chapters_used >= 1
    assert result.chars_used <= 500
    assert "請按以下結構撮要" in seen["user"]
    assert "繁體中文" in seen["system"]


def test_user_template_asks_for_per_chapter_takeaways() -> None:
    """Each chapter must yield >= 3 takeaway bullets — verify the prompt
    actually requests this so a regression to the older template is caught."""
    template = summarize._USER_TEMPLATE
    assert "啟發" in template or "得著" in template
    assert "最少 3" in template or "至少 3" in template
    assert "每章" in template


# ---- map-reduce path ----


def test_split_into_batches_packs_chapters_under_budget() -> None:
    body = "## A\n" + "x" * 60 + "\n\n## B\n" + "y" * 60 + "\n\n## C\n" + "z" * 60
    batches = summarize._split_into_batches(body, budget=140)
    # Each batch holds at most 2 chapters of length ~63 chars.
    assert all(len(b) <= 140 for b in batches)
    # All chapter headings preserved.
    full = "\n".join(batches)
    for h in ("## A", "## B", "## C"):
        assert h in full


def test_split_into_batches_hard_splits_oversize_chapter() -> None:
    body = "## big\n" + ("x" * 1000)
    batches = summarize._split_into_batches(body, budget=300)
    assert len(batches) >= 4
    assert all(len(b) <= 300 for b in batches)


def test_short_book_uses_single_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    epub = _build_book(tmp_path)
    calls = {"n": 0, "user": []}

    class FakeClient:
        def complete(self, system: str, user: str, **kw) -> str:
            calls["n"] += 1
            calls["user"].append(user)
            return "## 一句話總結\n短書"

    summarize.summarise_epub(epub, max_chars=2000, client=FakeClient(), per_call_budget=10_000)
    assert calls["n"] == 1
    assert "請按以下結構撮要" in calls["user"][0]


def test_long_book_takes_map_reduce_path(
    tmp_path: Path,
) -> None:
    epub = _build_book(tmp_path)
    calls = {"prompts": []}

    class FakeClient:
        def complete(self, system: str, user: str, **kw) -> str:
            calls["prompts"].append(user)
            if "請整合" in user:
                return "## 一句話總結\n合併版"
            return "### 章節事件 / 內容\n- 段落筆記"

    # per_call_budget tiny enough that the (small) test book triggers map-reduce.
    result = summarize.summarise_epub(
        epub, max_chars=10_000, client=FakeClient(), per_call_budget=200,
    )
    # Expect: N chunk calls + 1 combine call.
    assert len(calls["prompts"]) >= 2
    # First few prompts use the chunk template.
    assert any("唔好寫總結" in p for p in calls["prompts"][:-1])
    # Final prompt is the combine template.
    assert "請整合" in calls["prompts"][-1]
    assert result.text.startswith("## 一句話總結")


def test_chunk_template_asks_for_per_chapter_takeaways() -> None:
    """Per-chunk extraction must also collect takeaways so the combine
    step has material to merge into the final structured summary."""
    template = summarize._CHUNK_TEMPLATE
    assert "啟發" in template or "得著" in template
    assert "最少 3" in template or "至少 3" in template


def test_combine_template_produces_structured_sections() -> None:
    template = summarize._COMBINE_TEMPLATE
    for header in ("一句話總結", "主要人物", "主要主題", "章節摘要", "啟發", "寫作風格"):
        assert header in template


def test_failure_in_chunk_phase_raises_summary_error_with_batch_context(
    tmp_path: Path,
) -> None:
    epub = _build_book(tmp_path)

    class FailingClient:
        def __init__(self) -> None:
            self.calls = 0
        def complete(self, system: str, user: str, **kw) -> str:
            self.calls += 1
            if self.calls >= 2:  # fail on the second batch
                raise RuntimeError("Upstream error: Input too long")
            return "### 章節事件 / 內容\n- ok"

    with pytest.raises(summarize.SummaryError) as excinfo:
        summarize.summarise_epub(
            epub, max_chars=10_000, client=FailingClient(), per_call_budget=200,
        )
    msg = str(excinfo.value)
    # Error names which batch failed and how many chars were sent.
    assert "batch-2" in msg
    assert "Input too long" in msg
    assert "input chars" in msg
    # __cause__ preserves the upstream exception type for debuggers.
    assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_single_call_failure_also_wrapped_in_summary_error(
    tmp_path: Path,
) -> None:
    epub = _build_book(tmp_path)

    class FailingClient:
        def complete(self, system: str, user: str, **kw) -> str:
            raise RuntimeError("Upstream error: Input too long")

    with pytest.raises(summarize.SummaryError) as excinfo:
        summarize.summarise_epub(
            epub, max_chars=10_000, client=FailingClient(), per_call_budget=999_999,
        )
    assert "single" in str(excinfo.value)


# ---- adaptive halving ----


def test_looks_too_long_recognises_common_messages() -> None:
    assert summarize._looks_too_long(RuntimeError("Single message too long"))
    assert summarize._looks_too_long(RuntimeError("Upstream error: Input too long"))
    assert summarize._looks_too_long(RuntimeError("context_length_exceeded"))
    assert summarize._looks_too_long(RuntimeError("max_tokens limit hit"))
    assert not summarize._looks_too_long(RuntimeError("rate limit exceeded"))
    assert not summarize._looks_too_long(RuntimeError("authentication_error"))


def test_long_book_halves_budget_when_upstream_rejects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First call fails with 'too long' → budget halves automatically;
    subsequent calls succeed at the smaller size, no user intervention."""
    monkeypatch.setattr(summarize, "_MIN_BATCH_BUDGET", 50)
    epub = _build_book(tmp_path)
    seen_sizes: list[int] = []

    class HalveOnceClient:
        """Reject the first oversized message; accept everything after."""
        def __init__(self) -> None:
            self.rejected_once = False

        def complete(self, system: str, user: str, **kw) -> str:
            body_len = len(user)
            seen_sizes.append(body_len)
            # Reject the first call regardless of size to force a halving event;
            # subsequent calls always succeed.
            if not self.rejected_once:
                self.rejected_once = True
                raise RuntimeError("Upstream error: Single message too long")
            if "請整合" in user:
                return "## 一句話總結\n合併"
            return "### 內容\n- ok"

    result = summarize.summarise_epub(
        epub, max_chars=10_000, client=HalveOnceClient(), per_call_budget=400,
    )
    # The second-and-later batches should be smaller than the first attempt.
    assert seen_sizes[0] > seen_sizes[1]
    assert result.text.startswith("## 一句話總結")


def test_adaptive_floor_eventually_gives_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If upstream rejects every size down to the floor (1500 chars),
    the original error surfaces instead of looping forever."""
    monkeypatch.setattr(summarize, "_MIN_BATCH_BUDGET", 1500)
    epub = _build_book(tmp_path)

    class AlwaysTooLong:
        def complete(self, system: str, user: str, **kw) -> str:
            raise RuntimeError("Upstream error: Single message too long")

    with pytest.raises(summarize.SummaryError):
        summarize.summarise_epub(
            epub, max_chars=20_000, client=AlwaysTooLong(), per_call_budget=10_000,
        )


def test_adaptive_floor_eventually_gives_up(tmp_path: Path) -> None:
    """If upstream rejects every size down to the floor (1500 chars),
    the original error surfaces instead of looping forever."""
    epub = _build_book(tmp_path)

    class AlwaysTooLong:
        def complete(self, system: str, user: str, **kw) -> str:
            raise RuntimeError("Upstream error: Single message too long")

    with pytest.raises(summarize.SummaryError):
        summarize.summarise_epub(
            epub, max_chars=20_000, client=AlwaysTooLong(), per_call_budget=10_000,
        )


def test_adaptive_does_not_kick_in_for_other_errors(tmp_path: Path) -> None:
    """Auth / rate-limit / random errors should NOT trigger halving — they
    should bubble up immediately."""
    epub = _build_book(tmp_path)
    calls = {"n": 0}

    class AuthError:
        def complete(self, system: str, user: str, **kw) -> str:
            calls["n"] += 1
            raise RuntimeError("authentication_error: token invalidated")

    with pytest.raises(summarize.SummaryError):
        summarize.summarise_epub(
            epub, max_chars=20_000, client=AuthError(), per_call_budget=200,
        )
    # Exactly one call — no halving retry.
    assert calls["n"] == 1


def test_summarise_epub_raises_on_empty_book(tmp_path: Path) -> None:
    # Build an epub with no chunkable content (only a nav file).
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/c.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="b">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="b">urn:e</dc:identifier><dc:title>e</dc:title>'
        '<dc:language>zh-CN</dc:language></metadata>'
        '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>'
        '<spine/></package>'
    )
    nav = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<body><nav epub:type="toc"><ol/></nav></body></html>'
    )
    epub = tmp_path / "empty.epub"
    with zipfile.ZipFile(epub, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/c.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav)

    with pytest.raises(ValueError, match="no readable text"):
        summarize.summarise_epub(epub, client=object())  # client never called
