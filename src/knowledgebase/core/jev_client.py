"""JEV System One client for typed agent control-loop decisions.

JEV returns structured judgments (choice / noul / score), not prose. This
module implements the tool-guard preset used before consequential MCP tool
calls. See docs/jev-tool-guard-poc.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Optional, Sequence

import httpx
import structlog

logger = structlog.get_logger(__name__)

GuardDecision = Literal["allow", "confirm", "review", "deny"]
VALID_DECISIONS: frozenset[str] = frozenset({"allow", "confirm", "review", "deny"})

DEFAULT_TOOL_GUARD_URL = "https://www.jevai.org/api/v1/decisions/tool-guard"
DEFAULT_SYSTEMONE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_TIMEOUT_SECONDS = 2.5


@dataclass(frozen=True)
class JevSettings:
    """Runtime settings for the JEV tool-guard control loop."""

    enabled: bool = False
    mode: Literal["off", "live", "stub"] = "off"
    api_key: str = ""
    endpoint: str = DEFAULT_TOOL_GUARD_URL
    protocol: Literal["preset", "systemone"] = "preset"
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    # When live JEV is unreachable: allow | deny
    on_error: Literal["allow", "deny"] = "allow"
    # Decisions that block tool execution (POC treats confirm/review as block).
    block_decisions: frozenset[str] = field(
        default_factory=lambda: frozenset({"deny", "confirm", "review"})
    )
    min_confidence: float = 0.0

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "JevSettings":
        """Load settings from environment variables.

        Env vars (all optional):
          JEV_TOOL_GUARD_ENABLED=true|false
          JEV_MODE=off|live|stub
          JEV_API_KEY / TYPESAFE_API_KEY
          JEV_ENDPOINT
          JEV_PROTOCOL=preset|systemone
          JEV_TIMEOUT_SECONDS
          JEV_ON_ERROR=allow|deny
          JEV_MIN_CONFIDENCE
        """
        env: Mapping[str, str] = environ if environ is not None else os.environ
        enabled_raw = (env.get("JEV_TOOL_GUARD_ENABLED") or "").strip().lower()
        mode_raw = (env.get("JEV_MODE") or "").strip().lower()
        if mode_raw in {"off", "live", "stub"}:
            mode: Literal["off", "live", "stub"] = mode_raw  # type: ignore[assignment]
        elif enabled_raw in {"1", "true", "yes", "on"}:
            mode = "live"
        elif enabled_raw in {"stub"}:
            mode = "stub"
        else:
            mode = "off"

        api_key = (
            (env.get("JEV_API_KEY") or env.get("TYPESAFE_API_KEY") or env.get("AUTOJEV_API_KEY") or "")
            .strip()
        )
        endpoint = (env.get("JEV_ENDPOINT") or DEFAULT_TOOL_GUARD_URL).strip()
        protocol_raw = (env.get("JEV_PROTOCOL") or "preset").strip().lower()
        protocol: Literal["preset", "systemone"] = (
            "systemone" if protocol_raw == "systemone" else "preset"
        )
        try:
            timeout_seconds = float(env.get("JEV_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
        except ValueError:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        on_error_raw = (env.get("JEV_ON_ERROR") or "allow").strip().lower()
        on_error: Literal["allow", "deny"] = "deny" if on_error_raw == "deny" else "allow"
        try:
            min_confidence = float(env.get("JEV_MIN_CONFIDENCE") or 0.0)
        except ValueError:
            min_confidence = 0.0

        enabled = mode in {"live", "stub"}
        return cls(
            enabled=enabled,
            mode=mode,
            api_key=api_key,
            endpoint=endpoint,
            protocol=protocol,
            timeout_seconds=max(0.2, timeout_seconds),
            on_error=on_error,
            min_confidence=max(0.0, min(1.0, min_confidence)),
        )


@dataclass(frozen=True)
class ToolGuardRequest:
    """Business fields for a tool-guard decision."""

    tool: str
    action: str
    arguments_summary: Sequence[str] = ()
    side_effects: Sequence[str] = ()
    safeguards: Sequence[str] = ()
    policy: Sequence[str] = ()
    reversibility: str = "reversible"


@dataclass(frozen=True)
class ToolGuardResult:
    """Typed tool-guard outcome consumed by the MCP control loop."""

    decision: GuardDecision
    confidence: float
    probabilities: Mapping[str, float] = field(default_factory=dict)
    guidance: str = ""
    source: str = "jev"
    raw: Mapping[str, Any] = field(default_factory=dict)
    blocked: bool = False
    error: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize a safe subset for agent-facing error/text payloads."""
        return {
            "decision": self.decision,
            "confidence": round(self.confidence, 4),
            "probabilities": dict(self.probabilities),
            "guidance": self.guidance,
            "source": self.source,
            "blocked": self.blocked,
            "error": self.error or None,
        }


