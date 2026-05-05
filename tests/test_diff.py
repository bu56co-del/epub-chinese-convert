from __future__ import annotations

from pathlib import Path

from epubconv.diff import build_diff_report
from epubconv.engines.opencc_engine import OpenCCEngine


def test_diff_report_writes_html(tmp_path: Path, sample_epub: Path) -> None:
    out = tmp_path / "report.html"
    result = build_diff_report(sample_epub, OpenCCEngine("zh-CN", "zh-TW"), out)
    assert result == out
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "epubconv diff" in html
    # HtmlDiff produces table.diff for changed sections.
    assert "table" in html.lower()


def test_diff_report_includes_changed_filenames(tmp_path: Path, sample_epub: Path) -> None:
    out = tmp_path / "report.html"
    build_diff_report(sample_epub, OpenCCEngine("zh-CN", "zh-TW"), out)
    html = out.read_text(encoding="utf-8")
    # chapter1 has obvious 简->繁 differences in the fixture.
    assert "chapter1.xhtml" in html


def test_diff_report_no_changes(tmp_path: Path, sample_epub: Path) -> None:
    out = tmp_path / "report.html"
    # Identity engine: no conversion happens.
    from epubconv.engines.base import Engine

    class IdentityEngine(Engine):
        name = "identity"

        def convert(self, text: str) -> str:
            return text

    build_diff_report(sample_epub, IdentityEngine(), out)
    html = out.read_text(encoding="utf-8")
    assert "No changes" in html
