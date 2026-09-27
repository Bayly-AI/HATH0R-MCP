"""Unit tests for Hath0r MCP voice tools, session state, and JEV guard."""

import pytest
from unittest.mock import patch

from knowledgebase.services.voice_service import (
    get_voice_session_state,
    reset_voice_session_state,
    synthesize_speech,
    voice_speak_service,
    voice_listen_service,
    voice_dispatch_action_service,
    VOICE_ACTION_SCHEMA,
)
from knowledgebase.core.jev_client import ToolGuardResult
from knowledgebase.core.jev_tool_guard import is_guarded_tool, build_tool_guard_request


@pytest.fixture(autouse=True)
def reset_voice():
    reset_voice_session_state()
    yield
    reset_voice_session_state()


def test_is_guarded_tool_includes_voice_dispatch():
    assert is_guarded_tool("voice_dispatch_action") is True
    request = build_tool_guard_request(
        "voice_dispatch_action",
        {"intent": "cli_command", "command": "hath0r doctor", "transcript": "run doctor"},
    )
    assert request is not None
    assert "voice_dispatch_action" in request.tool
    assert "hath0r doctor" in request.action


def test_synthesize_speech_empty_returns_false():
    assert synthesize_speech("") is False
    assert synthesize_speech("   ") is False


@pytest.mark.asyncio
async def test_voice_speak_service_basic():
    with patch("knowledgebase.services.voice_service.synthesize_speech", return_value=True):
        res = await voice_speak_service("Hello world")
        assert res["status"] == "spoken"
        assert res["text"] == "Hello world"
        assert "latency_ms" in res
        assert "session_id" in res

        session = get_voice_session_state()
        assert len(session.events) == 1
        assert session.events[0].event_type == "feedback"
        assert session.events[0].data["text"] == "Hello world"


@pytest.mark.asyncio
async def test_voice_listen_service_simulated():
    res = await voice_listen_service(
        prompt="What is your command?",
        timeout_seconds=5.0,
        simulated_input="hath0r doctor",
    )
    assert res["status"] == "captured"
    assert res["transcript"] == "hath0r doctor"
    assert res["prompt"] == "What is your command?"

    session = get_voice_session_state()
    assert len(session.events) == 1
    assert session.events[0].event_type == "utterance"
    assert session.events[0].data["transcript"] == "hath0r doctor"


@pytest.mark.asyncio
async def test_voice_listen_service_empty_timeout():
    res = await voice_listen_service(prompt=None, simulated_input="")
    assert res["status"] == "silence_or_timeout"
    assert res["transcript"] == ""


@pytest.mark.asyncio
async def test_voice_dispatch_action_service_success():
    res = await voice_dispatch_action_service(
        transcript="show status",
        intent="cli_command",
        routing_tier="system_one",
        confidence=0.98,
        command="hath0r status",
        args=["--json"],
        feedback_text="Checking system status now",
    )
    assert res["dispatched"] is True
    action = res["action"]
    assert action["schema"] == VOICE_ACTION_SCHEMA
    assert action["intent"] == "cli_command"
    assert action["routing_tier"] == "system_one"
    assert action["confidence"] == 0.98
    assert action["payload"]["command"] == "hath0r status"
    assert action["payload"]["args"] == ["--json"]
    assert action["payload"]["feedback_text"] == "Checking system status now"
    assert "action_id" in action
    assert "timestamp" in action
    assert "platform" in action


@pytest.mark.asyncio
async def test_voice_dispatch_action_service_blocked_by_jev():
    stub_blocked = ToolGuardResult(
        decision="deny",
        confidence=0.99,
        probabilities={"deny": 0.99},
        guidance="Blocked by JEV policy",
        source="jev",
        blocked=True,
    )

    with patch("knowledgebase.services.voice_service.evaluate_tool_guard", return_value=stub_blocked):
        res = await voice_dispatch_action_service(
            transcript="delete all indices",
            intent="system_control",
            command="rm -rf /",
        )
        assert "error" in res
        assert res["error"] == "jev_tool_guard_blocked"
        assert res["guard"]["decision"] == "deny"
        assert res["guard"]["blocked"] is True
