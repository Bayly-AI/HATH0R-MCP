"""Unit and API tests for Issue #85: Level 1 suite tools, AgentGraph, SuperSqueeze, and OTel/OpenObserve/OpenFeature."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import pytest

from knowledgebase.api.main import _MCP_TOOL_HANDLERS, _execute_mcp_tool
from knowledgebase.core import observability
from knowledgebase.core.feature_flags import evaluate_feature_flags_snapshot, get_catalog_flag_defaults
from knowledgebase.core.mcp_tools import DEFAULT_MCP_TOOL_SPECS, get_default_mcp_tool_schema
from knowledgebase.core.suite_tools import (
    SERVICE_BOT_WORKFLOW_REGISTRY,
    execute_agentgraph_query,
    execute_agentgraph_route,
    execute_agentgraph_status,
    execute_agentgraph_validate,
    offer_missing_workflow,
)
from knowledgebase.core.supersqueeze import (
    SuperSqueezeEngine,
    apply_supersqueeze_middleware,
    estimate_tokens,
)


def test_every_level1_mcp_tool_has_owning_bot_and_workflow_metadata() -> None:
    """CR-FEATURE-WORKFLOW-STANDARD-001: Every Feature/Tool is a Service run by >= 1 Bot with a Workflow ID."""
    assert len(DEFAULT_MCP_TOOL_SPECS) >= 65
    for spec in DEFAULT_MCP_TOOL_SPECS:
        assert not spec.name.startswith("infraos_"), f"Legacy infraos_ tool found: {spec.name}"
        assert len(spec.owning_bots) >= 1, f"Tool {spec.name} missing owning_bots"
        assert spec.workflow_id.startswith("cfg/factories/"), f"Tool {spec.name} missing workflow_id"
        assert spec.agentgraph_level == "L1_MCP"
        schema = get_default_mcp_tool_schema(spec.name)
        assert schema.get("x-hath0r-owning-bot") == list(spec.owning_bots)
        assert schema.get("x-hath0r-workflow-id") == spec.workflow_id
        assert schema.get("x-hath0r-agentgraph-level") == "L1_MCP"

    for handler_name in _MCP_TOOL_HANDLERS:
        assert not handler_name.startswith("infraos_"), f"Legacy infraos_ handler found: {handler_name}"


def test_observability_uses_otel_phoenix_and_openobservation_without_ddtrace(tmp_path: Path) -> None:
    """Verify ddtrace is purged and OTel + OpenObservation point to Hath0r-phoenix on hath0r-net."""
    src_text = inspect.getsource(observability)
    assert "ddtrace" not in src_text
    assert observability.get_phoenix_endpoint() == "http://localhost:38000/phoenix"

    env = observability.record_openobservation_event(
        "test_op",
        12.345,
        spool_root=tmp_path,
        tool="hath0r_supersqueeze",
        api_token="should-be-filtered",
    )
    assert env["service"] == "hath0r-mcp"
    assert env["phoenix_endpoint"] == "http://localhost:38000/phoenix"
    assert "api_token" not in env["attributes"]
    assert env["feature_flags"]["mcp.supersqueeze.enabled"] is True
    spool_file = tmp_path / "mcp_telemetry.jsonl"
    assert spool_file.is_file()


def test_supersqueeze_compression_achieves_target_savings_and_respects_openfeature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify SuperSqueeze achieves >= 45% token savings on >1024 token payloads and respects OpenFeature flags."""
    engine = SuperSqueezeEngine()
    paragraphs = [
        "# Canonical Hath0r Architecture and SuperSqueeze Specification",
        "Every Feature in the Hath0r OpenSource Suite is a Service operated by at least one registered Bot in BotRegistry.",
    ]
    for i in range(120):
        paragraphs.append(
            f"Section {i}: Routine background diagnostic commentary on cluster node {i} with filler words and telemetry logs."
        )
    paragraphs.append("Critical conclusion: SuperSqueeze reduces token tax across Level 1 MCP and Level 2 CLI.")
    long_text = "\n".join(paragraphs)

    assert estimate_tokens(long_text) > 1024
    res = engine.compress(long_text, query="SuperSqueeze Service BotRegistry", target_ratio=0.35)
    assert res.squeezed is True
    assert res.savings_ratio >= 0.45
    assert res.owning_bot == "SuperSqueezeBot"
    assert "Canonical Hath0r Architecture" in res.compressed_text

    # Middleware enabled (default)
    compressed_out, meta_on = apply_supersqueeze_middleware(
        long_text, query="SuperSqueeze", target_ratio=0.35, token_threshold=1024
    )
    assert meta_on["squeezed"] is True
    assert meta_on["savings_ratio"] >= 0.45
    assert len(compressed_out) < len(long_text)

    # Middleware disabled via OpenFeature env override
    monkeypatch.setenv("KB_FEATURE_FLAG_MCP_SUPERSQUEEZE_ENABLED", "false")
    raw_out, meta_off = apply_supersqueeze_middleware(
        long_text, query="SuperSqueeze", target_ratio=0.35, token_threshold=1024
    )
    assert meta_off["enabled"] is False
    assert meta_off["squeezed"] is False
    assert raw_out == long_text


