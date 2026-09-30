"""Unit tests for embedding and MCP timeout guard behavior."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

import knowledgebase.api.main as main
from knowledgebase.embeddings.openai import OpenAIEmbeddingProvider


@pytest.mark.unit
def test_openai_provider_sets_client_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI provider should initialize AsyncOpenAI with a 10 second timeout."""

    captured_kwargs: dict[str, Any] = {}

    class DummyClient:
        def __init__(self) -> None:
            self.embeddings = object()

    def fake_async_openai(**kwargs: Any) -> DummyClient:
        captured_kwargs.update(kwargs)
        return DummyClient()

    monkeypatch.setattr("knowledgebase.embeddings.openai.AsyncOpenAI", fake_async_openai)
    _ = OpenAIEmbeddingProvider(api_key="test-key")

    assert captured_kwargs["timeout"] == 30.0


@pytest.mark.asyncio
async def test_get_query_embedding_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """_get_query_embedding should fail fast when provider embed_query stalls."""

    class SlowEmbeddings:
        model_name = "slow-model"
        dimensions = 768

        async def embed_query(self, query: str) -> list[float]:  # noqa: ARG002
            await asyncio.sleep(0.1)
            return [0.1]

    monkeypatch.setattr(main, "_embeddings", SlowEmbeddings())
    monkeypatch.setattr(main, "_QUERY_EMBED_TIMEOUT_SECONDS", 0.01)

    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await main._get_query_embedding("timeout me")


@pytest.mark.asyncio
async def test_get_document_embedding_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_document_embedding should fail fast when provider embed_text stalls."""

    class SlowEmbeddings:
        model_name = "slow-model"
        dimensions = 768

        async def embed_text(self, text: str) -> list[float]:  # noqa: ARG002
            await asyncio.sleep(0.1)
            return [0.1]

    monkeypatch.setattr(main, "_embeddings", SlowEmbeddings())
    monkeypatch.setattr(main, "_DOCUMENT_EMBED_TIMEOUT_SECONDS", 0.01)

    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await main._get_document_embedding("timeout me")


@pytest.mark.asyncio
async def test_kb_add_document_timeout_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """kb_add_document should return MCP error payload when embedding times out."""

    class SlowEmbeddings:
        model_name = "slow-model"
        dimensions = 768

        async def embed_text(self, text: str) -> list[float]:  # noqa: ARG002
            await asyncio.sleep(0.1)
            return [0.1]

    mock_storage = AsyncMock()
    mock_storage.add_document = AsyncMock()

    monkeypatch.setattr(main, "_embeddings", SlowEmbeddings())
    monkeypatch.setattr(main, "_storage", mock_storage)
    monkeypatch.setattr(main, "_mcp_service", None)
    monkeypatch.setattr(main, "_DOCUMENT_EMBED_TIMEOUT_SECONDS", 0.01)

    result = await main._execute_mcp_tool(
        "kb_add_document",
        {"id": "doc-timeout", "content": "hello"},
    )

    assert result["isError"] is True
    assert "Document embedding timed out" in result["content"][0]["text"]
    mock_storage.add_document.assert_not_called()


@pytest.mark.asyncio
async def test_mcp_tool_call_timeout_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tools/call should return MCP error payload when execution exceeds timeout."""

    async def slow_execute(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        await asyncio.sleep(0.1)
        return {"content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(main, "_execute_mcp_tool", slow_execute)
    monkeypatch.setattr(main, "_MCP_TOOL_TIMEOUT_SECONDS", 0.01)

    response = await main._handle_mcp_rpcs_request(
        "tools/call",
        {"name": "kb_search", "arguments": {"query": "hello"}},
        request_id=1,
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == 1
    assert payload["result"]["isError"] is True
    assert "timed out" in payload["result"]["content"][0]["text"]
