import httpx2
import typer
import uvicorn
from rich import print

from .config import settings

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """DataBank scraping, analysis and API commands."""


@app.command()
def serve() -> None:
    """Start the development API."""
    print(f"[bold green]Starting {settings.app_name}[/bold green]")
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )


@app.command()
def ping() -> None:
    """Check whether the API is running."""
    try:
        response = httpx2.get(
            f"http://{settings.host}:{settings.port}/api/health",
            timeout=1,
        )
        response.raise_for_status()
    except httpx2.HTTPError:
        print(f"[red]{settings.app_name} is unavailable[/red]")
        raise typer.Exit(code=1) from None

    print(f"[green]{settings.app_name} is healthy[/green]")
