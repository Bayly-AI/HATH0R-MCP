"""Unit tests for knowledgebase.server (FastMCP Hath0r service)."""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from knowledgebase.server import (
    ServiceSettings,
    load_documents,
    create_app,
)


def test_service_settings_defaults():
    settings = ServiceSettings()
    assert settings.environment == "local"
    assert "localhost:*" in settings.allowed_hosts


def test_service_settings_production_requires_token():
    with pytest.raises(ValueError, match="Production requires HATH0R_MCP_TOKEN"):
        ServiceSettings(environment="production", token=SecretStr("short"))

    valid_token = "a" * 32
    settings = ServiceSettings(environment="production", token=SecretStr(valid_token))
    assert settings.token.get_secret_value() == valid_token


def test_load_documents_from_fixture(tmp_path: Path):
    doc1 = tmp_path / "test.md"
    doc1.write_text("# Test Title\n\nThis is a test document about policy.", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    doc2 = sub / "nested.md"
    doc2.write_text("No header, just nested content.", encoding="utf-8")

    docs = load_documents(tmp_path)
    assert len(docs) == 2
    assert "test.md" in docs
    assert docs["test.md"]["title"] == "Test Title"
    assert "nested.md" in docs["sub/nested.md"]["id"]


def test_load_documents_empty_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="at least one Markdown document"):
        load_documents(tmp_path)


def test_server_endpoints(tmp_path: Path):
    doc = tmp_path / "guide.md"
    doc.write_text("# Hath0r Guide\n\nVoting records and transparency.", encoding="utf-8")

    settings = ServiceSettings(
        environment="local",
        knowledge_root=tmp_path,
        allowed_origins=["http://localhost:5173"],
    )
    app = create_app(settings)

    with TestClient(app) as client:
        # Health check
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"
        assert res.json()["service"] == "hath0r-mcp"

        # Version check
        res = client.get("/version")
        assert res.status_code == 200
        assert "version" in res.json()

        # Ready check (lifespan runs in TestClient context)
        res = client.get("/ready")
        assert res.status_code == 200
        assert res.json()["status"] == "ready"
        assert res.json()["documents"] == 1


def test_server_auth_and_origin(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text("# Test\nSample content.", encoding="utf-8")

    token = "x" * 32
    settings = ServiceSettings(
        environment="production",
        knowledge_root=tmp_path,
        token=SecretStr(token),
        allowed_origins=["http://localhost:5173"],
    )
    app = create_app(settings)

    with TestClient(app) as client:
        # Invalid origin
        res = client.get("/ready", headers={"origin": "http://evil.com"})
        assert res.status_code == 200  # unauthenticated probe exempt

        # MCP endpoint with wrong token
        res = client.post("/mcp", headers={"origin": "http://localhost:5173", "authorization": "Bearer bad"})
        assert res.status_code == 401

        # MCP endpoint with forbidden origin
        res = client.post(
            "/mcp",
            headers={"origin": "http://evil.com", "authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_fastmcp_voice_tools_registered(tmp_path: Path):
    doc = tmp_path / "test.md"
    doc.write_text("# Test\nSample content.", encoding="utf-8")
    settings = ServiceSettings(environment="local", knowledge_root=tmp_path)
    app = create_app(settings)

    # Voice tools should be registered on app or callable through service
    from knowledgebase.services.voice_service import (
        voice_speak_service,
        voice_listen_service,
        voice_dispatch_action_service,
    )

    speak_res = await voice_speak_service("test voice")
    assert speak_res["status"] in ("spoken", "simulated")

    listen_res = await voice_listen_service(simulated_input="hath0r doctor")
    assert listen_res["status"] == "captured"
    assert listen_res["transcript"] == "hath0r doctor"

    dispatch_res = await voice_dispatch_action_service(
        transcript="test command",
        intent="cli_command",
        command="hath0r status",
    )
    assert dispatch_res["dispatched"] is True
    assert dispatch_res["action"]["intent"] == "cli_command"
