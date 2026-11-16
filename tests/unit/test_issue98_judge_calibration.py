"""HATH0R-MCP #98: read-only judge calibration report and the level-aware JEV trust fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledgebase.api.main import _MCP_TOOL_HANDLERS, _execute_mcp_tool
from knowledgebase.core import qa_state
from knowledgebase.core.jev_client import ToolGuardResult
from knowledgebase.core.jev_tool_guard import apply_trust_fallback, risk_level
from knowledgebase.core.mcp_tools import DEFAULT_MCP_TOOL_SPECS


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    import knowledgebase.api.main as api_main

    monkeypatch.setattr(api_main, "_mcp_service", None)
    monkeypatch.setenv("HATH0R_MCP_QA_ROOT", str(tmp_path))
    d = tmp_path / ".hath0r" / "evals" / "judges"
    d.mkdir(parents=True)
    (d / "latest.json").write_text(
        json.dumps(
            {
                "study_id": "judges-1",
                "complete": True,
                "spend_usd": 12.3,
                "judges": [{"id": "jev"}, {"id": "claude-opus"}],
                "banks": {
                    "jev": {
                        "summary": {"certified": 3},
                        "anchors": ["truth"],
                        "bias": {"reference": "anchors:truth", "swings": {"jev": {"swing": 0.4}}},
                        "decisions": {"jev": {"R2": {"status": "certified"}, "R4": {"status": "removed_bias"}}, "claude-opus": {"R2": {"status": "certified"}}},
                        "fit": {"parts": {"p1": {}}},
                    }
                },
            }
        )
    )
    (d / "registry.json").write_text(json.dumps({"judges": {"jev": {"banks": {"jev": {"certified_levels": ["R2"], "levels": {"R2": "certified", "R4": "removed_bias"}}}}}}))
    return tmp_path


def test_report_and_filters(workspace: Path) -> None:
    rep = qa_state.judge_calibration_report()
    assert rep["exists"] and rep["study_id"] == "judges-1"
    assert "fit" not in rep["banks"]["jev"]  # per-part tables are left out
    one = qa_state.judge_calibration_report(judge="jev", level="R4")
    assert set(one["banks"]["jev"]["decisions"]) == {"jev"} and one["certified"] is False
    assert qa_state.judge_calibration_report(judge="jev", level="R2")["certified"] is True
    assert qa_state.judge_certified("jev", "R2") is True
    assert qa_state.judge_certified("claude-haiku", "R2") is None
    with pytest.raises(ValueError):
        qa_state.judge_calibration_report(judge="../etc")
    with pytest.raises(ValueError):
        qa_state.judge_calibration_report(level="L9")


def test_report_missing(tmp_path: Path) -> None:
    assert qa_state.judge_calibration_report(root=tmp_path)["exists"] is False
    assert qa_state.judge_certified("jev", "R2", root=tmp_path) is None


@pytest.mark.asyncio
async def test_tool_registered_and_dispatched(workspace: Path) -> None:
    assert "evals_judge_calibration_report" in _MCP_TOOL_HANDLERS
    assert any(s.name == "evals_judge_calibration_report" for s in DEFAULT_MCP_TOOL_SPECS)
    res = await _execute_mcp_tool("evals_judge_calibration_report", {"judge": "jev", "level": "R4"})
    body = json.loads(res["content"][0]["text"])
    assert body["certified"] is False and body["owning_bots"] == ["judge-calibration-bot"]


def test_risk_levels() -> None:
    assert risk_level("kb_index_delete") == "R5"
    assert risk_level("kb_add_document") == "R2"
    assert risk_level("kb_search") is None


def _allow(source: str = "jev_live") -> ToolGuardResult:
    return ToolGuardResult(decision="allow", confidence=0.9, guidance="ok", source=source)


def test_trust_fallback_modes() -> None:
    assert apply_trust_fallback(_allow(), "R4", certified=True, mode="enforce").blocked is False
    blocked = apply_trust_fallback(_allow(), "R4", certified=False, mode="enforce")
    assert blocked.blocked and "not certified at R4" in blocked.guidance
    warned = apply_trust_fallback(_allow(), "R5", certified=None, mode="warn")
    assert not warned.blocked and "never calibrated" in warned.guidance
    assert apply_trust_fallback(_allow(), "R2", certified=False, mode="enforce").blocked is False  # below R3
    assert apply_trust_fallback(_allow("stub"), "R4", certified=False, mode="enforce").blocked is False
    assert apply_trust_fallback(_allow(), "R4", certified=False, mode="off").blocked is False
