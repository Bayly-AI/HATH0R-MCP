"""Unit tests for the JEV tool-guard agent control-loop POC."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from knowledgebase.core.jev_client import (
    JevClient,
    JevSettings,
    ToolGuardRequest,
    parse_tool_guard_response,
    reset_jev_client,
    set_jev_client,
    stub_tool_guard,
)
from knowledgebase.core.jev_tool_guard import (
    GUARDED_TOOL_PROFILES,
    build_tool_guard_request,
    evaluate_tool_guard,
    format_block_message,
    is_guarded_tool,
)


@pytest.fixture(autouse=True)
def _clear_jev_singleton() -> None:
    reset_jev_client()
    yield
    reset_jev_client()


def test_settings_default_off() -> None:
    settings = JevSettings.from_env({})
    assert settings.mode == "off"
    assert settings.enabled is False


def test_settings_stub_and_live_from_env() -> None:
    stub = JevSettings.from_env({"JEV_MODE": "stub"})
    assert stub.mode == "stub" and stub.enabled is True

    live = JevSettings.from_env(
        {"JEV_TOOL_GUARD_ENABLED": "true", "JEV_API_KEY": "ts_test", "JEV_ON_ERROR": "deny"}
    )
    assert live.mode == "live"
    assert live.api_key == "ts_test"
    assert live.on_error == "deny"


def test_guarded_tool_catalog_covers_destructive_ops() -> None:
    assert is_guarded_tool("kb_index_delete")
    assert is_guarded_tool("kb_sync_all")
    assert is_guarded_tool("runbook_delete")
    assert not is_guarded_tool("kb_search")
    assert not is_guarded_tool("kb_health")
    assert "kb_remove_document" in GUARDED_TOOL_PROFILES


def test_build_request_redacts_secrets_and_formats_action() -> None:
    req = build_tool_guard_request(
        "kb_index_delete",
        {"name": "prod-index", "force": True, "api_key": "super-secret"},
    )
    assert req is not None
    assert "prod-index" in req.action
    assert any(item.startswith("api_key=[REDACTED]") for item in req.arguments_summary)
    assert req.reversibility == "irreversible"
    assert build_tool_guard_request("kb_search", {"query": "x"}) is None


def test_stub_denies_delete_and_confirms_sync() -> None:
    denied = stub_tool_guard(
        ToolGuardRequest(tool="kb_index_delete", action="Delete knowledge index prod")
    )
    assert denied.decision == "deny"
    assert denied.source == "stub"

    confirm = stub_tool_guard(
        ToolGuardRequest(tool="kb_sync_all", action="Trigger full knowledgebase sync")
    )
    assert confirm.decision == "confirm"


def test_parse_preset_envelope() -> None:
    body = {
        "code": 0,
        "message": "ok",
        "data": {
            "decision": "confirm",
            "confidence": 0.86,
            "probabilities": {"allow": 0.08, "confirm": 0.71, "review": 0.16, "deny": 0.05},
            "guidance": "Obtain explicit user confirmation before invoking the tool.",
        },
    }
    result = parse_tool_guard_response(body)
    assert result.decision == "confirm"
    assert result.confidence == pytest.approx(0.86)
    assert result.probabilities["confirm"] == pytest.approx(0.71)


def test_parse_systemone_answers() -> None:
    body = {
        "answers": {
            "verdict": {
                "type": "choice",
                "choice": "deny",
                "confidence": 0.91,
                "probabilities": {"allow": 0.02, "confirm": 0.04, "review": 0.03, "deny": 0.91},
            }
        }
    }
    result = parse_tool_guard_response(body, source="systemone")
    assert result.decision == "deny"
    assert result.confidence == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_client_stub_blocks_delete() -> None:
    client = JevClient(JevSettings(enabled=True, mode="stub"))
    result = await client.guard_tool_call(
        ToolGuardRequest(tool="kb_remove_document", action="Remove document x")
    )
    assert result.decision == "deny"
    assert result.blocked is True


@pytest.mark.asyncio
async def test_client_disabled_allows() -> None:
    client = JevClient(JevSettings(enabled=False, mode="off"))
    result = await client.guard_tool_call(
        ToolGuardRequest(tool="kb_index_delete", action="Delete anything")
    )
    assert result.decision == "allow"
    assert result.blocked is False
    assert result.source == "disabled"


@pytest.mark.asyncio
async def test_client_live_http_mock_allow() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "tool-guard" in str(request.url) or request.url.path.endswith("/tool-guard")
        payload = {
            "code": 0,
            "data": {
                "decision": "allow",
                "confidence": 0.95,
                "probabilities": {"allow": 0.95, "confirm": 0.03, "review": 0.01, "deny": 0.01},
                "guidance": "Safe under policy.",
            },
        }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = JevClient(
        JevSettings(
            enabled=True,
            mode="live",
            api_key="ts_test",
            endpoint="https://www.jevai.org/api/v1/decisions/tool-guard",
            protocol="preset",
        ),
        transport=transport,
    )
    result = await client.guard_tool_call(
        ToolGuardRequest(
            tool="kb_add_document",
            action="Add document",
            arguments_summary=["id=doc-1"],
            side_effects=["Writes document content"],
            policy=["No secrets"],
            reversibility="reversible",
        )
    )
    assert result.decision == "allow"
    assert result.blocked is False
    assert result.source == "jev_live"


@pytest.mark.asyncio
async def test_client_live_error_fail_open() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "overloaded"})

    client = JevClient(
        JevSettings(enabled=True, mode="live", api_key="ts_test", on_error="allow"),
        transport=httpx.MockTransport(handler),
    )
    result = await client.guard_tool_call(
        ToolGuardRequest(tool="kb_sync_all", action="sync")
    )
    assert result.decision == "allow"
    assert result.source == "error_fallback"
    assert result.blocked is False


@pytest.mark.asyncio
async def test_evaluate_tool_guard_skips_readonly_and_when_off() -> None:
    set_jev_client(JevClient(JevSettings(enabled=True, mode="stub")))
    assert await evaluate_tool_guard("kb_search", {"query": "hello"}) is None

    set_jev_client(JevClient(JevSettings(enabled=False, mode="off")))
    assert await evaluate_tool_guard("kb_index_delete", {"name": "x"}) is None


@pytest.mark.asyncio
async def test_evaluate_tool_guard_blocks_mutating_in_stub() -> None:
    set_jev_client(JevClient(JevSettings(enabled=True, mode="stub")))
    result = await evaluate_tool_guard("kb_index_delete", {"name": "x", "force": True})
    assert result is not None
    assert result.blocked is True
    message = format_block_message("kb_index_delete", result)
    payload: dict[str, Any] = json.loads(message)
    assert payload["error"] == "jev_tool_guard_blocked"
    assert payload["tool"] == "kb_index_delete"
    assert payload["jev"]["decision"] == "deny"


@pytest.mark.asyncio
async def test_execute_mcp_tool_respects_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration-ish: _execute_mcp_tool returns isError when guard blocks."""
    from knowledgebase.api import main as api_main

    set_jev_client(JevClient(JevSettings(enabled=True, mode="stub")))

    async def _fake_handler(tool_name: str, args: dict[str, Any], fail):  # type: ignore[no-untyped-def]
        raise AssertionError("handler must not run when JEV blocks")

    monkeypatch.setitem(api_main._MCP_TOOL_HANDLERS, "kb_index_delete", _fake_handler)
    # Avoid MCP service analytics dependency
    monkeypatch.setattr(api_main, "_mcp_service", None)

    result = await api_main._execute_mcp_tool("kb_index_delete", {"name": "danger"})
    assert result.get("isError") is True
    text = result["content"][0]["text"]
    assert "jev_tool_guard_blocked" in text
