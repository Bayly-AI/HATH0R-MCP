"""Unit tests for shared MCP tool catalog definitions."""

from __future__ import annotations

from knowledgebase.core.mcp_tools import (
    get_default_mcp_tool_schema,
    get_default_mcp_tool_specs,
)


def test_default_mcp_tool_specs_have_unique_names() -> None:
    """Default MCP tool registry should not contain duplicate tool names."""
    specs = get_default_mcp_tool_specs()
    names = [spec.name for spec in specs]

    assert len(specs) > 0
    assert len(names) == len(set(names))


def test_default_mcp_tool_specs_include_expected_key_tools() -> None:
    """Shared catalog should include core, docs, aegis, and runbook tool groups."""
    names = {spec.name for spec in get_default_mcp_tool_specs()}

    assert {"kb_search", "kb_sync_all", "kb_stats"}.issubset(names)
    assert {"docs_kb_list", "docs_kb_search", "docs_kb_info", "docs_read_meta"}.issubset(names)
    assert {"aegis_context", "aegis_echo"}.issubset(names)
    assert {"runbook_list", "runbook_create", "runbook_reindex"}.issubset(names)
    assert {"voice_speak", "voice_listen", "voice_dispatch_action"}.issubset(names)


def test_get_default_mcp_tool_schema_returns_defensive_copy() -> None:
    """Schema lookup should return independent copies to prevent accidental global mutation."""
    schema_first = get_default_mcp_tool_schema("kb_search")
    assert "query" in schema_first["properties"]
    schema_first["properties"]["query"]["description"] = "mutated"

    schema_second = get_default_mcp_tool_schema("kb_search")
    assert schema_second["properties"]["query"]["description"] == "Search query"


def test_get_default_mcp_tool_schema_returns_empty_object_for_unknown() -> None:
    """Unknown tools should resolve to an empty object schema."""
    schema = get_default_mcp_tool_schema("tool-that-does-not-exist")
    assert schema == {"type": "object", "properties": {}}
