from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import typer
from loguru import logger

from .batch import run_batch
from .converters.punctuation import punctuation_map_for
from .converters.writing_mode import WRITING_MODES
from .diff import build_diff_report
from .engines.base import Engine
from .engines.glossary_engine import GlossaryEngine
from .engines.opencc_engine import OPENCC_CONFIGS, OpenCCEngine
from .engines.punctuation_engine import PunctuationEngine
from .engines.llm_fallback_engine import LLMFallbackEngine
from .formats.mobi import CalibreNotFoundError, epub_to_mobi
from .glossary import Glossary
from .names import extract_candidates
from .pipeline import convert_epub
from .series import list_series, load_series, series_path

app = typer.Typer(
    add_completion=False,
    help="EPUB Traditional/Simplified Chinese converter.",
    no_args_is_help=True,
)

OUTPUT_FORMATS = ("epub", "mobi")


def _setup_logger(verbose: bool) -> None:
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO", format="{level: <8} {message}")


def _build_engine(
    source_lang: str,
    target_lang: str,
    engine_name: str,
    opencc_config: str | None,
    glossary_path: Path | None,
    punctuation: bool,
    series: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    llm_cache_path: Path | None = None,
) -> Engine:
    if engine_name == "opencc":
        engine: Engine = OpenCCEngine(source_lang, target_lang, config=opencc_config)
    else:
        raise typer.BadParameter(f"unknown engine: {engine_name}")

    if llm_provider:
        from .llm.cache import DEFAULT_CACHE_PATH, Cache
        from .llm.client import LLMClient, LLMConfig
        try:
            cfg = LLMConfig.for_provider(llm_provider, model=llm_model)
        except ValueError as exc:
            raise typer.BadParameter(str(exc))
        client = LLMClient(cfg)
        cache = Cache(llm_cache_path or DEFAULT_CACHE_PATH)
        logger.info(f"llm: {llm_provider} model={cfg.model} cache={cache.path} (entries={len(cache)})")
        engine = LLMFallbackEngine(engine, client, target_lang, cache)

    if punctuation:
        mapping = punctuation_map_for(target_lang)
        if mapping is not None:
            logger.info(f"punctuation: rewriting {len(mapping)} quote marks for {target_lang}")
            engine = PunctuationEngine(engine, mapping)

    glossary = Glossary.empty()
    if series is not None:
        try:
            series_g = load_series(series)
        except FileNotFoundError as exc:
            raise typer.BadParameter(str(exc))
        logger.info(f"series: {series} ({series_path(series)})")
        glossary = glossary.merge(series_g)
    if glossary_path is not None:
        glossary = glossary.merge(Glossary.from_yaml(glossary_path))

    if not glossary.is_empty():
        logger.info(
            f"glossary: protect={len(glossary.protect)} pre={len(glossary.pre)} post={len(glossary.post)}"
        )
        engine = GlossaryEngine(engine, glossary)

    return engine


