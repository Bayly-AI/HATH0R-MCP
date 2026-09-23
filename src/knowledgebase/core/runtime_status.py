"""Runtime and Docker status helpers for KnowledgeBase Engine.

This module provides a small, JSON-friendly view of how the API is running
(docker vs local) and the expected runtime services. It is designed to back the
`/api/v1/runtime/status` endpoint used by the UI dashboard.
"""

from __future__ import annotations

import http.client
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from knowledgebase import __version__
from knowledgebase.cli.runtime_start import DEFAULT_RUNTIME_CONFIG
from knowledgebase.core.config import get_settings

_RUNTIME_CFG_FILE = Path("cfg") / "cfg.json"
_DEFAULT_API_BASE_URL = os.getenv("BaylyAI_KNOWLEDGEBASE_HOST", "http://localhost:8083")


@dataclass
class _ResolvedRuntimeConfig:
    """Internal representation of the resolved runtime configuration."""

    mode: str
    source: str
    config: dict[str, Any]


class RuntimeMode(BaseModel):
    """Information about how the KnowledgeBase API is being run.

    Attributes:
        name: Runtime mode name (e.g. ``"docker"`` or ``"local"``).
        source: Where the mode was resolved from (``"env"``, ``"config"``, or
            ``"default"``).
        details: Additional mode-specific details such as compose file, service
            name, host, or port.
    """

    name: str
    source: str
    details: dict[str, Any] = Field(default_factory=dict)


class ServiceStatus(BaseModel):
    """Status information for a runtime service.

    Attributes:
        name: Logical service name (e.g. ``"knowledgebase-api"``).
        kind: Service category (``"api"``, ``"search"``, ``"dashboards"``).
        health: High-level health string (``"healthy"``, ``"degraded"``,
            ``"unavailable"``, or ``"unknown"``).
        url: Primary URL for accessing the service.
        message: Optional human-readable status message.
        last_checked: Timestamp when this status snapshot was produced.
    """

    name: str
    kind: str
    health: str
    url: str
    message: str | None = None
    last_checked: datetime


class RuntimeStatusResponse(BaseModel):
    """Runtime status payload returned by the public API endpoint.

    This structure is intentionally compact and stable so that the UI can rely
    on it for dashboards without depending on Docker or local runtime
    internals.
    """

    mode: RuntimeMode
    api_base_url: str
    services: list[ServiceStatus]
    version: str


def _load_runtime_section() -> dict[str, Any]:
    """Load the "runtime" section from cfg/cfg.json if present.

    Returns a dictionary merged with :data:`DEFAULT_RUNTIME_CONFIG` so that all
    expected keys are present even when the file is missing or incomplete.
    """

    if not _RUNTIME_CFG_FILE.exists():
        return DEFAULT_RUNTIME_CONFIG

    try:
        data = json.loads(_RUNTIME_CFG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):  # pragma: no cover - defensive
        return DEFAULT_RUNTIME_CONFIG

    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        return DEFAULT_RUNTIME_CONFIG

    merged: dict[str, Any] = {
        "default_start_mode": runtime.get(
            "default_start_mode", DEFAULT_RUNTIME_CONFIG["default_start_mode"]
        ),
        "modes": {
            **DEFAULT_RUNTIME_CONFIG["modes"],
            **runtime.get("modes", {}),
        },
    }
    return merged


def _probe_http_service(
    url: str, keyword: str | None = None, timeout: float = 1.5
) -> tuple[str, str]:
    """Probe an HTTP service and return a (health, message) tuple.

    This uses the standard library ``http.client`` so it works in constrained
    environments without introducing an additional dependency.
    """

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"

    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path)
        response = conn.getresponse()
        status = response.status
        body = response.read(4096)  # Limit to first few KB
        conn.close()
    except OSError as exc:  # Network failure, connection refused, etc.
        return "unavailable", f"Probe failed: {exc}"

    # Basic health classification based on HTTP status code.
    if status >= 500:
        return "unavailable", f"HTTP {status}: server error"
    if status >= 400:
        return "degraded", f"HTTP {status}: client error"

    if keyword is not None:
        try:
            if keyword.encode("utf-8") not in body:
                return "degraded", f"HTTP {status}: did not find expected marker"
        except Exception:
            return "degraded", f"HTTP {status}: unable to inspect body"

    return "healthy", f"HTTP {status}: OK"


