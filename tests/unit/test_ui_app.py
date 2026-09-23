"""Tests for the KnowledgeBase UI applet FastAPI application."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from knowledgebase.ui.app import DEFAULT_API_BASE_URL, create_app


def test_create_app_uses_default_base_url(tmp_path: Path) -> None:
    """create_app should expose the default API base URL when none is provided."""

    # Arrange: provide a minimal static directory so mounting does not fail.
    index_file = tmp_path / "index.html"
    index_file.write_text("<html><body>OK</body></html>")

    app = create_app(static_dir=tmp_path)
    client = TestClient(app)

    # Act
    response = client.get("/__config__")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["apiBaseUrl"] == DEFAULT_API_BASE_URL


def test_create_app_uses_custom_base_url(tmp_path: Path) -> None:
    """create_app should return the explicitly provided API base URL."""

    index_file = tmp_path / "index.html"
    index_file.write_text("<html><body>OK</body></html>")

    custom_url = "http://example.invalid:9000"
    app = create_app(api_base_url=custom_url, static_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/__config__")

    assert response.status_code == 200
    data = response.json()
    assert data["apiBaseUrl"] == custom_url


def test_create_app_missing_assets() -> None:
    """create_app should serve a missing assets message when static dir doesn't exist."""
    # Use a non-existent path
    app = create_app(static_dir="/nonexistent/path/that/does/not/exist")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert "not found" in data["message"].lower()
    assert "staticDir" in data