@app.command()
def convert(
    src: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Source EPUB"),
    dst: Path = typer.Argument(None, help="Output file (default: <src>.<target>.<format>)"),
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
    series: str = typer.Option(
        None,
        "--series",
        "-s",
        help="Named series glossary from EPUBCONV_CONFIG_DIR/series/<name>.yaml",
    ),
    punctuation: bool = typer.Option(
        True,
        "--punctuation/--no-punctuation",
        help="Convert quote marks to the target convention (\"\" ↔ 「」)",
    ),
    writing_mode: str = typer.Option(
        "preserve",
        "--writing-mode",
        "-w",
        help=f"Writing direction: one of {WRITING_MODES}",
    ),
    output_format: str = typer.Option(
        "epub",
        "--format",
        "-F",
        help=f"Output format: one of {OUTPUT_FORMATS} (mobi requires Calibre)",
    ),
    llm: str = typer.Option(None, "--llm", help="LLM fallback provider: gemini | banana2556"),
    llm_model: str = typer.Option(None, "--llm-model", help="Override default model"),
    llm_cache: Path = typer.Option(None, "--llm-cache", help="LLM response cache path"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Convert an EPUB between Chinese variants."""
    _setup_logger(verbose)

    if writing_mode not in WRITING_MODES:
        raise typer.BadParameter(f"writing-mode must be one of {WRITING_MODES}")
    if output_format not in OUTPUT_FORMATS:
        raise typer.BadParameter(f"format must be one of {OUTPUT_FORMATS}")

    if dst is None:
        dst = src.with_name(f"{src.stem}.{target_lang}.{output_format}")

    engine = _build_engine(
        source_lang, target_lang, engine_name, opencc_config, glossary_path, punctuation,
        series=series, llm_provider=llm, llm_model=llm_model, llm_cache_path=llm_cache,
    )

    if output_format == "epub":
        out = convert_epub(src, dst, engine, target_lang, writing_mode=writing_mode)
    else:
        # mobi: convert to a temp epub first, then hand to Calibre.
        with tempfile.TemporaryDirectory(prefix="epubconv-mobi-") as tmp:
            tmp_epub = Path(tmp) / f"{src.stem}.{target_lang}.epub"
            convert_epub(src, tmp_epub, engine, target_lang, writing_mode=writing_mode)
            try:
                out = epub_to_mobi(tmp_epub, dst)
            except CalibreNotFoundError as exc:
                raise typer.BadParameter(str(exc))

    typer.echo(str(out))


@app.command()
def diff(
    src: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True, help="Source EPUB"),
    output: Path = typer.Option(
        None, "--output", "-o", help="Report path (default: <src>.diff.html)"
    ),
    source_lang: str = typer.Option("zh-CN", "--from", "-f", help="Source language"),
    target_lang: str = typer.Option("zh-TW", "--to", "-t", help="Target language"),
    engine_name: str = typer.Option("opencc", "--engine", "-e"),
    opencc_config: str = typer.Option(None, "--opencc-config"),
    glossary_path: Path = typer.Option(
        None, "--glossary", "-g", exists=True, dir_okay=False, readable=True
    ),
    series: str = typer.Option(None, "--series", "-s"),
    punctuation: bool = typer.Option(True, "--punctuation/--no-punctuation"),
    llm: str = typer.Option(None, "--llm"),
    llm_model: str = typer.Option(None, "--llm-model"),
    llm_cache: Path = typer.Option(None, "--llm-cache"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Render a side-by-side HTML diff without writing an output EPUB."""
    _setup_logger(verbose)
    if output is None:
        output = src.with_name(f"{src.stem}.diff.html")
    engine = _build_engine(
        source_lang, target_lang, engine_name, opencc_config, glossary_path, punctuation,
        series=series, llm_provider=llm, llm_model=llm_model, llm_cache_path=llm_cache,
    )
    out = build_diff_report(src, engine, output)
    typer.echo(str(out))


@app.command()
def batch(
    inputs: Path = typer.Argument(..., exists=True, file_okay=False, help="Input directory"),
    outputs: Path = typer.Argument(..., help="Output directory"),
    source_lang: str = typer.Option("zh-CN", "--from", "-f"),
    target_lang: str = typer.Option("zh-TW", "--to", "-t"),
    engine_name: str = typer.Option("opencc", "--engine", "-e"),
    opencc_config: str = typer.Option(None, "--opencc-config"),
    glossary_path: Path = typer.Option(None, "--glossary", "-g", exists=True, dir_okay=False),
    series: str = typer.Option(None, "--series", "-s"),
    punctuation: bool = typer.Option(True, "--punctuation/--no-punctuation"),
    writing_mode: str = typer.Option("preserve", "--writing-mode", "-w"),
    no_resume: bool = typer.Option(False, "--no-resume", help="Re-convert files already marked done"),
    llm: str = typer.Option(None, "--llm"),
    llm_model: str = typer.Option(None, "--llm-model"),
    llm_cache: Path = typer.Option(None, "--llm-cache"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Convert every EPUB under <inputs> into <outputs>, with resume."""
    _setup_logger(verbose)
    if writing_mode not in WRITING_MODES:
        raise typer.BadParameter(f"writing-mode must be one of {WRITING_MODES}")

    engine = _build_engine(
        source_lang, target_lang, engine_name, opencc_config, glossary_path, punctuation,
        series=series, llm_provider=llm, llm_model=llm_model, llm_cache_path=llm_cache,
    )

    def _convert(src: Path, dst: Path) -> Path:
        return convert_epub(src, dst, engine, target_lang, writing_mode=writing_mode)

    result = run_batch(inputs, outputs, _convert, resume=not no_resume)
    typer.echo(
        f"done={len(result.done)} skipped={len(result.skipped)} errored={len(result.errored)}"
    )
    if result.errored:
        for src, err in result.errored:
            typer.echo(f"  ERR {src}: {err}", err=True)
        raise typer.Exit(code=1)


@app.command("extract-names")
def extract_names_cmd(
    src: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Path = typer.Option(
        None, "--output", "-o", help="Write a glossary YAML stub (default: stdout)"
    ),
    min_occurrences: int = typer.Option(3, "--min", help="Minimum occurrences across the book"),
    top: int = typer.Option(100, "--top", help="Limit to top N candidates"),
) -> None:
    """Suggest proper-noun candidates from <src>'s text.

    Output is intentionally noisy — review and prune before pasting into a
    glossary's ``protect`` list.
    """
    candidates = extract_candidates(src, min_occurrences=min_occurrences)[:top]
    if output is None:
        for token, count in candidates:
            typer.echo(f"{count:5d}  {token}")
        return
    lines = ["# epubconv extract-names: review and edit before use", "protect:"]
    for token, count in candidates:
        lines.append(f"  - {token}    # x{count}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo(str(output))


@app.command("list-configs")
def list_configs() -> None:
    """List supported OpenCC source -> target combinations."""
    for (s, t), cfg in sorted(OPENCC_CONFIGS.items()):
        typer.echo(f"{s:10s} -> {t:10s}  ({cfg})")


series_app = typer.Typer(help="Manage series glossaries.", no_args_is_help=True)
app.add_typer(series_app, name="series")


@series_app.command("list")
def series_list_cmd() -> None:
    """List available series glossaries in the config directory."""
    names = list_series()
    if not names:
        typer.echo("(no series glossaries found)")
        return
    for name in names:
        typer.echo(f"{name}\t{series_path(name)}")


@series_app.command("path")
def series_path_cmd(name: str = typer.Argument(...)) -> None:
    """Print the resolved path for a named series glossary."""
    typer.echo(str(series_path(name)))


if __name__ == "__main__":
    app()
