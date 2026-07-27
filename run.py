"""CLI entry point for the Skill Bill pipeline."""
import os
import click
from pathlib import Path

from skillbill.pipeline import Pipeline


@click.group()
def cli():
    """Skill Bill vol. 1 — turn YouTube playlists into Claude Code skills."""
    pass


@cli.command()
@click.argument("url")
@click.option("--stage", type=click.Choice(
    ["discovery", "transcript", "download", "screenshots", "capture", "generate", "all"]
), default="all", help="Run a specific pipeline stage")
@click.option("--transcript-only", is_flag=True, help="Skip video download and screenshots")
@click.option("--no-haiku", is_flag=True, help="Disable Claude Haiku for segment classification")
@click.option("--data-dir", type=click.Path(), default=None, help="Custom data directory")
@click.option("--cookies-from", type=str, default=None, help="Browser to read cookies from (e.g. safari, chrome, firefox)")
@click.option("--refine", is_flag=True, help="Enable Pro AI refinement (requires ANTHROPIC_API_KEY)")
def playlist(url, stage, transcript_only, no_haiku, data_dir, cookies_from, refine):
    """Process a YouTube playlist into a knowledge base."""
    data_path = Path(data_dir) if data_dir else None
    p = Pipeline(data_dir=data_path, use_haiku=not no_haiku, cookies_from=cookies_from, refine=refine)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "") if refine else ""
    if refine and not api_key:
        click.echo("Error: --refine requires ANTHROPIC_API_KEY environment variable")
        return

    if transcript_only:
        result = p.run_transcript_only(url, api_key=api_key)
        click.echo(f"Done: {result}")
        return

    if stage == "all":
        result = p.run_all(url, api_key=api_key)
        click.echo(f"Done: {result}")
    elif stage == "discovery":
        p.run_discovery(url)
    elif stage == "transcript":
        p.run_discovery(url)
        p.run_transcripts()
    else:
        click.echo(f"Stage '{stage}' requires previous stages. Use --stage all.")


@cli.command()
@click.argument("url")
@click.option("--transcript-only", is_flag=True, help="Skip video download and screenshots")
@click.option("--no-haiku", is_flag=True, help="Disable Claude Haiku for segment classification")
@click.option("--data-dir", type=click.Path(), default=None, help="Custom data directory")
@click.option("--cookies-from", type=str, default=None, help="Browser to read cookies from (e.g. safari, chrome, firefox)")
@click.option("--refine", is_flag=True, help="Enable Pro AI refinement (requires ANTHROPIC_API_KEY)")
def video(url, transcript_only, no_haiku, data_dir, cookies_from, refine):
    """Process a single YouTube video into a one-lesson knowledge base.

    Discovery treats a bare video URL as a one-item course, so this runs
    the same stages as `playlist`.
    """
    data_path = Path(data_dir) if data_dir else None
    p = Pipeline(data_dir=data_path, use_haiku=not no_haiku, cookies_from=cookies_from, refine=refine)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "") if refine else ""
    if refine and not api_key:
        click.echo("Error: --refine requires ANTHROPIC_API_KEY environment variable")
        return

    if transcript_only:
        result = p.run_transcript_only(url, api_key=api_key)
    else:
        result = p.run_all(url, api_key=api_key)
    click.echo(f"Done: {result}")


@cli.command()
@click.option("--port", default=8000, type=int, help="Port to serve on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
def serve(port, host):
    """Start the web interface."""
    import uvicorn
    from web.server import app

    click.echo(f"Starting Skill Bill at http://{host}:{port}")
    click.echo("Press Ctrl+C to stop")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    cli()
