"""Unit & API tests for Issue #86: Workflow-First engine, BotRegistry dispatch, MemoryGraph bridge, 4h auto-calibration, and Cruise Control/MLflow/Phoenix tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from knowledgebase.api.main import _MCP_TOOL_HANDLERS, _execute_mcp_tool
from knowledgebase.core.mcp_tools import DEFAULT_MCP_TOOL_SPECS
from knowledgebase.core.workflow_engine import (
    CANONICAL_BOT_REGISTRY,
    mcp_bot_health,
    mcp_bot_invoke,
    mcp_bot_list,
    mcp_cccd_calibrate,
    mcp_cccd_ensure_calibrated,
    mcp_cccd_status,
    mcp_factory_execute,
    mcp_factory_list,
    mcp_memory_compound,
    mcp_memory_read,
    mcp_memory_verify,
    mcp_workflow_list,
    mcp_workflow_match,
    mcp_workflow_run,
    mcp_workflow_scaffold,
    mcp_workflow_status,
    mcp_workflow_validate,
)


def test_all_24_issue86_tools_registered_with_service_bot_metadata() -> None:
    """Every Issue #86 tool must be registered in DEFAULT_MCP_TOOL_SPECS and _MCP_TOOL_HANDLERS with >= 1 owning bot."""
    expected_tools = {
        "mcp_workflow_list",
        "mcp_workflow_match",
        "mcp_workflow_scaffold",
        "mcp_workflow_run",
        "mcp_workflow_status",
        "mcp_workflow_validate",
        "mcp_factory_list",
        "mcp_factory_execute",
        "mcp_bot_list",
        "mcp_bot_invoke",
        "mcp_bot_health",
        "mcp_memory_read",
        "mcp_memory_compound",
        "mcp_memory_verify",
        "mcp_cccd_status",
        "mcp_cccd_calibrate",
        "mcp_cccd_ensure_calibrated",
        "mcp_cruise_status",
        "mcp_cruise_decisions",
        "mcp_cruise_approve_boundary",
        "mcp_cruise_settle",
        "mcp_mlflow_log_eval",
        "mcp_mlflow_query_runs",
        "mcp_phoenix_query_spans",
    }
    spec_map = {spec.name: spec for spec in DEFAULT_MCP_TOOL_SPECS}
    for tool_name in expected_tools:
        assert tool_name in spec_map, f"{tool_name} missing from DEFAULT_MCP_TOOL_SPECS"
        assert tool_name in _MCP_TOOL_HANDLERS, f"{tool_name} missing from _MCP_TOOL_HANDLERS"
        schema = spec_map[tool_name].input_schema
        assert len(schema.get("x-hath0r-owning-bot", [])) >= 1
        assert schema.get("x-hath0r-workflow-id", "").endswith(".yaml")
        assert schema.get("x-hath0r-agentgraph-level") == "L1_MCP"


def test_workflow_list_match_scaffold_validate_and_run(tmp_path: Path) -> None:
    """Test Workflow-First lifecycle: list, match, missing-workflow offer, scaffold, validate, run, and status."""
    state_file = tmp_path / "cccd_state.json"

    # 1. List built-in workflows
    listed = mcp_workflow_list()
    assert listed["count"] >= 8

    # 2. Match known intent
    matched = mcp_workflow_match("supersqueeze context compression token savings")
    assert matched["matched"] is True
    assert matched["workflow"]["workflow_id"] == "cfg/factories/supersqueeze-context-workflow.yaml"

    # 3. Match unmapped intent -> returns Missing-Workflow Offer with original intent as acceptance test
    unmapped = mcp_workflow_match("quantum hyperdrive plasma stabilizer")
    assert unmapped["matched"] is False
    assert unmapped["missing_workflow_offer"]["status"] == "missing_workflow_offer"
    assert (
        unmapped["missing_workflow_offer"]["acceptance_test"]["prompt"]
        == "quantum hyperdrive plasma stabilizer"
    )
    assert len(unmapped["missing_workflow_offer"]["owning_bots"]) >= 1

    # 4. Scaffold new workflow with valid BotRegistry owner
    scaffolded = mcp_workflow_scaffold(
        name="quantum-stabilizer",
        intent="Verify quantum stabilizer workflow execution",
        owning_bots=["MCPWorkflowEngineBot"],
    )
    assert scaffolded["scaffolded"] is True
    wid = scaffolded["workflow_id"]

    # 5. Validate scaffolded workflow
    validated = mcp_workflow_validate(wid)
    assert validated["passed"] is True
    assert validated["violations"] == []

    # 6. Run workflow and inspect status
    run_res = mcp_workflow_run(
        wid,
        params={"target": "reactor-1"},
        state_path=state_file,
    )
    assert run_res["status"] == "COMPLETED"
    assert run_res["executed"] is True
    assert run_res["calibration_gate_4h"]["is_fresh"] is True
    run_id = run_res["run_id"]

    status_res = mcp_workflow_status(run_id=run_id)
    assert status_res["found"] is True
    assert status_res["run"]["workflow_id"] == wid


