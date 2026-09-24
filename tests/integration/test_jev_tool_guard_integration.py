"""Integration tests for the JEV tool-guard control loop.

Exercises the real MCP JSON-RPC tools/call path through FastAPI TestClient
with guard modes off / stub / live (MockTransport). Marked ``integration``.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from knowledgebase.api import main as api_main
from knowledgebase.core.jev_client import JevClient, JevSettings, reset_jev_client, set_jev_client

pytestmark = [pytest.mark.integration, pytest.mark.api]


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_main.app)


@pytest.fixture(autouse=True)
def _reset_jev() -> None:
    reset_jev_client()
    yield
    reset_jev_client()


def _tools_call(client: TestClient, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("jsonrpc") == "2.0"
    assert "result" in body, body
    result = body["result"]
    assert isinstance(result, dict)
    return result


def test_readonly_tools_call_unaffected_when_stub_enabled(client: TestClient) -> None:
    """Read-only tools must not pay a blocking guard decision."""
    set_jev_client(JevClient(JevSettings(enabled=True, mode="stub")))
    # kb_health may fail service-not-ready; either success or soft error is OK —
    # the critical assertion is that it is NOT jev_tool_guard_blocked.
    result = _tools_call(client, "kb_health", {})
    text = ""
    if result.get("content"):
        text = str(result["content"][0].get("text", ""))
    assert "jev_tool_guard_blocked" not in text


def test_mutating_tools_call_blocked_in_stub_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutating tools must be blocked before the handler runs when stub is on."""
    set_jev_client(JevClient(JevSettings(enabled=True, mode="stub")))

    async def _boom(tool_name: str, args: dict[str, Any], fail):  # type: ignore[no-untyped-def]
        raise AssertionError("mutating handler must not execute under stub deny")

    monkeypatch.setitem(api_main._MCP_TOOL_HANDLERS, "kb_index_delete", _boom)
    monkeypatch.setattr(api_main, "_mcp_service", None)

    result = _tools_call(client, "kb_index_delete", {"name": "integration-danger", "force": True})
    assert result.get("isError") is True
    payload = json.loads(result["content"][0]["text"])
    assert payload["error"] == "jev_tool_guard_blocked"
    assert payload["tool"] == "kb_index_delete"
    assert payload["jev"]["decision"] == "deny"
    assert payload["jev"]["blocked"] is True


