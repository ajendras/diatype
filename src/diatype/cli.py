"""CLI for DiaType.

Provides `diatype generate` for terminal use and `diatype serve` to launch
the notebook web interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import Settings
from .generator import DiagramEngine
from .models import Diagram

app = typer.Typer(
    help="DiaType — Natural language → Mermaid diagrams",
    rich_markup_mode="rich",
    add_completion=True,
)


@app.command("generate")
def generate_command(
    prompt: Annotated[
        str,
        typer.Argument(
            help="Natural language description of the diagram you want to create."
        ),
    ],
    diagram_type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help="Type of diagram to generate.",
        ),
    ] = "flowchart",
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Path to save the Mermaid file (without extension).",
            dir_okay=False,
            writable=True,
        ),
    ] = None,
    explain: Annotated[
        bool,
        typer.Option("--explain", "-e", help="Also print an explanation."),
    ] = False,
) -> None:
    """Generate a Mermaid diagram from a plain English prompt.

    The diagram is always validated before being returned. When --output is
    given both .mmd and .md files are written.
    """
    if not prompt or len(prompt.strip()) < 8:
        typer.secho("Error: Prompt must be at least 8 characters.", fg=typer.colors.RED)
        raise typer.Exit(1)

    engine = DiagramEngine(Settings.load())

    try:
        diagram: Diagram = engine.generate(prompt.strip(), diagram_type)
        typer.secho("\nGenerated Diagram", fg=typer.colors.GREEN, bold=True)
        typer.echo(diagram.to_markdown())

        if explain:
            explanation = engine.explain(diagram)
            typer.secho("\nExplanation", fg=typer.colors.GREEN, bold=True)
            typer.echo(explanation)

        if output:
            mmd_path = output.with_suffix(".mmd")
            mmd_path.write_text(diagram.mermaid, encoding="utf-8")
            typer.secho(f"Saved Mermaid source → {mmd_path}", fg=typer.colors.CYAN)

            md_path = output.with_suffix(".md")
            md_path.write_text(diagram.to_markdown(), encoding="utf-8")
            typer.secho(f"Saved Markdown → {md_path}", fg=typer.colors.CYAN)

        typer.echo(
            "\n[italic]Tip: Open the hand-drawn notebook with [bold]diatype serve[/bold][/italic]"
        )

    except Exception as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


@app.command("serve")
def serve_command(
    host: Annotated[str, typer.Option("--host", "-H")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p")] = 8000,
    reload: Annotated[bool, typer.Option("--reload", "-r")] = False,
) -> None:
    """Launch the hand-drawn notebook web interface."""
    import uvicorn

    typer.secho(
        f"🌟 Starting DiaType notebook on http://{host}:{port}",
        fg=typer.colors.BRIGHT_GREEN,
        bold=True,
    )
    typer.echo("Press Ctrl+C to stop the server.\n")

    uvicorn.run(
        "diatype.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command("version")
def version_command() -> None:
    """Print the current version."""
    typer.echo(f"DiaType v{__version__}")


if __name__ == "__main__":
    app()
