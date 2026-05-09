"""TOC parsing, content-file filtering, and clean-text extraction.

Used by the ``epubconv export-skill`` pipeline. Three concerns live here:

* ``read_toc(pkg)``: prefer EPUB 3 nav.xhtml ``<nav epub:type="toc">``,
  fall back to EPUB 2 NCX, fall back to spine-file = chapter when neither
  exists. Returns a list of :class:`TocEntry` records in canonical order.

* ``is_content_file(path)``: drops cover / colophon / nav / TOC files
  (by ``epub:type`` and by filename), so they don't pollute the JSONL.

* ``clean_text(xml)``: shared visible-text extractor — strips
  ``<script>`` / ``<style>`` / ``<code>`` / ``<pre>`` / ``<rt>``
  (ruby pronunciation) and joins the rest with single spaces. Used by both
  this module and ``epubconv.names``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup
from lxml import etree

from ..epub import EpubPackage

NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"
XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"

# epub:type values that mean "this is not body content".
_NON_CONTENT_TYPES = frozenset({
    "cover", "titlepage", "title-page", "copyright-page", "copyright",
    "colophon", "nav", "toc", "frontmatter", "backmatter",
    "acknowledgments", "dedication", "imprint", "landmarks",
})

_NON_CONTENT_FILENAMES = re.compile(
    r"^(cover|nav|toc|colophon|copyright|titlepage|imprint|dedication|acknowledg\w*)\b",
    re.IGNORECASE,
)

_MIN_CONTENT_CHARS = 200


@dataclass
class TocEntry:
    """One canonical entry in the table of contents."""

    title: str
    src: Path                # absolute path to the XHTML file
    fragment: str = ""       # anchor inside the file (without the '#'), if any
    heading_path: list[str] = field(default_factory=list)


def read_toc(pkg: EpubPackage) -> list[TocEntry]:
    """Resolve the TOC, preferring nav.xhtml over NCX over spine fallback."""
    nav_entries = _read_nav(pkg)
    if nav_entries:
        return nav_entries
    ncx_entries = _read_ncx(pkg)
    if ncx_entries:
        return ncx_entries
    return _spine_fallback(pkg)


def is_content_file(path: Path) -> bool:
    """Return True if this XHTML file should be included in the knowledge base."""
    if path.suffix.lower() not in {".xhtml", ".html", ".htm"}:
        return False
    if _NON_CONTENT_FILENAMES.match(path.stem):
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    soup = BeautifulSoup(text, "lxml-xml")
    body = soup.find("body")
    if body is not None:
        epub_type = (body.get(f"{{{EPUB_NS}}}type") or body.get("epub:type") or "").strip().lower()
        for tok in epub_type.split():
            if tok in _NON_CONTENT_TYPES:
                return False
    visible = clean_text(text)
    return len(visible) >= _MIN_CONTENT_CHARS


def clean_text(xml: str, *, keep_footnotes: bool = False) -> str:
    """Return visible text, joined with single spaces. Skips code/style/ruby pronunciation."""
    soup = BeautifulSoup(xml, "lxml-xml")
    for tag in soup.find_all(["script", "style", "code", "pre", "rt", "rp"]):
        tag.decompose()
    if not keep_footnotes:
        for aside in soup.find_all("aside"):
            ep_type = (aside.get(f"{{{EPUB_NS}}}type") or aside.get("epub:type") or "").lower()
            if "footnote" in ep_type or "note" in ep_type:
                aside.decompose()
    raw = soup.get_text(" ")
    # Collapse runs of whitespace.
    return re.sub(r"\s+", " ", raw).strip()


# ---- internal helpers ----


def _read_nav(pkg: EpubPackage) -> list[TocEntry]:
    nav_path: Path | None = None
    tree = etree.parse(str(pkg.opf_path))
    root = tree.getroot()
    for item in root.iter(f"{{{pkg_opf_ns()}}}item"):
        props = (item.get("properties") or "").split()
        if "nav" in props:
            nav_path = (pkg.opf_path.parent / item.get("href")).resolve()
            break
    if nav_path is None or not nav_path.exists():
        return []

    soup = BeautifulSoup(nav_path.read_text(encoding="utf-8"), "lxml-xml")
    nav = soup.find("nav", attrs={"epub:type": "toc"}) or soup.find("nav")
    if nav is None:
        return []

    entries: list[TocEntry] = []
    _walk_nav_ol(nav.find("ol"), nav_path.parent, [], entries)
    return entries


def _walk_nav_ol(ol, base: Path, ancestors: list[str], out: list[TocEntry]) -> None:
    if ol is None:
        return
    for li in ol.find_all("li", recursive=False):
        a = li.find("a")
        if a is None:
            continue
        title = (a.get_text() or "").strip()
        href = a.get("href") or ""
        src_part, _, frag = href.partition("#")
        if src_part:
            src = (base / src_part).resolve()
            out.append(TocEntry(
                title=title,
                src=src,
                fragment=frag,
                heading_path=ancestors + [title],
            ))
        nested = li.find("ol")
        if nested is not None:
            _walk_nav_ol(nested, base, ancestors + [title], out)


def _read_ncx(pkg: EpubPackage) -> list[TocEntry]:
    ncx_path = next(
        (p for p in pkg.root.rglob("*") if p.is_file() and p.suffix.lower() == ".ncx"),
        None,
    )
    if ncx_path is None:
        return []

    tree = etree.parse(str(ncx_path))
    root = tree.getroot()
    nav_map = root.find(f"{{{NCX_NS}}}navMap")
    if nav_map is None:
        return []

    entries: list[TocEntry] = []
    _walk_navpoints(list(nav_map.findall(f"{{{NCX_NS}}}navPoint")), ncx_path.parent, [], entries)
    return entries


def _walk_navpoints(points, base: Path, ancestors: list[str], out: list[TocEntry]) -> None:
    for nav_point in points:
        label_el = nav_point.find(f"{{{NCX_NS}}}navLabel/{{{NCX_NS}}}text")
        title = (label_el.text or "").strip() if label_el is not None else ""
        content = nav_point.find(f"{{{NCX_NS}}}content")
        if content is not None:
            src_attr = content.get("src", "")
            src_part, _, frag = src_attr.partition("#")
            if src_part:
                out.append(TocEntry(
                    title=title,
                    src=(base / src_part).resolve(),
                    fragment=frag,
                    heading_path=ancestors + [title],
                ))
        children = list(nav_point.findall(f"{{{NCX_NS}}}navPoint"))
        if children:
            _walk_navpoints(children, base, ancestors + [title], out)


def _spine_fallback(pkg: EpubPackage) -> list[TocEntry]:
    """When no TOC is available, treat each content-y spine file as a chapter."""
    entries: list[TocEntry] = []
    for path in pkg.spine_files:
        if not is_content_file(path):
            continue
        title = _first_heading(path) or path.stem
        entries.append(TocEntry(title=title, src=path, fragment="", heading_path=[title]))
    return entries


def _first_heading(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    soup = BeautifulSoup(text, "lxml-xml")
    for tag_name in ("h1", "h2", "h3", "title"):
        tag = soup.find(tag_name)
        if tag is not None and tag.get_text(strip=True):
            return tag.get_text(strip=True)
    return None


def pkg_opf_ns() -> str:
    """Return the OPF namespace URI. Indirected so tests can monkey-patch."""
    from ..epub import OPF_NS as _NS
    return _NS
