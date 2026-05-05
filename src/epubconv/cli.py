from __future__ import annotations

import sys
from pathlib import Path

import typer
from loguru import logger

from .engines.glossary_engine import GlossaryEngine
from .engines.opencc_engine import OPENCC_CONFIGS, OpenCCEngine
from .glossary import Glossary
from .pipeline import convert_epub

app = typer.Typer(
    add_completion=False,
    help="EPUB Traditional/Simplified Chinese converter.",
    no_args_is_help=True,
)


@app.command()
def convert(
    src: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Source EPUB"),
    dst: Path = typer.Argument(None, help="Output EPUB (default: <src>.<target>.epub)"),
    source_lang: str = typer.Option("zh-CN", "--from", "-f", help="Source language (zh-CN, zh-TW, zh-HK, zh-Hant, zh-Hans)"),
    target_lang: str = typer.Option("zh-TW", "--to", "-t", help="Target language"),
    engine_name: str = typer.Option("opencc", "--engine", "-e", help="Conversion engine"),
    opencc_config: str = typer.Option(None, "--opencc-config", help="Override OpenCC config (e.g. s2twp)"),
    glossary_path: Path = typer.Option(
        None,
        "--glossary",
        "-g",
        exists=True,
        dir_okay=False,
        readable=True,
        help="YAML glossary with protect/pre/post rules",
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Convert an EPUB between Chinese variants."""
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO", format="{level: <8} {message}")

    if dst is None:
        dst = src.with_name(f"{src.stem}.{target_lang}.epub")

    if engine_name == "opencc":
        engine = OpenCCEngine(source_lang, target_lang, config=opencc_config)
    else:
        raise typer.BadParameter(f"unknown engine: {engine_name}")

    if glossary_path is not None:
        glossary = Glossary.from_yaml(glossary_path)
        if not glossary.is_empty():
            logger.info(
                f"glossary: {glossary_path.name} "
                f"(protect={len(glossary.protect)}, pre={len(glossary.pre)}, post={len(glossary.post)})"
            )
            engine = GlossaryEngine(engine, glossary)

    out = convert_epub(src, dst, engine, target_lang)
    typer.echo(str(out))


@app.command("list-configs")
def list_configs() -> None:
    """List supported OpenCC source -> target combinations."""
    for (s, t), cfg in sorted(OPENCC_CONFIGS.items()):
        typer.echo(f"{s:10s} -> {t:10s}  ({cfg})")


if __name__ == "__main__":
    app()
