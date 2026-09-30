"""
Observability helpers with optional Datadog tracing.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

try:
    from ddtrace import tracer
except Exception:  # pragma: no cover - optional dependency
    tracer = None


@contextmanager
def timed_operation(operation_name: str, **attributes: Any) -> Iterator[None]:
    """Record timing with ddtrace span when available, and always structured-log."""
    start = time.perf_counter()
    span = None
    if tracer is not None:
        try:
            span = tracer.trace(operation_name)
            for key, value in attributes.items():
                span.set_tag(str(key), value)
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
            span.set_tag("duration_ms", duration_ms)
            span.finish()
