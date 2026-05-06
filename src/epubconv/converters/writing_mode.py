"""Apply a horizontal/vertical writing mode to the package.

Vertical Chinese books need both:
  - CSS ``writing-mode: vertical-rl`` so renderers lay out columns right-to-left
  - OPF ``<spine page-progression-direction="rtl">`` so readers turn pages the
    correct way

We append a small override stylesheet rule to every existing CSS file (rather
than parsing each file with cssutils) so user-authored rules elsewhere in the
file don't get re-serialised. Cascade order means the appended rule wins.

If the package has no CSS, we emit a new ``epubconv-writing-mode.css`` and link
it into every XHTML file's ``<head>``.
"""
from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from lxml import etree

from ..epub import EpubPackage

OPF_NS = "http://www.idpf.org/2007/opf"

WRITING_MODES = ("preserve", "horizontal", "vertical")

_VERTICAL_CSS = "html, body { writing-mode: vertical-rl; -epub-writing-mode: vertical-rl; }\n"
_HORIZONTAL_CSS = "html, body { writing-mode: horizontal-tb; -epub-writing-mode: horizontal-tb; }\n"


def apply_writing_mode(pkg: EpubPackage, mode: str) -> None:
    if mode == "preserve":
        return
    if mode not in WRITING_MODES:
        raise ValueError(f"unknown writing mode: {mode}; expected one of {WRITING_MODES}")

    css_rule = _VERTICAL_CSS if mode == "vertical" else _HORIZONTAL_CSS
    direction = "rtl" if mode == "vertical" else "ltr"

    css_files = pkg.css_files
    if css_files:
        for css in css_files:
            existing = css.read_text(encoding="utf-8", errors="replace")
            sep = "" if existing.endswith("\n") or not existing else "\n"
            css.write_text(f"{existing}{sep}/* epubconv writing-mode override */\n{css_rule}", encoding="utf-8")
    else:
        # No CSS in the package; create one and link it.
        css_path = pkg.opf_path.parent / "epubconv-writing-mode.css"
        css_path.write_text(css_rule, encoding="utf-8")
        _link_css_in_xhtml(pkg, css_path)
        _add_css_to_manifest(pkg.opf_path, css_path)

    _set_spine_direction(pkg.opf_path, direction)


def _set_spine_direction(opf_path: Path, direction: str) -> None:
    tree = etree.parse(str(opf_path))
    root = tree.getroot()
    # Spine may be in default opf namespace or no namespace; handle both.
    spine = root.find(f"{{{OPF_NS}}}spine")
    if spine is None:
        spine = root.find("spine")
    if spine is None:
        raise ValueError(f"no <spine> in {opf_path}")
    spine.set("page-progression-direction", direction)
    tree.write(str(opf_path), xml_declaration=True, encoding="utf-8", standalone=False)


def _link_css_in_xhtml(pkg: EpubPackage, css_path: Path) -> None:
    for path in pkg.content_files:
        if path.suffix.lower() not in {".xhtml", ".html", ".htm"}:
            continue
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml-xml")
        head = soup.find("head")
        if head is None:
            continue
        rel = _relative_href(path, css_path)
        link = soup.new_tag("link", rel="stylesheet", type="text/css", href=rel)
        head.append(link)
        path.write_text(str(soup), encoding="utf-8")


def _add_css_to_manifest(opf_path: Path, css_path: Path) -> None:
    tree = etree.parse(str(opf_path))
    root = tree.getroot()
    manifest = root.find(f"{{{OPF_NS}}}manifest")
    if manifest is None:
        manifest = root.find("manifest")
    if manifest is None:
        return
    item = etree.SubElement(manifest, f"{{{OPF_NS}}}item")
    item.set("id", "epubconv-writing-mode-css")
    item.set("href", _relative_href(opf_path, css_path))
    item.set("media-type", "text/css")
    tree.write(str(opf_path), xml_declaration=True, encoding="utf-8", standalone=False)


def _relative_href(from_file: Path, to_file: Path) -> str:
    import os
    return os.path.relpath(to_file, start=from_file.parent).replace("\\", "/")


__all__ = ["WRITING_MODES", "apply_writing_mode"]
