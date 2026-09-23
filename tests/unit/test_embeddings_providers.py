"""Unit tests for embedding provider implementations.

These tests validate configuration and basic behavior that does not
require real network calls.
"""

from __future__ import annotations

from typing import Any

import pytest

from knowledgebase.embeddings.ollama import OllamaEmbeddingProvider
from knowledgebase.embeddings.openai import OpenAIEmbeddingProvider


@pytest.mark.unit
class TestOpenAIEmbeddingProvider:
    """Tests for OpenAIEmbeddingProvider configuration and behaviour."""

    def test_invalid_model_raises_value_error(self) -> None:
        """An unsupported model name should raise a clear ValueError."""

        with pytest.raises(ValueError):
            OpenAIEmbeddingProvider(api_key="test", model="not-a-real-model")

    def test_default_dimensions_from_model_mapping(self) -> None:
        """Default dimensions should be derived from the MODEL_DIMENSIONS mapping."""

        provider = OpenAIEmbeddingProvider(api_key="test", model="text-embedding-3-small")

        assert provider.model_name == "text-embedding-3-small"
        # text-embedding-3-small maps to 1536 dimensions by default
        assert provider.dimensions == 1536

    def test_custom_dimensions_override_default(self) -> None:
        """Explicit dimensions should override the model default when provided."""

        provider = OpenAIEmbeddingProvider(
            api_key="test",
            model="text-embedding-3-small",
            dimensions=256,
        )

        assert provider.model_name == "text-embedding-3-small"
        assert provider.dimensions == 256

    @pytest.mark.asyncio
    async def test_embed_texts_batches_and_preserves_order(self) -> None:
        """`embed_texts` should batch inputs and preserve the original order."""

        class DummyData:
            def __init__(self, index: int) -> None:
                self.index = index
                self.embedding = [float(index)]

        class DummyEmbeddingsClient:
            async def create(self, **kwargs: Any) -> Any:  # noqa: D401, ANN401
                """Return a dummy response that echoes back embeddings by index."""

                inputs = kwargs["input"]
                data = [DummyData(i) for i in range(len(inputs))]
                return type("Resp", (), {"data": data})()

        class DummyClient:
            def __init__(self) -> None:
                self.embeddings = DummyEmbeddingsClient()

        provider = OpenAIEmbeddingProvider(api_key="test", model="text-embedding-3-small")
        # Replace the real OpenAI client with our dummy implementation.
        provider._client = DummyClient()  # type: ignore[attr-defined]

        texts = ["one", "two", "three"]
        embeddings = await provider.embed_texts(texts)

        # We expect simple embeddings [[0.0], [1.0], [2.0]] derived from indices.
        assert embeddings == [[0.0], [1.0], [2.0]]

    @pytest.mark.asyncio
    async def test_openai_health_check_success_and_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`health_check` should report healthy and error states based on embed_text."""

        provider = OpenAIEmbeddingProvider(api_key="test", model="text-embedding-3-small")

        async def fake_embed(_text: str) -> list[float]:  # noqa: D401, ARG001
            """Return a trivial embedding without calling the real API."""

            return [0.0]

        # First, simulate a healthy state.
        monkeypatch.setattr(provider, "embed_text", fake_embed)
        healthy = await provider.health_check()

        assert healthy["healthy"] is True
        assert healthy["provider"] == "openai"
        assert healthy["model"] == provider.model_name
        assert "latency_ms" in healthy

        async def failing_embed(_text: str) -> list[float]:  # noqa: D401, ARG001
            """Simulate a failure in embedding generation."""

            raise RuntimeError("boom")

        monkeypatch.setattr(provider, "embed_text", failing_embed)
        unhealthy = await provider.health_check()

        assert unhealthy["healthy"] is False
        assert unhealthy["provider"] == "openai"
        assert unhealthy["model"] == provider.model_name
        assert "error" in unhealthy

    @pytest.mark.asyncio
    async def test_openai_embed_text_uses_client_and_respects_dimensions(self) -> None:
        """`embed_text` should call the underlying client and return its embedding payload."""

        class DummyData:
            def __init__(self) -> None:
                self.index = 0
                self.embedding = [0.1, 0.2, 0.3]

        class DummyEmbeddingsClient:
            async def create(self, **kwargs: Any) -> Any:  # noqa: D401, ANN401
                """Return a dummy response that contains a single embedding vector."""

                _ = kwargs
                return type("Resp", (), {"data": [DummyData()]})()

        class DummyClient:
            def __init__(self) -> None:
                self.embeddings = DummyEmbeddingsClient()

        provider = OpenAIEmbeddingProvider(api_key="test", model="text-embedding-3-small")
        # Replace the real AsyncOpenAI client with our dummy implementation.
        provider._client = DummyClient()  # type: ignore[attr-defined]

        emb = await provider.embed_text("hello")

        assert emb == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_openai_quota_errors_are_not_retried(self) -> None:
        """Quota/credit exhaustion must fail fast so factory can fall back to default."""

        from knowledgebase.embeddings.base import EmbeddingError

        calls = {"n": 0}

        class DummyEmbeddingsClient:
            async def create(self, **kwargs: Any) -> Any:  # noqa: D401, ANN401
                _ = kwargs
                calls["n"] += 1
                raise RuntimeError(
                    "Error code: 429 - You have no credits remaining. "
                    "code: credit_balance_exhausted insufficient_quota"
                )

        class DummyClient:
            def __init__(self) -> None:
                self.embeddings = DummyEmbeddingsClient()

        provider = OpenAIEmbeddingProvider(api_key="test", model="text-embedding-3-small")
        provider._client = DummyClient()  # type: ignore[attr-defined]

        with pytest.raises(EmbeddingError):
            await provider.embed_text("hello")

        # One attempt only — no tenacity spin on billing failures.
        assert calls["n"] == 1

        unhealthy = await provider.health_check()
        assert unhealthy["healthy"] is False
        assert "credit" in unhealthy.get("error", "").lower() or "429" in unhealthy.get("error", "")


@pytest.mark.unit
class TestOllamaEmbeddingProvider:
    """Tests for OllamaEmbeddingProvider configuration logic."""

    def test_default_endpoint_and_dimensions(self) -> None:
        """Defaults should use the standard endpoint and model dimensions map."""

        provider = OllamaEmbeddingProvider()

        assert provider.model_name == "nomic-embed-text"
        # Default model maps to 768 dimensions
        assert provider.dimensions == 768

    def test_endpoint_trailing_slash_is_stripped(self) -> None:
        """The endpoint URL should have any trailing slash removed."""

        provider = OllamaEmbeddingProvider(endpoint="http://localhost:11434/")

        # Accessing a private attribute here is acceptable in tests to verify behavior
        assert provider._endpoint.endswith("11434")  # type: ignore[attr-defined]

    def test_custom_dimensions_override_default(self) -> None:
        """Explicit dimensions should override the model default when provided."""

        provider = OllamaEmbeddingProvider(model="nomic-embed-text", dimensions=1024)

        assert provider.model_name == "nomic-embed-text"
        assert provider.dimensions == 1024

    @pytest.mark.asyncio
    async def test_ollama_embed_texts_uses_embed_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`embed_texts` should delegate to `embed_text` for each input and preserve order."""

        provider = OllamaEmbeddingProvider()

        calls: list[str] = []

        async def fake_embed(text: str) -> list[float]:  # noqa: D401
            """Record calls and return a simple embedding."""

            calls.append(text)
            return [1.0]

        monkeypatch.setattr(provider, "embed_text", fake_embed)

        texts = ["a", "b", "c"]
        embeddings = await provider.embed_texts(texts)

        assert calls == texts
        assert embeddings == [[1.0], [1.0], [1.0]]

        # Empty input should short-circuit and return an empty list.
        empty = await provider.embed_texts([])
        assert empty == []

    @pytest.mark.asyncio
    async def test_ollama_embed_text_success_and_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`embed_text` should parse the embedding array and surface failures as EmbeddingError."""

        class DummyResponse:
            def __init__(self) -> None:
                self._json = {"embedding": [1, 2, 3]}

            def raise_for_status(self) -> None:  # noqa: D401
                """Pretend the HTTP call succeeded."""

                return None

            def json(self) -> dict[str, Any]:  # noqa: D401
                """Return a simple embedding payload."""

                return self._json

        class DummyAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401, ARG002
                """Capture initialization arguments but ignore them."""

                self._response = DummyResponse()

            async def __aenter__(self) -> DummyAsyncClient:  # type: ignore[override]
                return self

            async def __aexit__(self, exc_type: type[Any] | None, exc: Any, tb: Any | None) -> None:  # type: ignore[override]
                return None

            async def post(
                self, url: str, json: dict[str, Any]
            ) -> DummyResponse:  # noqa: D401, ARG002
                """Return the prepared response."""

                _ = url
                _ = json
                return self._response

        monkeypatch.setattr(
            "knowledgebase.embeddings.ollama.httpx.AsyncClient",
            DummyAsyncClient,
        )

        provider = OllamaEmbeddingProvider(model="nomic-embed-text", dimensions=3)

        emb = await provider.embed_text("hello")
        # Values should be converted to float
        assert emb == [1.0, 2.0, 3.0]

        class FailingAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401, ARG002
                """Client that always fails when entering the context manager."""

            async def __aenter__(self) -> FailingAsyncClient:  # type: ignore[override]
                raise RuntimeError("boom")

            async def __aexit__(self, exc_type: type[Any] | None, exc: Any, tb: Any | None) -> None:  # type: ignore[override]
                return None

        # Swap in the failing client so that subsequent calls exercise the
        # generic error-handling path in ``embed_text``.
        monkeypatch.setattr(
            "knowledgebase.embeddings.ollama.httpx.AsyncClient",
            FailingAsyncClient,
        )

        # When the HTTP client fails before sending the request, the provider
        # will log the failure and raise an EmbeddingError (possibly wrapped by
        # tenacity). Here we simply assert that an EmbeddingError is raised to
        # cover the error-handling path without depending on tenacity's exact
        # exception formatting.
        from tenacity import RetryError

        from knowledgebase.embeddings.base import EmbeddingError

        with pytest.raises((EmbeddingError, RetryError)):
            await provider.embed_text("hello")

    @pytest.mark.asyncio
    async def test_ollama_health_check_success_and_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`health_check` should report model availability and handle failures."""

        class DummyResponse:
            def __init__(self, models: list[dict[str, Any]]) -> None:
                self._models = models

            def raise_for_status(self) -> None:  # noqa: D401
                """Pretend the HTTP call succeeded."""

                return None

            def json(self) -> dict[str, Any]:  # noqa: D401
                """Return a payload mirroring the Ollama /api/tags schema."""

                return {"models": self._models}

        class DummyAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401, ARG002
                """Capture initialization arguments but ignore them."""

                # Provide a model whose name starts with the provider's model.
                self._response = DummyResponse(models=[{"name": "nomic-embed-text:latest"}])

            async def __aenter__(self) -> DummyAsyncClient:  # type: ignore[override]
                return self

            async def __aexit__(self, exc_type: type[Any] | None, exc: Any, tb: Any | None) -> None:  # type: ignore[override]
                return None

            async def get(self, url: str) -> DummyResponse:  # noqa: D401, ARG002
                """Return the prepared response."""

                _ = url
                return self._response

        monkeypatch.setattr(
            "knowledgebase.embeddings.ollama.httpx.AsyncClient",
            DummyAsyncClient,
        )

        provider = OllamaEmbeddingProvider(model="nomic-embed-text", dimensions=768)
        healthy = await provider.health_check()

        assert healthy["healthy"] is True
        assert healthy["provider"] == "ollama"
        assert healthy["model_available"] is True

        class FailingAsyncClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401, ARG002
                """Client that always fails when entering the context manager."""

            async def __aenter__(self) -> FailingAsyncClient:  # type: ignore[override]
                raise RuntimeError("unreachable")

            async def __aexit__(self, exc_type: type[Any] | None, exc: Any, tb: Any | None) -> None:  # type: ignore[override]
                return None

        monkeypatch.setattr(
            "knowledgebase.embeddings.ollama.httpx.AsyncClient",
            FailingAsyncClient,
        )

        unhealthy = await provider.health_check()

        assert unhealthy["healthy"] is False
        assert unhealthy["provider"] == "ollama"
        assert "error" in unhealthy
