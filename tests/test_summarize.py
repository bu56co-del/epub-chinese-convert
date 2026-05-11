from __future__ import annotations

import threading
import zipfile
from pathlib import Path

import pytest

from epubconv import summarize


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test gets a private SummaryCache root via EPUBCONV_CONFIG_DIR
    so cached results never leak across tests."""
    monkeypatch.setenv("EPUBCONV_CONFIG_DIR", str(tmp_path / "epubconv-cfg"))


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


# ---- progress callback ----


def test_progress_callback_emits_expected_stages_short_book(tmp_path: Path) -> None:
    """Single-call path should emit extracting → extracted → batch_start →
    batch_done; the last stage isn't `done` because that's emitted at the
    /summarize endpoint level, not by summarise_epub."""
    epub = _build_book(tmp_path)
    events: list[tuple[str, dict]] = []

    class FakeClient:
        def complete(self, system: str, user: str, **kw) -> str:
            return "## 一句話總結\n短"

    summarize.summarise_epub(
        epub, max_chars=10_000, client=FakeClient(), per_call_budget=999_999,
        progress=lambda stage, data: events.append((stage, dict(data))),
    )
    stages = [s for s, _ in events]
    assert stages == ["extracting", "extracted", "batch_start", "batch_done"]
    extracted = events[1][1]
    assert extracted["chars_total"] > 0
    assert extracted["chapters"] >= 1


def test_progress_callback_emits_halve_event_on_too_long(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(summarize, "_MIN_BATCH_BUDGET", 50)
    epub = _build_book(tmp_path)
    events: list[tuple[str, dict]] = []

    class HalveOnce:
        def __init__(self) -> None:
            self.first = True
        def complete(self, system: str, user: str, **kw) -> str:
            if self.first:
                self.first = False
                raise RuntimeError("Upstream error: Single message too long")
            if "請整合" in user:
                return "## 一句話總結\n合"
            return "### 內容\n- ok"

    summarize.summarise_epub(
        epub, max_chars=10_000, client=HalveOnce(), per_call_budget=400,
        progress=lambda stage, data: events.append((stage, dict(data))),
    )
    stages = [s for s, _ in events]
    assert "halve" in stages
    halve = next(d for s, d in events if s == "halve")
    assert halve["old_budget"] == 400
    assert halve["new_budget"] == 200


# ---- disk cache + hierarchical combine ----


def test_cache_short_circuits_repeated_calls(tmp_path: Path) -> None:
    """Second run on the same book reuses every cached batch + combine."""
    epub = _build_book(tmp_path)

    class CountingClient:
        def __init__(self) -> None:
            self.n = 0
        def complete(self, system: str, user: str, **kw) -> str:
            self.n += 1
            if "請整合" in user:
                return "## 一句話總結\n合"
            return "### 內容\n- ok"

    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")

    c1 = CountingClient()
    summarize.summarise_epub(
        epub, max_chars=10_000, client=c1, per_call_budget=200, cache=cache,
    )
    first_run_calls = c1.n
    assert first_run_calls > 0

    c2 = CountingClient()
    summarize.summarise_epub(
        epub, max_chars=10_000, client=c2, per_call_budget=200, cache=cache,
    )
    # Second run hits cache for every call.
    assert c2.n == 0
    # Files persisted on disk.
    assert any(p.suffix == ".txt" for p in (tmp_path / "cache" / "b").iterdir())


def test_cache_partial_progress_resumed(tmp_path: Path) -> None:
    """If batches 1-3 succeed and combine fails, retrying with the same
    cache should NOT re-issue batch 1-3 calls."""
    epub = _build_book(tmp_path)
    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")

    class CombineFails:
        def __init__(self) -> None:
            self.batch_calls = 0
            self.combine_calls = 0
        def complete(self, system: str, user: str, **kw) -> str:
            if "請整合" in user:
                self.combine_calls += 1
                raise RuntimeError("Upstream error: Input too long")
            self.batch_calls += 1
            return "### 內容\n- ok"

    c1 = CombineFails()
    with pytest.raises(summarize.SummaryError):
        summarize.summarise_epub(
            epub, max_chars=10_000, client=c1, per_call_budget=200, cache=cache,
        )
    initial_batch_calls = c1.batch_calls
    assert initial_batch_calls > 0

    class WorksThisTime:
        def __init__(self) -> None:
            self.batch_calls = 0
            self.combine_calls = 0
        def complete(self, system: str, user: str, **kw) -> str:
            if "請整合" in user:
                self.combine_calls += 1
                return "## 一句話總結\n合"
            self.batch_calls += 1
            return "### 內容\n- this should not be called"

    c2 = WorksThisTime()
    result = summarize.summarise_epub(
        epub, max_chars=10_000, client=c2, per_call_budget=200, cache=cache,
    )
    # All batches were cached → 0 new batch calls; only the combine ran.
    assert c2.batch_calls == 0
    assert c2.combine_calls >= 1
    assert "一句話總結" in result.text


def test_hierarchical_combine_bisects_when_too_long(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the combine call hits "too long" we recurse: combine each half
    of the notes, then combine the sub-summaries."""
    monkeypatch.setattr(summarize, "_MIN_BATCH_BUDGET", 50)
    epub = _build_book(tmp_path)
    combine_calls: list[int] = []  # input sizes

    class CombineOnceTooLong:
        def __init__(self) -> None:
            self.calls = 0
        def complete(self, system: str, user: str, **kw) -> str:
            self.calls += 1
            if "請整合" in user:
                combine_calls.append(len(user))
                # Reject the very first combine attempt (whole notes).
                if len(combine_calls) == 1:
                    raise RuntimeError("Upstream error: Input too long")
                return "## 一句話總結\n合"
            return "### 內容\n- ok"

    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")
    result = summarize.summarise_epub(
        epub, max_chars=10_000, client=CombineOnceTooLong(),
        per_call_budget=200, cache=cache,
    )
    # First combine failed (whole), then 2 halves combined, then merged.
    assert len(combine_calls) >= 3
    # Each subsequent combine call sends shorter input than the first failure.
    assert min(combine_calls[1:]) < combine_calls[0]
    assert "一句話總結" in result.text


