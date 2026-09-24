"""Tests for the RAG configuration API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from knowledgebase.api.main import app, settings


def _rag_config_path() -> Path:
    return settings.config_dir / "rag.json"


def test_get_rag_config_returns_defaults_when_missing(tmp_path: Path) -> None:
    """GET /api/v1/rag/config should return defaults when no file exists."""

    # Ensure there is no existing rag.json so we exercise the default path.
    path = _rag_config_path()
    if path.exists():
        path.unlink()

    client = TestClient(app)

    response = client.get("/api/v1/rag/config")
    assert response.status_code == 200
    data = response.json()

    assert data["top_k"] == 10
    assert data["min_score"] == 0.5
    assert data["default_index"] is None
    assert data["include_sources"] is True


def test_put_rag_config_persists_values(tmp_path: Path) -> None:
    """PUT /api/v1/rag/config should persist and echo back the configuration."""

    client = TestClient(app)

    payload = {
        "top_k": 7,
        "min_score": 0.7,
        "default_index": "knowledgebase",
        "max_context_tokens": 4096,
        "max_answer_tokens": 1024,
        "include_sources": False,
        "use_reranker": True,
        "return_debug_metadata": True,
    }

    put_response = client.put("/api/v1/rag/config", json=payload)
    assert put_response.status_code == 200
    returned = put_response.json()

    for key, value in payload.items():
        assert returned[key] == value

    # A subsequent GET should return the same configuration.
    get_response = client.get("/api/v1/rag/config")
    assert get_response.status_code == 200
    fetched = get_response.json()

    for key, value in payload.items():
        assert fetched[key] == value
