"""
Observability helpers backed by OpenTelemetry (Hath0r-phoenix) and non-blocking OpenObservation spooling.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

import structlog

from knowledgebase.core.feature_flags import evaluate_feature_flags_snapshot

logger = structlog.get_logger(__name__)

try:
    from opentelemetry import trace as _otel_trace

    tracer: Any = _otel_trace.get_tracer("hath0r-mcp")
except Exception:  # pragma: no cover - optional dependency fallback
    tracer = None


def get_otel_config() -> dict[str, Any]:
    """Load canonical OpenTelemetry config from cfg/observability/otel.json."""
    cfg_path = Path(__file__).resolve().parents[3] / "cfg" / "observability" / "otel.json"
    if cfg_path.is_file():
        try:
            return dict(json.loads(cfg_path.read_text(encoding="utf-8")))
        except Exception:  # pragma: no cover
            pass
    return {
        "resource": {"service_name": "hath0r-mcp", "service_namespace": "hath0r-opensource"},
        "exporters": {"otlp": {"default_endpoint": "http://localhost:38000/phoenix"}},
    }


def get_phoenix_endpoint() -> str:
    """Resolve active Arize Phoenix OTLP endpoint (env override -> otel.json default)."""
    env_ep = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if env_ep:
        return env_ep
    cfg = get_otel_config()
    return str(
        cfg.get("exporters", {})
        .get("otlp", {})
        .get("default_endpoint", "http://localhost:38000/phoenix")
    )


def record_openobservation_event(
    operation: str,
    duration_ms: float,
    event_class: str = "ops",
    spool_root: Path | None = None,
    **attributes: Any,
) -> dict[str, Any]:
    """Write a non-blocking OpenObservation telemetry envelope to .hath0r/spool/mcp_telemetry.jsonl."""
    flags = evaluate_feature_flags_snapshot()
    safe_attrs = {
        str(k): v
        for k, v in attributes.items()
        if not any(secret_word in str(k).lower() for secret_word in ("token", "secret", "password", "key"))
    }
    envelope: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "hath0r-mcp",
        "event_class": event_class,
        "operation": operation,
        "duration_ms": round(duration_ms, 3),
        "phoenix_endpoint": get_phoenix_endpoint(),
        "feature_flags": flags,
        "attributes": safe_attrs,
    }
    try:
        base_dir = spool_root or (Path(__file__).resolve().parents[3] / ".hath0r" / "spool")
        base_dir.mkdir(parents=True, exist_ok=True)
        spool_file = base_dir / "mcp_telemetry.jsonl"
        with spool_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(envelope, default=str) + "\n")
    except Exception:  # pragma: no cover - never_block: true per OpenObservation policy
        pass
    return envelope


@contextmanager
def timed_operation(operation_name: str, **attributes: Any) -> Iterator[None]:
    """Record timing with OpenTelemetry span (or compatible tracer) and structured OpenObservation log."""
    start = time.perf_counter()
    span: Any = None
    if tracer is not None:
        try:
            if hasattr(tracer, "trace"):
                span = tracer.trace(operation_name)
                for key, value in attributes.items():
                    span.set_tag(str(key), value)
            elif hasattr(tracer, "start_span"):
                span = tracer.start_span(operation_name)
                for key, value in attributes.items():
                    if hasattr(span, "set_attribute"):
                        span.set_attribute(str(key), str(value))
        except Exception:  # pragma: no cover - non-critical tracing failures
            span = None

    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        logger.info(
            "timed_operation",
            operation=operation_name,
            duration_ms=round(duration_ms, 3),
            **attributes,
        )
        if span is not None:
            try:
                if hasattr(span, "set_tag"):
                    span.set_tag("duration_ms", duration_ms)
                elif hasattr(span, "set_attribute"):
                    span.set_attribute("duration_ms", round(duration_ms, 3))
                if hasattr(span, "finish"):
                    span.finish()
                elif hasattr(span, "end"):
                    span.end()
            except Exception:  # pragma: no cover
                pass
        record_openobservation_event(operation_name, duration_ms, **attributes)