def _coerce_decision(value: Any, default: GuardDecision = "review") -> GuardDecision:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VALID_DECISIONS:
            return normalized  # type: ignore[return-value]
    return default


def _coerce_confidence(value: Any, default: float = 0.0) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return default
    if conf < 0.0:
        return 0.0
    if conf > 1.0:
        return 1.0
    return conf


def _extract_preset_payload(body: Mapping[str, Any]) -> Mapping[str, Any]:
    """Unwrap {code, message, data} envelopes used by jevai/autojev gateways."""
    if not isinstance(body, Mapping):
        return {}
    data = body.get("data")
    if isinstance(data, Mapping):
        return data
    return body


def parse_tool_guard_response(body: Mapping[str, Any], *, source: str = "jev") -> ToolGuardResult:
    """Parse a tool-guard response from preset or systemone shapes."""
    payload = _extract_preset_payload(body)

    # Preset shape: decision + confidence + probabilities + guidance
    if "decision" in payload:
        decision = _coerce_decision(payload.get("decision"))
        confidence = _coerce_confidence(payload.get("confidence"), 0.0)
        probs_raw = payload.get("probabilities") or {}
        probabilities: dict[str, float] = {}
        if isinstance(probs_raw, Mapping):
            for key, val in probs_raw.items():
                if key in VALID_DECISIONS:
                    try:
                        probabilities[str(key)] = float(val)
                    except (TypeError, ValueError):
                        continue
        guidance = str(payload.get("guidance") or payload.get("message") or "").strip()
        return ToolGuardResult(
            decision=decision,
            confidence=confidence,
            probabilities=probabilities,
            guidance=guidance,
            source=source,
            raw=dict(body),
        )

    # System One shape: answers.verdict.choice (+ optional confidence)
    answers = payload.get("answers")
    if isinstance(answers, Mapping):
        verdict = answers.get("verdict") or answers.get("decision") or answers.get("action")
        if isinstance(verdict, Mapping):
            choice = verdict.get("choice") or verdict.get("decision")
            decision = _coerce_decision(choice)
            confidence = _coerce_confidence(
                verdict.get("confidence"),
                default=_coerce_confidence(
                    (verdict.get("probabilities") or {}).get(decision)
                    if isinstance(verdict.get("probabilities"), Mapping)
                    else None,
                    0.0,
                ),
            )
            probs_raw = verdict.get("probabilities") or {}
            probabilities = {}
            if isinstance(probs_raw, Mapping):
                for key, val in probs_raw.items():
                    if str(key) in VALID_DECISIONS:
                        try:
                            probabilities[str(key)] = float(val)
                        except (TypeError, ValueError):
                            continue
            return ToolGuardResult(
                decision=decision,
                confidence=confidence,
                probabilities=probabilities,
                guidance=str(payload.get("guidance") or "").strip(),
                source=source,
                raw=dict(body),
            )

    return ToolGuardResult(
        decision="review",
        confidence=0.0,
        guidance="Unrecognized JEV response shape; defaulting to review.",
        source=source,
        raw=dict(body),
        error="unrecognized_response",
    )


def stub_tool_guard(request: ToolGuardRequest) -> ToolGuardResult:
    """Deterministic offline policy for demos and unit tests without API keys.

    Heuristics (intentionally simple for a POC):
    - tools with delete/remove/prune/force → deny
    - sync / reindex / batch / directory / create / upsert / add → confirm
    - everything else guarded → review
    """
    name = request.tool.casefold()
    action = request.action.casefold()
    blob = f"{name} {action} {' '.join(request.arguments_summary)}".casefold()

    if any(tok in blob for tok in ("delete", "remove", "prune", "drop", "destroy", "force")):
        decision: GuardDecision = "deny"
        guidance = "Stub policy: destructive tool patterns require explicit human override."
        confidence = 0.92
    elif any(
        tok in blob
        for tok in ("sync", "reindex", "batch", "directory", "create", "upsert", "add", "write")
    ):
        decision = "confirm"
        guidance = "Stub policy: mutating write requires confirmation before execution."
        confidence = 0.8
    else:
        decision = "review"
        guidance = "Stub policy: guarded tool without a clear allow path."
        confidence = 0.55

    probabilities = {
        "allow": 0.05 if decision != "allow" else 0.85,
        "confirm": 0.1 if decision != "confirm" else 0.8,
        "review": 0.1 if decision != "review" else 0.55,
        "deny": 0.05 if decision != "deny" else 0.92,
    }
    probabilities[decision] = confidence
    return ToolGuardResult(
        decision=decision,
        confidence=confidence,
        probabilities=probabilities,
        guidance=guidance,
        source="stub",
        raw={"mode": "stub", "tool": request.tool},
    )


def _preset_body(request: ToolGuardRequest) -> dict[str, Any]:
    return {
        "tool": request.tool,
        "action": request.action,
        "arguments_summary": list(request.arguments_summary),
        "side_effects": list(request.side_effects),
        "safeguards": list(request.safeguards),
        "policy": list(request.policy),
        "reversibility": request.reversibility,
    }


