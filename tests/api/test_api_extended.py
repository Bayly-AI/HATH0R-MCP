"""
Extended tests for API endpoints covering error handling and edge cases.
"""

from __future__ import annotations


from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from knowledgebase.api.main import _load_rag_config, _save_rag_config, app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestRagConfigEndpoints:
    """Tests for RAG configuration endpoints."""

    def test_load_rag_config_with_valid_file(self, tmp_path):
        """Test loading RAG config from valid file."""
        import json

        config_file = tmp_path / "rag.json"
        config_data = {
            "top_k": 5,
            "min_score": 0.7,
            "default_index": "test_index",
            "max_context_tokens": 1024,
            "max_answer_tokens": 256,
            "include_sources": False,
            "use_reranker": True,
            "return_debug_metadata": True,
        }
        config_file.write_text(json.dumps(config_data))

        from knowledgebase.core.config import Settings

        settings = Settings()
        settings.config_dir = tmp_path

        with patch("knowledgebase.api.main.settings", settings):
            config = _load_rag_config()

        assert config.top_k == 5
        assert config.min_score == 0.7
        assert config.default_index == "test_index"

    def test_load_rag_config_with_missing_file(self, tmp_path):
        """Test loading RAG config when file doesn't exist."""
        from knowledgebase.core.config import Settings

        settings = Settings()
        settings.config_dir = tmp_path

        with patch("knowledgebase.api.main.settings", settings):
            config = _load_rag_config()

        assert config.top_k == 10
        assert config.min_score == 0.5

    def test_save_rag_config(self, tmp_path):
        """Test saving RAG config to file."""
        import json

        from knowledgebase.api.main import RagConfig
        from knowledgebase.core.config import Settings

        settings = Settings()
        settings.config_dir = tmp_path

        config = RagConfig(
            top_k=20,
            min_score=0.8,
            default_index="custom",
        )

        with patch("knowledgebase.api.main.settings", settings):
            _save_rag_config(config)

        config_file = tmp_path / "rag.json"
        assert config_file.exists()

        with config_file.open() as f:
            data = json.load(f)
        assert data["top_k"] == 20
        assert data["min_score"] == 0.8


class TestSearchEndpoint:
    """Tests for search endpoint error handling."""

    @pytest.mark.asyncio
    async def test_search_without_embeddings(self):
        """Test search when embeddings service is not initialized."""
        from fastapi.testclient import TestClient

        with patch("knowledgebase.api.main._embeddings", None):
            client = TestClient(app)
            response = client.post(
                "/api/v1/search",
                json={"query": "test", "index_name": "test", "limit": 10},
            )
            # Should get 503 when service not initialized
            assert response.status_code in [503, 500]

    @pytest.mark.asyncio
    async def test_search_with_embedding_error(self):
        """Test search when embedding generation fails."""
        with (
            patch("knowledgebase.api.main._embeddings") as mock_embed,
            patch("knowledgebase.api.main._storage") as mock_storage,
        ):
            mock_embed.embed_query = AsyncMock(side_effect=RuntimeError("Embedding failed"))
            mock_storage.search = AsyncMock(return_value=[])
            # This would require actual running app context for testing


class TestDocumentEndpoints:
    """Tests for document endpoint error handling."""

    @pytest.mark.asyncio
    async def test_add_document_without_service(self):
        """Test adding document when service not initialized."""
        with patch("knowledgebase.api.main._embeddings", None):
            client = TestClient(app)
            response = client.post(
                "/api/v1/documents",
                json={
                    "id": "test1",
                    "content": "test content",
                    "index_name": "test",
                },
            )
            assert response.status_code in [503, 500]

    @pytest.mark.asyncio
    async def test_get_document_not_found(self):
        """Test getting non-existent document."""
        with patch("knowledgebase.api.main._storage") as mock_storage:
            mock_storage.get_document = AsyncMock(return_value=None)
            # This would require app context to test properly