def test_factory_list_and_execute(tmp_path: Path) -> None:
    """Verify Level 1 AgentFactory listing and execution."""
    state_file = tmp_path / "cccd_state.json"
    factories = mcp_factory_list()
    assert factories["count"] >= 8
    first_id = factories["workflows"][0]["workflow_id"]

    exec_res = mcp_factory_execute(first_id, params={"env": "test"}, state_path=state_file)
    assert exec_res["status"] == "COMPLETED"
    assert exec_res["workflow_id"] == first_id
    assert len(exec_res["owning_bots"]) >= 1


def test_bot_registry_list_invoke_and_health() -> None:
    """Verify BotRegistry list, invoke (including unregistered bot rejection), and health."""
    bots = mcp_bot_list()
    assert bots["count"] >= len(CANONICAL_BOT_REGISTRY)
    assert "SuperCompressBot" in [b["name"] for b in bots["bots"]]

    invoked = mcp_bot_invoke(
        "SuperCompressBot",
        action="compress",
        params={"query": "architecture"},
    )
    assert invoked["invoked"] is True
    assert invoked["status"] == "COMPLETED"
    assert invoked["bot_name"] == "SuperCompressBot"

    with pytest.raises(ValueError, match="CR-FEATURE-WORKFLOW-STANDARD-001 violation"):
        mcp_bot_invoke("NonExistentGhostBot", action="haunt")

    health = mcp_bot_health()
    assert health["status"] == "healthy"
    assert health["registered_bots_count"] >= len(CANONICAL_BOT_REGISTRY)
    assert health["orphan_services"] == []
    assert health["orphan_workflows"] == []


def test_level1_level2_memorygraph_bridge(tmp_path: Path) -> None:
    """Verify Level 1 MCP <-> Level 2 .hath0r/memory/graph.json compound, read, and verify."""
    graph_file = tmp_path / "memory" / "graph.json"
    comp = mcp_memory_compound(
        node_id="episode:test-issue-86",
        node_type="episode",
        label="Issue 86 Test Episode",
        content="Verified Level 1 to Level 2 MemoryGraph compounding via AgentGraph.",
        importance=0.95,
        tags=["issue-86", "memorygraph"],
        graph_path=graph_file,
    )
    assert comp["compounded"] is True
    assert comp["node_id"] == "episode:test-issue-86"

    read_res = mcp_memory_read(topic="issue-86", graph_path=graph_file)
    assert read_res["count"] == 1
    assert read_res["nodes"][0]["id"] == "episode:test-issue-86"

    ver_res = mcp_memory_verify(graph_path=graph_file)
    assert ver_res["verified"] is True
    assert ver_res["node_count"] == 1