def _systemone_body(request: ToolGuardRequest) -> dict[str, Any]:
    return {
        "model": "jev-latest",
        "state": {
            "tool": request.tool,
            "action": request.action,
            "arguments_summary": list(request.arguments_summary),
            "side_effects": list(request.side_effects),
            "safeguards": list(request.safeguards),
            "policy": list(request.policy),
            "reversibility": request.reversibility,
        },
        "questions": {
            "verdict": {
                "type": "choice",
                "instructions": (
                    "Choose the safest next step for this tool call. "
                    "allow = execute now; confirm = need explicit human OK; "
                    "review = pause for human review; deny = do not execute."
                ),
                "criteria": {
                    "allow": "Safe to execute automatically under stated policy and safeguards.",
                    "confirm": "Need explicit human confirmation before executing.",
                    "review": "Ambiguous or high-stakes; route to human review.",
                    "deny": "Unsafe or policy-violating; do not execute.",
                },
            }
        },
    }


class JevClient:
    """Thin async client for JEV tool-guard decisions."""

    def __init__(
        self,
        settings: Optional[JevSettings] = None,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.settings = settings or JevSettings.from_env()
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return self.settings.enabled and self.settings.mode in {"live", "stub"}

    async def guard_tool_call(self, request: ToolGuardRequest) -> ToolGuardResult:
        """Evaluate a tool call and return a typed guard result."""
        if not self.enabled or self.settings.mode == "off":
            return ToolGuardResult(
                decision="allow",
                confidence=1.0,
                guidance="JEV tool-guard disabled.",
                source="disabled",
            )

        if self.settings.mode == "stub":
            result = stub_tool_guard(request)
            return self._apply_block_policy(result)

        if not self.settings.api_key:
            logger.warning("jev_tool_guard_missing_api_key", mode=self.settings.mode)
            fallback = ToolGuardResult(
                decision="deny" if self.settings.on_error == "deny" else "allow",
                confidence=0.0,
                guidance="JEV API key missing; applied on_error policy.",
                source="config_error",
                error="missing_api_key",
            )
            return self._apply_block_policy(fallback)

        try:
            body = await self._post_decision(request)
            result = parse_tool_guard_response(body, source="jev_live")
            return self._apply_block_policy(result)
        except Exception as exc:  # noqa: BLE001 - control loop must never crash tool path unexpectedly
            logger.warning(
                "jev_tool_guard_error",
                error=str(exc),
                tool=request.tool,
                on_error=self.settings.on_error,
            )
            fallback = ToolGuardResult(
                decision="deny" if self.settings.on_error == "deny" else "allow",
                confidence=0.0,
                guidance=f"JEV unavailable ({exc}); applied on_error={self.settings.on_error}.",
                source="error_fallback",
                error=str(exc),
            )
            return self._apply_block_policy(fallback)

    def _apply_block_policy(self, result: ToolGuardResult) -> ToolGuardResult:
        blocked = result.decision in self.settings.block_decisions
        if (
            not blocked
            and result.decision == "allow"
            and result.confidence < self.settings.min_confidence
        ):
            blocked = True
            guidance = (
                f"{result.guidance} Low confidence "
                f"({result.confidence:.2f} < {self.settings.min_confidence:.2f}); blocking."
            ).strip()
            return ToolGuardResult(
                decision=result.decision,
                confidence=result.confidence,
                probabilities=result.probabilities,
                guidance=guidance,
                source=result.source,
                raw=result.raw,
                blocked=True,
                error=result.error,
            )
        return ToolGuardResult(
            decision=result.decision,
            confidence=result.confidence,
            probabilities=result.probabilities,
            guidance=result.guidance,
            source=result.source,
            raw=result.raw,
            blocked=blocked,
            error=result.error,
        )

    async def _post_decision(self, request: ToolGuardRequest) -> dict[str, Any]:
        if self.settings.protocol == "systemone":
            url = self.settings.endpoint or DEFAULT_SYSTEMONE_URL
            payload = _systemone_body(request)
        else:
            url = self.settings.endpoint or DEFAULT_TOOL_GUARD_URL
            payload = _preset_body(request)

        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout = httpx.Timeout(self.settings.timeout_seconds)
        async with httpx.AsyncClient(transport=self._transport, timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("JEV response was not a JSON object")
            return data


# Process-wide client used by the MCP tool loop (tests may replace).
_CLIENT: Optional[JevClient] = None


def get_jev_client() -> JevClient:
    """Return the shared JEV client, creating it from env on first use."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = JevClient()
    return _CLIENT


def set_jev_client(client: Optional[JevClient]) -> None:
    """Replace or clear the shared client (tests / hot reload)."""
    global _CLIENT
    _CLIENT = client


def reset_jev_client() -> None:
    """Drop the shared client so the next call reloads settings."""
    set_jev_client(None)
