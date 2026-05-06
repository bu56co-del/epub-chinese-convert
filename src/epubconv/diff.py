"""Side-by-side diff report between original and converted EPUB content.

Walks the source EPUB without writing an output EPUB, runs each chapter
through the engine, and emits a single self-contained HTML file with
``difflib.HtmlDiff`` tables per content file. Only files that actually
change are included.
"""
from __future__ import annotations

import difflib
import html
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup

from .converters.content import convert_xhtml
from .engines.base import Engine
from .epub import extract_epub
from .pipeline import _read_text


def _visible_text_lines(xhtml: str) -> list[str]:
    """Strip markup, keep one block of visible text per line."""
    soup = BeautifulSoup(xhtml, "lxml-xml")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    return [line for line in (l.strip() for l in text.splitlines()) if line]


def build_diff_report(src: Path, engine: Engine, out: Path) -> Path:
    """Produce an HTML report at ``out``. Returns the output path."""
    with tempfile.TemporaryDirectory(prefix="epubconv-diff-") as tmp:
        pkg = extract_epub(src, Path(tmp))
        sections: list[str] = []
        differ = difflib.HtmlDiff(wrapcolumn=60)

        for path in pkg.content_files:
            original = _read_text(path)
            converted = convert_xhtml(original, engine)
            before = _visible_text_lines(original)
            after = _visible_text_lines(converted)
            if before == after:
                # Re-serialisation can change byte-level output even with an
                # identity engine; only count visible-text changes.
                continue
            table = differ.make_table(
                before, after,
                fromdesc=f"{path.name} (source)",
                todesc=f"{path.name} (converted)",
                context=True,
                numlines=2,
            )
            sections.append(f"<h2>{html.escape(path.relative_to(pkg.root).as_posix())}</h2>\n{table}")

    out.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(sections) if sections else "<p>No changes.</p>"
    out.write_text(_HTML_SHELL.format(title=html.escape(src.name), body=body), encoding="utf-8")
    return out


_HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>epubconv diff: {title}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 2em; }}
  table.diff {{ border-collapse: collapse; font-family: monospace; font-size: 0.9em; }}
  .diff_header {{ background: #eee; }}
  td.diff_header {{ text-align: right; padding: 0 0.5em; }}
  .diff_next {{ background: #f7f7f7; }}
  .diff_add {{ background: #cfc; }}
  .diff_chg {{ background: #ffc; }}
  .diff_sub {{ background: #fcc; }}
  h2 {{ margin-top: 2em; border-bottom: 1px solid #ccc; padding-bottom: 0.3em; }}
</style>
</head>
<body>
<h1>epubconv diff: {title}</h1>
{body}
</body>
</html>
"""
