"""CLI for DiaType.

Provides `diatype generate` for terminal use and `diatype serve` to launch
the notebook web interface. The new `history` command lists or loads
versioned diagrams from the file-based history.
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
    given both .mmd and .md files are written. The diagram is also saved
    to the versioned history.
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


@app.command("history")
def history_command(
    diagram_id: Annotated[
        str | None,
        typer.Option("--id", "-i", help="Diagram series ID to load (lists history if omitted)"),
    ] = None,
    version: Annotated[
        int,
        typer.Option("--version", "-v", min=1, help="Version number to load when an ID is supplied."),
    ] = 1,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Path to save loaded diagram (without extension).",
            dir_okay=False,
            writable=True,
        ),
    ] = None,
) -> None:
    """List diagram history or load a specific version from the file-based history.

    History is stored as JSON files in the configured history directory.
    """
    engine = DiagramEngine(Settings.load())

    if diagram_id:
        diagram = engine.load_version(diagram_id, version)
        if not diagram:
            typer.secho(
                f"Error: Version v{version} of diagram '{diagram_id}' not found.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)

        typer.secho(
            f"\nLoaded Diagram (ID: {diagram_id} v{version})",
            fg=typer.colors.GREEN,
            bold=True,
        )
        typer.echo(diagram.to_markdown())

        if output:
            mmd_path = output.with_suffix(".mmd")
            mmd_path.write_text(diagram.mermaid, encoding="utf-8")
            typer.secho(f"Saved Mermaid source → {mmd_path}", fg=typer.colors.CYAN)

            md_path = output.with_suffix(".md")
            md_path.write_text(diagram.to_markdown(), encoding="utf-8")
            typer.secho(f"Saved Markdown → {md_path}", fg=typer.colors.CYAN)
    else:
        history = engine.list_history(limit=15)
        if not history:
            typer.echo("No history entries yet. Generate some diagrams first!")
            return

        typer.secho("\nDiagram History", fg=typer.colors.BRIGHT_GREEN, bold=True)
        for entry in history:
            ts = entry.get("created_at", "N/A")[:16]
            typer.echo(
                f"{ts}  {entry['id']}_v{entry['version']:02d}  "
                f"{entry.get('diagram_type', 'flowchart'):<12} {entry.get('title', 'Untitled')}"
            )
        typer.echo(
            "\n[italic]Tip: use [bold]--id <ID> --version <N>[/bold] to load a specific version.[/italic]"
        )


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