def test_cccd_4_hour_auto_calibration_gate(tmp_path: Path) -> None:
    """Verify 4-hour calibration freshness check and automatic pre-task recalibration when expired (> 4.0h)."""
    state_file = tmp_path / "cccd_state.json"

    # Write a stale timestamp (5.5 hours ago)
    stale_dt = datetime.now(timezone.utc) - timedelta(hours=5.5)
    state_file.write_text(
        json.dumps(
            {
                "last_run": stale_dt.isoformat(),
                "last_calibrated_at": stale_dt.isoformat(),
                "total_runs": 2,
                "ttl_hours": 4.0,
            }
        ),
        encoding="utf-8",
    )

    status_before = mcp_cccd_status(max_age_hours=4.0, state_path=state_file)
    assert status_before["is_fresh"] is False
    assert status_before["age_hours"] >= 5.4

    ensured = mcp_cccd_ensure_calibrated(max_age_hours=4.0, state_path=state_file)
    assert ensured["is_fresh"] is True
    assert ensured["auto_calibrated"] is True
    assert ensured["calibration_id"] == 3

    status_after = mcp_cccd_status(max_age_hours=4.0, state_path=state_file)
    assert status_after["is_fresh"] is True
    assert status_after["age_hours"] < 0.1

    # Calling ensure_calibrated again when fresh should not re-run calibration
    ensured_again = mcp_cccd_ensure_calibrated(max_age_hours=4.0, state_path=state_file)
    assert ensured_again["is_fresh"] is True
    assert ensured_again["auto_calibrated"] is False

    # Explicit calibrate call increments count
    manual = mcp_cccd_calibrate(trigger_source="manual_test", state_path=state_file)
    assert manual["calibrated"] is True
    assert manual["calibration_id"] == 4


@pytest.mark.asyncio
async def test_hath0r_net_cruise_mlflow_and_phoenix_bridges_via_execute_mcp_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Cruise Control, MLflow, and Arize Phoenix bridges via _execute_mcp_tool."""
    monkeypatch.setattr("knowledgebase.api.main._mcp_service", None)

    # Cruise Control status, approve boundary, decisions, settle
    c_status = await _execute_mcp_tool("mcp_cruise_status", {})
    assert c_status.get("isError") is not True
    c_payload = json.loads(c_status["content"][0]["text"])
    assert c_payload["container"] == "Hath0r-Cruise-Control"

    c_approve = await _execute_mcp_tool(
        "mcp_cruise_approve_boundary",
        {"gate_type": "input", "task_id": "issue-86", "decision": "approved"},
    )
    assert c_approve.get("isError") is not True

    c_settle = await _execute_mcp_tool(
        "mcp_cruise_settle",
        {"fact_key": "issue.86.settled", "fact_value": True},
    )
    assert c_settle.get("isError") is not True
    settle_payload = json.loads(c_settle["content"][0]["text"])
    assert settle_payload["settled"] is True

    c_decisions = await _execute_mcp_tool("mcp_cruise_decisions", {"status": "all"})
    assert c_decisions.get("isError") is not True
    decisions_payload = json.loads(c_decisions["content"][0]["text"])
    assert decisions_payload["count"] >= 1

    # MLflow log_eval and query_runs
    m_log = await _execute_mcp_tool(
        "mcp_mlflow_log_eval",
        {
            "task_id": "issue-86",
            "r_task": 0.9412,
            "tier_scores": {"tier1": 0.96, "tier2": 0.91, "tier3": 0.94, "tier4": 0.95},
            "experiment_name": "hath0r-task-evals",
        },
    )
    assert m_log.get("isError") is not True
    m_payload = json.loads(m_log["content"][0]["text"])
    assert m_payload["logged"] is True

    m_query = await _execute_mcp_tool(
        "mcp_mlflow_query_runs",
        {"experiment_name": "hath0r-task-evals", "limit": 5},
    )
    assert m_query.get("isError") is not True
    mq_payload = json.loads(m_query["content"][0]["text"])
    assert mq_payload["count"] >= 1

    # Arize Phoenix query_spans
    p_spans = await _execute_mcp_tool(
        "mcp_phoenix_query_spans",
        {"service_name": "hath0r-mcp", "limit": 5},
    )
    assert p_spans.get("isError") is not True
    p_payload = json.loads(p_spans["content"][0]["text"])
    assert p_payload["container"] == "Hath0r-phoenix"
    assert len(p_payload["spans"]) >= 1
