"""CLI entrypoint for launching the KnowledgeBase UI applet."""

from __future__ import annotations

import os
import webbrowser

import click
import uvicorn

from knowledgebase.ui.app import DEFAULT_API_BASE_URL, create_app


@click.command()
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Host interface for the UI applet server.",
)
@click.option(
    "--port",
    default=8080,
    type=int,
    show_default=True,
    help="Port for the UI applet server.",
)
@click.option(
    "--open-browser/--no-open-browser",
    "open_browser",
    default=True,
    show_default=True,
    help="Automatically open the UI in a browser tab after startup.",
)
def main(host: str, port: int, open_browser: bool) -> None:
    """Launch the KnowledgeBase UI applet server."""
    api_base_url = os.getenv("BaylyAI_KNOWLEDGEBASE_HOST", DEFAULT_API_BASE_URL)

    try:
        app = create_app(api_base_url=api_base_url)
    except Exception as exc:
        raise click.ClickException(f"Failed to start UI applet: {exc}") from exc

    if open_browser:
        # NOSONAR local dev applet server; no TLS listener on the bound host/port
        webbrowser.open(f"http://{host}:{port}/", new=2)  # NOSONAR

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":  # pragma: no cover - CLI invocation
    main()
