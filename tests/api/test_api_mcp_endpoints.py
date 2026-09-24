"""Tests for MCP protocol endpoints and handlers.

These tests cover the SSE and JSON-RPC endpoints used by Warp and other MCP clients.
"""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from knowledgebase.api.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestMCPSSEEndpoint:
    """Tests for MCP SSE endpoint."""

    @pytest.mark.skip(
        reason="Skipped: GET /mcp/sse has infinite stream; use POST /mcp/sse instead. SSE is for server->client streaming; tests use POST for request-response."
    )
    def test_sse_get_returns_streaming_response(self):
        """GET /mcp/sse should return SSE stream with endpoint message.

        SKIPPED: The GET endpoint implements MCP SSE spec with infinite keep-alive.
        This is correct for production (real streaming connections) but unsuitable
        for synchronous tests. Use POST /mcp/sse for testable request-response.
        """
        pass

    def test_sse_post_with_invalid_json(self):
        """POST /mcp/sse should handle invalid JSON."""
        client = TestClient(app)
        response = client.post(
            "/mcp/sse", content="invalid json", headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 400
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32700

    def test_sse_post_with_non_object_json(self):
        """POST /mcp/sse should reject JSON arrays (not objects)."""
        client = TestClient(app)
        response = client.post("/mcp/sse", json=[1, 2, 3])

        assert response.status_code == 400
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "expected a JSON object" in data["error"]["message"]


class TestMCPInitialize:
    """Tests for MCP initialize method."""

    def test_initialize_returns_server_info(self, client):
        """initialize method should return server capabilities and info."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        result = data["result"]
        assert "protocolVersion" in result
        assert "capabilities" in result
        assert "serverInfo" in result
        assert result["serverInfo"]["version"]
        assert result["serverInfo"]["name"] == "hath0r-mcp"


class TestMCPToolsList:
    """Tests for tools/list endpoint."""

    def test_tools_list_without_service(self, client):
        """tools/list should return empty list without MCP service."""
        with patch("knowledgebase.api.main._mcp_service", None):
            response = client.post(
                "/mcp/sse",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["jsonrpc"] == "2.0"
            assert data["result"]["tools"] == []


class TestMCPToolsCall:
    """Tests for tools/call endpoint."""

    def test_tools_call_missing_tool_name(self, client):
        """tools/call should fail when tool name is missing."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {},
                "id": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32602


class TestMCPNotifications:
    """Tests for notification handlers."""

    def test_notifications_initialized(self, client):
        """notifications/initialized should return 204."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        assert response.status_code == 204


class TestMCPPrompts:
    """Tests for prompts endpoints."""

    def test_prompts_list_empty_without_runbook_service(self, client):
        """prompts/list should return empty list without runbook service."""
        with patch("knowledgebase.api.main._runbook_service", None):
            response = client.post(
                "/mcp/sse",
                json={
                    "jsonrpc": "2.0",
                    "method": "prompts/list",
                    "id": 4,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["jsonrpc"] == "2.0"
            assert data["result"]["prompts"] == []

    def test_prompts_get_missing_name(self, client):
        """prompts/get should fail when name is missing."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "method": "prompts/get",
                "params": {},
                "id": 5,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32602

    def test_prompts_get_not_found_without_service(self, client):
        """prompts/get should return error when service missing."""
        with patch("knowledgebase.api.main._runbook_service", None):
            response = client.post(
                "/mcp/sse",
                json={
                    "jsonrpc": "2.0",
                    "method": "prompts/get",
                    "params": {"name": "test"},
                    "id": 6,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["jsonrpc"] == "2.0"
            assert data["error"]["code"] == -32602


class TestMCPResources:
    """Tests for resource endpoints."""

    def test_resources_list_without_services(self, client):
        """resources/list should return empty without storage/runbook."""
        with (
            patch("knowledgebase.api.main._storage", None),
            patch("knowledgebase.api.main._runbook_service", None),
        ):
            response = client.post(
                "/mcp/sse",
                json={
                    "jsonrpc": "2.0",
                    "method": "resources/list",
                    "id": 7,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["jsonrpc"] == "2.0"
            assert data["result"]["resources"] == []

    def test_resources_read_missing_uri(self, client):
        """resources/read should fail when URI is missing."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "method": "resources/read",
                "params": {},
                "id": 8,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32602

    def test_resources_read_resource_not_found(self, client):
        """resources/read should return 404 for unknown URI."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "method": "resources/read",
                "params": {"uri": "unknown://test"},
                "id": 9,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32604


class TestMCPRouting:
    """Tests for MCP request routing and validation."""

    def test_invalid_method_returns_error(self, client):
        """Unknown method should return method not found error."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "method": "unknown_method",
                "id": 10,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32601
        assert "Method not found" in data["error"]["message"]

    def test_invalid_jsonrpc_version(self, client):
        """Invalid jsonrpc version should return error."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "1.0",
                "method": "tools/list",
                "id": 11,
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "jsonrpc must be '2.0'" in data["error"]["message"]

    def test_missing_method_field(self, client):
        """Missing method field should return descriptive error."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "id": 12,
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "missing JSON-RPC method" in data["error"]["message"]

    def test_hints_for_document_payloads(self, client):
        """Should provide helpful hint when method is missing but looks like a document."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "documents": [{"content": "test"}],
            },
        )

        assert response.status_code == 400
        data = response.json()
        error_msg = data["error"]["message"]
        assert "missing JSON-RPC method" in error_msg

    def test_invalid_params_type(self, client):
        """params must be an object, not array or other type."""
        response = client.post(
            "/mcp/sse",
            json={
                "jsonrpc": "2.0",
                "method": "tools/list",
                "params": [],
                "id": 13,
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "params must be an object" in data["error"]["message"]


class TestMCPHelperFunctions:
    """Tests for MCP helper functions."""

    def test_mcp_invalid_request_builder(self):
        """_mcp_invalid_request should build proper JSON-RPC error response."""
        from knowledgebase.api.main import _mcp_invalid_request

        response = _mcp_invalid_request("Test error", 123)
        data = json.loads(response.body.decode())

        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32600
        assert data["error"]["message"] == "Test error"
        assert data["id"] == 123

    def test_mcp_error_builder(self):
        """_mcp_error should create standard MCP error response."""
        from knowledgebase.api.main import _mcp_error

        result = _mcp_error("Test failed")

        assert result["isError"] is True
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Test failed"

    def test_mcp_text_builder(self):
        """_mcp_text should create standard MCP text response."""
        from knowledgebase.api.main import _mcp_text

        result = _mcp_text("Success message")

        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Success message"

    def test_get_tool_schema(self):
        """_get_tool_schema should return schema for tool name."""
        from knowledgebase.api.main import _get_tool_schema

        # Should return a dict (even if empty) for any tool
        schema = _get_tool_schema("kb_search")
        assert isinstance(schema, dict)

    def test_merge_search_results(self):
        """_merge_search_results should merge and deduplicate results."""
        from knowledgebase.api.main import _merge_search_results
        from knowledgebase.core.models import SearchResult, Document, DocumentMetadata

        # Create test results with duplicates
        doc1 = Document(
            id="doc1",
            content="content1",
            embedding=[0.1] * 1536,
            index_name="index1",
            metadata=DocumentMetadata(title="Doc 1"),
        )
        doc2 = Document(
            id="doc2",
            content="content2",
            embedding=[0.2] * 1536,
            index_name="index1",
            metadata=DocumentMetadata(title="Doc 2"),
        )
        result1 = SearchResult(document=doc1, score=0.8)
        result2 = SearchResult(document=doc2, score=0.9)
        result1_dup = SearchResult(document=doc1, score=0.7)  # Lower score duplicate

        results = [result1, result2, result1_dup]
        merged = _merge_search_results(results, limit=2)

        # Should deduplicate and keep highest score
        assert len(merged) == 2
        assert merged[0].score == 0.9
        assert merged[0].document.id == "doc2"
        assert merged[1].score == 0.8
        assert merged[1].document.id == "doc1"

    def test_coerce_positive_int(self):
        """_coerce_positive_int should validate and clamp integers."""
        from knowledgebase.api.main import _coerce_positive_int

        assert _coerce_positive_int("10", default=5) == 10
        assert _coerce_positive_int(10, default=5) == 10
        assert _coerce_positive_int("-5", default=5) == 5
        assert _coerce_positive_int("invalid", default=5) == 5
        assert _coerce_positive_int("0", default=5, minimum=1) == 1

    def test_coerce_float(self):
        """_coerce_float should validate and clamp floats."""
        from knowledgebase.api.main import _coerce_float

        assert _coerce_float("0.8", default=0.5) == 0.8
        assert _coerce_float("2", default=0.5) == 1.0
        assert _coerce_float("-1", default=0.5) == 0.0
        assert _coerce_float("bad", default=0.5) == 0.5
        assert _coerce_float(0.5, default=0.2) == 0.5
        assert _coerce_float("1.5", default=0.5, maximum=1.2) == 1.2

    def test_coerce_string_list(self):
        """_coerce_string_list should extract valid strings."""
        from knowledgebase.api.main import _coerce_string_list

        assert _coerce_string_list(["a", " b ", "c"]) == ["a", "b", "c"]
        assert _coerce_string_list(["  ", "", "a"]) == ["a"]
        assert _coerce_string_list([]) == []
        assert _coerce_string_list("not a list") == []
        assert _coerce_string_list([1, "a", None]) == ["a"]

    def test_load_knowledgebase_config(self):
        """_load_knowledgebase_config should load config or return empty dict."""
        from knowledgebase.api.main import _load_knowledgebase_config

        with patch("knowledgebase.api.main.settings") as mock_settings:
            mock_settings.load_config_file.return_value = {"test": "value"}
            result = _load_knowledgebase_config()
            assert result == {"test": "value"}

            mock_settings.load_config_file.side_effect = Exception("fail")
            result = _load_knowledgebase_config()
            assert result == {}

    def test_get_index_aliases(self):
        """_get_index_aliases should extract normalized alias map."""
        from knowledgebase.api.main import _get_index_aliases

        config = {
            "aliases": {
                "  old1  ": "new1",
                "old2": "  new2  ",
                123: "invalid",
                "old3": None,
            }
        }
        result = _get_index_aliases(config)

        assert result == {
            "old1": "new1",
            "old2": "new2",
        }

        # Test with non-dict aliases
        assert _get_index_aliases({"aliases": []}) == {}
        assert _get_index_aliases({"aliases": "not a dict"}) == {}
        assert _get_index_aliases({}) == {}

    def test_resolve_index_alias(self):
        """_resolve_index_alias should follow alias chain."""
        from knowledgebase.api.main import _resolve_index_alias

        aliases = {
            "a": "b",
            "b": "c",
            "c": "c",  # Self-reference stops
        }

        assert _resolve_index_alias("a", aliases) == "c"
        assert _resolve_index_alias("b", aliases) == "c"
        assert _resolve_index_alias("d", aliases) == "d"
        assert _resolve_index_alias(None, aliases) is None
        assert _resolve_index_alias("", aliases) is None
        assert _resolve_index_alias("   ", aliases) is None  # Whitespace-only

        # Test alias chain with invalid next value
        bad_aliases = {"x": None, "y": "   ", "z": "a"}
        assert _resolve_index_alias("x", bad_aliases) == "x"  # Stops at invalid None
        assert _resolve_index_alias("y", bad_aliases) == "y"  # Stops at whitespace-only

    def test_extract_index_taxonomy(self):
        """_extract_index_taxonomy should extract normalized taxonomy."""
        from knowledgebase.api.main import _extract_index_taxonomy

        entry = {
            "top_group": "  Operations  ",
            "domain": "Connections",
            "subgroup": "  Active  ",
            "taxonomy": {
                "domain": "Should not override",
            },
            "lifecycle_state": None,
        }
        result = _extract_index_taxonomy(entry)

        assert result["top_group"] == "Operations"
        assert result["domain"] == "Connections"
        assert result["subgroup"] == "Active"
        assert result["lifecycle_state"] == "active"

    def test_normalize_kb_search_configuration_rejects_broad_unscoped_query(self):
        """Unscoped wildcard/all-style queries should be rejected early."""
        from knowledgebase.api.main import _normalize_kb_search_configuration

        normalized, notes, error = _normalize_kb_search_configuration({"query": "all"})

        assert normalized == {}
        assert notes == []
        assert error is not None
        assert "too broad" in error.lower()

    def test_normalize_kb_search_configuration_hardens_unscoped_query(self):
        """Unscoped single-term queries should be auto-hardened for bounded MCP calls."""
        from knowledgebase.api.main import (
            _KB_SEARCH_SAFE_MAX_OFFSET,
            _KB_SEARCH_SAFE_UNSCOPED_MIN_SCORE,
            _KB_SEARCH_SAFE_UNSCOPED_TOP_K,
            _normalize_kb_search_configuration,
        )

        normalized, notes, error = _normalize_kb_search_configuration(
            {
                "query": "status",
                "top_k": 25,
                "min_score": 0.1,
                "offset": 1000,
                "summarize": False,
                "full_content": True,
            }
        )

        assert error is None
        assert normalized["limit"] == _KB_SEARCH_SAFE_UNSCOPED_TOP_K
        assert normalized["min_score"] == _KB_SEARCH_SAFE_UNSCOPED_MIN_SCORE
        assert normalized["offset"] == _KB_SEARCH_SAFE_MAX_OFFSET
        assert normalized["summarize"] is True
        assert normalized["full_content"] is False
        assert notes


class TestMCPErrors:
    """Tests for MCP error handling."""

    def test_json_decode_error(self, client):
        """Invalid JSON should return parse error."""
        response = client.post(
            "/mcp/sse",
            data="not valid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32700

    def test_unexpected_error_returns_500(self, client):
        """Unexpected errors should return server error."""
        with patch("knowledgebase.api.main._handle_mcp_rpcs_request") as mock_handler:
            mock_handler.side_effect = Exception("Unexpected error")

            response = client.post(
                "/mcp/sse",
                json={"jsonrpc": "2.0", "method": "tools/list", "id": 99},
            )

            assert response.status_code == 500
            data = response.json()
            assert data["jsonrpc"] == "2.0"
            assert data["error"]["code"] == -32603
