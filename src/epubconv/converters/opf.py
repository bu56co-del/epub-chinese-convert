from __future__ import annotations

from pathlib import Path

from lxml import etree

from ..engines.base import Engine

DC_NS = "http://purl.org/dc/elements/1.1/"
NSMAP = {"dc": DC_NS}

# Map our supported lang codes to the canonical BCP47 tag we write into OPF.
LANG_MAP: dict[str, str] = {
    "zh-CN": "zh-CN",
    "zh-Hans": "zh-CN",
    "zh-TW": "zh-TW",
    "zh-Hant": "zh-TW",
    "zh-HK": "zh-HK",
}

# dc:* elements whose text is human-readable and should run through the engine.
TEXT_ELEMENTS = ("title", "creator", "description", "publisher", "subject", "contributor")


def update_opf(opf_path: Path, engine: Engine, target_lang: str) -> None:
    """Update OPF metadata: rewrite dc:language and convert text fields."""
    new_lang = LANG_MAP.get(target_lang, target_lang)

    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(opf_path), parser)

    for el in tree.findall(".//dc:language", NSMAP):
        el.text = new_lang

    for tag in TEXT_ELEMENTS:
        for el in tree.findall(f".//dc:{tag}", NSMAP):
            if el.text and el.text.strip():
                el.text = engine.convert(el.text)

    tree.write(
        str(opf_path),
        xml_declaration=True,
        encoding="utf-8",
        standalone=False,
    )
