"""Unit tests for the embeddings factory.

These tests focus on provider selection and fallback behavior without
performing real network calls to OpenAI, Ollama, or Bedrock.
"""

from __future__ import annotations

from typing import Any

import pytest

from knowledgebase.core.config import EmbeddingSettings
from knowledgebase.embeddings.factory import (
    _provider_candidate_order,
    get_embedding_provider,
    get_embedding_provider_with_fallback,
    resolve_embedding_provider,
)


class _DummyOpenAIProvider:
    """Dummy provider used to validate OpenAI configuration wiring."""

    def __init__(self, api_key: str | None, model: str, dimensions: int) -> None:  # type: ignore[unused-ignore]
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - not used in this test
        return {"healthy": True, "provider": "openai"}


class _DummyOllamaProvider:
    """Dummy provider used to validate Ollama configuration wiring."""

    def __init__(self, model: str, endpoint: str, dimensions: int) -> None:  # type: ignore[unused-ignore]
        self.model = model
        self.endpoint = endpoint
        self.dimensions = dimensions

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - not used in this test
        return {"healthy": True, "provider": "ollama"}


class _UnhealthyOpenAIProvider:
    """Dummy provider that always reports unhealthy (for fallback tests)."""

    def __init__(self, api_key: str | None, model: str, dimensions: int) -> None:  # type: ignore[unused-ignore]
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": False, "provider": "openai"}


class _HealthyOllamaProvider:
    """Dummy provider that always reports healthy (for fallback tests)."""

    def __init__(self, model: str, endpoint: str, dimensions: int) -> None:  # type: ignore[unused-ignore]
        self.model = model
        self.endpoint = endpoint
        self.dimensions = dimensions

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": True, "provider": "ollama"}


class _HealthyOpenAIProvider:
    """Dummy provider that always reports healthy (for fallback tests)."""

    def __init__(self, api_key: str | None, model: str, dimensions: int) -> None:  # type: ignore[unused-ignore]
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": True, "provider": "openai"}


class _UnhealthyOllamaProvider:
    """Dummy provider that always reports unhealthy (for fallback tests)."""

    def __init__(self, model: str, endpoint: str, dimensions: int) -> None:  # type: ignore[unused-ignore]
        self.model = model
        self.endpoint = endpoint
        self.dimensions = dimensions

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": False, "provider": "ollama"}


class _DummyBedrockProvider:
    """Dummy provider used to validate Bedrock configuration wiring."""

    def __init__(  # type: ignore[unused-ignore]
        self,
        model: str,
        region: str | None,
        dimensions: int,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ) -> None:
        self.model = model
        self.region = region
        self.dimensions = dimensions
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - not used in this test
        return {"healthy": True, "provider": "bedrock"}


class _HealthyBedrockProvider:
    """Dummy Bedrock provider that always reports healthy (for fallback tests)."""

    def __init__(  # type: ignore[unused-ignore]
        self,
        model: str,
        region: str | None,
        dimensions: int,
        aws_access_key_id: str | None = None,  # noqa: ARG002
        aws_secret_access_key: str | None = None,  # noqa: ARG002
    ) -> None:
        self.model = model
        self.region = region
        self.dimensions = dimensions

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": True, "provider": "bedrock"}


class _UnhealthyBedrockProvider:
    """Dummy Bedrock provider that always reports unhealthy (for fallback tests)."""

    def __init__(  # type: ignore[unused-ignore]
        self,
        model: str,
        region: str | None,
        dimensions: int,
        aws_access_key_id: str | None = None,  # noqa: ARG002
        aws_secret_access_key: str | None = None,  # noqa: ARG002
    ) -> None:
        self.model = model
        self.region = region
        self.dimensions = dimensions

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": False, "provider": "bedrock"}


