"""
Command-line interface for KnowledgeBase Engine.

Provides CLI commands for:
- Searching the knowledgebase
- Adding and removing documents
- Syncing from external sources
- Checking service status
"""

from __future__ import annotations

from typing import Any

__all__ = ["cli"]


def __getattr__(name: str) -> Any:
    """Lazily import the CLI entrypoint.

    This keeps API/runtime imports from pulling in optional CLI presentation
    dependencies (for example ``rich``) during normal server startup.
    """

    if name == "cli":
        from knowledgebase.cli.main import cli as command_line_interface

        return command_line_interface
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
