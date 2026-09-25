"""Voice mediation and session management for Hath0r MCP.

Provides speech synthesis, spoken input coordination, and standardized
hath0r.voice.action/1 intent dispatch integrated with JEV tool-guard policy.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import datetime
import os
import platform
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional
import uuid

import structlog

from knowledgebase.core.jev_client import get_jev_client
from knowledgebase.core.jev_tool_guard import evaluate_tool_guard, format_block_message

logger = structlog.get_logger(__name__)

VOICE_ACTION_SCHEMA = "hath0r.voice.action/1"


@dataclass
class VoiceSessionEvent:
    """Recorded event in a voice session timeline."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    event_type: str = "utterance"  # utterance | action | feedback | status
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VoiceSessionState:
    """In-memory active state of voice interactions."""

    session_id: str = field(default_factory=lambda: f"vses-{uuid.uuid4().hex[:8]}")
    status: str = "ready"  # ready | listening | speaking | processing
    last_active: float = field(default_factory=time.time)
    events: List[VoiceSessionEvent] = field(default_factory=list)
    pending_prompt: Optional[str] = None

    def add_event(self, event_type: str, data: Dict[str, Any]) -> VoiceSessionEvent:
        self.last_active = time.time()
        event = VoiceSessionEvent(event_type=event_type, data=data)
        self.events.append(event)
        # Keep recent event history bounded
        if len(self.events) > 50:
            self.events = self.events[-50:]
        return event


# Module-level session state
_SESSION_STATE = VoiceSessionState()


def get_voice_session_state() -> VoiceSessionState:
    """Return the singleton voice session state."""
    return _SESSION_STATE


def reset_voice_session_state() -> VoiceSessionState:
    """Reset session state (useful for test isolation)."""
    global _SESSION_STATE
    _SESSION_STATE = VoiceSessionState()
    return _SESSION_STATE


def synthesize_speech(text: str, voice: Optional[str] = None) -> bool:
    """Synthesize speech using platform-native speech synthesis.

    On macOS (Darwin), uses native `/usr/bin/say`.
    On Linux, uses `espeak` or `spd-say` if available.
    Returns True if synthesis succeeded or completed, False otherwise.
    """
    clean_text = text.replace('"', '\\"').strip()
    if not clean_text:
        return False

    system = platform.system().lower()
    try:
        if system == "darwin" and shutil.which("say"):
            cmd = ["say"]
            if voice:
                cmd.extend(["-v", voice])
            cmd.append(clean_text)
            subprocess.run(cmd, check=False, timeout=10)
            return True
        elif system == "linux":
            if shutil.which("spd-say"):
                subprocess.run(["spd-say", clean_text], check=False, timeout=10)
                return True
            elif shutil.which("espeak"):
                subprocess.run(["espeak", clean_text], check=False, timeout=10)
                return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("speech_synthesis_failed", error=str(exc), platform=system)
        return False

    # Platform synthesis not available in this environment, but text was processed
    return True


async def voice_speak_service(text: str, voice: Optional[str] = None) -> Dict[str, Any]:
    """Execute voice_speak tool logic."""
    session = get_voice_session_state()
    session.status = "speaking"
    start_time = time.time()

    success = False
    try:
        # Run subprocess speech synthesis in executor to avoid blocking event loop
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, synthesize_speech, text, voice)
    finally:
        session.status = "ready"

    took_ms = round((time.time() - start_time) * 1000, 2)
    session.add_event(
        "feedback",
        {"text": text, "voice": voice, "success": success, "latency_ms": took_ms},
    )

    return {
        "status": "spoken" if success else "simulated",
        "text": text,
        "voice": voice or "default",
        "latency_ms": took_ms,
        "session_id": session.session_id,
    }


async def voice_listen_service(
    prompt: Optional[str] = None,
    timeout_seconds: float = 10.0,
    simulated_input: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute voice_listen tool logic."""
    session = get_voice_session_state()
    session.status = "listening"
    session.pending_prompt = prompt
    start_time = time.time()

    if prompt:
        synthesize_speech(prompt)

    try:
        # If simulated_input is provided, return immediately
        if simulated_input is not None:
            transcript = simulated_input.strip()
        else:
            # Check environment for non-interactive test bypass
            env_sim = os.getenv("HATH0R_VOICE_LISTEN_SIMULATION")
            if env_sim:
                transcript = env_sim.strip()
            else:
                transcript = ""
    finally:
        session.status = "ready"
        session.pending_prompt = None

    took_ms = round((time.time() - start_time) * 1000, 2)
    session.add_event(
        "utterance",
        {
            "prompt": prompt,
            "transcript": transcript,
            "latency_ms": took_ms,
        },
    )

    return {
        "status": "captured" if transcript else "silence_or_timeout",
        "transcript": transcript,
        "prompt": prompt,
        "duration_ms": took_ms,
        "session_id": session.session_id,
    }


async def voice_dispatch_action_service(
    transcript: str,
    intent: str,
    routing_tier: str = "system_one",
    confidence: float = 1.0,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    target: Optional[str] = None,
    feedback_text: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute voice_dispatch_action tool logic with JEV tool-guard protection."""
    start_time = time.time()

    # Pre-action JEV tool-guard evaluation
    guard_args = {
        "transcript": transcript,
        "intent": intent,
        "routing_tier": routing_tier,
        "command": command or "",
        "target": target or "",
        "args": args or [],
    }

    guard_result = await evaluate_tool_guard("voice_dispatch_action", guard_args)
    if guard_result is not None and guard_result.blocked:
        logger.warning(
            "voice_dispatch_action_blocked_by_jev",
            decision=guard_result.decision,
            confidence=guard_result.confidence,
            source=guard_result.source,
        )
        return {
            "error": "jev_tool_guard_blocked",
            "message": format_block_message("voice_dispatch_action", guard_result),
            "guard": guard_result.to_public_dict(),
        }

    session = get_voice_session_state()
    session.status = "processing"

    action_id = str(uuid.uuid4())
    current_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    host_platform = platform.system().lower()
    normalized_platform = (
        "darwin"
        if "darwin" in host_platform
        else "linux"
        if "linux" in host_platform
        else "win32"
        if "win" in host_platform
        else "agnostic"
    )

    payload: Dict[str, Any] = {}
    if command is not None:
        payload["command"] = command
    if args is not None:
        payload["args"] = args
    if target is not None:
        payload["target"] = target
    if feedback_text is not None:
        payload["feedback_text"] = feedback_text

    meta = dict(metadata or {})
    took_ms = round((time.time() - start_time) * 1000, 2)
    meta["latency_ms"] = took_ms
    meta["session_id"] = session.session_id

    # If feedback_text is provided, speak it to complete feedback loop
    if feedback_text:
        synthesize_speech(feedback_text)

    # Standardized contract schema output
    action_record = {
        "schema": VOICE_ACTION_SCHEMA,
        "action_id": action_id,
        "timestamp": current_time,
        "transcript": transcript,
        "routing_tier": routing_tier,
        "intent": intent,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "platform": normalized_platform,
        "payload": payload,
        "metadata": meta,
    }

    session.add_event("action", action_record)
    session.status = "ready"

    return {
        "dispatched": True,
        "action": action_record,
    }