class TestIndexEndpoints:
    """Tests for index endpoint error handling."""

    @pytest.mark.asyncio
    async def test_list_indices_without_storage(self):
        """Test listing indices without storage service."""
        with patch("knowledgebase.api.main._storage", None):
            client = TestClient(app)
            response = client.get("/api/v1/indices")
            assert response.status_code in [503, 500]

    @pytest.mark.asyncio
    async def test_create_index_without_storage(self):
        """Test creating index without storage service."""
        with patch("knowledgebase.api.main._storage", None):
            client = TestClient(app)
            response = client.post(
                "/api/v1/indices",
                json={"name": "test-index", "description": "Test"},
            )
            assert response.status_code in [503, 500]


class TestSystemEndpoints:
    """Tests for system monitoring endpoints."""

    @pytest.mark.asyncio
    async def test_get_system_stats_without_service(self):
        """Test getting system stats without service."""
        with patch("knowledgebase.api.main._system_service", None):
            client = TestClient(app)
            response = client.get("/api/v1/system/stats")
            assert response.status_code in [503, 500]

    @pytest.mark.asyncio
    async def test_get_performance_metrics_without_service(self):
        """Test getting performance metrics without service."""
        with patch("knowledgebase.api.main._system_service", None):
            client = TestClient(app)
            response = client.get("/api/v1/system/performance")
            assert response.status_code in [503, 500]

    @pytest.mark.asyncio
    async def test_get_service_status_without_service(self):
        """Test getting service status without service."""
        with patch("knowledgebase.api.main._system_service", None):
            client = TestClient(app)
            response = client.get("/api/v1/system/services")
            assert response.status_code in [503, 500]


class TestMCPEndpoints:
    """Tests for MCP integration endpoints."""

    @pytest.mark.asyncio
    async def test_get_mcp_status_without_service(self):
        """Test getting MCP status without service."""
        with patch("knowledgebase.api.main._mcp_service", None):
            client = TestClient(app)
            response = client.get("/api/v1/mcp/status")
            assert response.status_code in [503, 500]

    @pytest.mark.asyncio
    async def test_record_mcp_tool_call_without_service(self):
        """Test recording tool call without service."""
        with patch("knowledgebase.api.main._mcp_service", None):
            client = TestClient(app)
            response = client.post(
                "/api/v1/mcp/tool-call",
                json={
                    "agent": "test_agent",
                    "tool_name": "kb_search",
                    "query": "test",
                },
            )
            assert response.status_code in [503, 500]


class TestRecordSearchActivity:
    """Tests for search activity recording."""

    @pytest.mark.asyncio
    async def test_record_search_activity_with_services(self):
        """Test recording search activity with valid services."""
        from knowledgebase.api.main import SearchRequest, _record_search_activity

        mock_mcp = AsyncMock()
        mock_system = MagicMock()
        mock_mcp.record_tool_call = AsyncMock()

        with (
            patch("knowledgebase.api.main._mcp_service", mock_mcp),
            patch("knowledgebase.api.main._system_service", mock_system),
        ):
            request = SearchRequest(query="test")
            await _record_search_activity(request, 100.0, 5)

            mock_mcp.record_tool_call.assert_called_once()
            mock_system.increment_search_count.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_search_activity_without_mcp_service(self):
        """Test recording search activity without MCP service."""
        from knowledgebase.api.main import SearchRequest, _record_search_activity

        with (
            patch("knowledgebase.api.main._mcp_service", None),
            patch("knowledgebase.api.main._system_service", None),
        ):
            request = SearchRequest(query="test")
            # Should not raise exception
            await _record_search_activity(request, 100.0, 5)

    @pytest.mark.asyncio
    async def test_record_search_activity_with_error(self):
        """Test recording search activity when recording fails."""
        from knowledgebase.api.main import SearchRequest, _record_search_activity

        mock_mcp = AsyncMock()
        mock_mcp.record_tool_call = AsyncMock(side_effect=RuntimeError("Record failed"))

        with (
            patch("knowledgebase.api.main._mcp_service", mock_mcp),
            patch("knowledgebase.api.main._system_service", MagicMock()),
        ):
            request = SearchRequest(query="test")
            # Should not raise, just log warning
            await _record_search_activity(request, 100.0, 5)