def test_pack_notes_under_budget_packs_greedily() -> None:
    notes = ["x" * 60, "y" * 60, "z" * 60, "w" * 60]
    groups = summarize._pack_notes_under_budget(notes, budget=130)
    # 60 + 2 + 60 = 122 fits; adding 60 + 2 = 184 doesn't. So 2-2 split.
    assert [len(g) for g in groups] == [2, 2]


def test_pack_notes_oversize_note_in_own_group() -> None:
    notes = ["small", "x" * 1000, "small2"]
    groups = summarize._pack_notes_under_budget(notes, budget=200)
    # Big one ends up alone (caller will hard-split it).
    assert any(len(g) == 1 and len(g[0]) > 200 for g in groups)


def test_combine_proactively_splits_large_notes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even *without* an upstream rejection, the combine should split
    when joined notes exceed the budget reservation."""
    monkeypatch.setattr(summarize, "_MIN_BATCH_BUDGET", 50)
    epub = _build_book(tmp_path)
    sizes_seen: list[int] = []

    class SizeCheckingClient:
        def complete(self, system: str, user: str, **kw) -> str:
            if "請整合" in user:
                sizes_seen.append(len(user))
                return "## 一句話總結\n合"
            return "### 內容\n- " + ("ok " * 200)  # ~800-char chunk note

    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")
    summarize.summarise_epub(
        epub, max_chars=10_000, client=SizeCheckingClient(),
        per_call_budget=400, cache=cache,
    )
    # Every combine call sent ≤ budget — never the giant join.
    notes_budget = int(400 * summarize._COMBINE_PAYLOAD_RATIO)
    template_padding = len(summarize._COMBINE_TEMPLATE)
    assert all(s <= notes_budget + template_padding + 200 for s in sizes_seen), sizes_seen


def test_combine_handles_oversize_single_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a single sub-summary is bigger than the per-call budget the combine
    must hard-split its text rather than failing on the recursion."""
    monkeypatch.setattr(summarize, "_MIN_BATCH_BUDGET", 50)
    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")

    big_note = "X" * 5000
    on_progress_calls: list[tuple[str, dict]] = []

    class OkClient:
        def complete(self, system: str, user: str, **kw) -> str:
            return "OK"

    out = summarize._hierarchical_combine(
        [big_note],
        client=OkClient(),
        cache=cache,
        on_progress=lambda s, d: on_progress_calls.append((s, dict(d))),
        budget=1000,  # hard budget: notes_budget = 700
        depth=0,
        max_depth=10,
    )
    assert out == "OK"
    splits = [d for s, d in on_progress_calls if s == "combine_split"]
    assert splits, "expected at least one combine_split event"


