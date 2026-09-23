"""API tests for the /health endpoint."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import knowledgebase.api.main as main


def _clear_health_caches() -> None:
    """Drop process-local health/status caches so tests see live snapshots."""
    main._HEALTH_CACHE.clear()
    main._STATUS_CACHE.clear()


class _FakeBackend:
    """Simple fake backend with a configurable health_check result."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - tests exercise API layer
        return self._payload


def test_health_endpoint_reports_healthy_components(monkeypatch: Any) -> None:
    """/health should aggregate healthy component statuses into a healthy result."""
    _clear_health_caches()

    healthy_payload = {"healthy": True, "backend": "fake"}
    storage = _FakeBackend(healthy_payload)
    embeddings = _FakeBackend(healthy_payload)

    monkeypatch.setattr("knowledgebase.api.main._storage", storage)
    monkeypatch.setattr("knowledgebase.api.main._embeddings", embeddings)

    client = TestClient(main.app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["components"]["storage"]["healthy"] is True
    assert data["components"]["embeddings"]["healthy"] is True


def test_health_endpoint_reports_degraded_when_component_unhealthy(monkeypatch: Any) -> None:
    """/health should report a degraded status when any component is unhealthy."""
    _clear_health_caches()

    storage = _FakeBackend({"healthy": False, "backend": "fake", "error": "boom"})
    embeddings = _FakeBackend({"healthy": True, "backend": "fake"})

    monkeypatch.setattr("knowledgebase.api.main._storage", storage)
    monkeypatch.setattr("knowledgebase.api.main._embeddings", embeddings)

    client = TestClient(main.app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["storage"]["healthy"] is False


def test_health_endpoint_handles_missing_backends(monkeypatch: Any) -> None:
    """/health should handle missing storage and embeddings backends."""
    _clear_health_caches()

    monkeypatch.setattr("knowledgebase.api.main._storage", None)
    monkeypatch.setattr("knowledgebase.api.main._embeddings", None)

    client = TestClient(main.app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["components"]["storage"]["healthy"] is False
    assert data["components"]["embeddings"]["healthy"] is False


def test_health_endpoint_includes_environment_field(monkeypatch: Any) -> None:
    """/health response should include the aegis_environment field."""
    from knowledgebase.core.config import Settings

    _clear_health_caches()

    healthy_payload = {"healthy": True, "backend": "fake"}
    storage = _FakeBackend(healthy_payload)
    embeddings = _FakeBackend(healthy_payload)

    monkeypatch.setattr("knowledgebase.api.main._storage", storage)
    monkeypatch.setattr("knowledgebase.api.main._embeddings", embeddings)

    # Mock settings with a specific aegis_environment
    mock_settings = Settings(aegis_environment="staging")
    monkeypatch.setattr("knowledgebase.api.main.settings", mock_settings)

    client = TestClient(main.app)
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert "environment" in data
    assert data["environment"] == "staging"


def test_health_endpoint_environment_field_is_optional(monkeypatch: Any) -> None:
    """The environment field in HealthResponse should be optional (not required)."""
    _clear_health_caches()

    healthy_payload = {"healthy": True, "backend": "fake"}
    storage = _FakeBackend(healthy_payload)
    embeddings = _FakeBackend(healthy_payload)

    monkeypatch.setattr("knowledgebase.api.main._storage", storage)
    monkeypatch.setattr("knowledgebase.api.main._embeddings", embeddings)

    client = TestClient(main.app)
    response = client.get("/health")

    assert response.status_code == 200
    # The response model allows None for environment, and it should be populated
    data = response.json()
    assert "environment" in data


def test_version_endpoint_returns_cvs_payload(monkeypatch: Any) -> None:
    """/version should return CVS-compatible metadata when enabled."""
    monkeypatch.delenv("KB_FEATURE_FLAGS__KB_VERSION_ENDPOINT_ENABLED", raising=False)
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    monkeypatch.setenv("AWS_PUSH_COUNTER", "7")
    monkeypatch.setenv("AWS_RELEASE_VER", "1.2.3.7")
    monkeypatch.setenv("VERSION_SOURCE", "cvs-registry")

    client = TestClient(main.app)
    response = client.get("/version", headers={"Accept": "application/json"})

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "1n-mcp"
    assert data["version"] == "1.2.3"
    assert data["aws_push_counter"] == 7
    assert data["aws_release_ver"] == "1.2.3.7"
    assert data["security_profile"] == "public"


def test_version_endpoint_can_be_disabled(monkeypatch: Any) -> None:
    """/version should return 404 when the feature flag is disabled."""
    monkeypatch.setenv("KB_FEATURE_FLAGS__KB_VERSION_ENDPOINT_ENABLED", "false")

    client = TestClient(main.app)
    response = client.get("/version")

    assert response.status_code == 404
