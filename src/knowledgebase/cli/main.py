"""
CLI main module for KnowledgeBase Engine.

Provides command-line interface using Click.
"""

from __future__ import annotations


import asyncio
import json
import os
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

import click
from rich.console import Console
from rich.table import Table

from knowledgebase import __version__
from knowledgebase.core.config import get_settings

console = Console(no_color=True, force_terminal=False)

ABORTED_MESSAGE = "[yellow]Aborted.[/yellow]"

T = TypeVar("T")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously.

    This helper provides a typed bridge between Click's synchronous
    command handlers and the async implementation functions.

    The implementation uses :func:`asyncio.run`, which creates and
    manages an event loop for the duration of the coroutine. This
    avoids the deprecated ``asyncio.get_event_loop`` behaviour that
    emits runtime warnings when no loop is present.
    """
    return asyncio.run(coro)


@click.group()
@click.version_option(version=__version__, prog_name="kb")
def cli() -> None:
    """
    KnowledgeBase Engine CLI.

    Manage and search your semantic knowledgebase from the command line.
    """
    pass


# ============================================================================
# Search Command
# ============================================================================


@cli.command()
@click.argument("query")
@click.option("-i", "--index", default=None, help="Index to search (default: all)")
@click.option("-l", "--limit", default=10, help="Maximum results to return")
@click.option("-s", "--min-score", default=0.5, help="Minimum score threshold")
@click.option("-j", "--json", "output_json", is_flag=True, help="Output as JSON")
def search(query: str, index: str | None, limit: int, min_score: float, output_json: bool) -> None:
    """
    Search the knowledgebase for documents matching QUERY.

    Example:
        kb search "how to configure AWS"
        kb search "error handling" --index code --limit 5
    """

    async def _search() -> None:
        from knowledgebase.embeddings import get_embedding_provider
        from knowledgebase.storage import get_storage_backend

        try:
            # Initialize components
            storage = get_storage_backend()
            await storage.initialize()
            embeddings = get_embedding_provider()

            # Generate embedding
            with console.status("Generating embedding..."):
                query_embedding = await embeddings.embed_query(query)

            # Search
            with console.status("Searching..."):
                results = await storage.search(
                    query_embedding=query_embedding,
                    index_name=index,
                    limit=limit,
                    min_score=min_score,
                )

            await storage.close()

            if output_json:
                output = [
                    {
                        "id": r.document.id,
                        "score": r.score,
                        "index": r.document.index_name,
                        "title": r.document.metadata.title,
                        "content": (
                            r.document.content[:200] + "..."
                            if len(r.document.content) > 200
                            else r.document.content
                        ),
                    }
                    for r in results
                ]
                click.echo(json.dumps(output))
            else:
                if not results:
                    console.print("[yellow]No results found.[/yellow]")
                    return

                table = Table(title=f"Search Results for: {query}")
                table.add_column("Score", style="cyan", width=8)
                table.add_column("Index", style="magenta", width=15)
                table.add_column("Title", style="green", width=30)
                table.add_column("Preview", style="white", width=50)

                for r in results:
                    preview = (
                        r.document.content[:100] + "..."
                        if len(r.document.content) > 100
                        else r.document.content
                    )
                    preview = preview.replace("\n", " ")
                    table.add_row(
                        f"{r.score:.3f}",
                        r.document.index_name,
                        r.document.metadata.title or r.document.id,
                        preview,
                    )

                console.print(table)
                console.print(f"\n[dim]Found {len(results)} results[/dim]")

        except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    run_async(_search())


# ============================================================================
# Add Command
# ============================================================================


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("-i", "--index", default="knowledgebase", help="Target index")
@click.option("--id", "doc_id", default=None, help="Document ID (default: filename)")
@click.option("-t", "--title", default=None, help="Document title")
def add(file_path: str, index: str, doc_id: str | None, title: str | None) -> None:
    """
    Add a document to the knowledgebase.

    Example:
        kb add README.md
        kb add docs/guide.md --index documentation --title "User Guide"
    """

    async def _add() -> None:
        from knowledgebase.core.models import Document, DocumentMetadata
        from knowledgebase.embeddings import get_embedding_provider
        from knowledgebase.storage import get_storage_backend

        try:
            path = Path(file_path)

            # Prefer UTF-8, but fall back to a more permissive decode so that
            # partially-invalid files (or mixed encodings) do not cause the
            # entire indexing run to fail.
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = path.read_bytes().decode("utf-8", errors="ignore")

            document_id = doc_id or path.stem

            # Initialize components
            storage = get_storage_backend()
            await storage.initialize()
            embeddings = get_embedding_provider()

            # Generate embedding
            with console.status("Generating embedding..."):
                embedding = await embeddings.embed_text(content)

            # Create document
            doc = Document(
                id=document_id,
                content=content,
                embedding=embedding,
                index_name=index,
                metadata=DocumentMetadata(
                    title=title or path.name,
                    path=str(path.absolute()),
                    source_type="file",
                ),
            )

            # Store document
            with console.status("Storing document..."):
                await storage.add_document(doc)

            await storage.close()

            console.print(f"[green]✓ Added document '{document_id}' to index '{index}'[/green]")

        except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    run_async(_add())


# ============================================================================
# Remove Command
# ============================================================================


@cli.command()
@click.argument("doc_id")
@click.option("-i", "--index", required=True, help="Index containing the document")
@click.option("-f", "--force", is_flag=True, help="Skip confirmation")
def remove(doc_id: str, index: str, force: bool) -> None:
    """
    Remove a document from the knowledgebase.

    Example:
        kb remove readme --index knowledgebase
    """

    async def _remove() -> None:
        from knowledgebase.storage import get_storage_backend

        try:
            if (not force) and (
                not click.confirm(f"Remove document '{doc_id}' from index '{index}'?")
            ):
                console.print(ABORTED_MESSAGE)
                return

            storage = get_storage_backend()
            await storage.initialize()

            deleted = await storage.delete_document(doc_id, index)
            await storage.close()

            if deleted:
                console.print(f"[green]✓ Removed document '{doc_id}' from index '{index}'[/green]")
            else:
                console.print(f"[yellow]Document '{doc_id}' not found in index '{index}'[/yellow]")

        except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    run_async(_remove())


# ============================================================================
# Status Command
# ============================================================================


@cli.command()
@click.option("-j", "--json", "output_json", is_flag=True, help="Output as JSON")
@click.option(
    "-f",
    "--full",
    "full_diagnostics",
    is_flag=True,
    help="Run comprehensive diagnostics on all tools and endpoints",
)
@click.option("-r", "--report", is_flag=True, help="Generate and save detailed diagnostic report")
def status(output_json: bool, full_diagnostics: bool, report: bool) -> None:
    """
    Show the status of the knowledgebase service.

    Example:
        kb status                    # Quick health check
        kb status --json            # Health check as JSON
        kb status --full            # Comprehensive tool and endpoint tests
        kb status --full --report   # Tests + save detailed report
    """

    async def _status() -> None:
        from knowledgebase.embeddings import get_embedding_provider
        from knowledgebase.storage import get_storage_backend

        try:
            settings = get_settings()

            # Full comprehensive diagnostics
            if full_diagnostics:
                from rich.table import Table

                from knowledgebase.services.status_service import StatusService

                status_service = StatusService(settings)
                await status_service.initialize()

                with console.status("Running comprehensive diagnostics..."):
                    full_status = await status_service.get_full_status()

                # Display results
                console.print("\n[bold]AegisCMCP Comprehensive Status Report[/bold]")
                status_color = "green" if full_status.overall_status == "healthy" else "yellow"
                console.print(
                    f"Overall Status: [{status_color}]{full_status.overall_status.upper()}[/]\n"
                )

                # Tools table
                tools_table = Table(title="MCP Tools Status")
                tools_table.add_column("Tool", style="cyan")
                tools_table.add_column("Status", style="magenta")
                tools_table.add_column("Duration", justify="right")
                for tool in full_status.tools:
                    status_icon = "✓" if tool.status == "pass" else "✗"
                    tools_table.add_row(
                        tool.name,
                        f"[{'green' if tool.status == 'pass' else 'red'}]{status_icon} {tool.status}[/]",
                        f"{tool.duration_ms:.1f}ms",
                    )
                console.print(tools_table)

                # Endpoints table
                endpoints_table = Table(title="API Endpoints Status")
                endpoints_table.add_column("Endpoint", style="cyan")
                endpoints_table.add_column("Method", style="magenta")
                endpoints_table.add_column("Status", justify="right")
                endpoints_table.add_column("Duration", justify="right")
                for endpoint in full_status.endpoints:
                    status_code = endpoint.status_code or "N/A"
                    status_color = (
                        "green" if endpoint.status_code and endpoint.status_code < 400 else "red"
                    )
                    endpoints_table.add_row(
                        endpoint.path,
                        endpoint.method,
                        f"[{status_color}]{status_code}[/]",
                        f"{endpoint.duration_ms:.1f}ms",
                    )
                console.print(endpoints_table)

                # Statistics
                stats_table = Table(title="System Statistics")
                stats_table.add_column("Metric", style="cyan")
                stats_table.add_column("Value", style="magenta")
                stats_table.add_row("Total Documents", str(full_status.stats.total_documents))
                stats_table.add_row("Total Indices", str(full_status.stats.total_indices))
                stats_table.add_row("Uptime", full_status.stats.uptime_formatted)
                stats_table.add_row("Memory Usage", f"{full_status.stats.memory_usage_mb:.1f} MB")
                stats_table.add_row("Storage Usage", f"{full_status.stats.storage_usage_gb:.2f} GB")
                console.print(stats_table)

                # Diagnostics
                if full_status.diagnostics.issues:
                    console.print("\n[bold yellow]Issues Detected:[/bold yellow]")
                    for issue in full_status.diagnostics.issues:
                        console.print(f"  [{issue.severity}]{issue.component}[/]: {issue.message}")
                        if issue.recommendation:
                            console.print(f"    → {issue.recommendation}")

                if report:
                    # Save report
                    from datetime import datetime

                    report_dir = Path("reports/status")
                    report_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    report_file = report_dir / f"status-{timestamp}.json"
                    report_file.write_text(
                        json.dumps(full_status.model_dump(), default=str, indent=2)
                    )
                    console.print(f"\n[green]✓ Report saved to {report_file}[/green]")

                if output_json:
                    click.echo(json.dumps(full_status.model_dump(), default=str))
            else:
                # Quick health check
                from knowledgebase.embeddings.factory import resolve_embedding_provider

                status_data: dict[str, Any] = {
                    "version": __version__,
                    "environment": settings.env,
                    "infraos_environment": settings.infraos_environment,
                    "aegis_environment": settings.infraos_environment,
                    "components": {},
                }

                # Check storage
                try:
                    storage = get_storage_backend()
                    await storage.initialize()
                    storage_health = await storage.health_check()
                    status_data["components"]["storage"] = storage_health
                    await storage.close()
                except Exception as e:
                    status_data["components"]["storage"] = {"healthy": False, "error": str(e)}

                # Check embeddings
                try:
                    embeddings = get_embedding_provider()
                    embeddings_health = await embeddings.health_check()
                    # Resolve provider to show whether it was auto-resolved or explicit
                    resolved_provider = resolve_embedding_provider(settings.embedding)
                    embeddings_health["resolved_provider"] = resolved_provider
                    status_data["components"]["embeddings"] = embeddings_health
                except Exception as e:
                    status_data["components"]["embeddings"] = {"healthy": False, "error": str(e)}

                if output_json:
                    click.echo(json.dumps(status_data))
                else:
                    console.print(f"\n[bold]KnowledgeBase Engine v{__version__}[/bold]")
                    console.print(f"App Environment: {settings.env}")
                    console.print(f"AegisCLI Environment: {settings.infraos_environment}\n")

                    for component, health in status_data["components"].items():
                        healthy = health.get("healthy", False)
                        status_icon = "[green]✓[/green]" if healthy else "[red]✗[/red]"
                        console.print(f"{status_icon} {component.title()}")

                        if "backend" in health:
                            console.print(f"   Backend: {health['backend']}")
                        if "provider" in health:
                            console.print(f"   Provider: {health['provider']}")
                        if "resolved_provider" in health:
                            explicit_marker = (
                                " (explicit)" if settings.embedding.provider else " (auto-resolved)"
                            )
                            console.print(
                                f"   Resolved Provider: {health['resolved_provider']}{explicit_marker}"
                            )
                        if "model" in health:
                            console.print(f"   Model: {health['model']}")
                        if "latency_ms" in health:
                            console.print(f"   Latency: {health['latency_ms']}ms")
                        if "document_count" in health:
                            console.print(f"   Documents: {health['document_count']}")
                        if "error" in health:
                            console.print(f"   [red]Error: {health['error']}[/red]")

        except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    run_async(_status())


# ============================================================================
# Sync Command
# ============================================================================


def _print_sync_report(report: Any) -> None:
    """Print a per-index synced/skipped/failed summary table for a SyncReport."""
    table = Table(title=f"Sync report ({report.target})")
    table.add_column("Index", style="cyan")
    table.add_column("Source", style="white")
    table.add_column("Files", style="white", justify="right")
    table.add_column("Synced", style="green", justify="right")
    table.add_column("Errors", style="red", justify="right")

    for index_result in report.index_results:
        table.add_row(
            index_result.index,
            index_result.sync_source,
            str(index_result.files_discovered),
            str(index_result.documents_synced),
            str(len(index_result.errors)),
        )

    console.print(table)
    for error in report.errors:
        console.print(f"[red]  {error}[/red]")


@cli.command()
@click.argument("index_name", required=False)
@click.option("-i", "--index", default=None, help="Index to sync (default: all)")
@click.option("--all", "sync_all", is_flag=True, help="Sync all configured indices")
@click.option(
    "--target",
    type=click.Choice(["local", "dev", "all"]),
    default="local",
    help="Sync destination: local (this instance), dev (configured remote), or all",
)
@click.option("--dry-run", is_flag=True, help="Show what would be synced without making changes")
def sync(
    index_name: str | None,
    index: str | None,
    sync_all: bool,
    target: str,
    dry_run: bool,
) -> None:
    """
    Sync documents from configured sources into this instance and/or a remote AegisCMCP.

    You can specify the index either positionally or via --index.

    Examples:
        kb sync --all
        kb sync --index knowledge --target dev
        kb sync --all --target all --dry-run
    """

    async def _sync() -> None:
        from knowledgebase.sync import AegisCMCPSyncService, load_sync_targets

        if index and index_name and index != index_name:
            console.print(
                "[red]Conflicting index values provided (positional vs --index). "
                "Use only one or ensure they match.[/red]"
            )
            sys.exit(1)

        effective_index = index or index_name
        if not effective_index and not sync_all:
            console.print("[yellow]Specify an INDEX name or use --all[/yellow]")
            sys.exit(1)

        indices = [effective_index] if effective_index else None
        sync_service = AegisCMCPSyncService()

        if dry_run:
            config = sync_service._load_config()
            plans = sync_service._resolve_plans(config, indices)
            if not plans:
                console.print("[yellow]No matching indices found in configuration[/yellow]")
                return
            console.print("[yellow]Dry run mode - no changes will be made[/yellow]\n")
            for plan in plans:
                console.print(f"[bold]{plan.index_name}[/bold]  ({plan.sync_source})")
                if not plan.sync_source.exists():
                    console.print("  [red]Source path does not exist[/red]")
                    continue
                file_count = len(sync_service.discover_files(plan))
                console.print(f"  Would sync {file_count} files")
            return

        targets = ["local", "dev"] if target == "all" else [target]

        try:
            for one_target in targets:
                if one_target == "local":
                    report = await sync_service.sync_local(indices=indices)
                else:
                    remote_targets = load_sync_targets()
                    dev_target = remote_targets.get("dev")
                    if not isinstance(dev_target, dict) or not dev_target.get("base_url"):
                        console.print("[red]No 'dev' sync target configured in cfg/sync.json[/red]")
                        sys.exit(1)
                    base_url = str(dev_target["base_url"])
                    api_key_env = dev_target.get("api_key_env")
                    api_key = (
                        os.getenv(api_key_env)
                        if isinstance(api_key_env, str) and api_key_env
                        else None
                    )
                    report = await sync_service.sync_dev(
                        base_url=base_url, api_key=api_key, indices=indices
                    )

                _print_sync_report(report)

            console.print("\n[green]✓ Sync complete[/green]")

        except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    run_async(_sync())


# ============================================================================
# Index Commands
# ============================================================================


@cli.group()
def index() -> None:
    """Manage indices."""
    pass


@index.command("list")
@click.option("-j", "--json", "output_json", is_flag=True, help="Output as JSON")
def list_indices(output_json: bool) -> None:
    """List all indices."""

    async def _list() -> None:
        from knowledgebase.storage import get_storage_backend

        try:
            storage = get_storage_backend()
            await storage.initialize()
            indices = await storage.list_indices()
            await storage.close()

            if output_json:
                output = [i.model_dump() for i in indices]
                click.echo(json.dumps(output, default=str))
            else:
                if not indices:
                    console.print("[yellow]No indices found.[/yellow]")
                    return

                table = Table(title="Indices")
                table.add_column("Name", style="cyan")
                table.add_column("Documents", style="green", justify="right")
                table.add_column("Description", style="white")

                for idx in indices:
                    table.add_row(idx.name, str(idx.document_count), idx.description or "-")

                console.print(table)

        except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    run_async(_list())


@index.command("create")
@click.argument("name")
@click.option("-d", "--description", default="", help="Index description")
def create_index(name: str, description: str) -> None:
    """Create a new index."""

    async def _create() -> None:
        from knowledgebase.storage import get_storage_backend

        try:
            storage = get_storage_backend()
            await storage.initialize()
            await storage.create_index(name)
            await storage.close()

            console.print(f"[green]✓ Created index '{name}'[/green]")

        except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    run_async(_create())


@index.command("delete")
@click.argument("name")
@click.option("-f", "--force", is_flag=True, help="Skip confirmation")
def delete_index(name: str, force: bool) -> None:
    """Delete an index and all its documents."""

    async def _delete() -> None:
        from knowledgebase.storage import get_storage_backend

        try:
            if (not force) and (not click.confirm(f"Delete index '{name}' and all its documents?")):
                console.print(ABORTED_MESSAGE)
                return

            storage = get_storage_backend()
            await storage.initialize()
            await storage.delete_index(name)
            await storage.close()

            console.print(f"[green]✓ Deleted index '{name}'[/green]")

        except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    run_async(_delete())


# ============================================================================
# Runbook Commands
# ============================================================================


@cli.group()
def runbook() -> None:
    """Manage runbooks."""
    pass


@runbook.command("list")
@click.option("-j", "--json", "output_json", is_flag=True, help="Output as JSON")
def list_runbooks(output_json: bool) -> None:
    """List all available runbooks."""
    import json as json_module

    def _list() -> None:
        from knowledgebase.runbooks.service import RunbookService

        try:
            service = RunbookService()
            result = service.list_runbooks()

            if output_json:
                click.echo(json_module.dumps(result, indent=2, default=str))
            else:
                if result["count"] == 0:
                    console.print("[yellow]No runbooks found.[/yellow]")
                    return

                table = Table(title="Runbooks")
                table.add_column("Name", style="cyan")
                table.add_column("Path", style="white")
                for rb in result["runbooks"]:
                    table.add_row(rb["name"], rb["path"])
                console.print(table)
                console.print(f"\n[dim]Found {result['count']} runbooks[/dim]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    _list()


@runbook.command("get")
@click.argument("name")
def get_runbook(name: str) -> None:
    """Get a runbook by name."""

    def _get() -> None:
        from knowledgebase.runbooks.service import RunbookService

        try:
            service = RunbookService()
            result = service.get_runbook(name)
            if not result:
                console.print(f"[yellow]Runbook '{name}' not found.[/yellow]")
                return
            console.print(f"[bold]Runbook: {result['name']}[/bold]\n")
            console.print(result["content"])
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    _get()


@runbook.command("create")
@click.argument("name")
@click.option("-f", "--file", "file_path", type=click.Path(exists=True), help="File to import")
@click.option("-c", "--content", "content_text", help="Content text")
def create_runbook(name: str, file_path: str | None, content_text: str | None) -> None:
    """Create a new runbook."""

    def _create() -> None:
        from knowledgebase.runbooks.service import RunbookService

        try:
            content = content_text or ""
            if file_path:
                path = Path(file_path)
                content = path.read_text(encoding="utf-8")
            if not content:
                console.print("[red]Error: provide either --file or --content[/red]")
                sys.exit(1)
            service = RunbookService()
            service.create_runbook(name, content, file_path)
            console.print(f"[green]✓ Created runbook '{name}'[/green]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    _create()


@runbook.command("delete")
@click.argument("name")
@click.option("-f", "--force", is_flag=True, help="Skip confirmation")
def delete_runbook(name: str, force: bool) -> None:
    """Delete a runbook."""

    def _delete() -> None:
        from knowledgebase.runbooks.service import RunbookService

        try:
            if (not force) and (not click.confirm(f"Delete runbook '{name}'?")):
                console.print(ABORTED_MESSAGE)
                return
            service = RunbookService()
            result = service.delete_runbook(name, force)
            if result.get("deleted"):
                console.print(f"[green]✓ Deleted runbook '{name}'[/green]")
            else:
                console.print(f"[yellow]{result.get('error', 'Not found')}[/yellow]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    _delete()


@runbook.command("prompt")
@click.argument("keyword")
@click.option("-v", "--vars", "vars_str", default="", help="Comma-separated key=value variables")
def get_runbook_prompt(keyword: str, vars_str: str) -> None:
    """Get a runnable prompt from a runbook."""

    def _prompt() -> None:
        from knowledgebase.runbooks.service import RunbookService

        try:
            service = RunbookService()
            result = service.get_prompt(keyword, vars_str)
            console.print(f"[bold]Prompt from runbook: {result.runbook_name}[/bold]\n")
            console.print(result.prompt_text)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    _prompt()


@runbook.command("reindex")
def reindex_runbooks() -> None:
    """Reindex all runbooks."""

    async def _reindex() -> None:
        from knowledgebase.runbooks.service import RunbookService

        try:
            service = RunbookService()
            result = service.reindex_runbooks()
            console.print(f"[green]✓ Reindexed {result['count']} runbooks[/green]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    run_async(_reindex())


@runbook.command("log")
@click.argument("name")
@click.option("-c", "--content", "log_content", help="Log content")
@click.option("-f", "--file", "log_file", type=click.Path(exists=True), help="Log file")
def create_runbook_log(name: str, log_content: str | None, log_file: str | None) -> None:
    """Create an execution log entry."""

    def _log() -> None:
        from knowledgebase.runbooks.service import RunbookService

        try:
            content = log_content
            if log_file:
                path = Path(log_file)
                content = path.read_text(encoding="utf-8")
            if not content:
                console.print("[red]Error: provide either --file or --content[/red]")
                sys.exit(1)
            service = RunbookService()
            service.create_log(name, content)
            console.print("[green]✓ Log entry created[/green]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            sys.exit(1)

    _log()


if __name__ == "__main__":
    cli()
