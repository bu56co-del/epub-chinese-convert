from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

XHTML_EXTS = {".xhtml", ".html", ".htm"}
NCX_EXTS = {".ncx"}
OPF_EXTS = {".opf"}

CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"


@dataclass
class EpubPackage:
    """Represents an extracted EPUB on disk."""

    root: Path

    @property
    def opf_path(self) -> Path:
        container = self.root / "META-INF" / "container.xml"
        if not container.exists():
            raise FileNotFoundError(f"missing META-INF/container.xml in {self.root}")
        tree = etree.parse(str(container))
        rootfile = tree.find(".//c:rootfile", CONTAINER_NS)
        if rootfile is None:
            raise ValueError(f"no rootfile in {container}")
        return self.root / rootfile.get("full-path")

    @property
    def content_files(self) -> list[Path]:
        return sorted(
            p for p in self.root.rglob("*")
            if p.is_file() and p.suffix.lower() in XHTML_EXTS | NCX_EXTS
        )

    @property
    def css_files(self) -> list[Path]:
        return sorted(p for p in self.root.rglob("*.css") if p.is_file())

    @property
    def spine_files(self) -> list[Path]:
        """Content files in OPF spine order, resolved to absolute paths.

        Falls back to ``content_files`` (sorted-by-path) if no spine is found.
        """
        opf = self.opf_path
        tree = etree.parse(str(opf))
        root = tree.getroot()

        manifest_items: dict[str, str] = {}
        for item in root.iter(f"{{{OPF_NS}}}item"):
            item_id = item.get("id")
            href = item.get("href")
            if item_id and href:
                manifest_items[item_id] = href

        ordered: list[Path] = []
        for itemref in root.iter(f"{{{OPF_NS}}}itemref"):
            idref = itemref.get("idref")
            href = manifest_items.get(idref)
            if not href:
                continue
            ordered.append((opf.parent / href).resolve())

        return ordered or self.content_files

    def metadata(self) -> dict[str, str | list[str]]:
        """Return book metadata from OPF ``<dc:*>`` elements.

        Multi-valued elements (e.g. multiple ``<dc:creator>``) come back as
        lists; single-valued ones as strings. Missing keys are omitted.
        """
        tree = etree.parse(str(self.opf_path))
        root = tree.getroot()
        out: dict[str, str | list[str]] = {}
        for el in root.iter():
            if not isinstance(el.tag, str) or not el.tag.startswith(f"{{{DC_NS}}}"):
                continue
            key = el.tag[len(DC_NS) + 2 :]  # strip "{ns}"
            value = (el.text or "").strip()
            if not value:
                continue
            existing = out.get(key)
            if existing is None:
                out[key] = value
            elif isinstance(existing, list):
                existing.append(value)
            else:
                out[key] = [existing, value]
        return out


def extract_epub(epub_path: Path, dest: Path) -> EpubPackage:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(epub_path) as zf:
        zf.extractall(dest)
    return EpubPackage(dest)


def pack_epub(src_root: Path, output: Path) -> None:
    """Pack a directory back into an EPUB.

    EPUB spec requires the `mimetype` file to be the first entry and stored
    uncompressed. Everything else is deflated.
    """
    if output.exists():
        output.unlink()

    mimetype = src_root / "mimetype"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        if mimetype.exists():
            zf.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
        for p in sorted(src_root.rglob("*")):
            if not p.is_file():
                continue
            if p == mimetype:
                continue
            arcname = p.relative_to(src_root).as_posix()
            zf.write(p, arcname)