@pytest.mark.asyncio
async def test_level1_agentgraph_workflow_offer_and_ported_suite_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Level 1 AgentGraph tools, Missing-Workflow Offer, and ported suite tools execute via MCP."""
    monkeypatch.setattr("knowledgebase.api.main._mcp_service", None)
    ag_status = execute_agentgraph_status()
    assert ag_status["status"] == "healthy"
    assert ag_status["service_bot_registry_count"] == len(SERVICE_BOT_WORKFLOW_REGISTRY)

    ag_query = execute_agentgraph_query("CR-CLI-ENTRY-001", top_k=3)
    assert ag_query["agentgraph_level"] == "L1_MCP_AND_L2_CLI_MEMORY"

    ag_route = execute_agentgraph_route("developer", tool="hath0r_supersqueeze")
    assert ag_route["allowed"] is True
    assert "SuperSqueezeBot" in ag_route["owning_bots"]

    ag_val = execute_agentgraph_validate()
    assert ag_val["passed"] is True
    assert ag_val["orphan_services"] == []

    offer = offer_missing_workflow("Audit multi-region Kubernetes GPU quotas")
    assert offer["status"] == "missing_workflow_offer"
    assert offer["rule"] == "CR-FEATURE-WORKFLOW-STANDARD-001"
    assert offer["acceptance_test"]["prompt"] == "Audit multi-region Kubernetes GPU quotas"
    assert "DeclarativeWorkflow" in offer["scaffold_yaml"]

    # Execute via _execute_mcp_tool backend
    sq_resp = await _execute_mcp_tool(
        "hath0r_supersqueeze",
        {"text": "Alpha sentence. " * 200, "query": "Alpha", "target_ratio": 0.30},
    )
    assert sq_resp.get("isError") is not True
    sq_data = json.loads(sq_resp["content"][0]["text"])
    assert sq_data["squeezed"] is True
    assert sq_data["savings_ratio"] >= 0.45

    taguchi_resp = await _execute_mcp_tool(
        "hath0r_optimize_taguchi",
        {"array": "L9", "factors": ["temp", "top_p"], "loss_k": 10.0, "target_m": 1.0, "measured_y": 0.8},
    )
    taguchi_data = json.loads(taguchi_resp["content"][0]["text"])
    assert taguchi_data["runs"] == 9
    assert taguchi_data["quality_loss"] == pytest.approx(0.4)
    assert "TaguchiBot" in taguchi_data["owning_bots"]

    cccd_resp = await _execute_mcp_tool("hath0r_cicccdct_status", {})
    cccd_data = json.loads(cccd_resp["content"][0]["text"])
    assert cccd_data["ttl_hours"] == 4.0

    defaults = get_catalog_flag_defaults()
    snap = evaluate_feature_flags_snapshot()
    assert defaults["workflow.first.strict_offer"] is True
    assert snap["feature.service_bot.enforce"] is True