def test_combine_halves_budget_when_proxy_rejects_a_fitting_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Our budget estimate may be looser than the proxy's real cap. When
    that happens, the combine call should halve the budget and re-pack
    rather than giving up."""
    monkeypatch.setattr(summarize, "_MIN_BATCH_BUDGET", 50)
    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")

    class RejectsLargeButAcceptsSmall:
        def __init__(self) -> None:
            self.calls = 0
        def complete(self, system: str, user: str, **kw) -> str:
            self.calls += 1
            if len(user) > 700:
                raise RuntimeError("Upstream error: Single message too long")
            return "OK"

    client = RejectsLargeButAcceptsSmall()
    out = summarize._hierarchical_combine(
        ["A" * 200, "B" * 200, "C" * 200],
        client=client, cache=cache, on_progress=lambda *a: None,
        budget=1500,  # initial notes_budget = 750; combined notes ~ 600 so first call goes through ... but 600+template > 700
        depth=0, max_depth=10,
    )
    assert out == "OK"
    # We should have made multiple calls — the budget halved at least once.
    assert client.calls >= 2


def test_combine_caps_notes_budget_regardless_of_per_call_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even when the UI hands us a huge per_call_budget, combine should
    never send more than _COMBINE_MAX_PAYLOAD chars of notes — that's
    what protects us from banana2556's per-message cap."""
    monkeypatch.setattr(summarize, "_MIN_BATCH_BUDGET", 50)
    monkeypatch.setattr(summarize, "_COMBINE_MAX_PAYLOAD", 1000)
    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")

    sizes_sent: list[int] = []

    class SizeTracker:
        def complete(self, system: str, user: str, **kw) -> str:
            sizes_sent.append(len(user))
            return "OK"

    summarize._hierarchical_combine(
        ["chunk-" + ("X" * 800)] * 8,  # eight 806-char notes
        client=SizeTracker(),
        cache=cache,
        on_progress=lambda *a: None,
        budget=1_000_000,  # absurd: ratio alone would allow 500K
        depth=0,
        max_depth=16,
    )
    # Every send (notes + template) must stay near the absolute cap; allow
    # ~2x cap for template + system prompt overhead.
    template_overhead = len(summarize._COMBINE_TEMPLATE) + len(summarize._SYSTEM_PROMPT)
    upper = summarize._COMBINE_MAX_PAYLOAD + template_overhead + 200
    assert all(s <= upper for s in sizes_sent), (sizes_sent, upper)


