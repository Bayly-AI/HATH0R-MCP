"""Tests for the runtime status API endpoint and helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledgebase.api.main import app
from knowledgebase.cli.runtime_start import DEFAULT_RUNTIME_CONFIG
from knowledgebase.core import runtime_status


def test_runtime_status_basic_shape() -> None:
    """GET /api/v1/runtime/status should return a well-formed payload."""

    client = TestClient(app)

    response = client.get("/api/v1/runtime/status")
    assert response.status_code == 200

    data = response.json()

    # Top-level fields
    assert data["version"]
    assert data["api_base_url"]
    assert isinstance(data["mode"], dict)
    assert isinstance(data["services"], list)

    # Mode structure
    mode = data["mode"]
    assert "name" in mode
    assert "source" in mode
    assert "details" in mode

    # Services must include the API service
    service_names = {svc["name"] for svc in data["services"]}
    assert "knowledgebase-api" in service_names


def test_runtime_status_mode_is_non_empty() -> None:
    """Runtime mode name should always be a non-empty string."""

    client = TestClient(app)

    response = client.get("/api/v1/runtime/status")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data["mode"]["name"], str)
    assert data["mode"]["name"].strip() != ""


# ---------------------------------------------------------------------------
# Unit tests for core.runtime_status helpers
# ---------------------------------------------------------------------------


def test_load_runtime_section_missing_file_uses_default(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cfg.json is missing, the default runtime config should be used."""

    dummy_cfg_path = tmp_path / "cfg.json"
    monkeypatch.setattr(runtime_status, "_RUNTIME_CFG_FILE", dummy_cfg_path)

    cfg = runtime_status._load_runtime_section()

    assert cfg == DEFAULT_RUNTIME_CONFIG