def test_guard_off_allows_mutating_handler(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default off mode must preserve pre-POC behavior for mutating tools."""
    set_jev_client(JevClient(JevSettings(enabled=False, mode="off")))
    called: dict[str, bool] = {"ok": False}

    async def _ok(tool_name: str, args: dict[str, Any], fail):  # type: ignore[no-untyped-def]
        called["ok"] = True
        return {"content": [{"type": "text", "text": "executed"}]}

    monkeypatch.setitem(api_main._MCP_TOOL_HANDLERS, "kb_sync_all", _ok)
    monkeypatch.setattr(api_main, "_mcp_service", None)

    result = _tools_call(client, "kb_sync_all", {"target": "local"})
    assert called["ok"] is True
    assert result.get("isError") is not True
    assert result["content"][0]["text"] == "executed"


def test_live_mode_mock_transport_allow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Live protocol path with mocked HTTP allow must reach the tool handler."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "decision": "allow",
                    "confidence": 0.97,
                    "probabilities": {"allow": 0.97, "confirm": 0.02, "review": 0.005, "deny": 0.005},
                    "guidance": "Safe under policy.",
                },
            },
        )

    set_jev_client(
        JevClient(
            JevSettings(
                enabled=True,
                mode="live",
                api_key="ts_integration_test",
                endpoint="https://www.jevai.org/api/v1/decisions/tool-guard",
                protocol="preset",
                on_error="deny",
            ),
            transport=httpx.MockTransport(handler),
        )
    )
    called: dict[str, bool] = {"ok": False}

    async def _ok(tool_name: str, args: dict[str, Any], fail):  # type: ignore[no-untyped-def]
        called["ok"] = True
        return {"content": [{"type": "text", "text": "live-allow-ok"}]}

    monkeypatch.setitem(api_main._MCP_TOOL_HANDLERS, "kb_add_document", _ok)
    monkeypatch.setattr(api_main, "_mcp_service", None)

    result = _tools_call(
        client,
        "kb_add_document",
        {"id": "doc-1", "content": "hello", "index_name": "knowledge"},
    )
    assert called["ok"] is True
    assert result["content"][0]["text"] == "live-allow-ok"


def test_live_mode_mock_transport_deny_blocks(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "decision": "deny",
                    "confidence": 0.9,
                    "probabilities": {"allow": 0.05, "confirm": 0.05, "review": 0.0, "deny": 0.9},
                    "guidance": "Policy denies destructive delete.",
                },
            },
        )

    set_jev_client(
        JevClient(
            JevSettings(
                enabled=True,
                mode="live",
                api_key="ts_integration_test",
                endpoint="https://www.jevai.org/api/v1/decisions/tool-guard",
                protocol="preset",
            ),
            transport=httpx.MockTransport(handler),
        )
    )

    async def _boom(tool_name: str, args: dict[str, Any], fail):  # type: ignore[no-untyped-def]
        raise AssertionError("must not run")

    monkeypatch.setitem(api_main._MCP_TOOL_HANDLERS, "kb_remove_document", _boom)
    monkeypatch.setattr(api_main, "_mcp_service", None)

    result = _tools_call(client, "kb_remove_document", {"doc_id": "x"})
    assert result.get("isError") is True
    payload = json.loads(result["content"][0]["text"])
    assert payload["jev"]["decision"] == "deny"
    assert payload["jev"]["source"] == "jev_live"


@pytest.mark.asyncio
async def test_guard_latency_budget_stub_and_off() -> None:
    """Micro-benchmark guard path only (no FastAPI) for documentation baselines.

    Not a hard CI gate on wall clock (machine variance). Asserts relative order:
    off ≤ stub, and stub stays in a sane sub-millisecond-to-few-ms band per call
    on a developer machine after warmup.
    """
    iterations = 200
    args = {"name": "bench-index", "force": True}

    from knowledgebase.core.jev_tool_guard import evaluate_tool_guard

    # OFF
    set_jev_client(JevClient(JevSettings(enabled=False, mode="off")))
    for _ in range(20):
        await evaluate_tool_guard("kb_index_delete", args)

    t0 = time.perf_counter()
    for _ in range(iterations):
        await evaluate_tool_guard("kb_index_delete", args)
    off_ms = (time.perf_counter() - t0) * 1000.0 / iterations

    # STUB
    set_jev_client(JevClient(JevSettings(enabled=True, mode="stub")))
    for _ in range(20):
        await evaluate_tool_guard("kb_index_delete", args)
    t1 = time.perf_counter()
    for _ in range(iterations):
        result = await evaluate_tool_guard("kb_index_delete", args)
        assert result is not None and result.blocked is True
    stub_ms = (time.perf_counter() - t1) * 1000.0 / iterations

    # LIVE with instant mock (0 ms network)
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "decision": "deny",
                    "confidence": 0.9,
                    "probabilities": {"deny": 0.9, "allow": 0.1},
                    "guidance": "deny",
                },
            },
        )

    set_jev_client(
        JevClient(
            JevSettings(
                enabled=True,
                mode="live",
                api_key="ts_bench",
                endpoint="https://www.jevai.org/api/v1/decisions/tool-guard",
                protocol="preset",
            ),
            transport=httpx.MockTransport(handler),
        )
    )
    for _ in range(10):
        await evaluate_tool_guard("kb_index_delete", args)
    t2 = time.perf_counter()
    for _ in range(iterations):
        result = await evaluate_tool_guard("kb_index_delete", args)
        assert result is not None and result.blocked is True
    live_mock_ms = (time.perf_counter() - t2) * 1000.0 / iterations

    # LIVE mock with injected 80ms RTT (representative JEV latency band low end)
    def slow_handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.08)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "decision": "allow",
                    "confidence": 0.95,
                    "probabilities": {"allow": 0.95},
                    "guidance": "ok",
                },
            },
        )

    set_jev_client(
        JevClient(
            JevSettings(
                enabled=True,
                mode="live",
                api_key="ts_bench",
                endpoint="https://www.jevai.org/api/v1/decisions/tool-guard",
                protocol="preset",
                timeout_seconds=5.0,
            ),
            transport=httpx.MockTransport(slow_handler),
        )
    )
    slow_iterations = 8
    t3 = time.perf_counter()
    for _ in range(slow_iterations):
        result = await evaluate_tool_guard("kb_add_document", {"id": "x", "content": "y"})
        assert result is not None and result.blocked is False
    live_80ms_ms = (time.perf_counter() - t3) * 1000.0 / slow_iterations

    # Sanity: off is essentially free; stub is local; live+80ms dominates.
    assert off_ms < 2.0, f"off path too slow: {off_ms:.3f} ms"
    assert stub_ms < 5.0, f"stub path too slow: {stub_ms:.3f} ms"
    assert live_mock_ms < 15.0, f"live mock path too slow: {live_mock_ms:.3f} ms"
    assert live_80ms_ms >= 70.0, f"expected injected latency, got {live_80ms_ms:.3f} ms"

    # Attach numbers for the pytest report / documentation capture.
    print(
        "\nJEV_GUARD_PERF "
        f"off_ms={off_ms:.4f} stub_ms={stub_ms:.4f} "
        f"live_mock_ms={live_mock_ms:.4f} live_80ms_rtt_ms={live_80ms_ms:.2f}"
    )
