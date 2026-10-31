"""
Feature flag helpers backed by OpenFeature with catalog and env fallback.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
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


@lru_cache(maxsize=1)
def get_catalog_flag_defaults() -> dict[str, bool]:
    """Load boolean defaults declared in cfg/feature-flags/catalog.example.json."""
    catalog_path = Path(__file__).resolve().parents[3] / "cfg" / "feature-flags" / "catalog.example.json"
    if not catalog_path.is_file():
        return {}
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        flags = raw.get("flags", [])
        return {
            str(entry["key"]): bool(entry.get("default", False))
            for entry in flags
            if isinstance(entry, dict) and "key" in entry and entry.get("type") == "boolean"
        }
    except Exception:  # pragma: no cover
        return {}


def _flag_env_keys(flag_key: str) -> list[str]:
    normalized = flag_key.upper().replace(".", "_").replace("-", "_")
    return [
        f"KB_FEATURE_FLAGS__{normalized}",
        f"KB_FEATURE_FLAG_{normalized}",
        f"HATH0R_FLAG_{normalized}",
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


def evaluate_feature_flags_snapshot(
    keys: tuple[str, ...] = (
        "mcp.supersqueeze.enabled",
        "mcp.pbac.enforce",
        "mcp.l2_sanitizer.enforce",
        "workflow.first.strict_offer",
        "feature.service_bot.enforce",
        "cccd.auto_calibrate.pre_task_enabled",
    ),
) -> dict[str, bool]:
    """Evaluate a canonical snapshot of OpenFeature flags using catalog defaults and env overrides."""
    catalog_defaults = get_catalog_flag_defaults()
    return {
        key: is_feature_enabled(key, default=catalog_defaults.get(key, True))
        for key in keys
    }
