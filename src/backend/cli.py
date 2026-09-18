import json
from pathlib import Path
from typing import Annotated

import typer
from rich import print

from .config import settings
from .logging_config import setup_logging
from .pipeline import run_pipeline

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Scrape DataBank, check data quality and publish analysis."""


@app.command()
def run(
    market: Annotated[
        str | None, typer.Option(help="Market URL slug, e.g. chicago")
    ] = None,
    all_markets: Annotated[
        bool, typer.Option(help="Discover every market from the directory")
    ] = False,
    from_snapshot: Annotated[
        Path | None,
        typer.Option(
            exists=True,
            file_okay=False,
            help="Replay a raw snapshot directory without network access",
        ),
    ] = None,
    data_dir: Annotated[
        Path | None,
        typer.Option(file_okay=False, help="Output root; defaults to BACKEND_DATA_DIR"),
    ] = None,
) -> None:
    """Fetch or replay, validate, analyze, and publish a complete run."""
    setup_logging()
    try:
        result = run_pipeline(
            data_dir or settings.data_dir,
            market=market,
            all_markets=all_markets,
            from_snapshot=from_snapshot,
        )
    except (ValueError, OSError, KeyError) as exc:
        print(f"[red]Run failed: {exc}[/red]")
        raise typer.Exit(code=1) from None
    typer.echo(
        json.dumps(
            {
                "run_id": result.run_id,
                "published": result.published,
                "accepted": result.accepted,
                "rejected": result.rejected,
                "report": str(result.report_path),
                "snapshot": str(result.raw_path),
            }
        )
    )
    if not result.published:
        raise typer.Exit(code=1)