def test_load_runtime_section_merges_runtime_config(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Custom runtime section should overlay defaults without dropping keys."""

    runtime_data: dict[str, Any] = {
        "runtime": {
            "default_start_mode": "local",
            "modes": {
                "local": {
                    "host": "127.0.0.1",
                    "port": 9999,
                    "reload": True,
                },
            },
        }
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(runtime_data), encoding="utf-8")
    monkeypatch.setattr(runtime_status, "_RUNTIME_CFG_FILE", cfg_path)

    cfg = runtime_status._load_runtime_section()

    assert cfg["default_start_mode"] == "local"
    # Docker mode from DEFAULT_RUNTIME_CONFIG should still be present
    assert "docker" in cfg["modes"]
    # Local mode settings should reflect the override
    local_mode = cfg["modes"]["local"]
    assert local_mode["host"] == "127.0.0.1"
    assert int(local_mode["port"]) == 9999


def test_resolve_runtime_mode_prefers_env_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """KB_START_MODE environment variable should take precedence over config."""

    config: dict[str, Any] = {
        "default_start_mode": "docker",
        "modes": DEFAULT_RUNTIME_CONFIG["modes"],
    }
    monkeypatch.setenv("KB_START_MODE", "local")

    resolved = runtime_status._resolve_runtime_mode(config)

    assert resolved.mode == "local"
    assert resolved.source == "env"


def test_resolve_runtime_mode_falls_back_to_docker_for_unknown_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown mode names should fall back to the built-in docker defaults."""

    monkeypatch.delenv("KB_START_MODE", raising=False)
    config: dict[str, Any] = {
        "default_start_mode": "unknown-mode",
        "modes": {},
    }

    resolved = runtime_status._resolve_runtime_mode(config)

    assert resolved.mode == "docker"
    assert resolved.source == "default"


def _patch_http_connection(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    body: bytes,
    raise_os_error: bool = False,
) -> None:
    """Helper to patch http.client.HTTPConnection used by _probe_http_service."""

    class DummyResponse:
        def __init__(self, status_code: int, payload: bytes) -> None:
            self.status = status_code
            self._payload = payload

        def read(self, _limit: int) -> bytes:  # noqa: D401 - simple wrapper
            """Return the payload body."""

            return self._payload

    class DummyConnection:
        def __init__(
            self, host: str, port: int, timeout: float | None = None
        ) -> None:  # noqa: D401
            """Record connection parameters and optionally raise an error."""

            if raise_os_error:
                raise OSError("simulated connection failure")
            self._host = host
            self._port = port
            self._timeout = timeout

        def request(self, method: str, path: str) -> None:  # noqa: D401
            """No-op request method for testing."""

            self._method = method
            self._path = path

        def getresponse(self) -> DummyResponse:
            return DummyResponse(status, body)

        def close(self) -> None:
            """Close the dummy connection (no-op)."""

    monkeypatch.setattr(runtime_status.http.client, "HTTPConnection", DummyConnection)


def test_probe_http_service_healthy_with_keyword(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 200 with the expected marker keyword should be healthy."""

    _patch_http_connection(monkeypatch, status=200, body=b"...cluster_name...")

    health, message = runtime_status._probe_http_service(
        "http://localhost:9200/_cluster/health", keyword="cluster_name"
    )

    assert health == "healthy"
    assert "HTTP 200" in message


def test_probe_http_service_degraded_when_keyword_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 200 but missing the marker keyword should be degraded."""

    _patch_http_connection(monkeypatch, status=200, body=b"{}")

    health, message = runtime_status._probe_http_service(
        "http://localhost:9200/_cluster/health", keyword="cluster_name"
    )

    assert health == "degraded"
    assert "did not find expected marker" in message


def test_probe_http_service_unavailable_on_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """5xx responses should be reported as unavailable."""

    _patch_http_connection(monkeypatch, status=503, body=b"maintenance")

    health, message = runtime_status._probe_http_service("http://localhost:9200")

    assert health == "unavailable"
    assert "HTTP 503" in message


def test_probe_http_service_degraded_on_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """4xx responses should be reported as degraded."""

    _patch_http_connection(monkeypatch, status=404, body=b"not found")

    health, message = runtime_status._probe_http_service("http://localhost:9200")

    assert health == "degraded"
    assert "HTTP 404" in message


def test_probe_http_service_unavailable_on_os_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network failures should report the service as unavailable."""

    _patch_http_connection(monkeypatch, status=0, body=b"", raise_os_error=True)

    health, message = runtime_status._probe_http_service("http://localhost:9200")

    assert health == "unavailable"
    assert "Probe failed" in message


def test_get_runtime_status_local_backend_only_reports_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """When using local storage, only the API service should be reported."""

    dummy_settings = SimpleNamespace(storage=SimpleNamespace(backend="local"))
    monkeypatch.setattr(runtime_status, "get_settings", lambda: dummy_settings)

    status = runtime_status.get_runtime_status()

    service_names = {svc.name for svc in status.services}
    assert service_names == {"knowledgebase-api"}


def test_get_runtime_status_opensearch_backend_reports_additional_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenSearch backend should report both search and dashboards services."""

    dummy_settings = SimpleNamespace(storage=SimpleNamespace(backend="opensearch"))
    monkeypatch.setattr(runtime_status, "get_settings", lambda: dummy_settings)

    probe_calls: list[tuple[str, str | None]] = []

    def fake_probe(url: str, keyword: str | None = None, timeout: float = 1.5) -> tuple[str, str]:
        probe_calls.append((url, keyword))
        return "healthy", "ok"

    monkeypatch.setattr(runtime_status, "_probe_http_service", fake_probe)

    status = runtime_status.get_runtime_status()

    service_names = {svc.name for svc in status.services}
    assert "knowledgebase-api" in service_names
    assert "opensearch" in service_names
    assert "opensearch-dashboards" in service_names

    # Ensure probes were issued against the expected URLs and keyword
    assert ("http://localhost:9200", "cluster_name") in probe_calls
    assert any(url == "http://localhost:5601" for url, _ in probe_calls)
