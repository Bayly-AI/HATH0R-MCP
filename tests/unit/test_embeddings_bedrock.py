"""Unit tests for the Bedrock embedding provider.

These tests validate configuration and basic behavior without
performing real AWS API calls.
"""

from __future__ import annotations

import io
import json
import time
from typing import Any

import pytest
from botocore.exceptions import ClientError
from knowledgebase.embeddings.base import EmbeddingError

from knowledgebase.embeddings.bedrock import BedrockEmbeddingProvider


class _MockStreamingBody:
    """Mock for boto3 StreamingBody response."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = json.dumps(data).encode()
        self._stream = io.BytesIO(self._data)

    def read(self) -> bytes:
        return self._stream.read()


class _MockBedrockClient:
    """Mock boto3 bedrock-runtime client for testing."""

    def __init__(self, response_data: dict[str, Any] | None = None) -> None:
        self._response_data = response_data or {"embedding": [0.1, 0.2, 0.3]}
        self._calls: list[dict[str, Any]] = []

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        """Mock invoke_model that returns configured response."""
        self._calls.append(kwargs)
        return {"body": _MockStreamingBody(self._response_data)}


class _MockFailingBedrockClient:
    """Mock boto3 client that raises ClientError."""

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        """Mock invoke_model that raises a ClientError."""
        _ = kwargs
        error_response = {
            "Error": {
                "Code": "ValidationException",
                "Message": "Model not found",
            }
        }
        raise ClientError(error_response, "InvokeModel")


class _MockSlowBedrockClient:
    """Mock boto3 client that delays invoke_model responses."""

    def __init__(self, delay_seconds: float = 0.1) -> None:
        self._delay_seconds = delay_seconds

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        """Mock invoke_model that sleeps before returning."""
        _ = kwargs
        time.sleep(self._delay_seconds)
        return {"body": _MockStreamingBody({"embedding": [0.1, 0.2, 0.3]})}


@pytest.mark.unit
class TestBedrockEmbeddingProvider:
    """Tests for BedrockEmbeddingProvider configuration and behaviour."""

    def test_invalid_model_raises_value_error(self) -> None:
        """An unsupported model name should raise a clear ValueError."""
        with pytest.raises(ValueError):
            BedrockEmbeddingProvider(model="not-a-real-model")

    def test_default_dimensions_from_model_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default dimensions should be derived from the MODEL_DIMENSIONS mapping."""
        # Mock boto3.client to avoid actual AWS calls during init
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: _MockBedrockClient(),
        )

        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v2:0")

        assert provider.model_name == "amazon.titan-embed-text-v2:0"
        # Titan v2 maps to 1024 dimensions by default
        assert provider.dimensions == 1024

    def test_titan_v1_dimensions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Titan v1 should have 1536 dimensions."""
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: _MockBedrockClient(),
        )

        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v1")

        assert provider.model_name == "amazon.titan-embed-text-v1"
        assert provider.dimensions == 1536

    def test_custom_dimensions_for_titan_v2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit dimensions should work for Titan v2 which supports configurable dims."""
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: _MockBedrockClient(),
        )

        provider = BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v2:0",
            dimensions=512,
        )

        assert provider.dimensions == 512

    def test_custom_dimensions_ignored_for_non_configurable_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Models without configurable dimensions should ignore the dimensions argument."""
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: _MockBedrockClient(),
        )

        # Titan v1 doesn't support configurable dimensions
        provider = BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v1",
            dimensions=512,  # Should be ignored
        )

        # Should use model default, not the requested value
        assert provider.dimensions == 1536

    def test_region_configuration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Region should be configurable via constructor."""
        client_kwargs: dict[str, Any] = {}

        def mock_client(*args: Any, **kwargs: Any) -> _MockBedrockClient:
            client_kwargs.update(kwargs)
            return _MockBedrockClient()

        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            mock_client,
        )

        BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v2:0",
            region="us-west-2",
        )

        assert client_kwargs.get("region_name") == "us-west-2"

    def test_invoke_timeout_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Provider should read default invoke timeout from environment."""
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: _MockBedrockClient(),
        )
        monkeypatch.setenv("KB_BEDROCK_INVOKE_TIMEOUT_SECONDS", "12.5")

        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v2:0")

        assert provider._invoke_timeout_seconds == 12.5

    @pytest.mark.asyncio
    async def test_embed_text_titan_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`embed_text` should call the Bedrock API and return embeddings for Titan models."""
        mock_client = _MockBedrockClient(response_data={"embedding": [0.1, 0.2, 0.3]})
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: mock_client,
        )

        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v2:0")
        embedding = await provider.embed_text("hello world")

        assert embedding == [0.1, 0.2, 0.3]
        assert len(mock_client._calls) == 1

        # Verify the request body format for Titan
        call = mock_client._calls[0]
        request_body = json.loads(call["body"])
        assert "inputText" in request_body
        assert request_body["inputText"] == "hello world"
        assert request_body.get("dimensions") == 1024
        assert request_body.get("normalize") is True

    @pytest.mark.asyncio
    async def test_embed_text_cohere_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`embed_text` should format requests correctly for Cohere models."""
        mock_client = _MockBedrockClient(response_data={"embeddings": [[0.4, 0.5, 0.6]]})
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: mock_client,
        )

        provider = BedrockEmbeddingProvider(model="cohere.embed-english-v3")
        embedding = await provider.embed_text("hello world")

        assert embedding == [0.4, 0.5, 0.6]

        # Verify the request body format for Cohere
        call = mock_client._calls[0]
        request_body = json.loads(call["body"])
        assert "texts" in request_body
        assert request_body["texts"] == ["hello world"]
        assert request_body["input_type"] == "search_document"

    @pytest.mark.asyncio
    async def test_embed_texts_sequential_for_titan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`embed_texts` should process texts sequentially for Titan (no batch support)."""
        call_count = 0

        def mock_invoke(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"body": _MockStreamingBody({"embedding": [float(call_count)]})}

        class CountingClient:
            def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
                return mock_invoke(**kwargs)

        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: CountingClient(),
        )

        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v2:0")
        embeddings = await provider.embed_texts(["one", "two", "three"])

        # Each text should result in a separate API call
        assert call_count == 3
        assert embeddings == [[1.0], [2.0], [3.0]]

    @pytest.mark.asyncio
    async def test_embed_texts_batch_for_cohere(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`embed_texts` should use batch API for Cohere models."""
        mock_client = _MockBedrockClient(response_data={"embeddings": [[0.1], [0.2], [0.3]]})
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: mock_client,
        )

        provider = BedrockEmbeddingProvider(model="cohere.embed-english-v3")
        embeddings = await provider.embed_texts(["one", "two", "three"])

        # Cohere should batch - only one API call
        assert len(mock_client._calls) == 1
        assert embeddings == [[0.1], [0.2], [0.3]]

        # Verify batch request format
        call = mock_client._calls[0]
        request_body = json.loads(call["body"])
        assert request_body["texts"] == ["one", "two", "three"]

    @pytest.mark.asyncio
    async def test_embed_texts_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`embed_texts` should return empty list for empty input."""
        mock_client = _MockBedrockClient()
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: mock_client,
        )

        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v2:0")
        embeddings = await provider.embed_texts([])

        assert embeddings == []
        assert len(mock_client._calls) == 0

    @pytest.mark.asyncio
    async def test_embed_query_cohere_uses_search_query_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`embed_query` should use 'search_query' input type for Cohere models."""
        mock_client = _MockBedrockClient(response_data={"embeddings": [[0.7, 0.8, 0.9]]})
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: mock_client,
        )

        provider = BedrockEmbeddingProvider(model="cohere.embed-english-v3")
        embedding = await provider.embed_query("search query")

        assert embedding == [0.7, 0.8, 0.9]

        # Verify input_type is search_query for queries
        call = mock_client._calls[0]
        request_body = json.loads(call["body"])
        assert request_body["input_type"] == "search_query"

    @pytest.mark.asyncio
    async def test_health_check_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`health_check` should report healthy when API responds correctly."""
        mock_client = _MockBedrockClient(response_data={"embedding": [0.1, 0.2, 0.3]})
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: mock_client,
        )

        provider = BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v2:0",
            region="us-east-1",
        )
        health = await provider.health_check()

        assert health["healthy"] is True
        assert health["provider"] == "bedrock"
        assert health["model"] == "amazon.titan-embed-text-v2:0"
        assert health["dimensions"] == 1024
        assert "latency_ms" in health

    @pytest.mark.asyncio
    async def test_health_check_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`health_check` should report unhealthy when API fails."""
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: _MockFailingBedrockClient(),
        )

        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v2:0")
        health = await provider.health_check()

        assert health["healthy"] is False
        assert health["provider"] == "bedrock"
        assert "error" in health

    @pytest.mark.asyncio
    async def test_embed_text_client_error_handling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`embed_text` should raise EmbeddingError on ClientError."""
        from tenacity import RetryError

        from knowledgebase.embeddings.base import EmbeddingError

        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: _MockFailingBedrockClient(),
        )

        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v2:0")

        with pytest.raises((EmbeddingError, RetryError)):
            await provider.embed_text("hello")

    @pytest.mark.asyncio
    async def test_invoke_model_async_timeout_raises_embedding_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_invoke_model_async` should produce a bounded timeout EmbeddingError."""
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: _MockSlowBedrockClient(delay_seconds=0.05),
        )
        provider = BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v2:0",
            invoke_timeout_seconds=0.01,
        )

        request_body = provider._build_request_body("hello")
        with pytest.raises(EmbeddingError, match="timed out"):
            await provider._invoke_model_async(request_body)

    @pytest.mark.asyncio
    async def test_text_truncation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Long text should be truncated to 8000 characters."""
        mock_client = _MockBedrockClient(response_data={"embedding": [0.1]})
        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            lambda *_, **__: mock_client,
        )

        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v2:0")
        long_text = "x" * 10000
        await provider.embed_text(long_text)

        call = mock_client._calls[0]
        request_body = json.loads(call["body"])
        assert len(request_body["inputText"]) == 8000

    def test_aws_credentials_passed_to_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AWS credentials should be passed to boto3 client when provided."""
        client_kwargs: dict[str, Any] = {}

        def mock_client(*args: Any, **kwargs: Any) -> _MockBedrockClient:
            client_kwargs.update(kwargs)
            return _MockBedrockClient()

        monkeypatch.setattr(
            "knowledgebase.embeddings.bedrock.boto3.client",
            mock_client,
        )

        BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v2:0",
            aws_access_key_id="test-key-id",
            aws_secret_access_key="test-secret",
        )

        assert client_kwargs.get("aws_access_key_id") == "test-key-id"
        assert client_kwargs.get("aws_secret_access_key") == "test-secret"
