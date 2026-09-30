"""
Sync service for KnowledgeBase Engine.

Syncs the local canonical knowledgebase content (``knowledgebase/canonical/*``,
configured in ``cfg/knowledgebase.json``) either into this AegisCMCP instance's own
storage (``local``) or by pushing it to another AegisCMCP instance over that
instance's own REST API (``dev``). Self-contained: no dependency on any other
InfraSuite repo.
"""

from __future__ import annotations
import json

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import httpx
import structlog

from knowledgebase.core.config import Settings, get_settings
from knowledgebase.indexing.chunker import DocumentChunker, create_chunker
from knowledgebase.indexing.pipeline import IndexingPipeline

logger = structlog.get_logger(__name__)


class SyncTarget(str, Enum):
    """Sync destination for knowledgebase content."""

    LOCAL = "local"
    DEV = "dev"


@dataclass
class SyncFileError:
    """A single file/chunk that failed to sync."""

    path: str
    message: str


@dataclass
class SyncIndexResult:
    """Result of syncing one configured index."""

    index: str
    sync_source: str
    files_discovered: int = 0
    documents_synced: int = 0
    errors: list[SyncFileError] = field(default_factory=list)


@dataclass
class SyncReport:
    """Overall result of a sync run across one or more indices."""

    target: str
    indices_processed: int = 0
    indices_synced: int = 0
    files_discovered: int = 0
    documents_synced: int = 0
    index_results: list[SyncIndexResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to a plain dict (for MCP tool/JSON responses)."""
        return {
            "target": self.target,
            "indices_processed": self.indices_processed,
            "indices_synced": self.indices_synced,
            "files_discovered": self.files_discovered,
            "documents_synced": self.documents_synced,
            "index_results": [
                {
                    "index": r.index,
                    "sync_source": r.sync_source,
                    "files_discovered": r.files_discovered,
                    "documents_synced": r.documents_synced,
                    "errors": [f"{e.path}: {e.message}" for e in r.errors],
                }
                for r in self.index_results
            ],
            "errors": list(self.errors),
        }


@dataclass
class _IndexPlan:
    """Resolved configuration for a single index to sync."""

    index_name: str
    index_config_name: str
    sync_source: Path
    patterns: list[str]
    exclude_patterns: list[str]
    tags: list[str]
    taxonomy: dict[str, str]


def _coerce_string_list(value: Any) -> list[str]:
    """Coerce an arbitrary value into a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _get_index_aliases(config: dict[str, Any]) -> dict[str, str]:
    """Extract a normalized alias map from configuration."""
    raw_aliases = config.get("aliases", {})
    if not isinstance(raw_aliases, dict):
        return {}
    aliases: dict[str, str] = {}
    for raw_key, raw_value in raw_aliases.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            continue
        key = raw_key.strip()
        value = raw_value.strip()
        if key and value:
            aliases[key] = value
    return aliases


def _resolve_index_alias(index_name: str | None, aliases: dict[str, str]) -> str | None:
    """Resolve an index name through aliases until stable."""
    if not isinstance(index_name, str):
        return None
    resolved = index_name.strip()
    if not resolved:
        return None
    visited: set[str] = set()
    while resolved in aliases and resolved not in visited:
        visited.add(resolved)
        next_name = aliases.get(resolved)
        if not isinstance(next_name, str) or not next_name.strip():
            break
        resolved = next_name.strip()
    return resolved


def _extract_index_taxonomy(entry: dict[str, Any]) -> dict[str, str]:
    """Extract taxonomy metadata from an index config entry."""
    taxonomy_raw = entry.get("taxonomy", {})
    taxonomy = taxonomy_raw if isinstance(taxonomy_raw, dict) else {}
    top_group = entry.get("top_group", taxonomy.get("top_group", ""))
    domain = entry.get("domain", taxonomy.get("domain", ""))
    subgroup = entry.get("subgroup", taxonomy.get("subgroup", ""))
    lifecycle_state = entry.get("lifecycle_state", taxonomy.get("lifecycle_state", "active"))
    lifecycle_state_str = str(lifecycle_state).strip() if lifecycle_state is not None else ""
    return {
        "top_group": str(top_group).strip(),
        "domain": str(domain).strip(),
        "subgroup": str(subgroup).strip(),
        "lifecycle_state": lifecycle_state_str or "active",
    }


def _build_exclude_patterns(config: dict[str, Any], entry: dict[str, Any]) -> list[str]:
    """Build effective exclude patterns from global + per-index config."""
    sync_defaults = config.get("sync_defaults", {})
    global_excludes = (
        _coerce_string_list(sync_defaults.get("global_excludes", []))
        if isinstance(sync_defaults, dict)
        else []
    )
    entry_excludes = _coerce_string_list(entry.get("exclude_patterns", []))
    if not entry_excludes:
        entry_excludes = _coerce_string_list(entry.get("excludes", []))
    patterns: list[str] = []
    for pattern in [*global_excludes, *entry_excludes]:
        if pattern not in patterns:
            patterns.append(pattern)
    return patterns


def _should_skip_file(file_path: Path, sync_source: Path, exclude_patterns: list[str]) -> bool:
    """Evaluate whether a sync candidate should be excluded."""
    resolved = file_path.resolve()
    try:
        rel_path = str(resolved.relative_to(sync_source.resolve())).replace("\\", "/")
    except ValueError:
        rel_path = str(resolved).replace("\\", "/")
    abs_path = str(resolved).replace("\\", "/")
    for pattern in exclude_patterns:
        normalized = pattern.replace("\\", "/")
        if fnmatch(rel_path, normalized) or fnmatch(abs_path, normalized):
            return True
    return False


def _read_text(path: Path) -> str:
    """Read file content using utf-8 with a permissive fallback."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_bytes().decode("utf-8", errors="ignore")


def _build_doc_id(index_name: str, file_path: Path, root: Path) -> str:
    """Build a deterministic document id for a synced file."""
    try:
        rel_path = file_path.relative_to(root)
    except ValueError:
        rel_path = Path(file_path.name)
    normalized = str(rel_path).replace("\\", "/").replace("/", "__").replace(" ", "_")
    return f"{index_name}__{normalized}"


def load_sync_targets(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Load configured remote sync targets from ``cfg/sync.json``."""
    settings = settings or get_settings()
    try:
        config = settings.load_config_file("sync.json")
    except FileNotFoundError:
        return {}
    targets = config.get("targets", {})
    return targets if isinstance(targets, dict) else {}


class AegisCMCPSyncService:
    """
    Syncs local canonical knowledgebase content to this AegisCMCP instance's own
    storage (``local``) or to another AegisCMCP instance over its own REST API
    (``dev``).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        pipeline: IndexingPipeline | None = None,
        chunker: DocumentChunker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.pipeline = pipeline
        self.chunker = chunker or create_chunker()

    async def _ensure_pipeline(self) -> IndexingPipeline:
        """Return the configured pipeline, lazily creating a default one."""
        if self.pipeline is None:
            from knowledgebase.indexing.pipeline import create_pipeline

            self.pipeline = await create_pipeline()
        return self.pipeline

    def _load_config(self) -> dict[str, Any]:
        try:
            config = self.settings.load_config_file("knowledgebase.json")
            return config if isinstance(config, dict) else {}
        except Exception:
            return {}

    def _persist_sync_status(
        self,
        *,
        report: SyncReport,
        completed_at: datetime,
        duration_seconds: float,
    ) -> None:
        """Persist latest sync metadata for status reporting."""
        payload = {
            "last_sync": completed_at.isoformat(),
            "last_sync_time": completed_at.isoformat(),
            "sync_duration_seconds": round(duration_seconds, 3),
            "indices_synced": report.indices_synced,
            "documents_synced": report.documents_synced,
            "sync_errors": list(report.errors),
        }
        status_paths: list[Path] = []
        config_dir = getattr(self.settings, "config_dir", None)
        data_dir = getattr(self.settings, "data_dir", None)
        if isinstance(config_dir, Path):
            status_paths.append(config_dir / "status.json")
        if isinstance(data_dir, Path):
            status_paths.append(data_dir / "status.json")
        if not status_paths:
            logger.debug("sync_status_persist_skipped_missing_settings_paths")
            return
        seen_paths: set[str] = set()
        unique_status_paths: list[Path] = []
        for path in status_paths:
            path_key = str(path)
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            unique_status_paths.append(path)
        errors: dict[str, str] = {}
        written_paths: list[str] = []
        for status_path in unique_status_paths:
            try:
                status_path.parent.mkdir(parents=True, exist_ok=True)
                status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                written_paths.append(str(status_path))
            except Exception as exc:
                errors[str(status_path)] = str(exc)
        if not written_paths:
            logger.warning("sync_status_persist_failed", errors=errors)
            return
        if errors:
            logger.warning(
                "sync_status_persist_partial",
                written_paths=written_paths,
                errors=errors,
            )

    def _resolve_plans(self, config: dict[str, Any], indices: list[str] | None) -> list[_IndexPlan]:
        raw_indices = config.get("indices", [])
        if not isinstance(raw_indices, list):
            return []
        aliases = _get_index_aliases(config)
        wanted = {name.strip() for name in indices} if indices else None

        plans: list[_IndexPlan] = []
        for raw_entry in raw_indices:
            if not isinstance(raw_entry, dict):
                continue
            index_name_raw = raw_entry.get("name")
            if not isinstance(index_name_raw, str) or not index_name_raw.strip():
                continue
            index_config_name = index_name_raw.strip()
            if wanted is not None and index_config_name not in wanted:
                continue
            index_name = _resolve_index_alias(index_config_name, aliases)
            if not index_name:
                continue

            sync_source_raw = raw_entry.get("sync_source", "")
            if not isinstance(sync_source_raw, str) or not sync_source_raw.strip():
                continue
            sync_source = Path(sync_source_raw).expanduser()
            if not sync_source.is_absolute():
                sync_source = (Path.cwd() / sync_source).resolve()

            raw_patterns = raw_entry.get("file_patterns", ["*.md"])
            patterns = (
                [p for p in raw_patterns if isinstance(p, str) and p.strip()]
                if isinstance(raw_patterns, list)
                else ["*.md"]
            ) or ["*.md"]

            plans.append(
                _IndexPlan(
                    index_name=index_name,
                    index_config_name=index_config_name,
                    sync_source=sync_source,
                    patterns=patterns,
                    exclude_patterns=_build_exclude_patterns(config, raw_entry),
                    tags=_coerce_string_list(raw_entry.get("tags", [])),
                    taxonomy=_extract_index_taxonomy(raw_entry),
                )
            )
        return plans

    def discover_files(self, plan: _IndexPlan) -> list[Path]:
        """Discover matching, non-excluded files for one resolved index plan."""
        if not plan.sync_source.exists():
            return []
        files: set[Path] = set()
        for pattern in plan.patterns:
            files.update(
                path
                for path in plan.sync_source.rglob(pattern)
                if path.is_file()
                and not _should_skip_file(path, plan.sync_source, plan.exclude_patterns)
            )
        return sorted(files)

    async def sync_local(self, indices: list[str] | None = None) -> SyncReport:
        """Sync configured indices from local files into this instance's own storage."""
        started_at = datetime.now(timezone.utc)
        pipeline = await self._ensure_pipeline()
        config = self._load_config()
        plans = self._resolve_plans(config, indices)
        report = SyncReport(target=SyncTarget.LOCAL.value)

        existing_indices = {idx.name for idx in await pipeline.storage.list_indices()}

        for plan in plans:
            if plan.index_name not in existing_indices:
                await pipeline.storage.create_index(plan.index_name)
                existing_indices.add(plan.index_name)

            index_result = SyncIndexResult(index=plan.index_name, sync_source=str(plan.sync_source))

            if not plan.sync_source.exists():
                message = (
                    f"Sync source does not exist for index '{plan.index_name}': {plan.sync_source}"
                )
                index_result.errors.append(
                    SyncFileError(path=str(plan.sync_source), message=message)
                )
                report.errors.append(message)
                report.index_results.append(index_result)
                report.indices_processed += 1
                continue

            files = self.discover_files(plan)
            index_result.files_discovered = len(files)
            report.files_discovered += len(files)

            for file_path in files:
                try:
                    documents = await pipeline.index_file(
                        file_path=file_path,
                        index_name=plan.index_name,
                        doc_id=_build_doc_id(plan.index_name, file_path, plan.sync_source),
                        metadata={
                            "path": str(file_path),
                            "title": file_path.name,
                            "source_type": "file",
                            "tags": plan.tags,
                            "extra": {
                                "index_config_name": plan.index_config_name,
                                **plan.taxonomy,
                            },
                        },
                    )
                    index_result.documents_synced += len(documents)
                    report.documents_synced += len(documents)
                except Exception as exc:
                    message = f"{file_path}: {exc}"
                    index_result.errors.append(SyncFileError(path=str(file_path), message=str(exc)))
                    report.errors.append(message)

            if index_result.documents_synced > 0:
                report.indices_synced += 1
            report.index_results.append(index_result)
            report.indices_processed += 1
        completed_at = datetime.now(timezone.utc)
        self._persist_sync_status(
            report=report,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
        )

        return report

    async def sync_dev(
        self,
        base_url: str,
        api_key: str | None = None,
        indices: list[str] | None = None,
    ) -> SyncReport:
        """Chunk local files and push them to another AegisCMCP instance's REST API.

        Content is chunked locally (so a single large file never hits the
        remote instance's own truncate-by-character-count fallback) but never
        embedded locally -- the remote instance embeds with its own configured
        provider/model.
        """
        started_at = datetime.now(timezone.utc)
        config = self._load_config()
        plans = self._resolve_plans(config, indices)
        report = SyncReport(target=SyncTarget.DEV.value)

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        url = base_url.rstrip("/") + "/api/v1/documents"

        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            for plan in plans:
                index_result = SyncIndexResult(
                    index=plan.index_name, sync_source=str(plan.sync_source)
                )

                if not plan.sync_source.exists():
                    message = (
                        f"Sync source does not exist for index '{plan.index_name}': "
                        f"{plan.sync_source}"
                    )
                    index_result.errors.append(
                        SyncFileError(path=str(plan.sync_source), message=message)
                    )
                    report.errors.append(message)
                    report.index_results.append(index_result)
                    report.indices_processed += 1
                    continue

                files = self.discover_files(plan)
                index_result.files_discovered = len(files)
                report.files_discovered += len(files)

                for file_path in files:
                    content = _read_text(file_path)
                    if not content.strip():
                        continue

                    doc_id = _build_doc_id(plan.index_name, file_path, plan.sync_source)
                    chunks = self.chunker.chunk_text(content)
                    total_chunks = len(chunks)

                    for chunk in chunks:
                        chunk_id = doc_id if total_chunks == 1 else f"{doc_id}-chunk-{chunk.index}"
                        payload = {
                            "id": chunk_id,
                            "content": chunk.text,
                            "index_name": plan.index_name,
                            "metadata": {
                                "path": str(file_path),
                                "title": file_path.name,
                                "source_type": "file",
                                "tags": plan.tags,
                                "extra": {
                                    "index_config_name": plan.index_config_name,
                                    "parent_doc_id": doc_id,
                                    "chunk_index": chunk.index,
                                    "total_chunks": total_chunks,
                                    **plan.taxonomy,
                                },
                            },
                        }
                        try:
                            response = await client.post(url, json=payload)
                            response.raise_for_status()
                            index_result.documents_synced += 1
                            report.documents_synced += 1
                        except Exception as exc:
                            message = f"{file_path} (chunk {chunk.index}): {exc}"
                            index_result.errors.append(
                                SyncFileError(path=str(file_path), message=str(exc))
                            )
                            report.errors.append(message)

                if index_result.documents_synced > 0:
                    report.indices_synced += 1
                report.index_results.append(index_result)
                report.indices_processed += 1
        completed_at = datetime.now(timezone.utc)
        self._persist_sync_status(
            report=report,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
        )

        return report

    async def health(self, target: SyncTarget, base_url: str | None = None) -> dict[str, Any]:
        """Check reachability/health of a sync target."""
        if target == SyncTarget.LOCAL:
            pipeline = await self._ensure_pipeline()
            storage_health = await pipeline.storage.health_check()
            embeddings_health = await pipeline.embeddings.health_check()
            return {"storage": storage_health, "embeddings": embeddings_health}

        if not base_url:
            return {"healthy": False, "error": "No base_url configured for target"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(base_url.rstrip("/") + "/health")
                response.raise_for_status()
                return {"healthy": True, "status_code": response.status_code}
        except Exception as exc:
            return {"healthy": False, "error": str(exc)}