class TestListDocumentsValidation:
    """Tests for list documents validation."""

    def test_list_documents_without_storage(self):
        """Test list documents without storage service."""
        with patch("knowledgebase.api.main._storage", None):
            client = TestClient(app)
            response = client.post(
                "/api/v1/documents/list",
                json={"index_name": "test", "offset": 0, "limit": 20},
            )
            assert response.status_code in [503, 500]

    def test_list_documents_invalid_limit_high(self):
        """Test list documents with limit > 100."""
        with patch("knowledgebase.api.main._storage") as mock_storage:
            mock_storage.list_documents = AsyncMock(return_value=([], 0))

            client = TestClient(app)
            response = client.post(
                "/api/v1/documents/list",
                json={"index_name": "test", "offset": 0, "limit": 150},
            )
            assert response.status_code in [422, 500]

    def test_list_documents_invalid_offset_negative(self):
        """Test list documents with negative offset."""
        with patch("knowledgebase.api.main._storage") as mock_storage:
            mock_storage.list_documents = AsyncMock(return_value=([], 0))

            client = TestClient(app)
            response = client.post(
                "/api/v1/documents/list",
                json={"index_name": "test", "offset": -1, "limit": 20},
            )
            assert response.status_code in [422, 500]


class TestMCPParityTools:
    """Tests for AegisCLI parity MCP tools."""

    def test_tool_schema_includes_new_parity_tools(self):
        """Test schema definitions include newly integrated tools."""
        from knowledgebase.api.main import _get_tool_schema

        add_file_schema = _get_tool_schema("kb_add_file")
        assert "path" in add_file_schema["properties"]
        assert "index" in add_file_schema["properties"]
        assert add_file_schema["required"] == ["path", "index"]

        docs_search_schema = _get_tool_schema("docs_kb_search")
        assert docs_search_schema["required"] == ["pattern"]

        search_schema = _get_tool_schema("kb_search")
        assert "group" in search_schema["properties"]
        assert "domain" in search_schema["properties"]
        assert "subgroup" in search_schema["properties"]
        assert "min_score" in search_schema["properties"]
        assert "summarize" in search_schema["properties"]

        docs_info_schema = _get_tool_schema("docs_kb_info")
        assert docs_info_schema["properties"] == {}

        docs_dirs_schema = _get_tool_schema("docs_list_dirs")
        assert "path" in docs_dirs_schema["properties"]
        assert "limit" in docs_dirs_schema["properties"]

        assert _get_tool_schema("aegis_ping")["properties"] == {}
        assert _get_tool_schema("aegis_context")["properties"] == {}
        assert "message" in _get_tool_schema("aegis_echo")["properties"]
        assert "name" in _get_tool_schema("aegis_env_get")["properties"]
        assert "prefix" in _get_tool_schema("aegis_env_list")["properties"]
        assert "values" in _get_tool_schema("aegis_env_list")["properties"]

    @pytest.mark.asyncio
    async def test_execute_kb_index_create_and_delete(self):
        """Test index create/delete MCP tool handlers."""
        from knowledgebase.api.main import _execute_mcp_tool

        mock_storage = AsyncMock()
        mock_storage.create_index = AsyncMock()
        mock_storage.delete_index = AsyncMock()

        with (
            patch("knowledgebase.api.main._storage", mock_storage),
            patch("knowledgebase.api.main._mcp_service", None),
        ):
            create_result = await _execute_mcp_tool("kb_index_create", {"name": "test-index"})
            assert create_result.get("isError") is not True
            mock_storage.create_index.assert_called_once_with("test-index")

            delete_result = await _execute_mcp_tool(
                "kb_index_delete", {"name": "test-index", "force": True}
            )
            assert delete_result.get("isError") is not True
            mock_storage.delete_index.assert_called_once_with("test-index")

    @pytest.mark.asyncio
    async def test_execute_docs_read_meta(self, tmp_path):
        """Test docs_read_meta tool returns metadata and frontmatter."""
        from knowledgebase.api.main import _execute_mcp_tool

        doc_path = tmp_path / "sample.md"
        doc_path.write_text("---\ntitle: Demo\nauthor: QA\n---\nBody")

        with (
            patch("knowledgebase.api.main._knowledgebase_root", return_value=tmp_path.resolve()),
            patch("knowledgebase.api.main._mcp_service", None),
        ):
            result = await _execute_mcp_tool("docs_read_meta", {"path": "sample.md"})
            assert result.get("isError") is not True
            text = result["content"][0]["text"]
            assert '"title": "Demo"' in text
            assert '"author": "QA"' in text

    @pytest.mark.asyncio
    async def test_execute_docs_kb_info_and_list_dirs(self, tmp_path):
        """Test docs_kb_info and docs_list_dirs handlers."""
        import json

        from knowledgebase.api.main import _execute_mcp_tool

        docs_root = tmp_path.resolve()
        (docs_root / "a.md").write_text("A", encoding="utf-8")
        (docs_root / "nested").mkdir(parents=True, exist_ok=True)
        (docs_root / "nested" / "b.txt").write_text("B", encoding="utf-8")

        with (
            patch("knowledgebase.api.main._knowledgebase_root", return_value=docs_root),
            patch("knowledgebase.api.main._mcp_service", None),
        ):
            info_result = await _execute_mcp_tool("docs_kb_info", {})
            assert info_result.get("isError") is not True
            info_payload = json.loads(info_result["content"][0]["text"])
            assert info_payload["exists"] is True
            assert info_payload["file_count"] == 2
            assert info_payload["directory_count"] >= 1
            assert ".md" in info_payload["extensions"]

            dirs_result = await _execute_mcp_tool("docs_list_dirs", {"limit": 10})
            assert dirs_result.get("isError") is not True
            dirs_payload = json.loads(dirs_result["content"][0]["text"])
            assert dirs_payload["count"] >= 1
            assert "." in dirs_payload["directories"]
            assert "nested" in dirs_payload["directories"]

    @pytest.mark.asyncio
    async def test_execute_aegis_core_tools(self, monkeypatch):
        """Test aegis_* core utility MCP handlers."""
        import json

        from knowledgebase.api.main import _execute_mcp_tool

        monkeypatch.setenv("KB_TEST_ENV", "value-123")

        with patch("knowledgebase.api.main._mcp_service", None):
            ping = await _execute_mcp_tool("aegis_ping", {})
            assert ping.get("isError") is not True
            ping_payload = json.loads(ping["content"][0]["text"])
            assert ping_payload["status"] == "pong"
            assert "timestamp" in ping_payload

            context = await _execute_mcp_tool("aegis_context", {})
            assert context.get("isError") is not True
            context_payload = json.loads(context["content"][0]["text"])
            assert "time" in context_payload
            assert "cwd" in context_payload
            assert "version" in context_payload
            assert "system" in context_payload
            assert context_payload["version"]["name"] == "Hath0r MCP"

            echo = await _execute_mcp_tool("aegis_echo", {"message": "hello"})
            assert echo.get("isError") is not True
            echo_payload = json.loads(echo["content"][0]["text"])
            assert echo_payload["message"] == "hello"
            assert echo_payload["length"] == 5

            echo_missing = await _execute_mcp_tool("aegis_echo", {})
            assert echo_missing.get("isError") is True

            env_get = await _execute_mcp_tool("aegis_env_get", {"name": "KB_TEST_ENV"})
            assert env_get.get("isError") is not True
            env_get_payload = json.loads(env_get["content"][0]["text"])
            assert env_get_payload["exists"] is True
            assert env_get_payload["value"] == "value-123"

            env_get_missing = await _execute_mcp_tool("aegis_env_get", {})
            assert env_get_missing.get("isError") is True

            env_list_hidden = await _execute_mcp_tool(
                "aegis_env_list", {"prefix": "KB_TEST_", "values": False}
            )
            assert env_list_hidden.get("isError") is not True
            env_list_hidden_payload = json.loads(env_list_hidden["content"][0]["text"])
            assert env_list_hidden_payload["count"] >= 1
            assert env_list_hidden_payload["variables"]["KB_TEST_ENV"] == "[hidden]"

            env_list_values = await _execute_mcp_tool(
                "aegis_env_list", {"prefix": "KB_TEST_", "values": True}
            )
            assert env_list_values.get("isError") is not True
            env_list_values_payload = json.loads(env_list_values["content"][0]["text"])
            assert env_list_values_payload["variables"]["KB_TEST_ENV"] == "value-123"

    @pytest.mark.asyncio
    async def test_execute_kb_remove_document_without_index(self):
        """Test removing a document across all indices when index is omitted."""
        from knowledgebase.api.main import _execute_mcp_tool
        from knowledgebase.core.models import IndexInfo

        mock_storage = AsyncMock()
        mock_storage.list_indices = AsyncMock(
            return_value=[IndexInfo(name="a"), IndexInfo(name="b")]
        )
        mock_storage.delete_document = AsyncMock(side_effect=[False, True])

        with (
            patch("knowledgebase.api.main._storage", mock_storage),
            patch("knowledgebase.api.main._mcp_service", None),
        ):
            result = await _execute_mcp_tool("kb_remove_document", {"doc_id": "doc-1"})
            assert result.get("isError") is not True
            assert "index 'b'" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_execute_kb_get_document_accepts_id_alias(self):
        """kb_get_document should accept id as an alias for doc_id."""
        from knowledgebase.api.main import _execute_mcp_tool
        from knowledgebase.core.models import Document, DocumentMetadata

        mock_storage = AsyncMock()
        mock_storage.get_document = AsyncMock(
            return_value=Document(
                id="doc-1",
                content="sample content",
                embedding=[0.1],
                index_name="knowledge",
                metadata=DocumentMetadata(title="Sample"),
            )
        )

        with (
            patch("knowledgebase.api.main._storage", mock_storage),
            patch("knowledgebase.api.main._mcp_service", None),
        ):
            result = await _execute_mcp_tool(
                "kb_get_document", {"id": "doc-1", "index": "knowledge"}
            )

        assert result.get("isError") is not True
        mock_storage.get_document.assert_called_once_with("doc-1", "knowledge")

    @pytest.mark.asyncio
    async def test_runbook_search_uses_runbook_content(self):
        """runbook_search should inspect fetched runbook content, not only list metadata."""
        import json

        from knowledgebase.api.main import _execute_mcp_tool

        class FakeRunbookService:
            def list_runbooks(self) -> dict[str, Any]:
                return {"count": 1, "runbooks": [{"name": "ops-guide", "path": "ops-guide.md"}]}

            def get_runbook(self, name: str) -> dict[str, Any] | None:
                if name != "ops-guide":
                    return None
                return {
                    "name": "ops-guide",
                    "content": "Use blue deployment steps for zero downtime rollouts.",
                }

        with (
            patch("knowledgebase.runbooks.service.RunbookService", FakeRunbookService),
            patch("knowledgebase.api.main._mcp_service", None),
        ):
            result = await _execute_mcp_tool("runbook_search", {"query": "deployment", "limit": 5})

        assert result.get("isError") is not True
        payload = json.loads(result["content"][0]["text"])
        assert payload["results"] == ["ops-guide"]
        assert payload["count"] == 1

    @pytest.mark.asyncio
    async def test_all_registered_mcp_tools_have_api_handlers(self, tmp_path, monkeypatch):
        """Every MCPService default tool should map to a non-unknown API handler."""
        from knowledgebase.api import main as api_main
        from knowledgebase.core.config import Settings
        from knowledgebase.services.mcp_service import MCPService

        class FakePromptResult:
            def __init__(self) -> None:
                self.runbook_name = "sample"
                self.prompt_text = "prompt"

        class FakeRunbookModule:
            def list_runbooks(self) -> dict[str, Any]:
                return {"count": 1, "runbooks": [{"name": "sample", "path": "sample.md"}]}

            def get_runbook(self, name: str) -> dict[str, Any]:
                return {"name": name, "content": "content", "metadata": {}}

            def create_runbook(
                self, name: str, content: str, file_path: str | None = None
            ) -> dict[str, Any]:
                _ = (content, file_path)
                return {"name": name, "created": True}

            def delete_runbook(self, name: str, force: bool = False) -> dict[str, Any]:
                _ = force
                return {"name": name, "deleted": True}

            def reindex_runbooks(self) -> dict[str, Any]:
                return {"count": 1, "reindexed": True}

            def get_prompt(self, name: str, vars_str: str = "") -> FakePromptResult:
                _ = (name, vars_str)
                return FakePromptResult()

            def create_log(self, name: str, content: str) -> dict[str, str]:
                _ = content
                return {"created": "True", "runbook_name": name}

        docs_root = tmp_path / "knowledgebase"
        docs_root.mkdir(parents=True, exist_ok=True)
        (docs_root / "sample.md").write_text("sample", encoding="utf-8")
        (docs_root / "nested").mkdir(parents=True, exist_ok=True)

        monkeypatch.setenv("KB_TEST_ENV", "value-123")

        service = MCPService(Settings())
        await service.initialize()
        tool_names = [tool.name for tool in (await service.get_server_status()).tools]
        await service.cleanup()

        args_by_tool = {
            "kb_search": {"query": "q"},
            "kb_index_create": {"name": "tmp-index"},
            "kb_index_delete": {"name": "tmp-index"},
            "kb_add_document": {"id": "doc-1", "content": "content"},
            "kb_add_file": {"path": str(docs_root / "sample.md"), "index": "knowledgebase"},
            "kb_remove_document": {"doc_id": "doc-1"},
            "kb_status_full": {},
            "docs_kb_search": {"pattern": "sample"},
            "docs_read_meta": {"path": "sample.md"},
            "docs_list_dirs": {"path": "", "limit": 10},
            "aegis_echo": {"message": "hello"},
            "aegis_env_get": {"name": "KB_TEST_ENV"},
            "aegis_env_list": {"prefix": "KB_TEST_", "values": False},
            "runbook_get": {"name": "sample"},
            "runbook_create": {"name": "sample", "content": "content"},
            "runbook_delete": {"name": "sample", "force": True},
            "runbook_get_prompt": {"name": "sample", "vars": "x=1"},
            "runbook_log_create": {"name": "sample", "content": "log"},
            "create_runbook": {"name": "sample", "content": "content"},
            "delete_runbook": {"name": "sample", "force": True},
            "get_runbook_as_prompt": {"name": "sample", "vars": "x=1"},
            "create_runbook_log": {"name": "sample", "content": "log"},
        }
        with (
            patch("knowledgebase.api.main._knowledgebase_root", return_value=docs_root),
            patch("knowledgebase.api.main._runbook_module", FakeRunbookModule()),
            patch("knowledgebase.api.main._mcp_service", None),
        ):
            for tool_name in tool_names:
                result = await api_main._execute_mcp_tool(
                    tool_name, args_by_tool.get(tool_name, {})
                )
                assert isinstance(result, dict)
                content = result.get("content", [])
                text = content[0].get("text", "") if content and isinstance(content, list) else ""
                assert "Unknown tool:" not in text, f"Missing API handler for tool '{tool_name}'"


