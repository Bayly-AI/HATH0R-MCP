"""Unit tests for the storage backend factory.

These tests validate backend selection and configuration without
connecting to real infrastructure.
"""

from __future__ import annotations

from typing import Any

import pytest

from knowledgebase.core.config import StorageSettings
from knowledgebase.storage.factory import get_storage_backend


class _DummyLocalBackend:
    """Dummy local backend used to validate configuration wiring."""

    def __init__(self, base_path: str) -> None:  # type: ignore[unused-ignore]
        self.base_path = base_path


class _DummyOpenSearchBackend:
    """Dummy OpenSearch backend used to validate configuration wiring."""

    def __init__(
        self,
        endpoint: str,
        region: str,
        use_sigv4: bool,
        index_prefix: str,
        vector_dimension: int,
    ) -> None:  # type: ignore[unused-ignore]
        self.endpoint = endpoint
        self.region = region
        self.use_sigv4 = use_sigv4
        self.index_prefix = index_prefix
        self.vector_dimension = vector_dimension


@pytest.mark.unit
class TestGetStorageBackend:
    """Tests for storage backend selection."""

    def test_local_backend_uses_configured_base_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_storage_backend should construct a LocalStorageBackend with the configured path."""

        created: dict[str, Any] = {}

        def _factory(base_path: str) -> _DummyLocalBackend:  # type: ignore[override]
            created["base_path"] = base_path
            return _DummyLocalBackend(base_path=base_path)

        monkeypatch.setattr(
            "knowledgebase.storage.factory.LocalStorageBackend",
            _factory,
        )

        settings = StorageSettings(backend="local", local_path="/tmp/indices")

        backend = get_storage_backend(backend="local", settings=settings)

        assert isinstance(backend, _DummyLocalBackend)
        assert created["base_path"] == "/tmp/indices"

    def test_opensearch_backend_uses_settings_values(
        self, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
    ) -> None:
        """get_storage_backend should construct an OpenSearch backend with correct parameters."""

        from knowledgebase.core.config import get_settings

        # get_settings() is @lru_cache'd process-wide, so a prior test's call
        # (with the default KB_EMBEDDING__DIMENSIONS) can otherwise leak into
        # this one -- clear it before setting the env var (same pattern as
        # test_config_settings.py's cache-clearing tests), and clear it again
        # on teardown so this test's 1024 override doesn't leak into whatever
        # runs next.
        get_settings.cache_clear()
        request.addfinalizer(get_settings.cache_clear)
        monkeypatch.setenv("KB_EMBEDDING__DIMENSIONS", "1024")

        created: dict[str, Any] = {}

        def _factory(
            endpoint: str,
            region: str,
            use_sigv4: bool,
            index_prefix: str,
            vector_dimension: int,
        ) -> _DummyOpenSearchBackend:  # type: ignore[override]
            created["endpoint"] = endpoint
            created["region"] = region
            created["use_sigv4"] = use_sigv4
            created["index_prefix"] = index_prefix
            created["vector_dimension"] = vector_dimension
            return _DummyOpenSearchBackend(
                endpoint=endpoint,
                region=region,
                use_sigv4=use_sigv4,
                index_prefix=index_prefix,
                vector_dimension=vector_dimension,
            )

        # Ensure that when get_storage_backend imports
        # ``knowledgebase.storage.opensearch.OpenSearchStorageBackend`` it
        # receives our dummy implementation instead of the real backend,
        # avoiding any dependency on opensearchpy.
        import sys
        import types

        dummy_module = types.SimpleNamespace(OpenSearchStorageBackend=_factory)
        monkeypatch.setitem(sys.modules, "knowledgebase.storage.opensearch", dummy_module)

        settings = StorageSettings(
            backend="opensearch",
            OPENSEARCH_ENDPOINT="https://search.example.com",  # type: ignore[arg-type]
            AWS_REGION="us-west-2",  # type: ignore[arg-type]
            opensearch_use_sigv4=False,
            index_prefix="kb-",
        )

        backend = get_storage_backend(backend="opensearch", settings=settings)

        assert isinstance(backend, _DummyOpenSearchBackend)
        assert created["endpoint"] == "https://search.example.com"
        assert created["region"] == "us-west-2"
        assert created["use_sigv4"] is False
        assert created["index_prefix"] == "kb-"
        assert created["vector_dimension"] == 1024

    def test_unsupported_backend_raises_value_error(self) -> None:
        """An unsupported backend name should raise a clear ValueError."""

        # Cast to satisfy the type checker while exercising the error path.
        settings = StorageSettings(backend="local")

        with pytest.raises(ValueError):
            get_storage_backend(backend="not-supported", settings=settings)  # type: ignore[arg-type]
