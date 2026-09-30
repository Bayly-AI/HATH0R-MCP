"""
Feature flag helpers backed by OpenFeature with env fallback.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)
_openfeature_api: Any = None

try:
    from openfeature import api as _loaded_openfeature_api

    _openfeature_api = _loaded_openfeature_api
except Exception:  # pragma: no cover - defensive import fallback
    pass

openfeature_api = _openfeature_api


def _flag_env_keys(flag_key: str) -> list[str]:
    normalized = flag_key.upper().replace(".", "_").replace("-", "_")
    return [
        f"KB_FEATURE_FLAGS__{normalized}",
        f"KB_FEATURE_FLAG_{normalized}",
        normalized,
    ]


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def is_feature_enabled(
    flag_key: str,
    *,
    default: bool = False,
    evaluation_context: dict[str, Any] | None = None,
) -> bool:
    """Return True when a feature flag is enabled."""
    for env_key in _flag_env_keys(flag_key):
        if env_key in os.environ:
            return _parse_bool(os.getenv(env_key), default=default)
    if openfeature_api is not None:
        try:
            client = openfeature_api.get_client()
            return bool(
                client.get_boolean_value(
                    flag_key=flag_key,
                    default_value=default,
                    evaluation_context=evaluation_context,
                )
            )
        except Exception as e:  # pragma: no cover - falls back to env parsing
            logger.debug(
                "OpenFeature evaluation failed; using env fallback", flag_key=flag_key, error=str(e)
            )

    return default
