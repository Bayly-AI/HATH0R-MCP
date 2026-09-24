"""Archive exclusion policy for AegisCMCP default search (Phase 4).

Default (unscoped) search must not walk archive-polluted indices or return
documents whose metadata/id/path identify them as archive or mirror content.
Callers may opt in with ``include_archive=true``.
"""

from __future__ import annotations

from typing import Any

# Phase 1 / Phase 4 domain taxonomy — owned, default-searchable indices.
DOMAIN_INDICES: frozenset[str] = frozenset(
    {
        "knowledge",
        "lessons-learned",
        "runbooks",
        "workflows",
        "plans",
        "rules",
        "playbooks",
        "checklists",
        "procedures",
        "strategies",
    }
)

# Indices that may exist on disk but must never join unscoped default search.
DEFAULT_EXCLUDED_INDICES: frozenset[str] = frozenset(
    {
        "reference",
        "archive",
        "archive-knowledge",
        "knowledge-archive",
        "legacy",
        "local-sync",
    }
)

_ARCHIVE_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "archive",
        "archived",
        "mirror",
        "legacy-archive",
        "knowledge-archive",
    }
)

_ARCHIVE_OWNERSHIP: frozenset[str] = frozenset(
    {
        "archive",
        "archived",
        "mirror",
        "mirrored",
        "legacy",
    }
)

_ARCHIVE_PATH_MARKERS: tuple[str, ...] = (
    "knowledge-archive",
    "/archive/",
    "\\archive\\",
    "local-sync/archived",
    "local-sync\\archived",
    "source_type=archive",
)

_ARCHIVE_ID_PREFIXES: tuple[str, ...] = (
    "archive__",
    "archive-",
    "archived__",
    "mirror__",
)


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def is_archive_source_type(source_type: Any) -> bool:
    """Return True when source_type marks archive/mirror content."""
    return _norm(source_type) in _ARCHIVE_SOURCE_TYPES


def is_archive_ownership(ownership: Any) -> bool:
    """Return True when ownership marks archive/mirror content."""
    return _norm(ownership) in _ARCHIVE_OWNERSHIP


def is_archive_path(path: Any) -> bool:
    """Return True when a filesystem/URI path looks like archive content."""
    text = _norm(path)
    if not text:
        return False
    return any(marker in text for marker in _ARCHIVE_PATH_MARKERS)


def is_archive_document_id(doc_id: Any) -> bool:
    """Return True when a document id uses the archive chunk naming convention."""
    text = _norm(doc_id)
    if not text:
        return False
    return any(text.startswith(prefix) for prefix in _ARCHIVE_ID_PREFIXES)


def metadata_indicates_archive(
    metadata: dict[str, Any] | None, *, doc_id: str | None = None
) -> bool:
    """Inspect document metadata (and optional id) for archive signals."""
    if doc_id and is_archive_document_id(doc_id):
        return True
    if not metadata:
        return False

    if is_archive_source_type(metadata.get("source_type")):
        return True
    if is_archive_ownership(metadata.get("ownership")):
        return True
    if is_archive_path(metadata.get("path")):
        return True

    extra = metadata.get("extra")
    if isinstance(extra, dict):
        if is_archive_source_type(extra.get("source_type")):
            return True
        if is_archive_ownership(extra.get("ownership")):
            return True
        if is_archive_path(extra.get("path")) or is_archive_path(extra.get("source_path")):
            return True

    # Flat extra keys sometimes land at top level via ConfigDict(extra="allow").
    for key in ("ownership", "lifecycle_state", "origin"):
        value = _norm(metadata.get(key))
        if value in _ARCHIVE_OWNERSHIP or value == "archive":
            return True

    return False


def is_excluded_default_index(index_name: str | None) -> bool:
    """Return True for index names that must not join unscoped default search."""
    name = _norm(index_name)
    if not name:
        return False
    if name in {_norm(x) for x in DEFAULT_EXCLUDED_INDICES}:
        return True
    if name.startswith("archive") or name.endswith("-archive"):
        return True
    return False


def default_search_indices_from_config(config: dict[str, Any] | None) -> list[str]:
    """Resolve the configured default-search allowlist.

    Preference order:
    1. ``search.default_indices`` / ``default_search_indices`` explicit list
    2. Configured ``indices[].name`` entries whose taxonomy lifecycle is active
       and name is not archive-excluded
    3. Built-in ``DOMAIN_INDICES``
    """
    cfg = config if isinstance(config, dict) else {}

    explicit = cfg.get("default_search_indices")
    if explicit is None and isinstance(cfg.get("search"), dict):
        explicit = cfg["search"].get("default_indices")

    if isinstance(explicit, list) and explicit:
        resolved: list[str] = []
        for item in explicit:
            if not isinstance(item, str):
                continue
            name = item.strip()
            if name and not is_excluded_default_index(name) and name not in resolved:
                resolved.append(name)
        if resolved:
            return resolved

    raw_indices = cfg.get("indices", [])
    if isinstance(raw_indices, list):
        from_config: list[str] = []
        for entry in raw_indices:
            if not isinstance(entry, dict):
                continue
            name_raw = entry.get("name")
            if not isinstance(name_raw, str) or not name_raw.strip():
                continue
            name = name_raw.strip()
            if is_excluded_default_index(name):
                continue
            taxonomy_raw = entry.get("taxonomy")
            taxonomy: dict[str, Any] = taxonomy_raw if isinstance(taxonomy_raw, dict) else {}
            lifecycle_raw = entry.get("lifecycle_state")
            if lifecycle_raw is None:
                lifecycle_raw = taxonomy.get("lifecycle_state")
            lifecycle = _norm(lifecycle_raw or "active")
            if lifecycle in {"archived", "archive", "legacy", "mirror"}:
                continue
            if name not in from_config:
                from_config.append(name)
        if from_config:
            return from_config

    return sorted(DOMAIN_INDICES)


def should_exclude_archive_document(
    *,
    metadata: dict[str, Any] | None,
    doc_id: str | None = None,
    include_archive: bool = False,
) -> bool:
    """Return True when a document should be filtered out of default search."""
    if include_archive:
        return False
    return metadata_indicates_archive(metadata, doc_id=doc_id)


def apply_default_archive_filters(
    filters: dict[str, Any] | None,
    *,
    include_archive: bool = False,
) -> dict[str, Any] | None:
    """Merge soft archive-exclusion hints into metadata filters.

    Local storage also applies ``should_exclude_archive_document`` for path/id
    patterns that simple equality filters cannot express. OpenSearch benefits
    from the explicit ``source_type`` / ownership denylist when fields exist.
    """
    if include_archive:
        return filters

    merged: dict[str, Any] = dict(filters or {})
    # Do not overwrite an explicit caller filter on these keys.
    merged.setdefault("_exclude_archive", True)
    return merged
