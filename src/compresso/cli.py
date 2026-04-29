from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from tqdm import tqdm

from compresso import __version__
from compresso.core import (
    ALL_FORMATS,
    CannotFitError,
    FitResult,
    LosslessTooBigError,
    convert,
    normalize_format,
)
from compresso.sizing import SizeParseError, format_size, parse_size

console = Console()
err_console = Console(stderr=True)


def _resolve_output(source: Path, target_format: str, output: Path | None) -> Path:
    if output is not None:
        return output
    return source.with_suffix(f".{normalize_format(target_format)}")


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="compresso")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-t",
    "--to",
    "target_format",
    required=True,
    type=click.Choice(sorted(ALL_FORMATS), case_sensitive=False),
    help="Output format.",
)
@click.option(
    "-m",
    "--max",
    "max_size",
    type=str,
    default=None,
    help="Maximum output size, e.g. 3MB, 500KB, 1048576. Omit for no size cap.",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output path. Defaults to <source-stem>.<target-format> next to the source.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite the output file if it already exists.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Skip the downscale prompt for lossless formats; auto-approve downscaling.",
)
def cli(
    source: Path,
    target_format: str,
    max_size: str | None,
    output: Path | None,
    force: bool,
    yes: bool,
) -> None:
    """Convert SOURCE to a different format and (optionally) fit under a size cap.

    Examples:

      compresso photo.heif --to jpg --max 3MB

      compresso scan.pdf --to png -o scan.png

      compresso photo.png --to jpg --max 500KB --force
    """
    fmt = normalize_format(target_format)
    out_path = _resolve_output(source, fmt, output)

    cap_bytes: int | None = None
    if max_size is not None:
        try:
            cap_bytes = parse_size(max_size)
        except SizeParseError as exc:
            err_console.print(f"[red]Error:[/red] {exc}")
            sys.exit(2)

    src_size = source.stat().st_size
    err_console.print(
        f"[bold]Converting[/bold] {source.name} ({format_size(src_size)}) "
        f"→ [cyan]{fmt}[/cyan]"
        + (f" under [magenta]{format_size(cap_bytes)}[/magenta]" if cap_bytes else "")
    )

    progress: tqdm | None = None  # type: ignore[type-arg]
    if cap_bytes is not None and fmt not in {"gif", "png"}:
        progress = tqdm(desc="searching", unit="try", leave=False)

    def _on_attempt(quality: int, encoded_bytes: int) -> None:
        if progress is not None:
            progress.set_postfix_str(f"q={quality} → {format_size(encoded_bytes)}")
            progress.update(1)

    try:
        result = _run(
            source=source,
            target_format=fmt,
            output=out_path,
            cap_bytes=cap_bytes,
            force=force,
            yes=yes,
            on_attempt=_on_attempt,
        )
    except FileExistsError as exc:
        if progress is not None:
            progress.close()
        err_console.print(f"[red]Error:[/red] {exc} Pass --force to overwrite.")
        sys.exit(1)
    except CannotFitError as exc:
        if progress is not None:
            progress.close()
        err_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    finally:
        if progress is not None:
            progress.close()

    _print_result(result, src_size, cap_bytes)


def _run(
    source: Path,
    target_format: str,
    output: Path,
    cap_bytes: int | None,
    force: bool,
    yes: bool,
    on_attempt: object,
) -> FitResult:
    try:
        return convert(
            source=source,
            target_format=target_format,
            output=output,
            max_size=cap_bytes,
            overwrite=force,
            allow_downscale_lossless=yes,
            on_attempt=on_attempt,
        )
    except LosslessTooBigError as exc:
        err_console.print(
            f"[yellow]Lossless {target_format.upper()} is "
            f"{format_size(exc.attempted_size)}[/yellow] — over the "
            f"{format_size(exc.cap)} cap. Lossless formats can't shrink further "
            "without dropping resolution."
        )
        if not click.confirm("Downscale to fit?", default=True):
            raise CannotFitError("Aborted: user declined to downscale.") from exc
        return convert(
            source=source,
            target_format=target_format,
            output=output,
            max_size=cap_bytes,
            overwrite=force,
            allow_downscale_lossless=True,
            on_attempt=on_attempt,
        )


def _print_result(result: FitResult, src_size: int, cap_bytes: int | None) -> None:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("output", str(result.output_path))
    table.add_row("size", f"{format_size(result.final_bytes)} ({result.final_bytes:,} B)")
    if cap_bytes is not None:
        slack = cap_bytes - result.final_bytes
        table.add_row("under cap by", format_size(max(0, slack)))
    table.add_row("source size", format_size(src_size))
    if result.quality is not None:
        table.add_row("jpeg quality", str(result.quality))
    if result.scale != 1.0:
        table.add_row("scale", f"{result.scale:.2f}x")
    if result.pages > 1:
        table.add_row("pages", str(result.pages))
    console.print(table)