@pytest.mark.unit
class TestGetEmbeddingProvider:
    """Tests for basic provider selection."""

    def test_openai_provider_uses_settings_and_env_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_embedding_provider should construct an OpenAI provider with the given settings."""

        created: dict[str, Any] = {}

        def _factory(api_key: str | None, model: str, dimensions: int) -> _DummyOpenAIProvider:  # type: ignore[override]
            created["api_key"] = api_key
            created["model"] = model
            created["dimensions"] = dimensions
            return _DummyOpenAIProvider(api_key=api_key, model=model, dimensions=dimensions)

        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OpenAIEmbeddingProvider",
            _factory,
        )

        settings = EmbeddingSettings(
            provider="openai",
            model="text-embedding-3-small",
            dimensions=1024,
            OPENAI_API_KEY="test-key",  # type: ignore[arg-type]
        )

        provider = get_embedding_provider(provider="openai", settings=settings)

        assert isinstance(provider, _DummyOpenAIProvider)
        assert created["api_key"] == "test-key"
        assert created["model"] == "text-embedding-3-small"
        assert created["dimensions"] == 1024

    def test_ollama_provider_rewrites_default_model_and_dimensions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When provider is ollama and model is the OpenAI default, the factory should use nomic-embed-text."""

        created: dict[str, Any] = {}

        def _factory(model: str, endpoint: str, dimensions: int) -> _DummyOllamaProvider:  # type: ignore[override]
            created["model"] = model
            created["endpoint"] = endpoint
            created["dimensions"] = dimensions
            return _DummyOllamaProvider(model=model, endpoint=endpoint, dimensions=dimensions)

        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OllamaEmbeddingProvider",
            _factory,
        )

        settings = EmbeddingSettings(
            provider="ollama",
            model="text-embedding-3-small",
            dimensions=1536,
        )

        provider = get_embedding_provider(provider="ollama", settings=settings)

        assert isinstance(provider, _DummyOllamaProvider)
        # The factory maps the OpenAI default model to "nomic-embed-text" and 768 dims for Ollama.
        assert created["model"] == "nomic-embed-text"
        assert created["dimensions"] == 768
        # Endpoint should come from settings.ollama_endpoint
        assert created["endpoint"] == settings.ollama_endpoint

    def test_unsupported_provider_raises_value_error(self) -> None:
        """Passing an unsupported provider name should raise a ValueError."""

        settings = EmbeddingSettings(provider="openai")

        with pytest.raises(ValueError):
            # type: ignore[arg-type] - deliberately passing an invalid provider type
            get_embedding_provider(provider="not-a-provider", settings=settings)

    def test_bedrock_provider_uses_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_embedding_provider should construct a Bedrock provider with the given settings."""

        created: dict[str, Any] = {}

        def _factory(  # type: ignore[override]
            model: str,
            region: str | None,
            dimensions: int,
            aws_access_key_id: str | None = None,
            aws_secret_access_key: str | None = None,
        ) -> _DummyBedrockProvider:
            created["model"] = model
            created["region"] = region
            created["dimensions"] = dimensions
            created["aws_access_key_id"] = aws_access_key_id
            created["aws_secret_access_key"] = aws_secret_access_key
            return _DummyBedrockProvider(
                model=model,
                region=region,
                dimensions=dimensions,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
            )

        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.BedrockEmbeddingProvider",
            _factory,
        )
        # Set environment variables for region and credentials
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")

        settings = EmbeddingSettings(
            provider="bedrock",
            model="amazon.titan-embed-text-v2:0",
            dimensions=1024,
        )

        provider = get_embedding_provider(provider="bedrock", settings=settings)

        assert isinstance(provider, _DummyBedrockProvider)
        assert created["model"] == "amazon.titan-embed-text-v2:0"
        assert created["region"] == "us-west-2"
        assert created["dimensions"] == 1024
        assert created["aws_access_key_id"] == "test-access-key"
        assert created["aws_secret_access_key"] == "test-secret-key"

    def test_bedrock_provider_rewrites_non_bedrock_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When provider is bedrock but model is not a Bedrock model, use default Titan model."""

        created: dict[str, Any] = {}

        def _factory(  # type: ignore[override]
            model: str,
            region: str | None,
            dimensions: int,
            aws_access_key_id: str | None = None,
            aws_secret_access_key: str | None = None,
        ) -> _DummyBedrockProvider:
            created["model"] = model
            return _DummyBedrockProvider(
                model=model,
                region=region,
                dimensions=dimensions,
            )

        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.BedrockEmbeddingProvider",
            _factory,
        )

        settings = EmbeddingSettings(
            provider="bedrock",
            model="text-embedding-3-small",  # OpenAI model, should be rewritten
            dimensions=1024,
        )

        provider = get_embedding_provider(provider="bedrock", settings=settings)

        assert isinstance(provider, _DummyBedrockProvider)
        # Should be rewritten to Bedrock default
        assert created["model"] == "amazon.titan-embed-text-v2:0"


