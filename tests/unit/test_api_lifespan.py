"""Unit tests for API lifespan startup and shutdown behavior."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import knowledgebase.api.main as main


class _FakeStorage:
    """Minimal async storage double for lifespan tests."""

    def __init__(self, health_result: dict[str, Any] | Exception) -> None:
        self._health_result = health_result
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def health_check(self) -> dict[str, Any]:
        if isinstance(self._health_result, Exception):
            raise self._health_result
        return self._health_result

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_lifespan_raises_when_opensearch_required_but_backend_is_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifespan should refuse to start if KB_REQUIRE_OPENSEARCH_STORAGE is set
    but the resolved storage backend isn't opensearch -- guards against a
    manifest silently dropping KB_STORAGE__BACKEND and stranding documents
    on ephemeral storage.
    """

    get_storage_backend = MagicMock()
    monkeypatch.setattr(main, "get_storage_backend", get_storage_backend)
    monkeypatch.setattr(main.settings.storage, "backend", "local")
    monkeypatch.setenv("KB_REQUIRE_OPENSEARCH_STORAGE", "true")

    with pytest.raises(RuntimeError, match="KB_REQUIRE_OPENSEARCH_STORAGE"):
        async with main.lifespan(main.app):
            pass

    get_storage_backend.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_allows_local_backend_when_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without KB_REQUIRE_OPENSEARCH_STORAGE set, a local backend should start normally."""

    fake_storage = _FakeStorage({"backend": "local", "healthy": True})
    monkeypatch.setattr(main, "get_storage_backend", lambda: fake_storage)
    monkeypatch.setattr(
        main,
        "get_embedding_provider_with_fallback",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(main, "SystemMonitoringService", MagicMock())
    monkeypatch.setattr(main, "MCPService", MagicMock())
    monkeypatch.setattr(main.service_registry, "register", MagicMock())
    monkeypatch.setattr(main.service_registry, "initialize_all", AsyncMock())
    monkeypatch.setattr(main.service_registry, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.settings.storage, "backend", "local")
    monkeypatch.delenv("KB_REQUIRE_OPENSEARCH_STORAGE", raising=False)
    monkeypatch.setenv("KB_WARM_EMBEDDINGS_ON_STARTUP", "false")

    async with main.lifespan(main.app):
        assert fake_storage.initialized is True


@pytest.mark.asyncio
async def test_lifespan_logs_storage_health_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lifespan should log backend, health, and document counts after storage init."""

    storage_health = {
        "backend": "local",
        "healthy": True,
        "index_count": 2,
        "document_count": 7,
    }
    fake_storage = _FakeStorage(storage_health)
    fake_embeddings = object()
    system_service = MagicMock()
    mcp_service = MagicMock()
    register = MagicMock()
    initialize_all = AsyncMock()
    cleanup_all = AsyncMock()
    log_info = MagicMock()
    log_warning = MagicMock()

    monkeypatch.setattr(main, "get_storage_backend", lambda: fake_storage)
    monkeypatch.setattr(
        main,
        "get_embedding_provider_with_fallback",
        AsyncMock(return_value=fake_embeddings),
    )
    monkeypatch.setattr(main, "SystemMonitoringService", MagicMock(return_value=system_service))
    monkeypatch.setattr(main, "MCPService", MagicMock(return_value=mcp_service))
    monkeypatch.setattr(main.service_registry, "register", register)
    monkeypatch.setattr(main.service_registry, "initialize_all", initialize_all)
    monkeypatch.setattr(main.service_registry, "cleanup_all", cleanup_all)
    monkeypatch.setattr(main.logger, "info", log_info)
    monkeypatch.setattr(main.logger, "warning", log_warning)
    monkeypatch.setenv("KB_WARM_EMBEDDINGS_ON_STARTUP", "false")

    async with main.lifespan(main.app):
        assert fake_storage.initialized is True

    assert fake_storage.closed is True
    register.assert_any_call("system", system_service)
    register.assert_any_call("mcp", mcp_service)
    initialize_all.assert_awaited_once()
    cleanup_all.assert_awaited_once()
    log_info.assert_any_call(
        "Storage backend initialized",
        backend="local",
        healthy=True,
        index_count=2,
        document_count=7,
        details=storage_health,
    )
    log_warning.assert_not_called()


@pytest.mark.asyncio
async def test_lifespan_logs_warning_when_storage_health_snapshot_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifespan should continue and warn if the post-init storage health snapshot fails."""

    fake_storage = _FakeStorage(RuntimeError("health unavailable"))
    fake_embeddings = object()
    initialize_all = AsyncMock()
    cleanup_all = AsyncMock()
    log_warning = MagicMock()

    monkeypatch.setattr(main, "get_storage_backend", lambda: fake_storage)
    monkeypatch.setattr(
        main,
        "get_embedding_provider_with_fallback",
        AsyncMock(return_value=fake_embeddings),
    )
    monkeypatch.setattr(main, "SystemMonitoringService", MagicMock())
    monkeypatch.setattr(main, "MCPService", MagicMock())
    monkeypatch.setattr(main.service_registry, "register", MagicMock())
    monkeypatch.setattr(main.service_registry, "initialize_all", initialize_all)
    monkeypatch.setattr(main.service_registry, "cleanup_all", cleanup_all)
    monkeypatch.setattr(main.logger, "warning", log_warning)
    monkeypatch.setenv("KB_WARM_EMBEDDINGS_ON_STARTUP", "false")

    async with main.lifespan(main.app):
        assert fake_storage.initialized is True

    assert fake_storage.closed is True
    initialize_all.assert_awaited_once()
    cleanup_all.assert_awaited_once()
    log_warning.assert_called_with(
        "Storage backend initialized but health snapshot failed",
        backend=main.settings.storage.backend,
        error="health unavailable",
    )