def _resolve_runtime_mode(config: dict[str, Any]) -> _ResolvedRuntimeConfig:
    """Resolve the effective runtime mode from config and environment.

    Resolution order:

    1. ``KB_START_MODE`` environment variable
    2. ``runtime.default_start_mode`` from configuration
    3. Built-in default (``"docker"``)
    """

    env_mode = os.getenv("KB_START_MODE")
    if env_mode:
        source = "env"
        mode = env_mode
    else:
        source = "config"
        mode = str(config.get("default_start_mode", DEFAULT_RUNTIME_CONFIG["default_start_mode"]))

    modes_cfg = config.get("modes", {})
    effective_cfg = modes_cfg.get(mode, DEFAULT_RUNTIME_CONFIG["modes"].get(mode, {}))

    # Fallback if an unknown mode is specified.
    if not effective_cfg:
        mode = "docker"
        source = "default"
        effective_cfg = DEFAULT_RUNTIME_CONFIG["modes"]["docker"]

    return _ResolvedRuntimeConfig(mode=mode, source=source, config=effective_cfg)


def get_runtime_status() -> RuntimeStatusResponse:
    """Build a snapshot of the current runtime and expected services.

    The snapshot does *not* call out to Docker directly; instead it relies on
    configuration and known defaults so that it remains safe to use even when
    Docker is not installed or when running in local mode.
    """

    runtime_cfg = _load_runtime_section()
    resolved = _resolve_runtime_mode(runtime_cfg)

    mode_details: dict[str, Any] = {}
    services: list[ServiceStatus] = []
    now = datetime.now(timezone.utc)

    # Determine storage backend so we only report OpenSearch services when
    # they are actually configured. This avoids showing them as
    # "unavailable" in purely local setups.
    try:
        settings = get_settings()
        storage_backend = settings.storage.backend
    except Exception:  # pragma: no cover - defensive
        storage_backend = "local"

    if resolved.mode == "docker":
        mode_details = {
            "compose_file": resolved.config.get("compose_file", "docker-compose.yml"),
            "service": resolved.config.get("service", "knowledgebase-api"),
            "port": int(resolved.config.get("port", 8000)),
        }
    elif resolved.mode == "local":
        mode_details = {
            "host": resolved.config.get("host", "0.0.0.0"),  # nosec B104 - API server binding
            "port": int(resolved.config.get("port", 8000)),
            "reload": bool(resolved.config.get("reload", False)),
        }

    # API service – if this code is executing, the API itself is up.
    services.append(
        ServiceStatus(
            name="knowledgebase-api",
            kind="api",
            health="healthy",
            url=_DEFAULT_API_BASE_URL,
            message="API process is running (status generated from within the service)",
            last_checked=now,
        )
    )

    # Optional OpenSearch services as defined in docker-compose.yml. Only
    # report them when the storage backend is configured to use OpenSearch so
    # that local-only deployments do not see them as "unavailable".
    if storage_backend == "opensearch":
        # Probe their HTTP endpoints with a small timeout so this remains
        # cheap and safe even when services are not running.
        opensearch_url = "http://localhost:9200"
        os_health, os_message = _probe_http_service(opensearch_url, keyword="cluster_name")
        services.append(
            ServiceStatus(
                name="opensearch",
                kind="search",
                health=os_health,
                url=opensearch_url,
                message=os_message,
                last_checked=now,
            )
        )

        dashboards_url = "http://localhost:5601"
        dash_health, dash_message = _probe_http_service(dashboards_url)
        services.append(
            ServiceStatus(
                name="opensearch-dashboards",
                kind="dashboards",
                health=dash_health,
                url=dashboards_url,
                message=dash_message,
                last_checked=now,
            )
        )

    mode = RuntimeMode(name=resolved.mode, source=resolved.source, details=mode_details)

    return RuntimeStatusResponse(
        mode=mode,
        api_base_url=_DEFAULT_API_BASE_URL,
        services=services,
        version=__version__,
    )