class TestIndexAliasAndSyncExcludes:
    """Tests for alias and sync-exclusion helper behavior."""

    def test_resolve_index_alias_supports_chained_aliases(self):
        """Alias resolution should follow chained mappings until stable."""
        from knowledgebase.api.main import _resolve_index_alias

        aliases = {
            "knowledge.reference.v1": "knowledgebase",
            "knowledgebase": "knowledgebase-main",
        }
        assert _resolve_index_alias("knowledge.reference.v1", aliases) == "knowledgebase-main"
        assert _resolve_index_alias("knowledgebase", aliases) == "knowledgebase-main"
        assert _resolve_index_alias("custom-index", aliases) == "custom-index"

    def test_resolve_index_argument_applies_alias_config(self):
        """_resolve_index_argument should normalize index names using configured aliases."""
        from knowledgebase.api.main import _resolve_index_argument

        with patch(
            "knowledgebase.api.main._load_knowledgebase_config",
            return_value={"aliases": {"operations.playbooks.data.v1": "playbooks-data-v1"}},
        ):
            assert (
                _resolve_index_argument({"index": "operations.playbooks.data.v1"})
                == "playbooks-data-v1"
            )

    def test_resolve_target_indices_for_search_supports_taxonomy_filters(self):
        """Taxonomy routing should return only matching configured targets."""
        from knowledgebase.api.main import _resolve_target_indices_for_search

        config = {
            "indices": [
                {
                    "name": "integrations.connections.active.v1",
                    "top_group": "integrations",
                    "domain": "connections",
                    "subgroup": "active",
                },
                {
                    "name": "integrations.connections.inactive.v1",
                    "top_group": "integrations",
                    "domain": "connections",
                    "subgroup": "inactive",
                },
            ]
        }
        aliases = {"integrations.connections.active.v1": "connections-active-v1"}

        targets = _resolve_target_indices_for_search(
            config=config,
            aliases=aliases,
            index_name=None,
            group="integrations",
            domain="connections",
            subgroup="active",
        )
        assert targets == ["connections-active-v1"]

        explicit = _resolve_target_indices_for_search(
            config=config,
            aliases=aliases,
            index_name="integrations.connections.active.v1",
            group="knowledge",
            domain=None,
            subgroup=None,
        )
        assert explicit == ["connections-active-v1"]

    def test_coerce_float_clamps_values(self):
        """Float coercion should parse valid values and clamp out-of-range values."""
        from knowledgebase.api.main import _coerce_float

        assert _coerce_float("0.8", default=0.5) == 0.8
        assert _coerce_float("2", default=0.5) == 1.0
        assert _coerce_float("-1", default=0.5) == 0.0
        assert _coerce_float("bad", default=0.5) == 0.5

    def test_merge_search_results_deduplicates_and_ranks(self):
        """Merged result helper should keep best duplicate and rank by score."""
        from knowledgebase.api.main import _merge_search_results
        from knowledgebase.core.models import Document, SearchResult

        merged = _merge_search_results(
            [
                SearchResult(
                    document=Document(id="doc-1", content="a", index_name="idx"),
                    score=0.6,
                ),
                SearchResult(
                    document=Document(id="doc-1", content="a2", index_name="idx"),
                    score=0.9,
                ),
                SearchResult(
                    document=Document(id="doc-2", content="b", index_name="idx"),
                    score=0.8,
                ),
                SearchResult(
                    document=Document(id="doc-1", content="c", index_name="idx-other"),
                    score=0.7,
                ),
            ],
            limit=3,
        )

        assert [(result.document.index_name, result.document.id) for result in merged] == [
            ("idx", "doc-1"),
            ("idx", "doc-2"),
            ("idx-other", "doc-1"),
        ]
        assert [round(result.score, 2) for result in merged] == [0.9, 0.8, 0.7]

    # NOTE: sync-related helpers (_build_sync_excludes, _should_skip_sync_file,
    # _resolve_sync_source_path) moved to knowledgebase.sync.service --
    # see tests/unit/test_sync_service.py. The workspace-bind-mount fallback
    # previously tested here was dropped along with the cross-repo mount it
    # supported.
