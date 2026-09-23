"""Exercise the actual MCP transport, corpus boundaries, and deployment guards."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from knowledgebase.server import ServiceSettings, create_app, load_documents

HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def config(tmp_path):
    (tmp_path / "suite.md").write_text("# Suite\nATC owns the hath0r Docker network.")
    return ServiceSettings(
        _env_file=None, knowledge_root=tmp_path, allowed_hosts=["testserver"], token=""
    )


def rpc(client, method, params=None):
    return client.post(
        "/mcp",
        headers=HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def test_protocol_lifecycle_and_real_tools(config):
    with TestClient(create_app(config)) as client:
        assert client.get("/health").json()["status"] == "healthy"
        assert client.get("/ready").json() == {"status": "ready", "documents": 1}
        assert client.get("/version").json()["service"] == "hath0r-mcp"
        init = rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        assert init.json()["result"]["serverInfo"]["name"] == "HATH0R-MCP"
        assert (
            client.post(
                "/mcp",
                headers=HEADERS,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            ).status_code
            == 202
        )
        tools = rpc(client, "tools/list").json()["result"]["tools"]
        assert {t["name"] for t in tools} == {"suite_info", "kb_search", "kb_get_document"}
        for name, args in [
            ("suite_info", {}),
            ("kb_search", {"query": "Docker"}),
            ("kb_get_document", {"document_id": "suite.md"}),
        ]:
            result = rpc(client, "tools/call", {"name": name, "arguments": args}).json()["result"]
            assert not result.get("isError"), result
            assert "suite.md" in json.dumps(result)
        assert rpc(client, "ping").json()["result"] == {}
        assert rpc(client, "unknown").json()["error"]["code"] == -32602


@pytest.mark.parametrize(
    "name,args",
    [
        ("kb_search", {"query": "Docker", "limit": 21}),
        ("kb_search", {"query": ""}),
        ("kb_search", {"query": "!!!"}),
        ("kb_get_document", {"document_id": "../../.env"}),
        ("missing_tool", {}),
    ],
)
def test_bad_tool_calls(config, name, args):
    with TestClient(create_app(config)) as client:
        assert rpc(client, "tools/call", {"name": name, "arguments": args}).json()["result"][
            "isError"
        ]


def test_transport_guards(config):
    with TestClient(create_app(config)) as client:
        assert client.post("/mcp", content="not json", headers=HEADERS).status_code == 400
        assert client.post("/mcp", content="x" * 65537, headers=HEADERS).status_code == 413
        assert (
            client.post("/mcp", headers={**HEADERS, "Origin": "https://evil.example"}).status_code
            == 403
        )
        assert (
            client.post("/mcp", headers={**HEADERS, "Host": "evil.example"}, json={}).status_code
            == 421
        )


def test_token_and_production_configuration(config):
    config.token = "x" * 32
    # Revalidate assignment through construction, as operators do at startup.
    config = ServiceSettings(_env_file=None, **config.model_dump())
    with TestClient(create_app(config)) as client:
        assert client.get("/health").status_code == 200
        assert rpc(client, "tools/list").status_code == 401
        client.headers["Authorization"] = "Bearer " + "x" * 32
        assert rpc(client, "tools/list").status_code == 200
    with pytest.raises(ValidationError):
        ServiceSettings(_env_file=None, environment="production", token="")


def test_startup_fails_for_missing_empty_and_oversize_corpus(tmp_path):
    for root in [tmp_path / "missing", tmp_path]:
        with pytest.raises((ValueError, FileNotFoundError)):
            load_documents(root)
    (tmp_path / "big.md").write_bytes(b"x" * (256 * 1024 + 1))
    with pytest.raises(ValueError, match="bounds"):
        load_documents(tmp_path)


def test_external_symlink_rejected(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    outside = tmp_path / "secret.md"
    outside.write_text("private")
    (root / "link.md").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        load_documents(root)


def test_readiness_before_startup(config):
    app = create_app(config)
    assert TestClient(app).get("/ready").status_code == 503


@pytest.mark.asyncio
async def test_sdk_smoke_checks_real_asgi_service(config, monkeypatch):
    """Run the shipped smoke verifier through real SDK serialization and routing."""
    import httpx
    from knowledgebase.cli import smoke

    config = ServiceSettings(_env_file=None, **{**config.model_dump(), "token": "smoke-token"})
    app = create_app(config)
    client_type = httpx.AsyncClient

    def local_client(**kwargs):
        return client_type(transport=httpx.ASGITransport(app=app), **kwargs)

    monkeypatch.setenv("HATH0R_MCP_TOKEN", "smoke-token")
    monkeypatch.setattr(smoke.httpx, "AsyncClient", local_client)
    async with app.router.lifespan_context(app):
        assert await smoke.verify("http://testserver") == {"api": "ok", "mcp": "ok", "tools": 3}
    assert not app.state.ready


def test_smoke_cli_reports_results(monkeypatch, capsys):
    from knowledgebase.cli import smoke

    async def verify(base_url):
        assert base_url == "http://localhost:8083"
        return {"api": "ok", "mcp": "ok", "tools": 3}

    monkeypatch.setattr(smoke, "verify", verify)
    smoke.smoke("http://localhost:8083/")
    assert json.loads(capsys.readouterr().out)["tools"] == 3
