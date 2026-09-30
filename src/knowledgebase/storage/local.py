"""
Local file-based storage backend.

Provides a simple file-based vector storage for development and testing.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

import structlog
from knowledgebase.core.feature_flags import is_feature_enabled

from knowledgebase.core.models import (
    Document,
    DocumentMetadata,
    IndexInfo,
    SearchResult,
)
from knowledgebase.core.observability import timed_operation
from knowledgebase.storage.base import StorageBackend, StorageError

logger = structlog.get_logger(__name__)

JSON_FILE_GLOB = "*.json"
JSON_FILE_GLOB_RECURSIVE = "**/*.json"  # For nested doc IDs with '/'

# Avoid re-globbing multi-million-file index trees on every stats/list call.
_INDEX_STATS_CACHE_TTL_SECONDS = float(os.getenv("KB_INDEX_STATS_CACHE_TTL_SECONDS", "300"))
_STORAGE_SIZE_CACHE_TTL_SECONDS = float(os.getenv("KB_STORAGE_SIZE_CACHE_TTL_SECONDS", "600"))


@dataclass
class _IndexStatsCacheEntry:
    document_count: int
    description: str
    sync_source: str | None
    metadata_schema: dict[str, str]
    counted_at: float


@dataclass
class _CachedDocumentRef:
    doc_id: str
    index_name: str
    metadata: dict[str, Any]
    file_path: Path
    chunk_index: int
    total_chunks: int


@dataclass
class _IndexVectorCache:
    directory_mtime: float
    doc_refs: list[_CachedDocumentRef]
    embedding_matrix: np.ndarray


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        float: Cosine similarity (-1 to 1, higher is more similar).
    """
    if len(a) != len(b):
        raise ValueError(f"Vector dimensions must match: {len(a)} vs {len(b)}")

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