@pytest.mark.unit
class TestGetEmbeddingProviderWithFallback:
    """Tests for provider fallback behavior based on health checks."""

    def test_candidate_order_prefers_openai_then_default_ollama(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With credentials, order is openai then configured default (ollama)."""

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        settings = EmbeddingSettings(provider="ollama", OPENAI_API_KEY="sk-test-key")  # type: ignore[arg-type]
        order = _provider_candidate_order(settings, "ollama")
        assert order[0] == "openai"
        assert order[1] == "ollama"

    @pytest.mark.asyncio
    async def test_unhealthy_openai_falls_back_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unhealthy OpenAI should fail over to a healthy default (ollama)."""

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OpenAIEmbeddingProvider",
            _UnhealthyOpenAIProvider,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OllamaEmbeddingProvider",
            _HealthyOllamaProvider,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.BedrockEmbeddingProvider",
            _UnhealthyBedrockProvider,
        )

        settings = EmbeddingSettings(provider="openai")

        provider = await get_embedding_provider_with_fallback(settings=settings)
        assert isinstance(provider, _HealthyOllamaProvider)

    @pytest.mark.asyncio
    async def test_preferred_healthy_openai_is_returned(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Healthy OpenAI is preferred when credentials exist."""

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OpenAIEmbeddingProvider",
            _HealthyOpenAIProvider,
        )
        # Fallback provider should not be consulted but we patch it defensively.
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OllamaEmbeddingProvider",
            _UnhealthyOllamaProvider,
        )

        settings = EmbeddingSettings(provider="ollama")

        provider = await get_embedding_provider_with_fallback(settings=settings)

        assert isinstance(provider, _HealthyOpenAIProvider)

    @pytest.mark.asyncio
    async def test_primary_healthy_provider_is_returned(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the primary provider is healthy, no fallback should be used."""

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.dotenv_values",
            lambda *_a, **_k: {},
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory._has_openai_credentials",
            lambda _settings: False,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OpenAIEmbeddingProvider",
            _HealthyOpenAIProvider,
        )
        # Fallback provider should not be consulted but we patch it defensively.
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OllamaEmbeddingProvider",
            _UnhealthyOllamaProvider,
        )

        settings = EmbeddingSettings(provider="openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        provider = await get_embedding_provider_with_fallback(settings=settings)

        assert isinstance(provider, _HealthyOpenAIProvider)

    @pytest.mark.asyncio
    async def test_no_healthy_providers_raises_runtime_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If all providers are unhealthy, a RuntimeError should be raised."""

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OpenAIEmbeddingProvider",
            _UnhealthyOpenAIProvider,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OllamaEmbeddingProvider",
            _UnhealthyOllamaProvider,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.BedrockEmbeddingProvider",
            _UnhealthyBedrockProvider,
        )

        settings = EmbeddingSettings(provider="openai")

        with pytest.raises(RuntimeError, match="No healthy embedding provider"):
            await get_embedding_provider_with_fallback(settings=settings)

    @pytest.mark.asyncio
    async def test_unhealthy_bedrock_falls_back_to_ollama(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unhealthy Bedrock default should fail over to healthy Ollama."""

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.dotenv_values",
            lambda *_a, **_k: {},
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory._has_openai_credentials",
            lambda _settings: False,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.BedrockEmbeddingProvider",
            _UnhealthyBedrockProvider,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OllamaEmbeddingProvider",
            _HealthyOllamaProvider,
        )

        settings = EmbeddingSettings(provider="bedrock")

        provider = await get_embedding_provider_with_fallback(settings=settings)
        assert isinstance(provider, _HealthyOllamaProvider)

    @pytest.mark.asyncio
    async def test_primary_healthy_bedrock_provider_is_returned(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the primary Bedrock provider is healthy, no fallback should be used."""

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.dotenv_values",
            lambda *_a, **_k: {},
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory._has_openai_credentials",
            lambda _settings: False,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.BedrockEmbeddingProvider",
            _HealthyBedrockProvider,
        )
        # Fallback provider should not be consulted
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OllamaEmbeddingProvider",
            _UnhealthyOllamaProvider,
        )

        settings = EmbeddingSettings(provider="bedrock")

        provider = await get_embedding_provider_with_fallback(settings=settings)

        assert isinstance(provider, _HealthyBedrockProvider)

    @pytest.mark.asyncio
    async def test_unhealthy_ollama_falls_back_to_bedrock(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unhealthy Ollama default should fail over to healthy Bedrock."""

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.dotenv_values",
            lambda *_a, **_k: {},
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory._has_openai_credentials",
            lambda _settings: False,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OllamaEmbeddingProvider",
            _UnhealthyOllamaProvider,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.BedrockEmbeddingProvider",
            _HealthyBedrockProvider,
        )

        settings = EmbeddingSettings(provider="ollama")

        provider = await get_embedding_provider_with_fallback(settings=settings)
        assert isinstance(provider, _HealthyBedrockProvider)

    @pytest.mark.asyncio
    async def test_auto_resolved_unhealthy_primary_can_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Auto-resolved primary may fall back when no explicit provider is set."""

        monkeypatch.setenv("INFRAOS_ENVIRONMENT", "local")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.OllamaEmbeddingProvider",
            _UnhealthyOllamaProvider,
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.BedrockEmbeddingProvider",
            _HealthyBedrockProvider,
        )
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.dotenv_values",
            lambda *_a, **_k: {},
        )
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory._has_openai_credentials",
            lambda _settings: False,
        )

        settings = EmbeddingSettings(provider=None)

        provider = await get_embedding_provider_with_fallback(settings=settings)
        assert isinstance(provider, _HealthyBedrockProvider)


@pytest.mark.unit
class TestResolveEmbeddingProvider:
    """Tests for embedding provider resolution with INFRAOS_ENVIRONMENT support."""

    def test_explicit_provider_takes_highest_precedence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit provider setting should override INFRAOS_ENVIRONMENT."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return staging environment
        mock_settings = Settings(aegis_environment="staging")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        # But explicitly set provider to ollama
        embedding_settings = EmbeddingSettings(provider="ollama")

        # Should use explicit provider, not cloud mapping
        resolved = resolve_embedding_provider(embedding_settings)
        assert resolved == "ollama"

    def test_local_environment_resolves_to_ollama(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """INFRAOS_ENVIRONMENT=local should resolve to ollama."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return local environment
        mock_settings = Settings(aegis_environment="local")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        settings = EmbeddingSettings(provider=None)  # No explicit provider

        resolved = resolve_embedding_provider(settings)
        assert resolved == "ollama"

    def test_dev_environment_resolves_to_bedrock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """INFRAOS_ENVIRONMENT=development should resolve to bedrock."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return dev environment
        mock_settings = Settings(aegis_environment="development")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        settings = EmbeddingSettings(provider=None)  # No explicit provider

        resolved = resolve_embedding_provider(settings)
        assert resolved == "bedrock"

    def test_staging_environment_resolves_to_bedrock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """INFRAOS_ENVIRONMENT=staging should resolve to bedrock."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return staging environment
        mock_settings = Settings(aegis_environment="staging")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        settings = EmbeddingSettings(provider=None)  # No explicit provider

        resolved = resolve_embedding_provider(settings)
        assert resolved == "bedrock"

    def test_testing_environment_resolves_to_bedrock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """INFRAOS_ENVIRONMENT=testing should resolve to bedrock."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return testing environment
        mock_settings = Settings(aegis_environment="testing")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        settings = EmbeddingSettings(provider=None)  # No explicit provider

        resolved = resolve_embedding_provider(settings)
        assert resolved == "bedrock"

    def test_production_environment_resolves_to_bedrock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """INFRAOS_ENVIRONMENT=production should resolve to bedrock."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return prod environment
        mock_settings = Settings(aegis_environment="production")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        settings = EmbeddingSettings(provider=None)  # No explicit provider

        resolved = resolve_embedding_provider(settings)
        assert resolved == "bedrock"

    def test_unknown_environment_falls_back_to_ollama(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unknown INFRAOS_ENVIRONMENT should fall back to ollama."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return unknown environment
        mock_settings = Settings(aegis_environment="unknown-env")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        settings = EmbeddingSettings(provider=None)  # No explicit provider

        resolved = resolve_embedding_provider(settings)
        assert resolved == "ollama"

    def test_none_provider_uses_aegis_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When provider is None, should use INFRAOS_ENVIRONMENT resolution."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return staging environment
        mock_settings = Settings(aegis_environment="staging")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        settings = EmbeddingSettings(provider=None)  # Explicitly None

        resolved = resolve_embedding_provider(settings)
        assert resolved == "bedrock"

    def test_openai_provider_preserved_with_aegis_environment_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Explicit openai provider should be preserved even when INFRAOS_ENVIRONMENT is set."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return prod environment
        mock_settings = Settings(aegis_environment="production")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        settings = EmbeddingSettings(provider="openai")  # Explicit openai

        resolved = resolve_embedding_provider(settings)
        assert resolved == "openai"

    def test_bedrock_provider_preserved_with_aegis_environment_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Explicit bedrock provider should be preserved even when INFRAOS_ENVIRONMENT is set."""
        from knowledgebase.core.config import Settings

        # Mock get_settings to return local environment (which normally maps to ollama)
        mock_settings = Settings(aegis_environment="local")
        monkeypatch.setattr(
            "knowledgebase.embeddings.factory.get_settings",
            lambda: mock_settings,
        )

        settings = EmbeddingSettings(
            provider="bedrock"
        )  # Explicit bedrock overrides local->ollama mapping

        resolved = resolve_embedding_provider(settings)
        assert resolved == "bedrock"
