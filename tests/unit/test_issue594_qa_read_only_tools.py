"""HATH0R-CLI #594: read-only Level 1 views of the industrial QA state (MSA, SPC, FMEA, Andon)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from knowledgebase.api.main import _MCP_TOOL_HANDLERS, _execute_mcp_tool
from knowledgebase.core import qa_state
from knowledgebase.core.mcp_tools import DEFAULT_MCP_TOOL_SPECS
from knowledgebase.server import ServiceSettings, create_app

QA_TOOLS = {
    "evals_msa_report": "measurement-system-bot",
    "quality_spc_status": "spc-monitor-bot",
    "fmea_query": "fmea-bot",
    "andon_status": "andon-bot",
}


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    import knowledgebase.api.main as api_main

    monkeypatch.setattr(api_main, "_mcp_service", None)  # other suites leave a mock behind
    monkeypatch.setenv("HATH0R_MCP_QA_ROOT", str(tmp_path))
    h = tmp_path / ".hath0r"
    (h / "evals" / "msa").mkdir(parents=True)
    (h / "evals" / "msa" / "latest.json").write_text(
        json.dumps({"study_id": "msa-1", "passed": True, "gage_rr": {"pct_grr": 0.076, "ndc": 100}, "measurements": [[1, 2]]})
    )
    (h / "spc").mkdir()
    (h / "spc" / "latest.json").write_text(
        json.dumps({"mode": "warn", "metrics": {"r_task": {"status": "in_control"}, "cost_usd": {"status": "out_of_control"}}, "capability": {"cpk": 1.1}})
    )
    (h / "fmea").mkdir()
    (h / "fmea" / "end-of-task.yaml").write_text(
        yaml.safe_dump(
            {
                "process": "end-of-task",
                "rows": [
                    {"id": "EOT-1", "action_priority": "M", "rpn": 300},
                    {"id": "EOT-2", "action_priority": "H", "rpn": 120},
                    {"id": "EOT-3", "action_priority": "H", "rpn": 180},
                    {"id": "EOT-4", "action_priority": "L", "rpn": 20},
                ],
            }
        )
    )
    andon = h / "state" / "andon"
    andon.mkdir(parents=True)
    events = [
        {"type": "event", "event_id": "a1", "severity": "stop", "source": "spc", "reason": "shift"},
        {"type": "event", "event_id": "a2", "severity": "warn", "source": "dag", "reason": "slow"},
        {"type": "event", "event_id": "a3", "severity": "stop", "source": "budget", "reason": "cap"},
        {"type": "ack", "event_id": "a3"},
        {"type": "clear", "event_id": "a3"},
        {"type": "ack", "event_id": "a1"},
    ]
    (andon / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\nnot json\n")
    return tmp_path


def test_tools_are_registered_with_owning_bots() -> None:
    spec_map = {s.name: s for s in DEFAULT_MCP_TOOL_SPECS}
    for name, bot in QA_TOOLS.items():
        assert name in spec_map
        assert spec_map[name].input_schema["x-hath0r-owning-bot"] == [bot]
        assert name in _MCP_TOOL_HANDLERS


def test_msa_report_drops_raw_measurements(workspace: Path) -> None:
    res = qa_state.msa_report()
    assert res["exists"] and res["gage_rr"]["pct_grr"] == 0.076
    assert "measurements" not in res


def test_spc_status_filters_metric(workspace: Path) -> None:
    assert set(qa_state.spc_status()["metrics"]) == {"r_task", "cost_usd"}
    assert set(qa_state.spc_status(metric="r_task")["metrics"]) == {"r_task"}
    with pytest.raises(ValueError):
        qa_state.spc_status(metric="nope")


def test_fmea_query_ranks_and_filters(workspace: Path) -> None:
    res = qa_state.fmea_query()
    assert [r["id"] for r in res["rows"]] == ["EOT-3", "EOT-2", "EOT-1", "EOT-4"]
    assert res["high_priority"] == 2
    assert [r["id"] for r in qa_state.fmea_query(priority="H", min_rpn=150)["rows"]] == ["EOT-3"]
    assert qa_state.fmea_query(limit=1)["total"] == 4
    assert qa_state.fmea_query(process="missing")["exists"] is False
    for bad in ("../etc", "End", "a/b"):
        with pytest.raises(ValueError):
            qa_state.fmea_query(process=bad)
    with pytest.raises(ValueError):
        qa_state.fmea_query(priority="X")


def test_andon_status_folds_the_ledger(workspace: Path) -> None:
    res = qa_state.andon_status()
    assert res["stopped"] is True
    assert {e["event_id"]: e["state"] for e in res["active"]} == {"a1": "acknowledged", "a2": "open"}
    assert res["stops"] == 1 and res["warnings"] == 1


def test_missing_state_is_reported_not_invented(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HATH0R_MCP_QA_ROOT", str(tmp_path))
    assert qa_state.msa_report()["exists"] is False
    assert qa_state.spc_status()["exists"] is False
    assert qa_state.fmea_query()["exists"] is False
    andon = qa_state.andon_status()
    assert andon["exists"] is False and andon["stopped"] is False


def test_oversized_state_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(qa_state, "MAX_STATE_BYTES", 10)
    (tmp_path / ".hath0r" / "spc").mkdir(parents=True)
    (tmp_path / ".hath0r" / "spc" / "latest.json").write_text(json.dumps({"metrics": {"a": 1, "b": 2}}))
    with pytest.raises(ValueError):
        qa_state.spc_status(root=tmp_path)


@pytest.mark.asyncio
async def test_backend_dispatch(workspace: Path) -> None:
    res = await _execute_mcp_tool("fmea_query", {"priority": "H"})
    body = json.loads(res["content"][0]["text"])
    assert body["total"] == 2 and body["owning_bots"] == ["fmea-bot"]
    res = await _execute_mcp_tool("quality_spc_status", {"metric": "nope"})
    assert res.get("isError")
    for name in ("evals_msa_report", "andon_status"):
        res = await _execute_mcp_tool(name, {})
        assert json.loads(res["content"][0]["text"])["success"] is True


@pytest.mark.asyncio
async def test_fastmcp_tools_are_read_only(tmp_path: Path, workspace: Path, monkeypatch) -> None:
    import knowledgebase.server as server_mod

    captured = []

    class CapturingFastMCP(server_mod.FastMCP):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(self)

    monkeypatch.setattr(server_mod, "FastMCP", CapturingFastMCP)
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "doc.md").write_text("# Doc\n\nbody\n")
    create_app(ServiceSettings(knowledge_root=tmp_path / "kb"))
    tools = {t.name: t for t in await captured[0].list_tools()}
    for name in QA_TOOLS:
        assert tools[name].annotations.readOnlyHint is True
    res = await captured[0].call_tool("fmea_query", {"priority": "H"})
    assert "EOT-3" in json.dumps(res, default=str)
