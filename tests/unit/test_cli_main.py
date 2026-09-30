"""Unit tests for the kb CLI commands.

These tests use Click's CliRunner with fake storage and embedding
backends so they do not require external services.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from knowledgebase.cli.main import cli
from knowledgebase.core.models import Document, DocumentMetadata, IndexInfo, SearchResult


class FakeStorage:
    """In-memory fake storage backend for CLI tests."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], Document] = {}
        self.indices: set[str] = set()

    # Lifecycle -------------------------------------------------------------

    async def initialize(self) -> None:  # pragma: no cover - trivial
        return None

    async def close(self) -> None:  # pragma: no cover - trivial
        return None

    # Index operations ------------------------------------------------------

    async def create_index(
        self, name: str, metadata_schema: dict[str, str] | None = None
    ) -> None:  # noqa: ARG002
        self.indices.add(name)

    async def delete_index(self, name: str) -> None:
        self.indices.discard(name)
        self.docs = {k: v for k, v in self.docs.items() if k[0] != name}

    async def list_indices(self) -> list[IndexInfo]:
        items: list[IndexInfo] = []
        for idx in sorted(self.indices):
            count = sum(1 for (name, _), _doc in self.docs.items() if name == idx)
            items.append(
                IndexInfo(
                    name=idx,
                    description="",
                    document_count=count,
                )
            )
        return items

    # Document operations ---------------------------------------------------

    async def add_document(self, document: Document) -> None:
        key = (document.index_name, document.id)
        self.indices.add(document.index_name)
        self.docs[key] = document

    async def get_document(self, doc_id: str, index_name: str) -> Document | None:
        return self.docs.get((index_name, doc_id))

    async def delete_document(self, doc_id: str, index_name: str) -> bool:
        key = (index_name, doc_id)
        if key in self.docs:
            del self.docs[key]
            return True
        return False

    async def list_documents(
        self,
        index_name: str,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Document], int]:
        docs = [doc for (idx, _), doc in sorted(self.docs.items()) if idx == index_name]
        total = len(docs)
        return docs[offset : offset + limit], total

    async def search(
        self,
        query_embedding: list[float],  # noqa: ARG002
        index_name: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,  # noqa: ARG002
        filters: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> list[SearchResult]:
        indices = [index_name] if index_name else sorted(self.indices)
        results: list[SearchResult] = []
        for idx in indices:
            for (name, _), doc in self.docs.items():
                if name != idx:
                    continue
                results.append(SearchResult(document=doc, score=1.0))
        return results[:limit]

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - simple
        return {"healthy": True, "backend": "fake"}


class FakeEmbeddings:
    """Simple fake embedding provider for CLI tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed_text(self, text: str) -> list[float]:
        self.calls.append("embed_text")
        return [float(len(text))]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append("embed_texts")
        return [[float(len(t))] for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        self.calls.append("embed_query")
        return [float(len(query))]

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - simple
        return {"healthy": True, "provider": "fake", "model": "fake-model"}


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> tuple[CliRunner, FakeStorage, FakeEmbeddings]:
    """Set up the CLI test environment with fake backends."""

    storage = FakeStorage()
    embeddings = FakeEmbeddings()

    # Patch factories used by kb CLI commands. The CLI imports these from
    # knowledgebase.storage and knowledgebase.embeddings, so we patch them
    # at those module paths.
    import knowledgebase.embeddings as embeddings_module
    import knowledgebase.storage as storage_module

    monkeypatch.setattr(storage_module, "get_storage_backend", lambda: storage)
    monkeypatch.setattr(embeddings_module, "get_embedding_provider", lambda: embeddings)

    runner = CliRunner()
    return runner, storage, embeddings


@pytest.mark.unit
class TestKbCli:
    """Unit tests for kb CLI commands."""

    def test_add_and_remove_document(
        self, cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings], tmp_path: Path
    ) -> None:
        """`kb add` should add a document and `kb remove` should delete it."""

        runner, storage, _ = cli_env

        doc_path = tmp_path / "doc.txt"
        doc_path.write_text("Hello from CLI")

        result = runner.invoke(
            cli,
            [
                "add",
                str(doc_path),
                "--index",
                "kb",
                "--id",
                "doc-1",
                "--title",
                "CLI Doc",
            ],
        )

        assert result.exit_code == 0, result.output
        assert ("kb", "doc-1") in storage.docs

        # Remove with --force to skip confirmation
        result_remove = runner.invoke(
            cli,
            [
                "remove",
                "doc-1",
                "--index",
                "kb",
                "--force",
            ],
        )
        assert result_remove.exit_code == 0, result_remove.output
        assert ("kb", "doc-1") not in storage.docs

    def test_search_command(self, cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings]) -> None:
        """`kb search` should return results from the storage backend."""

        runner, storage, embeddings = cli_env

        # Pre-populate storage with a document.
        doc = Document(
            id="doc-search",
            content="Searchable CLI content",
            embedding=None,
            index_name="kb",
            metadata=DocumentMetadata(title="Search Doc"),
        )
        storage.docs[("kb", "doc-search")] = doc
        storage.indices.add("kb")

        result = runner.invoke(cli, ["search", "Searchable", "--index", "kb"])

        assert result.exit_code == 0, result.output
        # Ensure the embedding provider was called for the query.
        assert "embed_query" in embeddings.calls
        # Basic sanity check on output
        assert "Search Results for" in result.output

    def test_search_command_json_output(
        self, cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings]
    ) -> None:
        """`kb search --json` should emit JSON-formatted search results."""

        runner, storage, embeddings = cli_env

        doc = Document(
            id="doc-json",
            content="Searchable CLI content for JSON",
            embedding=None,
            index_name="kb",
            metadata=DocumentMetadata(title="Search Doc JSON"),
        )
        storage.docs[("kb", "doc-json")] = doc
        storage.indices.add("kb")

        result = runner.invoke(cli, ["search", "Searchable", "--index", "kb", "--json"])

        assert result.exit_code == 0, result.output
        assert "embed_query" in embeddings.calls
        # The JSON renderer should include the document id and score fields.
        assert '"id": "doc-json"' in result.output
        assert '"score"' in result.output

    def test_index_commands(self, cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings]) -> None:
        """`kb index` subcommands should manage indices via the storage backend."""

        runner, storage, _ = cli_env

        # Create an index
        create_result = runner.invoke(cli, ["index", "create", "kb-index"])
        assert create_result.exit_code == 0, create_result.output
        assert "kb-index" in storage.indices

        # List indices as JSON
        list_result = runner.invoke(cli, ["index", "list", "--json"])
        assert list_result.exit_code == 0, list_result.output
        assert "kb-index" in list_result.output

        # Delete index with --force
        delete_result = runner.invoke(cli, ["index", "delete", "kb-index", "--force"])
        assert delete_result.exit_code == 0, delete_result.output
        assert "kb-index" not in storage.indices

    def test_status_command_json(
        self, cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings]
    ) -> None:
        """`kb status --json` should return a JSON payload including components."""

        runner, _, _ = cli_env

        result = runner.invoke(cli, ["status", "--json"])

        assert result.exit_code == 0, result.output
        assert "components" in result.output
        assert "storage" in result.output
        assert "embeddings" in result.output

    def test_status_command_text_output(
        self, cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings]
    ) -> None:
        """`kb status` without --json should render a human-readable summary."""

        runner, _, _ = cli_env

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0, result.output
        # Should include the version header and environment label.
        assert "KnowledgeBase Engine v" in result.output
        assert "Environment:" in result.output or "App Environment:" in result.output
        # Components should be listed with checkmarks.
        assert "Storage" in result.output or "storage" in result.output
        assert "Embeddings" in result.output or "embeddings" in result.output

    def test_status_command_includes_aegis_environment(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`kb status` should display the AegisCLI environment."""
        from knowledgebase.core.config import Settings

        runner, _, _ = cli_env

        # Mock settings with a specific aegis_environment
        mock_settings = Settings(aegis_environment="staging")
        import knowledgebase.cli.main as cli_main

        monkeypatch.setattr(cli_main, "get_settings", lambda: mock_settings)

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0, result.output
        assert "AegisCLI Environment: staging" in result.output

    def test_status_command_json_includes_aegis_environment(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`kb status --json` should include the aegis_environment field."""
        import json

        from knowledgebase.core.config import Settings

        runner, _, _ = cli_env

        # Mock settings with a specific aegis_environment
        mock_settings = Settings(aegis_environment="prod")
        import knowledgebase.cli.main as cli_main

        monkeypatch.setattr(cli_main, "get_settings", lambda: mock_settings)

        result = runner.invoke(cli, ["status", "--json"])

        assert result.exit_code == 0, result.output
        # Rich's print_json may include extra markup, extract just the JSON part
        try:
            data = json.loads(result.output)
        except json.JSONDecodeError:
            # Try to extract JSON from the output if there's markup around it
            lines = result.output.strip().split("\n")
            json_str = "\n".join([line for line in lines if not line.startswith("[")])
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # As a last resort, find the JSON object in the output
                import re

                match = re.search(r"\{.*\}", result.output, re.DOTALL)
                assert match, f"Could not find JSON in output: {result.output}"
                data = json.loads(match.group())

        assert "aegis_environment" in data
        assert data["aegis_environment"] == "prod"

    def test_status_shows_resolved_provider_info(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`kb status` should show whether provider was auto-resolved or explicitly set."""
        from knowledgebase.core.config import Settings

        runner, _, embeddings = cli_env

        # Update fake embeddings to return resolved_provider (async method)
        async def health_check_with_resolved() -> dict[str, Any]:
            return {
                "healthy": True,
                "provider": "fake",
                "model": "fake-model",
                "resolved_provider": "ollama",
            }

        embeddings.health_check = health_check_with_resolved  # type: ignore[assignment]

        # Mock settings with auto-resolved environment (provider not explicitly set)
        mock_settings = Settings(aegis_environment="local")
        import knowledgebase.cli.main as cli_main

        monkeypatch.setattr(cli_main, "get_settings", lambda: mock_settings)

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0, result.output
        # Should show resolved provider with auto-resolved indicator
        # The resolved provider should be shown as part of the embeddings section
        assert "Resolved Provider" in result.output

    def test_status_handles_storage_error(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
    ) -> None:
        """Storage failures in `kb status` should be reported, not crash the CLI."""

        runner, storage, _ = cli_env

        async def failing_health_check() -> dict[str, Any]:  # type: ignore[override]
            raise RuntimeError("storage boom")

        # Replace the health_check implementation on this storage instance so
        # that the CLI status command exercises the error-handling branch.
        storage.health_check = failing_health_check  # type: ignore[assignment]

        result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0, result.output
        assert "Error" in result.output

    def test_remove_aborts_when_user_declines_confirmation(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`kb remove` should abort when the user does not confirm deletion."""

        runner, storage, _ = cli_env

        # Seed storage with a document that would otherwise be deleted.
        doc = Document(
            id="doc-2",
            content="To be confirmed",
            embedding=None,
            index_name="kb",
            metadata=DocumentMetadata(title="Confirm Doc"),
        )
        storage.docs[("kb", "doc-2")] = doc
        storage.indices.add("kb")

        import knowledgebase.cli.main as cli_main

        def fake_confirm(prompt: str) -> bool:  # noqa: D401
            """Always decline confirmation in tests."""

            assert "Remove document" in prompt
            return False

        monkeypatch.setattr(cli_main.click, "confirm", fake_confirm)

        result = runner.invoke(
            cli,
            [
                "remove",
                "doc-2",
                "--index",
                "kb",
            ],
        )

        assert result.exit_code == 0, result.output
        # Document should still exist because the user declined.
        assert ("kb", "doc-2") in storage.docs
        assert "Aborted" in result.output

    def test_remove_reports_when_document_not_found(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`kb remove` should clearly report when the document does not exist."""

        runner, storage, _ = cli_env
        storage.docs.clear()
        storage.indices.add("kb")

        import knowledgebase.cli.main as cli_main

        # Always confirm deletion so we exercise the not-found branch.
        monkeypatch.setattr(cli_main.click, "confirm", lambda _prompt: True)

        result = runner.invoke(
            cli,
            [
                "remove",
                "missing-doc",
                "--index",
                "kb",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "not found" in result.output

    def test_sync_requires_index_or_all(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`kb sync` should prompt for an index or --all when neither is provided."""

        runner, _storage, _embeddings = cli_env

        class SettingsStub:
            def load_config_file(self, name: str) -> dict[str, Any]:  # noqa: D401, ARG002
                """Return a minimal indices configuration for sync tests."""

                return {
                    "indices": [{"name": "kb", "sync_source": "docs", "file_patterns": ["*.md"]}]
                }

        import knowledgebase.sync.service as sync_service_module

        monkeypatch.setattr(sync_service_module, "get_settings", lambda: SettingsStub())

        result = runner.invoke(cli, ["sync"])

        assert result.exit_code == 1, result.output
        assert "Specify an INDEX name or use --all" in result.output

    def test_sync_conflicting_index_values(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`kb sync` should error when positional and option indices conflict."""

        runner, _storage, _embeddings = cli_env

        class SettingsStub:
            def load_config_file(self, name: str) -> dict[str, Any]:  # noqa: D401, ARG002
                """Return a minimal indices configuration for sync tests."""

                return {
                    "indices": [{"name": "kb", "sync_source": "docs", "file_patterns": ["*.md"]}]
                }

        import knowledgebase.sync.service as sync_service_module

        monkeypatch.setattr(sync_service_module, "get_settings", lambda: SettingsStub())

        result = runner.invoke(cli, ["sync", "kb", "--index", "other"])

        assert result.exit_code == 1, result.output
        assert "Conflicting index values" in result.output

    def test_sync_dry_run_reports_missing_source_path(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`kb sync --all --dry-run` should report when the source path is missing."""

        runner, _storage, _embeddings = cli_env

        class SettingsStub:
            def load_config_file(self, name: str) -> dict[str, Any]:  # noqa: D401, ARG002
                """Return a configuration pointing at a non-existent path."""

                return {
                    "indices": [
                        {
                            "name": "kb",
                            "sync_source": "non-existent-path-for-sync-tests",
                            "file_patterns": ["*.md"],
                        }
                    ]
                }

        import knowledgebase.sync.service as sync_service_module

        monkeypatch.setattr(sync_service_module, "get_settings", lambda: SettingsStub())

        result = runner.invoke(cli, ["sync", "--all", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Source path does not exist" in result.output

    def test_sync_dry_run_counts_files_in_existing_source(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """`kb sync --all --dry-run` should report how many files would be synced."""

        runner, _storage, _embeddings = cli_env

        # Create a temporary directory with a few markdown files to be counted.
        source_dir = tmp_path / "docs"
        source_dir.mkdir()
        (source_dir / "a.md").write_text("A")
        (source_dir / "b.md").write_text("B")
        (source_dir / "c.txt").write_text("C")  # should be ignored by pattern

        class SettingsStub:
            def load_config_file(self, name: str) -> dict[str, Any]:  # noqa: D401, ARG002
                """Return a configuration pointing at the temporary docs directory."""

                return {
                    "indices": [
                        {
                            "name": "kb",
                            "sync_source": str(source_dir),
                            "file_patterns": ["*.md"],
                        }
                    ]
                }

        import knowledgebase.sync.service as sync_service_module

        monkeypatch.setattr(sync_service_module, "get_settings", lambda: SettingsStub())

        result = runner.invoke(cli, ["sync", "--all", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "Would sync 2 files" in result.output

    def test_sync_non_dry_run_executes_sync_loop(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """`kb sync --all` without --dry-run should actually index the file into storage."""

        runner, storage, _embeddings = cli_env

        source_dir = tmp_path / "docs"
        source_dir.mkdir()
        (source_dir / "a.md").write_text("A")

        class SettingsStub:
            def load_config_file(self, name: str) -> dict[str, Any]:  # noqa: D401, ARG002
                """Return a configuration pointing at the temporary docs directory."""

                return {
                    "indices": [
                        {
                            "name": "kb",
                            "sync_source": str(source_dir),
                            "file_patterns": ["*.md"],
                        }
                    ]
                }

        import knowledgebase.sync.service as sync_service_module

        monkeypatch.setattr(sync_service_module, "get_settings", lambda: SettingsStub())

        result = runner.invoke(cli, ["sync", "--all"])

        assert result.exit_code == 0, result.output
        assert "Sync complete" in result.output
        assert ("kb", "kb__a.md") in storage.docs
        assert storage.docs[("kb", "kb__a.md")].content == "A"


@pytest.mark.unit
class TestKbRunbookCli:
    """Unit tests for `kb runbook` CLI subcommands."""

    def test_runbook_list_json_and_table(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner, _storage, _embeddings = cli_env

        class FakeRunbookService:
            def list_runbooks(self) -> dict[str, Any]:
                return {
                    "count": 1,
                    "runbooks": [{"name": "deploy", "path": "/tmp/deploy.md"}],
                }

        import knowledgebase.runbooks.service as runbook_service_module

        monkeypatch.setattr(runbook_service_module, "RunbookService", lambda: FakeRunbookService())

        json_result = runner.invoke(cli, ["runbook", "list", "--json"])
        assert json_result.exit_code == 0, json_result.output
        assert '"count": 1' in json_result.output
        assert "deploy" in json_result.output

        table_result = runner.invoke(cli, ["runbook", "list"])
        assert table_result.exit_code == 0, table_result.output
        assert "Runbooks" in table_result.output
        assert "deploy" in table_result.output

    def test_runbook_list_empty_branch(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner, _storage, _embeddings = cli_env

        class FakeRunbookService:
            def list_runbooks(self) -> dict[str, Any]:
                return {"count": 0, "runbooks": []}

        import knowledgebase.runbooks.service as runbook_service_module

        monkeypatch.setattr(runbook_service_module, "RunbookService", lambda: FakeRunbookService())

        result = runner.invoke(cli, ["runbook", "list"])
        assert result.exit_code == 0, result.output
        assert "No runbooks found" in result.output

    def test_runbook_get_found_and_not_found(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner, _storage, _embeddings = cli_env

        class FakeRunbookService:
            def get_runbook(self, name: str) -> dict[str, Any] | None:
                if name == "deploy":
                    return {"name": "deploy", "content": "runbook-body"}
                return None

        import knowledgebase.runbooks.service as runbook_service_module

        monkeypatch.setattr(runbook_service_module, "RunbookService", lambda: FakeRunbookService())

        found = runner.invoke(cli, ["runbook", "get", "deploy"])
        assert found.exit_code == 0, found.output
        assert "Runbook: deploy" in found.output
        assert "runbook-body" in found.output

        missing = runner.invoke(cli, ["runbook", "get", "missing"])
        assert missing.exit_code == 0, missing.output
        assert "not found" in missing.output.lower()

    def test_runbook_create_from_content_and_file(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        runner, _storage, _embeddings = cli_env
        captured: dict[str, Any] = {}

        class FakeRunbookService:
            def create_runbook(
                self, name: str, content: str, file_path: str | None = None
            ) -> dict[str, Any]:
                captured["name"] = name
                captured["content"] = content
                captured["file_path"] = file_path
                return {"name": name, "created": True}

        import knowledgebase.runbooks.service as runbook_service_module

        monkeypatch.setattr(runbook_service_module, "RunbookService", lambda: FakeRunbookService())

        result_content = runner.invoke(
            cli, ["runbook", "create", "deploy", "--content", "inline-content"]
        )
        assert result_content.exit_code == 0, result_content.output
        assert captured["name"] == "deploy"
        assert captured["content"] == "inline-content"

        file_path = tmp_path / "rb.md"
        file_path.write_text("from-file", encoding="utf-8")
        result_file = runner.invoke(
            cli, ["runbook", "create", "deploy-file", "--file", str(file_path)]
        )
        assert result_file.exit_code == 0, result_file.output
        assert captured["name"] == "deploy-file"
        assert captured["content"] == "from-file"
        assert captured["file_path"] == str(file_path)

    def test_runbook_create_requires_content_or_file(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner, _storage, _embeddings = cli_env

        class FakeRunbookService:
            def create_runbook(
                self, name: str, content: str, file_path: str | None = None
            ) -> dict[str, Any]:
                _ = (content, file_path)
                return {"name": name, "created": True}

        import knowledgebase.runbooks.service as runbook_service_module

        monkeypatch.setattr(runbook_service_module, "RunbookService", lambda: FakeRunbookService())

        result = runner.invoke(cli, ["runbook", "create", "deploy"])
        assert result.exit_code == 1
        assert "provide either --file or --content" in result.output

    def test_runbook_delete_prompt_and_error_paths(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner, _storage, _embeddings = cli_env

        class FakeRunbookService:
            def delete_runbook(self, name: str, force: bool = False) -> dict[str, Any]:
                _ = force
                if name == "deploy":
                    return {"deleted": True}
                return {"deleted": False, "error": "Runbook 'missing' not found"}

        import knowledgebase.cli.main as cli_main
        import knowledgebase.runbooks.service as runbook_service_module

        monkeypatch.setattr(runbook_service_module, "RunbookService", lambda: FakeRunbookService())
        monkeypatch.setattr(cli_main.click, "confirm", lambda _prompt: False)

        aborted = runner.invoke(cli, ["runbook", "delete", "deploy"])
        assert aborted.exit_code == 0, aborted.output
        assert "Aborted" in aborted.output

        deleted = runner.invoke(cli, ["runbook", "delete", "deploy", "--force"])
        assert deleted.exit_code == 0, deleted.output
        assert "Deleted runbook 'deploy'" in deleted.output

        missing = runner.invoke(cli, ["runbook", "delete", "missing", "--force"])
        assert missing.exit_code == 0, missing.output
        assert "not found" in missing.output.lower()

    def test_runbook_prompt_reindex_and_log_commands(
        self,
        cli_env: tuple[CliRunner, FakeStorage, FakeEmbeddings],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        runner, _storage, _embeddings = cli_env

        class FakePromptResult:
            def __init__(self) -> None:
                self.runbook_name = "deploy"
                self.prompt_text = "rendered prompt"

        class FakeRunbookService:
            def get_prompt(self, keyword: str, vars_str: str = "") -> FakePromptResult:
                if keyword == "boom":
                    raise RuntimeError("prompt failed")
                _ = vars_str
                return FakePromptResult()

            def reindex_runbooks(self) -> dict[str, Any]:
                return {"count": 2, "reindexed": True}

            def create_log(self, name: str, content: str) -> dict[str, str]:
                return {"created": "True", "name": name, "content": content}

        import knowledgebase.runbooks.service as runbook_service_module

        monkeypatch.setattr(runbook_service_module, "RunbookService", lambda: FakeRunbookService())

        prompt_ok = runner.invoke(cli, ["runbook", "prompt", "deploy", "--vars", "a=1"])
        assert prompt_ok.exit_code == 0, prompt_ok.output
        assert "Prompt from runbook: deploy" in prompt_ok.output
        assert "rendered prompt" in prompt_ok.output

        prompt_fail = runner.invoke(cli, ["runbook", "prompt", "boom"])
        assert prompt_fail.exit_code == 1
        assert "Error:" in prompt_fail.output

        reindex = runner.invoke(cli, ["runbook", "reindex"])
        assert reindex.exit_code == 0, reindex.output
        assert "Reindexed 2 runbooks" in reindex.output

        log_ok = runner.invoke(cli, ["runbook", "log", "deploy", "--content", "done"])
        assert log_ok.exit_code == 0, log_ok.output
        assert "Log entry created" in log_ok.output

        log_file = tmp_path / "log.txt"
        log_file.write_text("from-file", encoding="utf-8")
        log_file_ok = runner.invoke(cli, ["runbook", "log", "deploy", "--file", str(log_file)])
        assert log_file_ok.exit_code == 0, log_file_ok.output

        log_missing = runner.invoke(cli, ["runbook", "log", "deploy"])
        assert log_missing.exit_code == 1
        assert "provide either --file or --content" in log_missing.output