class LocalStorageBackend(StorageBackend):
    """
    Local file-based storage backend.

    Stores documents as JSON files in a directory structure:
    - {base_path}/{index_name}/documents/{doc_id}.json
    - {base_path}/{index_name}/metadata.json

    Suitable for development and small-scale deployments.
    """

    def __init__(self, base_path: str = "./.infraOS/storage/indices") -> None:
        """
        Initialize the local storage backend.

        Args:
            base_path: Base directory for storing indices.
        """
        self._base_path = self._resolve_base_path(base_path)
        self._initialized = False
        self._vector_cache: dict[str, _IndexVectorCache] = {}
        self._index_stats_cache: dict[str, _IndexStatsCacheEntry] = {}
        self._storage_size_cache_bytes: int | None = None
        self._storage_size_cache_at: float = 0.0

        logger.info("Initialized local storage backend", base_path=str(self._base_path))

    def _resolve_base_path(self, base_path: str) -> Path:
        """Resolve storage path with explicit KB_STORAGE__LOCAL_PATH override."""
        override_path = os.getenv("KB_STORAGE__LOCAL_PATH")
        candidate = Path(override_path if override_path else base_path).expanduser()
        if not candidate.is_absolute():
            workspace_root = os.getenv("KB_WORKSPACE_ROOT")
            base_root = Path(workspace_root).expanduser() if workspace_root else Path.cwd()
            candidate = (base_root / candidate).resolve()
        return candidate

    async def initialize(self) -> None:
        """Initialize the storage backend by creating the base directory."""
        try:
            self._base_path.mkdir(parents=True, exist_ok=True)
            self._initialized = True
            logger.info("Local storage initialized", path=str(self._base_path))
        except Exception as e:
            raise StorageError(
                message=f"Failed to initialize local storage: {e}",
                backend="local",
                operation="initialize",
                original_error=e,
            ) from e

    async def close(self) -> None:
        """Close the storage backend (no-op for local storage)."""
        self._initialized = False
        logger.info("Local storage closed")

    def _get_index_path(self, index_name: str) -> Path:
        """Get the path to an index directory."""
        return self._base_path / index_name

    def _get_documents_path(self, index_name: str) -> Path:
        """Get the path to the documents directory for an index."""
        return self._get_index_path(index_name) / "documents"

    def _get_metadata_path(self, index_name: str) -> Path:
        """Get the path to the index metadata file."""
        return self._get_index_path(index_name) / "metadata.json"

    @property
    def base_path(self) -> Path:
        """Resolved on-disk root for local indices."""
        return self._base_path

    def _invalidate_index_stats(self, index_name: str | None = None) -> None:
        """Drop cached index document counts and storage size."""
        if index_name is None:
            self._index_stats_cache.clear()
        else:
            self._index_stats_cache.pop(index_name, None)
        self._storage_size_cache_bytes = None
        self._storage_size_cache_at = 0.0

    def _count_documents_sync(self, docs_path: Path) -> int:
        """Count JSON documents recursively (handles nested doc IDs with '/')."""
        if not docs_path.exists():
            return 0
        count = 0
        for _dirpath, _dirnames, filenames in os.walk(docs_path):
            for name in filenames:
                if name.endswith(".json"):
                    count += 1
        return count

    def _load_index_stats_sync(self, index_dir: Path) -> _IndexStatsCacheEntry | None:
        """Load metadata + document count for one index directory."""
        metadata_path = index_dir / "metadata.json"
        if not metadata_path.exists():
            return None
        metadata = self._read_json_file(metadata_path)
        docs_path = index_dir / "documents"
        return _IndexStatsCacheEntry(
            document_count=self._count_documents_sync(docs_path),
            description=str(metadata.get("description", "") or ""),
            sync_source=metadata.get("sync_source"),
            metadata_schema=metadata.get("metadata_schema", {}) or {},
            counted_at=time.time(),
        )

    def _directory_size_bytes_sync(self, root: Path) -> int:
        """Measure directory size; prefer ``du`` then fall back to a walk."""
        if not root.exists():
            return 0
        try:
            completed = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
                ["du", "-sk", str(root)],
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                kb_token = completed.stdout.split()[0]
                return int(kb_token) * 1024
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            logger.debug("du size probe failed; walking tree", path=str(root), error=str(exc))

        total = 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                try:
                    total += (Path(dirpath) / name).stat().st_size
                except OSError:
                    continue
        return total

    async def get_storage_usage_bytes(self, *, force_refresh: bool = False) -> int:
        """Return cached on-disk byte size of the local indices tree."""
        now = time.time()
        if (
            not force_refresh
            and self._storage_size_cache_bytes is not None
            and (now - self._storage_size_cache_at) < _STORAGE_SIZE_CACHE_TTL_SECONDS
        ):
            return self._storage_size_cache_bytes

        size_bytes = await asyncio.to_thread(self._directory_size_bytes_sync, self._base_path)
        self._storage_size_cache_bytes = size_bytes
        self._storage_size_cache_at = now
        return size_bytes

    # --- Sync I/O helpers (for use with asyncio.to_thread) ---

    def _write_json_file(self, file_path: Path, data: dict[str, Any]) -> None:
        """Write JSON data to a file (sync, thread-safe via asyncio.to_thread)."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _read_json_file(self, file_path: Path) -> dict[str, Any]:
        """Read JSON data from a file (sync, thread-safe via asyncio.to_thread)."""
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]

    # --- End sync I/O helpers ---

    async def create_index(self, name: str, metadata_schema: dict[str, str] | None = None) -> None:
        """Create a new index directory structure."""
        try:
            index_path = self._get_index_path(name)
            docs_path = self._get_documents_path(name)
            docs_path.mkdir(parents=True, exist_ok=True)

            # Save index metadata
            metadata = {
                "name": name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata_schema": metadata_schema or {},
            }
            metadata_path = self._get_metadata_path(name)
            await asyncio.to_thread(self._write_json_file, metadata_path, metadata)
            self._invalidate_index_cache(name)
            self._invalidate_index_stats(name)

            logger.info("Created index", index=name, path=str(index_path))

        except Exception as e:
            raise StorageError(
                message=f"Failed to create index: {e}",
                backend="local",
                operation="create_index",
                original_error=e,
            ) from e

    async def delete_index(self, name: str) -> None:
        """Delete an index and all its documents."""
        try:
            import shutil

            index_path = self._get_index_path(name)
            if index_path.exists():
                shutil.rmtree(index_path)
                self._invalidate_index_cache(name)
                self._invalidate_index_stats(name)
                logger.info("Deleted index", index=name)
            else:
                logger.warning("Index not found for deletion", index=name)

        except Exception as e:
            raise StorageError(
                message=f"Failed to delete index: {e}",
                backend="local",
                operation="delete_index",
                original_error=e,
            ) from e

    async def list_indices(self) -> list[IndexInfo]:
        """List all available indices.

        Document counts are TTL-cached. After bulk archive ingest a full
        recount of multi-million JSON trees is expensive enough to make
        ``/api/v1/system/stats`` miss short client timeouts (e.g. compliance).
        """
        try:
            indices: list[IndexInfo] = []

            if not self._base_path.exists():
                return indices

            now = time.time()
            live_names: set[str] = set()

            for item in self._base_path.iterdir():
                if not item.is_dir():
                    continue
                metadata_path = item / "metadata.json"
                if not metadata_path.exists():
                    continue

                index_name = item.name
                live_names.add(index_name)
                cached = self._index_stats_cache.get(index_name)
                if cached is None or (now - cached.counted_at) >= _INDEX_STATS_CACHE_TTL_SECONDS:
                    loaded = await asyncio.to_thread(self._load_index_stats_sync, item)
                    if loaded is None:
                        continue
                    self._index_stats_cache[index_name] = loaded
                    cached = loaded

                indices.append(
                    IndexInfo(
                        name=index_name,
                        description=cached.description,
                        document_count=cached.document_count,
                        sync_source=cached.sync_source,
                        metadata_schema=cached.metadata_schema,
                    )
                )

            # Drop cache entries for indices that no longer exist on disk.
            for stale in list(self._index_stats_cache.keys()):
                if stale not in live_names:
                    self._index_stats_cache.pop(stale, None)

            return indices

        except Exception as e:
            raise StorageError(
                message=f"Failed to list indices: {e}",
                backend="local",
                operation="list_indices",
                original_error=e,
            ) from e

    async def add_document(self, document: Document) -> None:
        """Add or update a document."""
        try:
            # Ensure index exists
            docs_path = self._get_documents_path(document.index_name)
            if not docs_path.exists():
                await self.create_index(document.index_name)
                docs_path = self._get_documents_path(document.index_name)

            # Save document
            # Document IDs may contain '/' (e.g. 'engage360/INDEX.md'), which
            # creates nested paths. Ensure parent directories exist.
            doc_path = docs_path / f"{document.id}.json"
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_data = document.model_dump()
            doc_data["metadata"]["updated_at"] = datetime.now(timezone.utc).isoformat()

            await asyncio.to_thread(self._write_json_file, doc_path, doc_data)
            self._invalidate_index_cache(document.index_name)
            self._invalidate_index_stats(document.index_name)

            logger.debug("Added document", doc_id=document.id, index=document.index_name)

        except Exception as e:
            raise StorageError(
                message=f"Failed to add document: {e}",
                backend="local",
                operation="add_document",
                original_error=e,
            ) from e

    async def add_documents(self, documents: list[Document]) -> None:
        """Add or update multiple documents in bulk."""
        for doc in documents:
            await self.add_document(doc)
        logger.info("Added documents", count=len(documents))

    async def get_document(self, doc_id: str, index_name: str) -> Document | None:
        """Retrieve a document by ID."""
        try:
            doc_path = self._get_documents_path(index_name) / f"{doc_id}.json"
            if not doc_path.exists():
                return None

            data = await asyncio.to_thread(self._read_json_file, doc_path)

            return Document(
                id=data["id"],
                content=data["content"],
                embedding=data.get("embedding"),
                metadata=DocumentMetadata(**data.get("metadata", {})),
                index_name=data.get("index_name", index_name),
                chunk_index=data.get("chunk_index", 0),
                total_chunks=data.get("total_chunks", 1),
            )

        except Exception as e:
            raise StorageError(
                message=f"Failed to get document: {e}",
                backend="local",
                operation="get_document",
                original_error=e,
            ) from e

    async def delete_document(self, doc_id: str, index_name: str) -> bool:
        """Delete a document by ID."""
        try:
            doc_path = self._get_documents_path(index_name) / f"{doc_id}.json"
            if doc_path.exists():
                os.remove(doc_path)
                self._invalidate_index_cache(index_name)
                self._invalidate_index_stats(index_name)
                logger.debug("Deleted document", doc_id=doc_id, index=index_name)
                return True
            return False

        except Exception as e:
            raise StorageError(
                message=f"Failed to delete document: {e}",
                backend="local",
                operation="delete_document",
                original_error=e,
            ) from e

    async def search(
        self,
        query_embedding: list[float],
        index_name: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search for documents similar to the query embedding."""
        if not is_feature_enabled("kb.search.vectorized", default=True):
            return await self._search_legacy(
                query_embedding=query_embedding,
                index_name=index_name,
                limit=limit,
                min_score=min_score,
                filters=filters,
            )
        with timed_operation(
            "knowledgebase.storage.local.search",
            mode="vectorized",
            index_name=index_name,
            limit=limit,
        ):
            return await self._search_vectorized(
                query_embedding=query_embedding,
                index_name=index_name,
                limit=limit,
                min_score=min_score,
                filters=filters,
            )

    async def _search_legacy(
        self,
        query_embedding: list[float],
        index_name: str | None,
        limit: int,
        min_score: float,
        filters: dict[str, Any] | None,
    ) -> list[SearchResult]:
        """Brute-force fallback path for compatibility and safe flag default."""
        try:
            results: list[SearchResult] = []

            # Determine which indices to search (Phase 4 allowlist when unscoped).
            indices = await self._resolve_target_indices(index_name=index_name)

            for idx_name in indices:
                docs_path = self._get_documents_path(idx_name)
                if not docs_path.exists():
                    continue

                # Use recursive glob to handle nested doc IDs with '/'
                for doc_file in docs_path.glob(JSON_FILE_GLOB_RECURSIVE):
                    data = await asyncio.to_thread(self._read_json_file, doc_file)

                    # Skip documents without embeddings
                    if not data.get("embedding"):
                        continue

                    # Apply filters
                    metadata = (
                        data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
                    )
                    if filters:
                        if not self._matches_filters(metadata, filters):
                            continue
                    if self._should_skip_archive_document(
                        metadata=metadata,
                        doc_id=str(data.get("id", "")),
                        filters=filters,
                    ):
                        continue

                    # Calculate similarity
                    score = cosine_similarity(query_embedding, data["embedding"])

                    # Normalize to 0-1 range
                    normalized_score = (score + 1) / 2

                    if normalized_score >= min_score:
                        doc = Document(
                            id=data["id"],
                            content=data["content"],
                            embedding=None,  # Don't return embeddings by default
                            metadata=DocumentMetadata(**data.get("metadata", {})),
                            index_name=data.get("index_name", idx_name),
                            chunk_index=data.get("chunk_index", 0),
                            total_chunks=data.get("total_chunks", 1),
                        )
                        results.append(
                            SearchResult(
                                document=doc,
                                score=normalized_score,
                                vector_score=normalized_score,
                            )
                        )

            # Sort by score and limit
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:limit]

        except Exception as e:
            raise StorageError(
                message=f"Failed to search: {e}",
                backend="local",
                operation="search",
                original_error=e,
            ) from e

    async def _search_vectorized(
        self,
        query_embedding: list[float],
        index_name: str | None,
        limit: int,
        min_score: float,
        filters: dict[str, Any] | None,
    ) -> list[SearchResult]:
        query_vector = np.asarray(query_embedding, dtype=np.float32)
        if query_vector.size == 0:
            return []
        query_norm = float(np.linalg.norm(query_vector))
        # Use tolerance-based comparison for floating point zero check
        if query_norm < 1e-10:
            return []
        normalized_query = query_vector / query_norm

        candidates: list[tuple[float, _CachedDocumentRef]] = []
        for idx_name in await self._resolve_target_indices(index_name=index_name):
            cache = await asyncio.to_thread(self._get_or_build_index_cache, idx_name)
            if cache is None or cache.embedding_matrix.size == 0:
                continue
            if cache.embedding_matrix.shape[1] != normalized_query.shape[0]:
                raise ValueError(
                    f"Vector dimensions must match: {normalized_query.shape[0]} vs {cache.embedding_matrix.shape[1]}"
                )

            with timed_operation(
                "knowledgebase.storage.local.vector_dot",
                index_name=idx_name,
                doc_count=len(cache.doc_refs),
            ):
                scores = cache.embedding_matrix @ normalized_query

            for row_idx, doc_ref in enumerate(cache.doc_refs):
                if filters and not self._matches_filters(doc_ref.metadata, filters):
                    continue
                if self._should_skip_archive_document(
                    metadata=doc_ref.metadata if isinstance(doc_ref.metadata, dict) else {},
                    doc_id=doc_ref.doc_id,
                    filters=filters,
                ):
                    continue
                normalized_score = (float(scores[row_idx]) + 1.0) / 2.0
                if normalized_score >= min_score:
                    candidates.append((normalized_score, doc_ref))

        candidates.sort(key=lambda x: x[0], reverse=True)
        top_hits = candidates[:limit]
        # Hydrate results in thread pool to avoid blocking async context
        results = []
        for score, doc_ref in top_hits:
            result = await asyncio.to_thread(self._hydrate_search_result, doc_ref, score)
            results.append(result)
        return results

    async def _resolve_target_indices(self, index_name: str | None) -> list[str]:
        if index_name:
            return [index_name]
        # Phase 4 defense-in-depth: never walk every on-disk index for unscoped
        # search. Prefer the configured domain allowlist intersected with live
        # indices so archive dumps cannot hang local vector search.
        from knowledgebase.search.archive_policy import (
            default_search_indices_from_config,
            is_excluded_default_index,
        )

        index_infos = await self.list_indices()
        live = {i.name for i in index_infos}
        try:
            from knowledgebase.core.config import get_settings

            settings = get_settings()
            config = settings.load_config_file("knowledgebase.json")
            if not isinstance(config, dict):
                config = {}
        except Exception:
            config = {}

        allowlist = default_search_indices_from_config(config)
        targets = [
            name for name in allowlist if name in live and not is_excluded_default_index(name)
        ]
        if targets:
            return targets
        # Fallback: live domain-looking indices only (still skip archive names).
        return sorted(name for name in live if not is_excluded_default_index(name))

    def _invalidate_index_cache(self, index_name: str | None = None) -> None:
        if index_name is None:
            self._vector_cache.clear()
            return
        self._vector_cache.pop(index_name, None)

    def _get_or_build_index_cache(self, index_name: str) -> _IndexVectorCache | None:
        docs_path = self._get_documents_path(index_name)
        if not docs_path.exists():
            self._invalidate_index_cache(index_name)
            return None

        directory_mtime = docs_path.stat().st_mtime
        cached = self._vector_cache.get(index_name)
        if cached and cached.directory_mtime >= directory_mtime:
            return cached

        vectors: list[np.ndarray] = []
        doc_refs: list[_CachedDocumentRef] = []
        doc_dimension: int | None = None
        # Use recursive glob to handle nested doc IDs with '/'
        for doc_file in docs_path.glob(JSON_FILE_GLOB_RECURSIVE):
            with open(doc_file) as f:
                data = json.load(f)

            embedding = data.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                continue

            vector = np.asarray(embedding, dtype=np.float32)
            if vector.size == 0:
                continue

            if doc_dimension is None:
                doc_dimension = int(vector.shape[0])
            elif int(vector.shape[0]) != doc_dimension:
                raise ValueError(
                    f"Vector dimensions must match: {vector.shape[0]} vs {doc_dimension}"
                )

            vector_norm = float(np.linalg.norm(vector))
            # Use tolerance-based comparison for floating point zero check
            if vector_norm < 1e-10:
                continue

            vectors.append(vector / vector_norm)
            doc_refs.append(
                _CachedDocumentRef(
                    doc_id=data["id"],
                    index_name=data.get("index_name", index_name),
                    metadata=data.get("metadata", {}),
                    file_path=doc_file,
                    chunk_index=data.get("chunk_index", 0),
                    total_chunks=data.get("total_chunks", 1),
                )
            )

        matrix = (
            np.vstack(vectors).astype(np.float32) if vectors else np.empty((0, 0), dtype=np.float32)
        )
        entry = _IndexVectorCache(
            directory_mtime=directory_mtime,
            doc_refs=doc_refs,
            embedding_matrix=matrix,
        )
        self._vector_cache[index_name] = entry
        return entry

    def _hydrate_search_result(self, doc_ref: _CachedDocumentRef, score: float) -> SearchResult:
        with timed_operation(
            "knowledgebase.storage.local.read_top_hit",
            index_name=doc_ref.index_name,
            doc_id=doc_ref.doc_id,
        ):
            with open(doc_ref.file_path) as f:
                data = json.load(f)

        doc = Document(
            id=data["id"],
            content=data["content"],
            embedding=None,
            metadata=DocumentMetadata(**data.get("metadata", {})),
            index_name=data.get("index_name", doc_ref.index_name),
            chunk_index=data.get("chunk_index", doc_ref.chunk_index),
            total_chunks=data.get("total_chunks", doc_ref.total_chunks),
        )
        return SearchResult(document=doc, score=score, vector_score=score)

    def _matches_filters(self, metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
        """Check if metadata matches all filters.

        Internal Phase 4 keys prefixed with ``_`` (e.g. ``_exclude_archive``)
        are policy hints, not document metadata fields, and are ignored here.
        """
        for key, value in filters.items():
            if key.startswith("_"):
                continue
            if key not in metadata:
                return False
            if isinstance(value, list):
                if metadata[key] not in value:
                    return False
            elif metadata[key] != value:
                return False
        return True

    def _should_skip_archive_document(
        self,
        *,
        metadata: dict[str, Any],
        doc_id: str,
        filters: dict[str, Any] | None,
    ) -> bool:
        """Skip archive/mirror docs unless caller opts in via filters."""
        from knowledgebase.search.archive_policy import should_exclude_archive_document

        include_archive = False
        if isinstance(filters, dict):
            # Opt-in: explicit include flag or absence of exclude hint after
            # apply_default_archive_filters was bypassed by the caller.
            if filters.get("_include_archive") is True:
                include_archive = True
            elif filters.get("_exclude_archive") is False:
                include_archive = True
            elif "_exclude_archive" not in filters and filters.get("include_archive") is True:
                include_archive = True

        return should_exclude_archive_document(
            metadata=metadata,
            doc_id=doc_id,
            include_archive=include_archive,
        )

    async def health_check(self) -> dict[str, Any]:
        """Check the health of the local storage.

        IMPORTANT: do **not** enumerate document JSON files here. After bulk
        archive ingest the local indices tree can contain millions of files
        (tens of GB); ``list_indices()`` globbing every ``*.json`` makes
        ``/health`` hang past Docker healthcheck timeouts and blocks host
        port probes (e.g. localhost:58121).

        Health only verifies path accessibility and counts index directories.
        Document counts are omitted (``document_count=-1``) unless
        ``KB_HEALTH_INCLUDE_DOC_COUNTS=true`` is explicitly set.
        """
        start_time = time.time()
        try:
            # Check if base path is accessible
            exists = self._base_path.exists()
            writable = os.access(self._base_path, os.W_OK) if exists else False

            index_count = 0
            total_docs = -1
            if exists:
                # Fast: only top-level index dirs with metadata.json.
                for item in self._base_path.iterdir():
                    if item.is_dir() and (item / "metadata.json").exists():
                        index_count += 1

                include_docs = os.getenv(
                    "KB_HEALTH_INCLUDE_DOC_COUNTS", "false"
                ).strip().lower() in {"1", "true", "yes", "on"}
                if include_docs:
                    # Expensive path kept for debugging only.
                    indices = await self.list_indices()
                    total_docs = sum(i.document_count for i in indices)
                    index_count = len(indices)

            latency_ms = (time.time() - start_time) * 1000

            return {
                "healthy": exists and writable,
                "backend": "local",
                "path": str(self._base_path),
                "exists": exists,
                "writable": writable,
                "index_count": index_count,
                "document_count": total_docs,
                "document_count_mode": (
                    "full" if total_docs >= 0 else "skipped_for_health_latency"
                ),
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "healthy": False,
                "backend": "local",
                "error": str(e),
                "latency_ms": round(latency_ms, 2),
            }

    async def list_documents(
        self,
        index_name: str,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Document], int]:
        """List documents for an index with offset/limit pagination."""
        try:
            docs_path = self._get_documents_path(index_name)
            if not docs_path.exists():
                return [], 0

            # List all document files and apply a deterministic order so that
            # paging is stable between calls. Use recursive glob to handle
            # nested doc IDs with '/'.
            doc_files = sorted(docs_path.glob(JSON_FILE_GLOB_RECURSIVE))
            total = len(doc_files)
            selected = doc_files[offset : offset + limit]

            documents: list[Document] = []
            for doc_file in selected:
                # A single unreadable/corrupt document file (e.g. an
                # un-hydrated git-lfs pointer stub that was ingested as
                # "content" instead of the real file, or a torn write from a
                # concurrent process) must not abort the entire page --
                # previously any bad file here raised and killed the whole
                # list_documents call, which in turn aborted a full-index
                # reindex partway through (see feedback_mcp_status_check_bugs
                # / project_aegis_cmcp_reindex_in_progress memory). Skip and log
                # instead so pagination can make forward progress.
                try:
                    data = await asyncio.to_thread(self._read_json_file, doc_file)
                    documents.append(
                        Document(
                            id=data["id"],
                            content=data["content"],
                            embedding=data.get("embedding"),
                            metadata=DocumentMetadata(**data.get("metadata", {})),
                            index_name=data.get("index_name", index_name),
                            chunk_index=data.get("chunk_index", 0),
                            total_chunks=data.get("total_chunks", 1),
                        )
                    )
                except Exception as doc_error:
                    logger.warning(
                        "Skipping unreadable document file in list_documents",
                        index=index_name,
                        file=str(doc_file),
                        error=str(doc_error),
                    )
                    continue

            return documents, total

        except Exception as e:
            raise StorageError(
                message=f"Failed to list documents: {e}",
                backend="local",
                operation="list_documents",
                original_error=e,
            ) from e