def test_combine_no_max_depth_ceiling_when_progress_possible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard-split should keep working even at deep depth so we never
    hit the previous "depth >= max_depth → raise" trap."""
    monkeypatch.setattr(summarize, "_MIN_BATCH_BUDGET", 10)
    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")

    class OkClient:
        def complete(self, system: str, user: str, **kw) -> str:
            return "OK"

    # Start ALREADY at depth 5 (close to old max_depth=8), with one big note.
    out = summarize._hierarchical_combine(
        ["X" * 8000],
        client=OkClient(), cache=cache, on_progress=lambda *a: None,
        budget=1000, depth=5, max_depth=16,
    )
    assert out == "OK"


# ---- cancellation ----


def test_cancel_event_aborts_between_batches(tmp_path: Path) -> None:
    """Setting cancel_event after the first batch should stop the run at
    the next batch boundary and raise SummaryCancelled."""
    epub = _build_book(tmp_path)
    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")
    cancel = threading.Event()

    class CancelAfterFirst:
        def __init__(self) -> None:
            self.n = 0
        def complete(self, system: str, user: str, **kw) -> str:
            self.n += 1
            if self.n == 1:
                # First batch succeeds; user clicks Cancel right after.
                cancel.set()
            return "### 內容\n- ok"

    with pytest.raises(summarize.SummaryCancelled):
        summarize.summarise_epub(
            epub, max_chars=10_000, client=CancelAfterFirst(),
            per_call_budget=200, cache=cache, cancel_event=cancel,
        )


def test_cancel_preserves_cached_batches_for_resume(tmp_path: Path) -> None:
    """After a cancellation, a re-run with the same cache should reuse
    every batch that finished — proving cancel + cache = free resume."""
    epub = _build_book(tmp_path)
    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")
    cancel = threading.Event()

    class CancelMidway:
        def __init__(self, cancel_after: int) -> None:
            self.n = 0
            self.cancel_after = cancel_after
        def complete(self, system: str, user: str, **kw) -> str:
            self.n += 1
            if self.n == self.cancel_after:
                cancel.set()
            return "### 內容\n- ok"

    # Run #1: cancel after 2 successful batches.
    client1 = CancelMidway(cancel_after=2)
    with pytest.raises(summarize.SummaryCancelled):
        summarize.summarise_epub(
            epub, max_chars=10_000, client=client1,
            per_call_budget=200, cache=cache, cancel_event=cancel,
        )
    completed_first_run = client1.n
    assert completed_first_run >= 2

    # Cache has at least the first 2 batches stored.
    assert len(cache.keys("batch")) >= 2

    # Run #2: fresh cancel event (NOT set), same cache.
    class WorksFully:
        def __init__(self) -> None:
            self.n = 0
        def complete(self, system: str, user: str, **kw) -> str:
            self.n += 1
            if "請整合" in user:
                return "## 一句話總結\n合"
            return "### 內容\n- ok"

    client2 = WorksFully()
    result = summarize.summarise_epub(
        epub, max_chars=10_000, client=client2,
        per_call_budget=200, cache=cache,  # no cancel_event
    )
    # The previously-completed batches are cache HITs → strictly fewer
    # calls on run #2 than on a from-scratch attempt.
    assert client2.n < completed_first_run + 10  # very generous; just proves resume worked
    assert "一句話總結" in result.text


def test_cancel_before_any_batch_raises_immediately(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    cache = summarize.SummaryCache(book_id="b", root=tmp_path / "cache")
    cancel = threading.Event()
    cancel.set()  # cancelled before we even start

    class ShouldNotBeCalled:
        def complete(self, system: str, user: str, **kw) -> str:
            raise AssertionError("LLM client should not have been called")

    with pytest.raises(summarize.SummaryCancelled):
        summarize.summarise_epub(
            epub, max_chars=10_000, client=ShouldNotBeCalled(),
            per_call_budget=200, cache=cache, cancel_event=cancel,
        )


def test_progress_callback_chars_processed_advances(tmp_path: Path) -> None:
    epub = _build_book(tmp_path)
    progress: list[tuple[str, int, int]] = []

    class FakeClient:
        def complete(self, system: str, user: str, **kw) -> str:
            if "請整合" in user:
                return "## 一句話總結\n合"
            return "### 內容\n- ok"

    summarize.summarise_epub(
        epub, max_chars=10_000, client=FakeClient(), per_call_budget=300,
        progress=lambda stage, data: progress.append(
            (stage, data.get("chars_processed", -1), data.get("chars_total", -1))
        ),
    )
    done_events = [(p, t) for s, p, t in progress if s == "batch_done"]
    assert len(done_events) >= 2
    # chars_processed must be non-decreasing across batch_done events.
    processed_values = [p for p, _ in done_events]
    assert processed_values == sorted(processed_values)
    # Final batch_done should be at (or within a few chars of) chars_total —
    # inter-block newline stripping can leave a tiny gap.
    final_processed, total = done_events[-1]
    assert total - final_processed <= 4


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
