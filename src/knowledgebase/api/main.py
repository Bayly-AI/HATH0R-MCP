"""
FastAPI application for KnowledgeBase Engine.

Provides RESTful API endpoints for semantic search and document management.
"""

from __future__ import annotations
import asyncio


import json
import os
import platform
import sys
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from knowledgebase import __version__
from knowledgebase.core.config import get_settings
from knowledgebase.core.feature_flags import is_feature_enabled
from knowledgebase.core.mcp_tools import get_default_mcp_tool_schema
from knowledgebase.core.models import (
    Document,
    DocumentMetadata,
    IndexInfo,
    MCPServerStatus,
    PerformanceMetrics,
    SearchResult,
    ServiceStatus,
    SystemStats,
)
from knowledgebase.core.observability import timed_operation
from knowledgebase.core.runtime_status import RuntimeStatusResponse, get_runtime_status
from knowledgebase.embeddings import (
    EmbeddingProvider,
    get_embedding_provider_with_fallback,
)
from knowledgebase.indexing.pipeline import IndexingPipeline
from knowledgebase.search.archive_policy import (
    apply_default_archive_filters,
    default_search_indices_from_config,
    is_excluded_default_index,
    should_exclude_archive_document,
)
from knowledgebase.search.hybrid_service import HybridSearchService, resolve_search_mode
from knowledgebase.services.base import service_registry
from knowledgebase.services.mcp_service import MCPService
from knowledgebase.services.system_service import SystemMonitoringService
from knowledgebase.storage import get_storage_backend
from knowledgebase.storage.base import StorageBackend
from knowledgebase.sync import AegisCMCPSyncService, load_sync_targets

# Runbook service import (lazy import to avoid circular dependency)
_runbook_module = None

logger = structlog.get_logger(__name__)

# Global instances (initialized on startup)
_storage: StorageBackend | None = None
_hybrid_search: HybridSearchService | None = None
_embeddings: EmbeddingProvider | None = None
_system_service: SystemMonitoringService | None = None
_mcp_service: MCPService | None = None
_runbook_service: Any = None
_TOOLS_CACHE: dict[str, Any] | None = None
_SEARCH_RESULT_CACHE: dict[str, tuple[float, list[SearchResult]]] = {}
_SEARCH_RESULT_CACHE_TTL_SECONDS = int(os.getenv("KB_SEARCH_RESULT_CACHE_TTL_SECONDS", "30"))
_EMBEDDING_CACHE: dict[str, tuple[float, list[float]]] = {}
_EMBEDDING_CACHE_TTL_SECONDS = int(os.getenv("KB_SEARCH_EMBEDDING_CACHE_TTL_SECONDS", "300"))
_HEALTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_HEALTH_CACHE_TTL_SECONDS = float(os.getenv("KB_HEALTH_CACHE_TTL_SECONDS", "10"))
_STATUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_STATUS_CACHE_TTL_SECONDS = float(os.getenv("KB_STATUS_CACHE_TTL_SECONDS", "10"))
_MAX_SEARCH_RESULT_CACHE_ENTRIES = int(os.getenv("KB_SEARCH_RESULT_CACHE_MAX_ENTRIES", "256"))
_MAX_EMBEDDING_CACHE_ENTRIES = int(os.getenv("KB_SEARCH_EMBEDDING_CACHE_MAX_ENTRIES", "512"))
_QUERY_EMBED_TIMEOUT_SECONDS = float(os.getenv("KB_QUERY_EMBED_TIMEOUT_SECONDS", "20"))
_DOCUMENT_EMBED_TIMEOUT_SECONDS = float(os.getenv("KB_DOCUMENT_EMBED_TIMEOUT_SECONDS", "20"))
_MCP_TOOL_TIMEOUT_SECONDS = float(os.getenv("KB_MCP_TOOL_TIMEOUT_SECONDS", "300"))
# Background tasks for async document indexing (cr-015: OpenFeature gated)
_ASYNC_INDEX_TASKS: set[asyncio.Task[None]] = set()


def _env_int(name: str, default: int) -> int:
    """Read an integer env var with a safe fallback."""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float env var with a safe fallback."""
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _cache_get(cache: dict[str, tuple[float, Any]], key: str, ttl: float) -> Any | None:
    """Return cached value when fresh; drop stale entries."""
    item = cache.get(key)
    if not item:
        return None
    ts, value = item
    if (time.time() - ts) > ttl:
        cache.pop(key, None)
        return None
    return value


def _cache_put(
    cache: dict[str, tuple[float, Any]],
    key: str,
    value: Any,
    *,
    max_entries: int,
) -> None:
    """Store cache value and bound memory with simple FIFO eviction."""
    cache[key] = (time.time(), value)
    overflow = len(cache) - max(1, max_entries)
    if overflow > 0:
        for stale_key in list(cache.keys())[:overflow]:
            cache.pop(stale_key, None)


async def _component_health_snapshot() -> dict[str, Any]:
    """Build storage/embeddings health once and reuse briefly for /health and /status."""
    components: dict[str, Any] = {}
    min_expected_indices = int(os.getenv("KB_MIN_EXPECTED_INDICES", "1"))
    min_expected_documents = int(os.getenv("KB_MIN_EXPECTED_DOCUMENTS", "1"))

    if _storage:
        storage_health = await _storage.health_check()
        error_text = str(storage_health.get("error", ""))
        auth_ok = "AuthorizationException" not in error_text and "403" not in error_text
        storage_connectivity_ok = bool(storage_health.get("healthy", False))
        index_count = int(storage_health.get("index_count", 0) or 0)
        # Local health may intentionally skip full document enumeration
        # (document_count=-1) so /health stays fast on multi-million-file
        # archives. Treat skipped counts as visibility-ok when indices exist.
        raw_document_count = storage_health.get("document_count", 0)
        try:
            document_count = int(raw_document_count if raw_document_count is not None else 0)
        except (TypeError, ValueError):
            document_count = 0
        docs_skipped = (
            document_count < 0
            or str(storage_health.get("document_count_mode", "")) == "skipped_for_health_latency"
        )
        index_visibility_ok = index_count >= min_expected_indices and (
            docs_skipped or document_count >= min_expected_documents
        )
        storage_health["auth_ok"] = auth_ok
        storage_health["storage_connectivity_ok"] = storage_connectivity_ok
        storage_health["index_visibility_ok"] = index_visibility_ok
        storage_health["min_expected_indices"] = min_expected_indices
        storage_health["min_expected_documents"] = min_expected_documents
        components["storage"] = storage_health
    else:
        components["storage"] = {"healthy": False, "error": _ERR_NOT_INITIALIZED}

    if _embeddings:
        embedding_health = await _embeddings.health_check()
        if hasattr(_embeddings, "provider_name"):
            embedding_health["active_provider"] = _embeddings.provider_name
        elif hasattr(_embeddings, "_model"):
            embedding_health["active_provider"] = getattr(
                _embeddings.__class__.__name__, "", "unknown"
            ).replace("EmbeddingProvider", "")
        components["embeddings"] = embedding_health
    else:
        components["embeddings"] = {"healthy": False, "error": _ERR_NOT_INITIALIZED}

    return components


_KB_SEARCH_SAFE_DEFAULT_TOP_K = max(1, _env_int("KB_SEARCH_SAFE_DEFAULT_TOP_K", 5))
_KB_SEARCH_SAFE_MAX_TOP_K = max(
    _KB_SEARCH_SAFE_DEFAULT_TOP_K,
    _env_int("KB_SEARCH_SAFE_MAX_TOP_K", 8),
)
_KB_SEARCH_SAFE_UNSCOPED_TOP_K = max(
    1,
    min(
        _KB_SEARCH_SAFE_MAX_TOP_K,
        _env_int("KB_SEARCH_SAFE_UNSCOPED_TOP_K", 3),
    ),
)
_KB_SEARCH_SAFE_UNSCOPED_MIN_SCORE = min(
    1.0,
    max(0.0, _env_float("KB_SEARCH_SAFE_UNSCOPED_MIN_SCORE", 0.65)),
)
_KB_SEARCH_SAFE_MAX_OFFSET = max(0, _env_int("KB_SEARCH_SAFE_MAX_OFFSET", 200))
_KB_INDEX_DIRECTORY_DEFAULT_MAX_FILES = max(
    1, _env_int("KB_INDEX_DIRECTORY_DEFAULT_MAX_FILES", 200)
)
_KB_INDEX_DIRECTORY_MAX_FILES_CAP = max(
    _KB_INDEX_DIRECTORY_DEFAULT_MAX_FILES,
    _env_int("KB_INDEX_DIRECTORY_MAX_FILES_CAP", 1000),
)
_KB_INDEX_DIRECTORY_DEFAULT_TIME_BUDGET_SECONDS = max(
    5,
    min(
        int(_MCP_TOOL_TIMEOUT_SECONDS) - 5,
        _env_int("KB_INDEX_DIRECTORY_DEFAULT_TIME_BUDGET_SECONDS", 30),
    ),
)
_VERSION_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}

# Shared error-message / media-type literals (avoid duplicating these strings
# across the many endpoints and MCP tool handlers below).
_ERR_NOT_INITIALIZED = "Not initialized"
_ERR_SERVICE_NOT_INITIALIZED = "Service not initialized"
_ERR_SYSTEM_SERVICE_NOT_INITIALIZED = "System service not initialized"
_ERR_DOCUMENT_EMBEDDING_TIMED_OUT = "Document embedding timed out"
_ERR_MISSING_PARAM_NAME = "Missing required parameter: name"
_ERR_MISSING_PARAM_PATH = "Missing required parameter: path"
_ERR_INVALID_PATH_KNOWLEDGEBASE = (
    "Invalid path: path must be inside the configured knowledgebase root"
)
_MEDIA_TYPE_JSON = "application/json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager for startup and shutdown."""
    global _storage, _hybrid_search, _embeddings, _system_service, _mcp_service

    logger.info("Starting KnowledgeBase API")

    # Guard against silently losing persistence: deployments that require
    # durable storage set KB_REQUIRE_OPENSEARCH_STORAGE=true explicitly (the
    # two AWS k8s deployments do; local docker-compose does not). If
    # KB_STORAGE__BACKEND is ever accidentally omitted from a manifest,
    # StorageSettings.backend silently defaults to "local" -- this fails
    # startup loudly instead of quietly stranding new documents on
    # ephemeral pod storage.
    if (
        os.getenv("KB_REQUIRE_OPENSEARCH_STORAGE", "").strip().lower() == "true"
        and settings.storage.backend != "opensearch"
    ):
        raise RuntimeError(
            "KB_REQUIRE_OPENSEARCH_STORAGE is set but KB_STORAGE__BACKEND resolved to "
            f"'{settings.storage.backend}' instead of 'opensearch' -- refusing to start "
            "with non-persistent storage in a deployment that requires durable storage."
        )

    # Initialize storage
    _storage = get_storage_backend()
    await _storage.initialize()
    default_mode = resolve_search_mode(
        os.getenv("KB_SEARCH_MODE", "hybrid"),
        default="hybrid",
    )
    _hybrid_search = HybridSearchService(
        _storage,
        default_mode=default_mode,
        hybrid_alpha=float(getattr(settings.search, "hybrid_alpha", 0.7) or 0.7),
    )
    logger.info(
        "Hybrid search service initialized",
        mode=default_mode,
        hybrid_alpha=_hybrid_search.hybrid_alpha,
    )
    try:
        storage_health = await _storage.health_check()
        logger.info(
            "Storage backend initialized",
            backend=storage_health.get("backend", settings.storage.backend),
            healthy=storage_health.get("healthy"),
            index_count=storage_health.get("index_count"),
            document_count=storage_health.get("document_count"),
            details=storage_health,
        )
    except Exception as e:
        logger.warning(
            "Storage backend initialized but health snapshot failed",
            backend=settings.storage.backend,
            error=str(e),
        )

    # Initialize embeddings with fallback support
    try:
        _embeddings = await get_embedding_provider_with_fallback()
        logger.info("Embeddings provider initialized with fallback support")
        # Pre-warm query embedding path so first agent search avoids cold Ollama.
        if os.getenv("KB_WARM_EMBEDDINGS_ON_STARTUP", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }:
            try:
                await _get_query_embedding("aegis_cmcp warmup")
                logger.info("Query embedding warm-up complete")
            except Exception as warm_exc:  # noqa: BLE001
                logger.warning("Query embedding warm-up skipped", error=str(warm_exc))
    except RuntimeError as e:
        logger.error("Failed to initialize embeddings provider", error=str(e))
        _embeddings = None

    # Initialize services
    _system_service = SystemMonitoringService(settings, _storage, _embeddings)
    _mcp_service = MCPService(settings)

    # Register services
    service_registry.register("system", _system_service)
    service_registry.register("mcp", _mcp_service)

    # Initialize all services
    await service_registry.initialize_all()

    logger.info("KnowledgeBase API started with services initialized")

    yield

    # Drain in-flight async-indexing tasks before tearing down storage
    if _ASYNC_INDEX_TASKS:
        logger.info("Draining async-indexing tasks", pending=len(_ASYNC_INDEX_TASKS))
        await asyncio.gather(*_ASYNC_INDEX_TASKS, return_exceptions=True)

    # Cleanup services
    await service_registry.cleanup_all()

    # Cleanup storage
    if _storage:
        await _storage.close()

    logger.info("KnowledgeBase API stopped")


# Create FastAPI application
settings = get_settings()
app = FastAPI(
    title="1-Nation MCP API",
    description="AWS-integrated hybrid RAG API (kNN/vector + BM25) for semantic document retrieval",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware with configurable origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.security.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Pydantic Models for API
# ============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    timestamp: str
    environment: str | None = None  # INFRAOS_ENVIRONMENT value
    components: dict[str, Any]


class SearchRequest(BaseModel):
    """Search request body."""

    model_config = ConfigDict(extra="ignore")

    query: str = Field(..., min_length=1, description="Search query text")
    index_name: str | None = Field(None, description="Index to search (None for all)")
    group: str | None = Field(None, description="Top-level taxonomy group filter")
    domain: str | None = Field(None, description="Taxonomy domain filter")
    subgroup: str | None = Field(None, description="Taxonomy subgroup filter")
    limit: int = Field(10, ge=1, le=100, description="Maximum results to return")
    min_score: float = Field(0.5, ge=0.0, le=1.0, description="Minimum score threshold")
    filters: dict[str, Any] = Field(default_factory=dict, description="Metadata filters")
    include_archive: bool = Field(
        False,
        description=(
            "When true, include archive/mirror documents and archive indices. "
            "Default false (Phase 4: exclude archives from default search)."
        ),
    )
    mode: str | None = Field(
        None,
        description="Search mode: hybrid (default), vector/kNN, or bm25.",
    )
    hybrid_alpha: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Vector weight for hybrid fusion (1.0=pure vector, 0.0=pure BM25).",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_fields(cls, value: Any) -> Any:
        """Support legacy clients that still send `index` and `top_k`."""
        if not isinstance(value, dict):
            return value

        normalized = dict(value)
        index_name = normalized.get("index_name")
        legacy_index = normalized.get("index")
        if (
            (index_name is None or (isinstance(index_name, str) and not index_name.strip()))
            and isinstance(legacy_index, str)
            and legacy_index.strip()
        ):
            normalized["index_name"] = legacy_index

        if "limit" not in normalized and normalized.get("top_k") is not None:
            normalized["limit"] = normalized.get("top_k")

        return normalized


class SearchResponse(BaseModel):
    """Search response body."""

    query: str
    results: list[SearchResult]
    total: int
    took_ms: float


class DocumentRequest(BaseModel):
    """Document creation/update request."""

    id: str = Field(..., description="Unique document ID")
    content: str = Field(..., min_length=1, description="Document content")
    index_name: str = Field("knowledgebase", description="Target index")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Document metadata")
    # When true, route through IndexingPipeline (chunk → embed → store) and
    # skip the async placeholder path. Used by aegis-cli knowledge push-multi
    # so pushed content is immediately searchable via vector retrieval.
    full_index: bool = Field(
        False,
        description=(
            "Run the full indexing pipeline (chunk + embed + store) synchronously. "
            "Ignores kb.async-indexing placeholders so has_embedding is true on success."
        ),
    )
    chunk: bool = Field(
        True,
        description="When full_index is true, chunk long documents before embedding.",
    )


class DocumentResponse(BaseModel):
    """Document response."""

    id: str
    content: str
    index_name: str
    metadata: dict[str, Any]
    has_embedding: bool


class DocumentListQuery(BaseModel):
    """Body parameters for listing documents.

    Used by the UI to page through documents for a given index.
    """

    index_name: str = Field(..., description="Index to list documents from")
    offset: int = Field(0, ge=0, description="Result offset for pagination")
    limit: int = Field(20, ge=1, le=100, description="Maximum number of documents to return")
    include_content: bool = Field(
        True,
        description=(
            "When false, omit document content bodies from the response "
            "(metadata-only listing). Content is truncated server-side when true."
        ),
    )


class DocumentListResponse(BaseModel):
    """Paginated list of documents for an index."""

    items: list[DocumentResponse]
    total: int
    offset: int
    limit: int


class IndexCreateRequest(BaseModel):
    """Index creation request."""

    name: str = Field(..., min_length=1, pattern=r"^[a-z0-9-]+$")
    description: str = ""
    metadata_schema: dict[str, str] = Field(default_factory=dict)


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
    success: bool


class RagConfig(BaseModel):
    """Configuration for Retrieval-Augmented Generation (RAG).

    This configuration controls how many documents are retrieved, score
    thresholds, and response-shaping options used by downstream RAG
    workflows and the UI.
    """

    top_k: int = Field(10, ge=1, le=50, description="Maximum number of documents to retrieve")
    min_score: float = Field(0.5, ge=0.0, le=1.0, description="Minimum similarity score threshold")
    default_index: str | None = Field(
        default=None,
        description=(
            "Default index to search. When null, the engine may route queries "
            "across multiple indices."
        ),
    )
    max_context_tokens: int = Field(
        2048,
        ge=128,
        le=32768,
        description="Approximate token budget for retrieved context snippets.",
    )
    max_answer_tokens: int = Field(
        512,
        ge=64,
        le=8192,
        description="Soft limit for generated answer length.",
    )
    include_sources: bool = Field(
        True,
        description="Whether answers should include source snippets and citations.",
    )
    use_reranker: bool = Field(
        False,
        description="Apply an additional reranking step before answering.",
    )
    return_debug_metadata: bool = Field(
        False,
        description="Return extra debug metadata (scores, signals) with responses.",
    )


_RAG_CONFIG_FILENAME = "rag.json"


def _rag_config_path() -> Path:
    """Return the filesystem path to the RAG configuration file."""

    return settings.config_dir / _RAG_CONFIG_FILENAME


def _load_rag_config() -> RagConfig:
    """Load the RAG configuration from disk or return defaults.

    If no explicit configuration file exists yet, this returns a RagConfig
    instance with default values only.
    """

    path = _rag_config_path()
    if not path.exists():
        # Use explicit field names so static type checking can verify
        # that all required configuration properties are provided.
        return RagConfig(
            top_k=10,
            min_score=0.5,
            default_index=None,
            max_context_tokens=2048,
            max_answer_tokens=512,
            include_sources=True,
            use_reranker=False,
            return_debug_metadata=False,
        )

    with path.open() as f:
        data = json.load(f)

    # Unknown fields in the file are ignored by Pydantic, so the config
    # format can evolve over time without breaking older installations.
    return RagConfig(**data)


def _save_rag_config(config: RagConfig) -> None:
    """Persist the RAG configuration to the configured cfg directory.

    The writer ensures a trailing newline so tools like pre-commit's
    ``end-of-file-fixer`` do not need to rewrite the file repeatedly.
    """

    settings.config_dir.mkdir(parents=True, exist_ok=True)
    path = _rag_config_path()
    with path.open("w") as f:
        json.dump(config.model_dump(), f, indent=2)
        f.write("\n")


# ============================================================================
# Root Endpoint
# ============================================================================


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Redirect root requests to the interactive API docs.

    Browsers hitting the service origin should land on a useful page instead
    of a bare ``{"detail": "Not Found"}`` 404 response.
    """

    return RedirectResponse(url="/docs", status_code=307)


# ============================================================================
# Health Endpoint
# ============================================================================


@app.get("/health", tags=["Health"])
async def health_check() -> HealthResponse:
    """
    Check the health of the KnowledgeBase API and its components.

    Returns component-level health status for storage and embeddings.
    Includes information about the active embedding provider.
    """
    cached = _cache_get(_HEALTH_CACHE, "health", _HEALTH_CACHE_TTL_SECONDS)
    if isinstance(cached, dict):
        return HealthResponse(**cached)

    components = await _component_health_snapshot()
    all_healthy = all(c.get("healthy", False) for c in components.values())
    payload = {
        "status": "healthy" if all_healthy else "degraded",
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.aegis_environment,
        "components": components,
    }
    _cache_put(_HEALTH_CACHE, "health", payload, max_entries=4)
    return HealthResponse(**payload)


def _version_feature_enabled(flag_key: str, default: bool) -> bool:
    return is_feature_enabled(flag_key, default=default)


def _version_header_truthy(raw_value: str | None) -> bool:
    if raw_value is None:
        return False
    return raw_value.strip().lower() in _VERSION_TRUE_VALUES


def _normalize_version_environment(raw_environment: str) -> str:
    normalized = raw_environment.strip().lower()
    if normalized in {"local", "development", "dev"}:
        return "dev"
    if normalized in {"production", "prod", "master"}:
        return "master"
    if normalized in {"testing", "staging"}:
        return normalized
    return "dev"


def _parse_aws_push_counter(raw_counter: str | None) -> int:
    if raw_counter is None:
        return 0
    try:
        return int(raw_counter.strip())
    except (TypeError, ValueError):
        return 0


def _build_version_payload(internal_header_value: str | None = None) -> dict[str, Any]:
    app_version = (os.getenv("APP_VERSION") or __version__).strip() or __version__
    push_counter = _parse_aws_push_counter(os.getenv("AWS_PUSH_COUNTER"))
    aws_release_ver = (os.getenv("AWS_RELEASE_VER") or f"{app_version}.{push_counter}").strip()
    environment = _normalize_version_environment(
        (settings.aegis_environment or os.getenv("INFRAOS_ENVIRONMENT") or "dev")
    )
    include_internal = _version_feature_enabled(
        "kb.version_endpoint.internal_metadata.enabled", default=False
    ) and _version_header_truthy(internal_header_value)
    payload: dict[str, Any] = {
        "service": "1n-mcp",
        "version": app_version,
        "aws_push_counter": push_counter,
        "aws_release_ver": aws_release_ver,
        "git_sha": os.getenv("GIT_SHA", "unknown"),
        "build_timestamp": os.getenv("BUILD_TIMESTAMP", "unknown"),
        "environment": environment,
        "source": os.getenv("VERSION_SOURCE", "cvs-registry"),
        "security_profile": "internal" if include_internal else "public",
    }
    if include_internal:
        payload["internal"] = {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "pid": os.getpid(),
        }
    return payload


def _render_version_html(payload: dict[str, Any]) -> str:
    pretty_payload = escape(json.dumps(payload, indent=2))
    return (
        "<!DOCTYPE html>"
        '<html lang="en">'
        '<head><meta charset="utf-8"><title>1-Nation MCP Version</title></head>'
        "<body><h1>1-Nation MCP Version</h1><pre>"
        f"{pretty_payload}"
        "</pre></body></html>"
    )


@app.get(
    "/version",
    tags=["Health"],
    responses={404: {"description": "Version endpoint disabled via feature flag"}},
)
async def version_endpoint(request: Request) -> Any:
    """Return CVS-compliant version metadata with JSON/HTML negotiation."""
    if not _version_feature_enabled("kb.version_endpoint.enabled", default=True):
        raise HTTPException(status_code=404, detail="version endpoint disabled")
    payload = _build_version_payload(request.headers.get("X-Aegis-Internal"))
    accepts = request.headers.get("accept", "").lower()
    if (
        "text/html" in accepts
        and _MEDIA_TYPE_JSON not in accepts
        and _version_feature_enabled("kb.version_endpoint.html.enabled", default=True)
    ):
        return HTMLResponse(content=_render_version_html(payload))
    return JSONResponse(payload)


@app.get("/status", tags=["Health"])
async def status_endpoint() -> Any:
    """Return CVS-compliant status with system health overview.

    This root-level /status endpoint provides a quick overview of system health
    aligned with the Container Version Standard (CVS). For detailed diagnostics,
    use /api/v1/status/full.
    """
    cached = _cache_get(_STATUS_CACHE, "status", _STATUS_CACHE_TTL_SECONDS)
    if isinstance(cached, dict):
        return JSONResponse(cached)

    health_components = await _component_health_snapshot()
    components: dict[str, Any] = {
        "storage": {
            "healthy": bool((health_components.get("storage") or {}).get("healthy", False)),
            "backend": (health_components.get("storage") or {}).get("backend", "unknown"),
        },
        "embeddings": {
            "healthy": bool((health_components.get("embeddings") or {}).get("healthy", False)),
            "provider": (health_components.get("embeddings") or {}).get("provider", "unknown"),
        },
    }

    if _mcp_service:
        mcp_status = await _mcp_service.get_server_status()
        components["mcp"] = {
            "healthy": mcp_status.status == "active",
            "tools_count": len(mcp_status.tools),
        }
    else:
        components["mcp"] = {"healthy": False, "error": _ERR_NOT_INITIALIZED}

    all_healthy = all(c.get("healthy", False) for c in components.values())
    payload = {
        "overallStatus": "healthy" if all_healthy else "degraded",
        "service": "1n-mcp",
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.aegis_environment or "local",
        "components": components,
        "details_url": "/api/v1/status/full",
    }
    _cache_put(_STATUS_CACHE, "status", payload, max_entries=4)
    return JSONResponse(payload)


# ============================================================================
# Runtime / Docker Status Endpoint
# ============================================================================


@app.get("/api/v1/runtime/status", tags=["Runtime"])
async def runtime_status() -> RuntimeStatusResponse:
    """Return a snapshot of the current runtime and expected services.

    This endpoint is designed primarily for the UI dashboard so that operators
    can quickly understand whether the API is running via Docker or a local
    server and which auxiliary services (such as OpenSearch) are expected.
    """

    return get_runtime_status()


# ============================================================================
# RAG Configuration Endpoints
# ============================================================================


@app.get("/api/v1/rag/config", tags=["RAG"])
async def get_rag_config() -> RagConfig:
    """Return the current RAG configuration.

    This is used by the UI to pre-populate the RAG settings screen.
    """

    return _load_rag_config()


@app.put("/api/v1/rag/config", tags=["RAG"])
async def update_rag_config(config: RagConfig) -> RagConfig:
    """Update and persist the RAG configuration."""

    _save_rag_config(config)
    return config


def _clear_search_caches() -> None:
    """Clear in-process search, embedding, and health caches."""
    _SEARCH_RESULT_CACHE.clear()
    _EMBEDDING_CACHE.clear()
    _HEALTH_CACHE.clear()
    _STATUS_CACHE.clear()
    if _hybrid_search is not None:
        _hybrid_search.invalidate()


def _embedding_cache_key(query: str) -> str:
    if _embeddings is None:
        provider_name = "unknown"
        model_name = "unknown"
        dimensions = "unknown"
    else:
        provider_name = _embeddings.__class__.__name__
        model_name = getattr(_embeddings, "model_name", "unknown")
        dimensions = str(getattr(_embeddings, "dimensions", "unknown"))
    raw = f"{provider_name}|{model_name}|{dimensions}|{query}"
    return sha256(raw.encode("utf-8")).hexdigest()


async def _get_query_embedding(query: str) -> list[float]:
    if _embeddings is None:
        return []

    cache_key = _embedding_cache_key(query)
    now = time.time()
    cached = _EMBEDDING_CACHE.get(cache_key)
    if cached and (now - cached[0]) <= _EMBEDDING_CACHE_TTL_SECONDS:
        logger.info("query_embedding_cache", hit=True)
        return cached[1]

    logger.info("query_embedding_cache", hit=False)
    with timed_operation("knowledgebase.api.embed_query"):
        embedding = await asyncio.wait_for(
            _embeddings.embed_query(query), timeout=_QUERY_EMBED_TIMEOUT_SECONDS
        )
    _cache_put(
        _EMBEDDING_CACHE,
        cache_key,
        embedding,
        max_entries=_MAX_EMBEDDING_CACHE_ENTRIES,
    )
    # _cache_put stores (ts, value); normalize to expected tuple shape already done.
    return embedding


async def _get_document_embedding(content: str) -> list[float]:
    if _embeddings is None:
        return []

    with timed_operation("knowledgebase.api.embed_text"):
        try:
            return await asyncio.wait_for(
                _embeddings.embed_text(content), timeout=_DOCUMENT_EMBED_TIMEOUT_SECONDS
            )
        except (TimeoutError, asyncio.TimeoutError) as e:
            raise TimeoutError(
                f"Embedding timed out after {_DOCUMENT_EMBED_TIMEOUT_SECONDS:.0f}s"
            ) from e


async def _async_index_document(
    doc_id: str,
    content: str,
    index_name: str,
    metadata: dict[str, Any],
) -> None:
    """Generate embedding and upsert document in the background.

    Fired when the ``kb.async-indexing`` feature flag is enabled so the
    caller receives an immediate 200 while embedding generation happens
    out-of-band.
    """
    try:
        embedding = await _get_document_embedding(content)
        doc = Document(
            id=doc_id,
            content=content,
            embedding=embedding,
            index_name=index_name,
            metadata=DocumentMetadata(**metadata),
        )
        if _storage:
            await _storage.add_document(doc)
            _clear_search_caches()
        logger.info(
            "async_index_complete",
            doc_id=doc_id,
            index_name=index_name,
        )
    except Exception:
        logger.exception(
            "async_index_failed",
            doc_id=doc_id,
            index_name=index_name,
        )


def _serialize_filters(filters: dict[str, Any] | None) -> str:
    if not filters:
        return ""
    return json.dumps(filters, sort_keys=True, default=str)


def _search_cache_key(
    *,
    query: str,
    target_indices: list[str] | None,
    filters: dict[str, Any] | None,
    limit: int,
    min_score: float,
    offset: int,
) -> str:
    resolved_indices = sorted(target_indices) if target_indices else ["__all__"]
    raw = "|".join(
        [
            ",".join(resolved_indices),
            _serialize_filters(filters),
            query,
            str(limit),
            str(min_score),
            str(offset),
        ]
    )
    return sha256(raw.encode("utf-8")).hexdigest()


# ============================================================================
# Search Endpoints
# ============================================================================


@app.post(
    "/api/v1/search",
    tags=["Search"],
    responses={
        503: {"description": "Storage/embeddings service not initialized"},
        504: {"description": "Search timed out while generating query embedding"},
        500: {"description": "Search failed"},
    },
)
async def search_documents(request: SearchRequest) -> SearchResponse:
    """
    Search for documents matching the query.

    Performs hybrid RAG search (kNN/vector + BM25) with optional metadata filtering.
    Use ``mode`` = hybrid|vector|bm25 to select the retrieval strategy.
    """
    start_time = time.time()

    if not _embeddings or not _storage:
        raise HTTPException(status_code=503, detail=_ERR_SERVICE_NOT_INITIALIZED)

    try:
        query_embedding = await asyncio.wait_for(
            _get_query_embedding(request.query), timeout=_QUERY_EMBED_TIMEOUT_SECONDS
        )

        with timed_operation("knowledgebase.api.search"):
            results = await _search_with_routing(
                query_embedding=query_embedding,
                query_text=request.query,
                limit=request.limit,
                min_score=request.min_score,
                filters=request.filters if request.filters else None,
                index_name=request.index_name,
                group=request.group,
                domain=request.domain,
                subgroup=request.subgroup,
                offset=0,
                include_archive=bool(request.include_archive),
                mode=request.mode,
                hybrid_alpha=request.hybrid_alpha,
            )

        took_ms = (time.time() - start_time) * 1000

        # Record search activity for analytics
        await _record_search_activity(request, took_ms, len(results))

        with timed_operation("knowledgebase.api.search.serialize", result_count=len(results)):
            return SearchResponse(
                query=request.query,
                results=results,
                total=len(results),
                took_ms=round(took_ms, 2),
            )

    except (TimeoutError, asyncio.TimeoutError) as e:
        logger.error("Search embedding timed out", error=str(e), query=request.query)
        raise HTTPException(
            status_code=504,
            detail="Search timed out while generating query embedding",
        ) from e
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Search failed", error=str(e), query=request.query)
        raise HTTPException(status_code=500, detail=f"Search failed: {e}") from e


# ============================================================================
# Document Endpoints
# ============================================================================


@app.post(
    "/api/v1/documents",
    tags=["Documents"],
    responses={
        503: {"description": "Storage/embeddings service not initialized"},
        504: {"description": "Document embedding timed out"},
        500: {"description": "Failed to add document"},
    },
)
async def add_document(request: DocumentRequest) -> DocumentResponse:
    """
    Add or update a document in the knowledgebase.

    By default generates an embedding for the document content and stores it
    in the specified index. When ``full_index`` is true, runs the full
    IndexingPipeline (chunk → embed → store) so content is immediately
    available for semantic search.
    """
    if not _embeddings or not _storage:
        raise HTTPException(status_code=503, detail=_ERR_SERVICE_NOT_INITIALIZED)

    try:
        config = _load_knowledgebase_config()
        aliases = _get_index_aliases(config)
        resolved_index_name = (
            _resolve_index_alias(request.index_name, aliases) or request.index_name
        )

        # ── Full indexing pipeline (push-multi / explicit clients) ──
        # Always synchronous: chunk → embed → store. Bypasses async
        # placeholder writes so has_embedding is true on success.
        if request.full_index:
            pipeline = IndexingPipeline(storage=_storage, embeddings=_embeddings)
            indexed_docs = await asyncio.wait_for(
                pipeline.index_text(
                    content=request.content,
                    doc_id=request.id,
                    index_name=resolved_index_name,
                    metadata=request.metadata,
                    chunk=request.chunk,
                ),
                timeout=_DOCUMENT_EMBED_TIMEOUT_SECONDS,
            )
            _clear_search_caches()
            primary = indexed_docs[0] if indexed_docs else None
            has_embedding = bool(primary and primary.has_embedding)
            if not has_embedding:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Full indexing pipeline completed without embeddings; "
                        "document is not searchable"
                    ),
                )
            logger.info(
                "document_full_index_complete",
                doc_id=request.id,
                index_name=resolved_index_name,
                chunks=len(indexed_docs),
            )
            return DocumentResponse(
                id=request.id,
                content=request.content,
                index_name=resolved_index_name,
                metadata=request.metadata,
                has_embedding=True,
            )

        # ── Async write path (cr-015: OpenFeature gated) ──────────
        if is_feature_enabled("kb.async-indexing"):
            # Store document immediately without embedding so the
            # caller gets a fast 200.  A background task will
            # generate the embedding and upsert the full document.
            placeholder_doc = Document(
                id=request.id,
                content=request.content,
                embedding=[],
                index_name=resolved_index_name,
                metadata=DocumentMetadata(**request.metadata),
            )
            await _storage.add_document(placeholder_doc)

            task = asyncio.create_task(
                _async_index_document(
                    doc_id=request.id,
                    content=request.content,
                    index_name=resolved_index_name,
                    metadata=request.metadata,
                )
            )
            _ASYNC_INDEX_TASKS.add(task)
            task.add_done_callback(_ASYNC_INDEX_TASKS.discard)

            logger.info(
                "document_accepted_async",
                doc_id=request.id,
                index_name=resolved_index_name,
            )
            return DocumentResponse(
                id=request.id,
                content=request.content,
                index_name=resolved_index_name,
                metadata=request.metadata,
                has_embedding=False,
            )

        # ── Legacy sync path (default) ────────────────────────────
        embedding = await _get_document_embedding(request.content)

        doc = Document(
            id=request.id,
            content=request.content,
            embedding=embedding,
            index_name=resolved_index_name,
            metadata=DocumentMetadata(**request.metadata),
        )

        await _storage.add_document(doc)
        _clear_search_caches()

        return DocumentResponse(
            id=doc.id,
            content=doc.content,
            index_name=doc.index_name,
            metadata=request.metadata,
            has_embedding=True,
        )

    except HTTPException:
        raise
    except (TimeoutError, asyncio.TimeoutError) as e:
        logger.error(
            "Document embedding timed out",
            error=str(e),
            index_name=request.index_name,
            document_id=request.id,
        )
        raise HTTPException(status_code=504, detail=_ERR_DOCUMENT_EMBEDDING_TIMED_OUT) from e
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to add document", error=str(e), doc_id=request.id)
        raise HTTPException(status_code=500, detail=f"Failed to add document: {e}") from e


@app.get(
    "/api/v1/documents/{index_name}/{doc_id}",
    tags=["Documents"],
    responses={
        503: {"description": "Storage service not initialized"},
        404: {"description": "Document not found"},
        500: {"description": "Failed to get document"},
    },
)
async def get_document(index_name: str, doc_id: str) -> DocumentResponse:
    """
    Retrieve a document by ID from a specific index.
    """
    if not _storage:
        raise HTTPException(status_code=503, detail=_ERR_SERVICE_NOT_INITIALIZED)

    try:
        config = _load_knowledgebase_config()
        aliases = _get_index_aliases(config)
        resolved_index_name = _resolve_index_alias(index_name, aliases) or index_name
        doc = await _storage.get_document(doc_id, resolved_index_name)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        return DocumentResponse(
            id=doc.id,
            content=doc.content,
            index_name=doc.index_name,
            metadata=doc.metadata.model_dump(),
            has_embedding=doc.has_embedding,
        )

    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to get document", error=str(e), doc_id=doc_id)
        raise HTTPException(status_code=500, detail=f"Failed to get document: {e}") from e


@app.delete(
    "/api/v1/documents/{index_name}/{doc_id}",
    tags=["Documents"],
    responses={
        503: {"description": "Storage service not initialized"},
        404: {"description": "Document not found"},
        500: {"description": "Failed to delete document"},
    },
)
async def delete_document(index_name: str, doc_id: str) -> MessageResponse:
    """
    Delete a document by ID from a specific index.
    """
    if not _storage:
        raise HTTPException(status_code=503, detail=_ERR_SERVICE_NOT_INITIALIZED)

    try:
        config = _load_knowledgebase_config()
        aliases = _get_index_aliases(config)
        resolved_index_name = _resolve_index_alias(index_name, aliases) or index_name
        deleted = await _storage.delete_document(doc_id, resolved_index_name)
        if not deleted:
            raise HTTPException(status_code=404, detail="Document not found")
        _clear_search_caches()

        return MessageResponse(
            message=f"Document {doc_id} deleted successfully",
            success=True,
        )

    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to delete document", error=str(e), doc_id=doc_id)
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}") from e


@app.post(
    "/api/v1/documents/list",
    tags=["Documents"],
    responses={
        503: {"description": "Storage service not initialized"},
        422: {"description": "Invalid limit/offset parameter"},
        500: {"description": "Failed to list documents"},
    },
)
async def list_documents(request: DocumentListQuery) -> DocumentListResponse:
    """List documents for a given index with simple offset/limit pagination.

    Content bodies are truncated (and optionally omitted) to keep responses
    under ALB idle timeouts when listing large OpenSearch indices.
    """

    if not _storage:
        raise HTTPException(status_code=503, detail=_ERR_SERVICE_NOT_INITIALIZED)

    if request.limit < 1 or request.limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")

    if request.offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")

    config = _load_knowledgebase_config()
    aliases = _get_index_aliases(config)
    index_name = _resolve_index_alias(request.index_name, aliases) or request.index_name
    offset = request.offset
    limit = request.limit
    content_max_chars = int(os.getenv("KB_OPENSEARCH_LIST_CONTENT_MAX_CHARS", "1200"))

    try:
        # Storage backends implement list_documents with native
        # pagination support so we can avoid loading everything into
        # memory when browsing from the UI.
        if _storage is None:
            raise HTTPException(status_code=503, detail=_ERR_SERVICE_NOT_INITIALIZED)
        docs, total = await _storage.list_documents(
            index_name=index_name,
            offset=offset,
            limit=limit,
        )

        items: list[DocumentResponse] = []
        for doc in docs:
            content = ""
            if request.include_content:
                content = doc.content or ""
                if content_max_chars > 0 and len(content) > content_max_chars:
                    content = content[:content_max_chars]
            items.append(
                DocumentResponse(
                    id=doc.id,
                    content=content,
                    index_name=doc.index_name,
                    metadata=(
                        doc.metadata.model_dump()
                        if hasattr(doc.metadata, "model_dump")
                        else dict(doc.metadata)
                    ),
                    has_embedding=doc.has_embedding,
                )
            )

        return DocumentListResponse(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to list documents", error=str(e), index=index_name)
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {e}") from e


# ============================================================================
# Index Endpoints
# ============================================================================


@app.get(
    "/api/v1/indices",
    tags=["Indices"],
    responses={
        503: {"description": "Storage service not initialized"},
        500: {"description": "Failed to list indices"},
    },
)
async def list_indices() -> list[IndexInfo]:
    """
    List all available indices.
    """
    if not _storage:
        raise HTTPException(status_code=503, detail=_ERR_SERVICE_NOT_INITIALIZED)

    try:
        return await _storage.list_indices()
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to list indices", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to list indices: {e}") from e


@app.post(
    "/api/v1/indices",
    tags=["Indices"],
    responses={
        503: {"description": "Storage service not initialized"},
        500: {"description": "Failed to create index"},
    },
)
async def create_index(request: IndexCreateRequest) -> MessageResponse:
    """
    Create a new index.
    """
    if not _storage:
        raise HTTPException(status_code=503, detail=_ERR_SERVICE_NOT_INITIALIZED)

    try:
        await _storage.create_index(request.name, request.metadata_schema)
        _clear_search_caches()
        return MessageResponse(
            message=f"Index '{request.name}' created successfully",
            success=True,
        )
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to create index", error=str(e), index=request.name)
        raise HTTPException(status_code=500, detail=f"Failed to create index: {e}") from e


@app.delete(
    "/api/v1/indices/{index_name}",
    tags=["Indices"],
    responses={
        503: {"description": "Storage service not initialized"},
        500: {"description": "Failed to delete index"},
    },
)
async def delete_index(index_name: str) -> MessageResponse:
    """
    Delete an index and all its documents.
    """
    if not _storage:
        raise HTTPException(status_code=503, detail=_ERR_SERVICE_NOT_INITIALIZED)

    try:
        await _storage.delete_index(index_name)
        _clear_search_caches()
        return MessageResponse(
            message=f"Index '{index_name}' deleted successfully",
            success=True,
        )
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to delete index", error=str(e), index=index_name)
        raise HTTPException(status_code=500, detail=f"Failed to delete index: {e}") from e


# ============================================================================
# System Monitoring Endpoints
# ============================================================================


@app.get(
    "/api/v1/system/stats",
    tags=["System"],
    responses={
        503: {"description": "System service not initialized"},
        500: {"description": "Failed to get system stats"},
    },
)
async def get_system_statistics() -> SystemStats:
    """
    Return current system statistics including document counts, memory usage, and uptime.

    This endpoint provides real-time system metrics for dashboard display.
    """
    if not _system_service:
        raise HTTPException(status_code=503, detail=_ERR_SYSTEM_SERVICE_NOT_INITIALIZED)

    try:
        return await _system_service.get_system_stats()
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to get system stats", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get system stats: {e}") from e


@app.get(
    "/api/v1/system/performance",
    tags=["System"],
    responses={
        503: {"description": "System service not initialized"},
        500: {"description": "Failed to get performance metrics"},
    },
)
async def get_performance_metrics() -> PerformanceMetrics:
    """
    Return detailed system performance metrics including CPU, memory, disk, and network usage.

    This endpoint provides comprehensive performance data for monitoring and alerting.
    """
    if not _system_service:
        raise HTTPException(status_code=503, detail=_ERR_SYSTEM_SERVICE_NOT_INITIALIZED)

    try:
        return await _system_service.get_performance_metrics()
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to get performance metrics", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to get performance metrics: {e}"
        ) from e


@app.get(
    "/api/v1/system/services",
    tags=["System"],
    responses={
        503: {"description": "System service not initialized"},
        500: {"description": "Failed to get service status"},
    },
)
async def get_service_status() -> list[ServiceStatus]:
    """
    Return the status of various system services and components.

    Provides health and performance information for different system components.
    """
    if not _system_service:
        raise HTTPException(status_code=503, detail=_ERR_SYSTEM_SERVICE_NOT_INITIALIZED)

    try:
        return await _system_service.get_service_status_list()
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to get service status", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get service status: {e}") from e


# ============================================================================
# Comprehensive Status Endpoints
# ============================================================================


@app.get(
    "/api/v1/status/full",
    tags=["Status"],
    responses={500: {"description": "Failed to get full status"}},
)
async def get_full_status() -> Any:
    """
    Get comprehensive status of all MCP components.

    Performs testing of all MCP tools, API endpoints, and aggregates system statistics.
    Returns a detailed diagnostic report if any issues are found.
    """
    from knowledgebase.services.status_service import StatusService

    status_service = StatusService(settings)
    await status_service.initialize()

    try:
        return await status_service.get_full_status()
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to get full status", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get full status: {e}") from e


# ============================================================================
# MCP Protocol Endpoints (for Warp and other MCP clients)
# ============================================================================


@app.get("/mcp/sse", tags=["MCP Protocol"])
async def mcp_sse_endpoint_get() -> StreamingResponse:
    """
    MCP SSE endpoint for Warp and other SSE-based MCP clients (GET handler).

    This implements the Streamable HTTP transport for MCP:
    - GET /mcp/sse returns SSE stream for server->client messages
    - POST /mcp/sse accepts client->server messages (Streamable HTTP)
    """
    import asyncio
    import uuid

    from starlette.responses import StreamingResponse

    session_id = str(uuid.uuid4())
    logger.info("MCP SSE connection opened", session_id=session_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events."""
        # Send initial endpoint message per MCP SSE spec
        endpoint_msg = f'data: {{"endpoint": "/mcp/sse?session={session_id}"}}'
        yield f"{endpoint_msg}\n\n"

        # Keep connection alive with periodic pings
        while True:
            await asyncio.sleep(30)
            yield ": ping\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/mcp/sse", tags=["MCP Protocol"])
async def mcp_sse_endpoint_post(request: Request) -> JSONResponse:
    """
    MCP Streamable HTTP endpoint (POST handler).

    This enables Warp's preferred Streamable HTTP transport mode.
    POST requests to /mcp/sse are handled as JSON-RPC messages,
    eliminating the preflight 404 that causes connection issues.
    """
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return _mcp_invalid_request("Invalid MCP request: expected a JSON object.")

        request_id = body.get("id")
        if "jsonrpc" in body and body.get("jsonrpc") != "2.0":
            return _mcp_invalid_request("Invalid MCP request: jsonrpc must be '2.0'.", request_id)

        method = body.get("method")
        if not isinstance(method, str) or not method.strip():
            hint = "Invalid MCP request: missing JSON-RPC method."
            if any(
                key in body
                for key in (
                    "documents",
                    "content",
                    "index",
                    "index_name",
                    "metadata",
                    "id",
                )
            ):
                hint = (
                    "Invalid MCP request: missing JSON-RPC method. "
                    "This endpoint only accepts MCP JSON-RPC. "
                    "For document storage, use POST /api/v1/documents or "
                    "call tools/call with kb_add_document or kb_add_file."
                )
            return _mcp_invalid_request(hint, request_id)

        raw_params = body.get("params", {})
        # Explicitly check for dict; empty dict {} is valid, but [] or other types are not
        if "params" in body and not isinstance(raw_params, dict):
            return _mcp_invalid_request(
                "Invalid MCP request: params must be an object.", request_id
            )
        # Use empty dict if params not provided
        if raw_params is None:
            raw_params = {}
        params: dict[str, Any] = raw_params
        return await _handle_mcp_rpcs_request(method, params, request_id)
    except json.JSONDecodeError:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None,
            },
            status_code=400,
        )
    except Exception as e:
        logger.error("MCP SSE POST request failed", error=str(e))
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": str(e)},
                "id": None,
            },
            status_code=500,
        )


class MCPJsonRpcRequest(BaseModel):
    """MCP JSON-RPC request model."""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: int | str | None = None


async def _rpc_initialize(
    params: dict[str, Any], create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    return JSONResponse(
        create_response(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "prompts": {},
                    "resources": {},
                },
                "serverInfo": {
                    "name": "1NMCP",
                    "version": __version__,
                },
            }
        )
    )


async def _rpc_tools_list(
    params: dict[str, Any], create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    # Simple caching (1 minute)
    global _TOOLS_CACHE
    current_time = time.time()
    if _TOOLS_CACHE and (current_time - _TOOLS_CACHE["timestamp"] < 60):
        return JSONResponse(create_response({"tools": _TOOLS_CACHE["data"]}))

    tools = []
    if _mcp_service:
        status = await _mcp_service.get_server_status()
        for tool in status.tools:
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": _get_tool_schema(tool.name),
                }
            )

    # Update cache
    _TOOLS_CACHE = {"timestamp": current_time, "data": tools}
    return JSONResponse(create_response({"tools": tools}))


async def _rpc_tools_call(
    params: dict[str, Any], create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    tool_name = params.get("name") if params else None
    tool_args = params.get("arguments", {}) if params else {}

    if not tool_name:
        return JSONResponse(
            create_response(
                error={
                    "code": -32602,
                    "message": "Invalid params: missing tool name",
                }
            )
        )

    try:
        result = await asyncio.wait_for(
            _execute_mcp_tool(tool_name, tool_args), timeout=_MCP_TOOL_TIMEOUT_SECONDS
        )
    except (TimeoutError, asyncio.TimeoutError):
        result = _mcp_error(f"Tool execution timed out after {_MCP_TOOL_TIMEOUT_SECONDS:.0f}s")
    return JSONResponse(create_response(result))


async def _rpc_notifications_initialized(
    params: dict[str, Any], create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    return JSONResponse(content={}, status_code=204)


async def _rpc_prompts_list(
    params: dict[str, Any], create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    prompts = []
    if _runbook_service:
        try:
            rb_data = _runbook_service.list_runbooks()
            rb_list = rb_data.get("runbooks", [])
            for rb in rb_list:
                prompts.append(
                    {
                        "name": rb["name"],
                        "description": f"Runbook: {rb['name']}",
                        "arguments": [
                            {
                                "name": "vars",
                                "description": "Optional variable overrides (key=value,key2=value2)",
                                "required": False,
                            }
                        ],
                    }
                )
        except Exception as e:
            logger.error("Failed to list prompts", error=str(e))
    return JSONResponse(create_response({"prompts": prompts}))


async def _rpc_prompts_get(
    params: dict[str, Any], create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    name = params.get("name")
    if not name:
        return JSONResponse(
            create_response(error={"code": -32602, "message": "Missing prompt name"})
        )

    if _runbook_service:
        try:
            args = params.get("arguments", {}) or {}
            vars_str = args.get("vars", "")
            prompt_resp = _runbook_service.get_prompt(name, vars_str)
            return JSONResponse(
                create_response(
                    {
                        "description": f"Runbook: {name}",
                        "messages": [
                            {
                                "role": "user",
                                "content": {
                                    "type": "text",
                                    "text": prompt_resp.prompt_text,
                                },
                            }
                        ],
                    }
                )
            )
        except ValueError:
            pass  # Not found
        except Exception as e:
            logger.error("Failed to get prompt", error=str(e), name=name)

    return JSONResponse(create_response(error={"code": -32602, "message": "Prompt not found"}))


async def _rpc_resources_list(
    params: dict[str, Any], create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    resources = []

    # Add indices
    if _storage:
        try:
            indices = await _storage.list_indices()
            for idx in indices:
                resources.append(
                    {
                        "uri": f"knowledgebase://{idx.name}",
                        "name": f"Index: {idx.name}",
                        "description": f"KnowledgeBase Index ({idx.document_count} documents)",
                        "mimeType": _MEDIA_TYPE_JSON,
                    }
                )
        except Exception as e:
            logger.error("Failed to list index resources", error=str(e))

    # Add runbooks
    if _runbook_service:
        try:
            rb_data = _runbook_service.list_runbooks()
            rb_list = rb_data.get("runbooks", [])
            for rb in rb_list:
                resources.append(
                    {
                        "uri": f"runbook://{rb['name']}",
                        "name": f"Runbook: {rb['name']}",
                        "description": "Executable runbook template",
                        "mimeType": "text/markdown",
                    }
                )
        except Exception as e:
            logger.error("Failed to list runbook resources", error=str(e))

    return JSONResponse(create_response({"resources": resources}))


async def _rpc_read_runbook_resource(uri: str) -> dict[str, Any] | None:
    """Return an MCP resource-read result for a runbook:// URI, or None if not found/applicable."""
    if not (uri.startswith("runbook://") and _runbook_service):
        return None
    name = uri.replace("runbook://", "")
    try:
        rb = _runbook_service.get_runbook(name)
        if rb:
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/markdown",
                        "text": rb["content"],
                    }
                ]
            }
    except Exception as e:
        logger.error("Failed to read runbook resource", error=str(e), uri=uri)
    return None


async def _rpc_read_knowledgebase_document(
    uri: str, index_name: str, doc_id: str, create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    storage = _storage
    if storage is None:
        return JSONResponse(
            create_response(error={"code": -32603, "message": _ERR_SERVICE_NOT_INITIALIZED})
        )
    doc = await storage.get_document(doc_id, index_name)
    if not doc:
        return JSONResponse(
            create_response(
                error={
                    "code": -32604,
                    "message": f"Document not found: {doc_id} in index {index_name}",
                }
            )
        )
    output = {
        "id": doc.id,
        "index": doc.index_name,
        "content": doc.content,
        "metadata": (
            doc.metadata.model_dump() if hasattr(doc.metadata, "model_dump") else dict(doc.metadata)
        ),
    }
    return JSONResponse(
        create_response(
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": _MEDIA_TYPE_JSON,
                        "text": json.dumps(output, indent=2, default=str),
                    }
                ]
            }
        )
    )


async def _rpc_read_knowledgebase_index(
    uri: str, index_name: str, create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    storage = _storage
    if storage is None:
        return JSONResponse(
            create_response(error={"code": -32603, "message": _ERR_SERVICE_NOT_INITIALIZED})
        )
    indices = await storage.list_indices()
    matching = [idx for idx in indices if idx.name == index_name]
    if not matching:
        return JSONResponse(
            create_response(error={"code": -32604, "message": f"Index not found: {index_name}"})
        )
    idx = matching[0]
    output = {
        "name": idx.name,
        "document_count": idx.document_count,  # type: ignore[dict-item]
    }
    return JSONResponse(
        create_response(
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": _MEDIA_TYPE_JSON,
                        "text": json.dumps(output, indent=2, default=str),
                    }
                ]
            }
        )
    )


async def _rpc_read_knowledgebase_resource(
    uri: str, create_response: Callable[..., dict[str, Any]]
) -> JSONResponse | None:
    """Handle a knowledgebase:// resource-read URI, or return None if not applicable."""
    if not (uri.startswith("knowledgebase://") and _storage):
        return None
    try:
        # Format: knowledgebase://index_name or knowledgebase://index_name/doc_id
        remainder = uri.replace("knowledgebase://", "")
        parts = remainder.split("/", 1)
        index_name = parts[0].strip() if parts[0].strip() else None
        doc_id = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None

        if not index_name:
            return JSONResponse(
                create_response(
                    error={
                        "code": -32604,
                        "message": "Invalid knowledgebase URI: missing index name",
                    }
                )
            )

        if doc_id:
            return await _rpc_read_knowledgebase_document(uri, index_name, doc_id, create_response)
        return await _rpc_read_knowledgebase_index(uri, index_name, create_response)
    except Exception as e:
        logger.error("Failed to read knowledgebase resource", error=str(e), uri=uri)
        return JSONResponse(
            create_response(
                error={
                    "code": -32604,
                    "message": f"Failed to read resource: {e}",
                }
            )
        )


async def _rpc_resources_read(
    params: dict[str, Any], create_response: Callable[..., dict[str, Any]]
) -> JSONResponse:
    uri = params.get("uri") if params else None
    if not uri:
        return JSONResponse(create_response(error={"code": -32602, "message": "Missing uri"}))

    runbook_result = await _rpc_read_runbook_resource(uri)
    if runbook_result is not None:
        return JSONResponse(create_response(runbook_result))

    kb_result = await _rpc_read_knowledgebase_resource(uri, create_response)
    if kb_result is not None:
        return kb_result

    return JSONResponse(create_response(error={"code": -32604, "message": "Resource not found"}))


_MCP_RPC_METHODS: dict[str, Callable[[dict[str, Any], Callable[..., dict[str, Any]]], Any]] = {
    "initialize": _rpc_initialize,
    "tools/list": _rpc_tools_list,
    "tools/call": _rpc_tools_call,
    "notifications/initialized": _rpc_notifications_initialized,
    "prompts/list": _rpc_prompts_list,
    "prompts/get": _rpc_prompts_get,
    "resources/list": _rpc_resources_list,
    "resources/read": _rpc_resources_read,
}


async def _handle_mcp_rpcs_request(
    method: str, params: dict[str, Any], request_id: Any
) -> JSONResponse:
    """
    Shared handler for MCP JSON-RPC requests.

    This consolidates the common logic between /mcp/sse POST and /mcp/message endpoints
    to avoid duplication and ensure consistent behavior across transports.
    """

    def create_response(result: Any = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error:
            response["error"] = error
        else:
            response["result"] = result
        return response

    handler = _MCP_RPC_METHODS.get(method)
    if handler is None:
        return JSONResponse(
            create_response(error={"code": -32601, "message": f"Method not found: {method}"})
        )
    return await handler(params, create_response)


def _mcp_invalid_request(message: str, request_id: Any | None = None) -> JSONResponse:
    """Build a JSON-RPC invalid request response."""
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": message},
            "id": request_id,
        },
        status_code=400,
    )


def _get_tool_schema(tool_name: str) -> dict[str, Any]:
    """Get input schema for a tool."""
    return get_default_mcp_tool_schema(tool_name)


def _mcp_error(message: str) -> dict[str, Any]:
    """Create a standard MCP error response."""
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _mcp_text(text: str) -> dict[str, Any]:
    """Create a standard MCP text response."""
    return {"content": [{"type": "text", "text": text}]}


def _coerce_positive_int(value: Any, default: int, minimum: int = 1) -> int:
    """Coerce a value to a bounded positive integer.

    Tries to parse value as int.
    - If parsing fails: return default
    - If parsed value < 0 (negative): return default
    - If parsed value >= minimum: return parsed value
    - If 0 <= parsed value < minimum: return minimum
    """
    try:
        parsed = int(value)
        if parsed < 0:
            return default
        return max(parsed, minimum)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    """Coerce a value to a bounded float."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def _coerce_string_list(value: Any) -> list[str]:
    """Coerce an arbitrary value into a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _normalize_optional_string(value: Any) -> str | None:
    """Normalize optional string arguments into stripped values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _is_unscoped_single_term_query(query: str) -> bool:
    """Return True when the query is a single token without obvious separators."""
    terms = [term for term in query.replace("\n", " ").split(" ") if term.strip()]
    return len(terms) <= 1


def _apply_unscoped_single_term_safeguards(
    *, limit: int, min_score: float, summarize: bool, full_content: bool
) -> tuple[int, float, bool, bool, list[str]]:
    """Apply extra protective defaults for unscoped single-term kb_search queries."""
    notes: list[str] = []
    if limit > _KB_SEARCH_SAFE_UNSCOPED_TOP_K:
        notes.append(
            f"reduced top_k to {_KB_SEARCH_SAFE_UNSCOPED_TOP_K} for unscoped single-term query"
        )
        limit = _KB_SEARCH_SAFE_UNSCOPED_TOP_K
    if min_score < _KB_SEARCH_SAFE_UNSCOPED_MIN_SCORE:
        notes.append(
            f"raised min_score to {_KB_SEARCH_SAFE_UNSCOPED_MIN_SCORE:.2f} for unscoped single-term query"
        )
        min_score = _KB_SEARCH_SAFE_UNSCOPED_MIN_SCORE
    if not summarize:
        notes.append("enabled summarize=true for unscoped single-term query to reduce payload size")
        summarize = True
    if full_content:
        notes.append(
            "disabled full_content for unscoped single-term query to avoid large responses"
        )
        full_content = False
    return limit, min_score, summarize, full_content, notes


def _normalize_kb_search_configuration(
    args: dict[str, Any],
) -> tuple[dict[str, Any], list[str], str | None]:
    """Normalize kb_search arguments and apply protective defaults."""
    query = _normalize_optional_string(args.get("query"))
    if query is None:
        return {}, [], "Missing required parameter: query"

    index_name = _resolve_index_argument(args)
    group = _normalize_optional_string(args.get("group"))
    domain = _normalize_optional_string(args.get("domain"))
    subgroup = _normalize_optional_string(args.get("subgroup"))
    source_repo = _normalize_optional_string(args.get("source_repo"))
    has_scope = any([index_name, group, domain, subgroup, source_repo])

    normalized_query = query.lower()
    broad_unscoped_literals = {"*", "all", "everything", "all docs", "all documents"}
    if normalized_query in broad_unscoped_literals and not has_scope:
        return (
            {},
            [],
            "Query is too broad for an unscoped kb_search call. "
            "Add index_name, group, domain, subgroup, or source_repo before retrying.",
        )

    limit = _coerce_positive_int(
        args.get("top_k", args.get("limit", _KB_SEARCH_SAFE_DEFAULT_TOP_K)),
        default=_KB_SEARCH_SAFE_DEFAULT_TOP_K,
    )
    min_score = _coerce_float(args.get("min_score", 0.5), default=0.5)
    offset = _coerce_positive_int(args.get("offset", 0), default=0, minimum=0)
    summarize = bool(args.get("summarize", True))
    full_content = bool(args.get("full_content", False))

    notes: list[str] = []
    if limit > _KB_SEARCH_SAFE_MAX_TOP_K:
        notes.append(f"capped top_k to {_KB_SEARCH_SAFE_MAX_TOP_K} to keep MCP searches bounded")
        limit = _KB_SEARCH_SAFE_MAX_TOP_K

    if offset > _KB_SEARCH_SAFE_MAX_OFFSET:
        notes.append(
            f"capped offset to {_KB_SEARCH_SAFE_MAX_OFFSET} to prevent deep-scan pagination stalls"
        )
        offset = _KB_SEARCH_SAFE_MAX_OFFSET

    if not has_scope and _is_unscoped_single_term_query(query):
        limit, min_score, summarize, full_content, unscoped_notes = (
            _apply_unscoped_single_term_safeguards(
                limit=limit, min_score=min_score, summarize=summarize, full_content=full_content
            )
        )
        notes.extend(unscoped_notes)

    if full_content and limit > 3:
        notes.append("reduced top_k to 3 because full_content=true increases response size")
        limit = 3

    include_archive = bool(args.get("include_archive", False))

    return (
        {
            "query": query,
            "index_name": index_name,
            "group": group,
            "domain": domain,
            "subgroup": subgroup,
            "source_repo": source_repo,
            "limit": limit,
            "min_score": min_score,
            "offset": offset,
            "summarize": summarize,
            "full_content": full_content,
            "include_archive": include_archive,
        },
        notes,
        None,
    )


def _load_knowledgebase_config() -> dict[str, Any]:
    """Load knowledgebase configuration with a safe empty fallback."""
    try:
        config = settings.load_config_file("knowledgebase.json")
        return config if isinstance(config, dict) else {}
    except Exception:
        return {}


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

    # Convert to string and strip, but handle None specially
    lifecycle_state_str = str(lifecycle_state).strip() if lifecycle_state is not None else ""
    lifecycle_state_final = lifecycle_state_str if lifecycle_state_str else "active"

    return {
        "top_group": str(top_group).strip(),
        "domain": str(domain).strip(),
        "subgroup": str(subgroup).strip(),
        "lifecycle_state": lifecycle_state_final,
    }


def _resolve_search_candidate_index_name(raw_entry: Any, aliases: dict[str, str]) -> str | None:
    """Resolve a single knowledgebase-config index entry to a concrete index name."""
    if not isinstance(raw_entry, dict):
        return None

    index_name_raw = raw_entry.get("name")
    if not isinstance(index_name_raw, str) or not index_name_raw.strip():
        return None

    return _resolve_index_alias(index_name_raw.strip(), aliases)


def _index_matches_search_filters(
    raw_entry: dict[str, Any],
    *,
    group: str,
    domain: str,
    subgroup: str,
    source_repo: str,
) -> bool:
    """Check whether an index config entry matches the normalized search filters."""
    taxonomy = _extract_index_taxonomy(raw_entry)
    candidate_group = taxonomy.get("top_group", "").strip().lower()
    candidate_domain = taxonomy.get("domain", "").strip().lower()
    candidate_subgroup = taxonomy.get("subgroup", "").strip().lower()
    # Extract source_repo from index config (added in Phase 9.2)
    candidate_source_repo = raw_entry.get("source_repo", "").strip()

    if group and candidate_group != group:
        return False
    if domain and candidate_domain != domain:
        return False
    if subgroup and candidate_subgroup != subgroup:
        return False
    return not (source_repo and candidate_source_repo != source_repo)


def _resolve_target_indices_for_search(
    *,
    config: dict[str, Any],
    aliases: dict[str, str],
    index_name: str | None,
    group: str | None,
    domain: str | None,
    subgroup: str | None,
    source_repo: str | None = None,
    include_archive: bool = False,
) -> list[str] | None:
    """Resolve explicit/filtered target indices for a search request.

    Phase 4: unscoped searches no longer return ``None`` (all indices). They
    resolve to the configured domain allowlist so archive dumps never join
    default multi-index search.
    """
    resolved_index_name = _resolve_index_alias(index_name, aliases)
    if resolved_index_name:
        if not include_archive and is_excluded_default_index(resolved_index_name):
            # Explicit archive index still requires include_archive=true.
            return []
        return [resolved_index_name]

    normalized_group = group.strip().lower() if isinstance(group, str) and group.strip() else ""
    normalized_domain = domain.strip().lower() if isinstance(domain, str) and domain.strip() else ""
    normalized_subgroup = (
        subgroup.strip().lower() if isinstance(subgroup, str) and subgroup.strip() else ""
    )
    normalized_source_repo = (
        source_repo.strip() if isinstance(source_repo, str) and source_repo.strip() else ""
    )

    raw_indices = config.get("indices", [])
    if not isinstance(raw_indices, list):
        raw_indices = []

    # Unscoped: domain allowlist only (never all-on-disk indices).
    if not any([normalized_group, normalized_domain, normalized_subgroup, normalized_source_repo]):
        allowlist = default_search_indices_from_config(config)
        targets: list[str] = []
        for name in allowlist:
            resolved = _resolve_index_alias(name, aliases) or name
            if not include_archive and is_excluded_default_index(resolved):
                continue
            if resolved not in targets:
                targets.append(resolved)
        return targets

    targets = []
    for raw_entry in raw_indices:
        candidate_name = _resolve_search_candidate_index_name(raw_entry, aliases)
        if not candidate_name:
            continue
        if not include_archive and is_excluded_default_index(candidate_name):
            continue
        if not _index_matches_search_filters(
            raw_entry,
            group=normalized_group,
            domain=normalized_domain,
            subgroup=normalized_subgroup,
            source_repo=normalized_source_repo,
        ):
            continue
        if candidate_name not in targets:
            targets.append(candidate_name)

    return targets


def _merge_search_results(results: list[SearchResult], limit: int) -> list[SearchResult]:
    """Merge multi-index results with score-ordered de-duplication."""
    deduped: dict[tuple[str, str], SearchResult] = {}
    for result in results:
        key = (result.document.index_name, result.document.id)
        existing = deduped.get(key)
        if existing is None or result.score > existing.score:
            deduped[key] = result

    ranked = sorted(deduped.values(), key=lambda item: item.score, reverse=True)
    return ranked[:limit]


async def _search_with_routing(
    *,
    query_embedding: list[float],
    query_text: str,
    limit: int,
    min_score: float,
    filters: dict[str, Any] | None,
    index_name: str | None = None,
    group: str | None = None,
    domain: str | None = None,
    subgroup: str | None = None,
    source_repo: str | None = None,
    offset: int = 0,
    include_archive: bool = False,
    mode: str | None = None,
    hybrid_alpha: float | None = None,
) -> list[SearchResult]:
    """Search using alias and taxonomy-aware routing with hybrid RAG.

    Default mode is hybrid (kNN/vector + BM25 fusion). Phase 4: default path
    excludes archive indices/documents unless ``include_archive`` is true.
    """
    if _storage is None:
        return []

    config = _load_knowledgebase_config()
    aliases = _get_index_aliases(config)
    search_raw = config.get("search")
    search_cfg: dict[str, Any] = search_raw if isinstance(search_raw, dict) else {}
    exclude_archive_by_default = bool(search_cfg.get("exclude_archive_by_default", True))
    effective_include_archive = bool(include_archive) or not exclude_archive_by_default

    target_indices = _resolve_target_indices_for_search(
        config=config,
        aliases=aliases,
        index_name=index_name,
        group=group,
        domain=domain,
        subgroup=subgroup,
        source_repo=source_repo,
        include_archive=effective_include_archive,
    )
    effective_filters = apply_default_archive_filters(
        filters,
        include_archive=effective_include_archive,
    )

    cache_enabled = is_feature_enabled("kb.search.result_cache", default=True)
    resolved_mode = resolve_search_mode(
        mode if isinstance(mode, str) else None,
        default=(_hybrid_search.default_mode if _hybrid_search else "hybrid"),
    )
    resolved_alpha = (
        float(hybrid_alpha)
        if hybrid_alpha is not None
        else (_hybrid_search.hybrid_alpha if _hybrid_search else 0.7)
    )
    cache_key = _search_cache_key(
        query=f"{resolved_mode}|{resolved_alpha}|{query_text}",
        target_indices=target_indices,
        filters={
            **(effective_filters or {}),
            "_include_archive": effective_include_archive,
        },
        limit=limit,
        min_score=min_score,
        offset=offset,
    )

    if cache_enabled:
        cached = _SEARCH_RESULT_CACHE.get(cache_key)
        now = time.time()
        if cached and (now - cached[0]) <= _SEARCH_RESULT_CACHE_TTL_SECONDS:
            logger.info("search_result_cache", hit=True)
            return cached[1]
        logger.info("search_result_cache", hit=False)

    if not target_indices:
        computed = []
    else:
        hybrid = _hybrid_search
        if hybrid is None:
            hybrid = HybridSearchService(_storage, default_mode="hybrid", hybrid_alpha=0.7)
        with timed_operation(
            "knowledgebase.api.search.storage",
            route=resolved_mode,
            index_count=len(target_indices),
        ):
            computed = await hybrid.search(
                query_text=query_text,
                query_embedding=query_embedding,
                index_names=target_indices,
                limit=limit,
                min_score=min_score,
                filters=effective_filters,
                mode=resolved_mode,
                hybrid_alpha=resolved_alpha,
            )

    if not effective_include_archive and computed:
        computed = [
            result
            for result in computed
            if not should_exclude_archive_document(
                metadata=(
                    result.document.metadata.model_dump()
                    if hasattr(result.document.metadata, "model_dump")
                    else dict(result.document.metadata or {})
                ),
                doc_id=result.document.id,
                include_archive=False,
            )
        ][:limit]

    if cache_enabled:
        _cache_put(
            _SEARCH_RESULT_CACHE,
            cache_key,
            computed,
            max_entries=_MAX_SEARCH_RESULT_CACHE_ENTRIES,
        )

    return computed


def _resolve_index_argument(args: dict[str, Any]) -> str | None:
    """Resolve index argument supporting both index and index_name."""
    index_value = args.get("index")
    aliases = _get_index_aliases(_load_knowledgebase_config())
    if isinstance(index_value, str) and index_value.strip():
        return _resolve_index_alias(index_value.strip(), aliases)
    alias_value = args.get("index_name")
    if isinstance(alias_value, str) and alias_value.strip():
        return _resolve_index_alias(alias_value.strip(), aliases)
    return None


def _read_text_content(path: Path) -> str:
    """Read file content using utf-8 with a permissive fallback."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_bytes().decode("utf-8", errors="ignore")


def _knowledgebase_root() -> Path:
    """Return canonical knowledgebase root path."""
    env_root = os.getenv("KB_KNOWLEDGEBASE_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    workspace_root = os.getenv("KB_WORKSPACE_ROOT", "").strip()
    candidate_roots: list[Path] = []
    if workspace_root:
        base = Path(workspace_root).expanduser()
        candidate_roots.extend(
            [
                (base / "knowledgebase").resolve(),
                (base / ".infraOS" / "knowledgebase").resolve(),
            ]
        )

    cwd = Path.cwd()
    candidate_roots.extend(
        [
            (cwd / "knowledgebase").resolve(),
            (cwd / ".infraOS" / "knowledgebase").resolve(),
        ]
    )

    for candidate in candidate_roots:
        if candidate.exists() and candidate.is_dir():
            return candidate

    return candidate_roots[0]


def _resolve_docs_subpath(subpath: str | None) -> Path | None:
    """Resolve docs subpath while preventing path traversal."""
    root_path = _knowledgebase_root()
    candidate = root_path if not subpath else (root_path / subpath).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError:
        return None
    return candidate


def _extract_frontmatter(text: str) -> dict[str, str]:
    """Extract simple YAML-like frontmatter key-value pairs."""
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}

    frontmatter: dict[str, str] = {}
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip().strip("\"'")
    return frontmatter


async def _sync_local_indices(indices: list[str] | None = None) -> Any:
    """Sync configured indices from local files into this instance's own storage."""
    if not _storage or not _embeddings:
        return None
    sync_service = AegisCMCPSyncService(
        pipeline=IndexingPipeline(storage=_storage, embeddings=_embeddings)
    )
    report = await sync_service.sync_local(indices=indices)
    _clear_search_caches()
    return report


async def _sync_dev_indices(indices: list[str] | None = None) -> Any:
    """Push configured indices from local files to the configured 'dev' AegisCMCP target."""
    targets = load_sync_targets()
    dev_target = targets.get("dev")
    if not isinstance(dev_target, dict) or not dev_target.get("base_url"):
        return "No 'dev' sync target configured in cfg/sync.json"

    base_url = str(dev_target["base_url"])
    api_key_env = dev_target.get("api_key_env")
    api_key = os.getenv(api_key_env) if isinstance(api_key_env, str) and api_key_env else None

    sync_service = AegisCMCPSyncService()
    return await sync_service.sync_dev(base_url=base_url, api_key=api_key, indices=indices)


async def _mcp_tool_kb_get_document(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)
    doc_id_value = args.get("doc_id", args.get("id"))
    doc_id = doc_id_value.strip() if isinstance(doc_id_value, str) else ""
    if not doc_id:
        return fail("Missing required parameter: doc_id or id")

    index_name = _resolve_index_argument(args)
    if not index_name:
        return fail("Missing required parameter: index or index_name")

    try:
        doc = await _storage.get_document(doc_id, index_name)
        if not doc:
            return fail(f"Document '{doc_id}' not found in index '{index_name}'")

        # Return document with full content
        output = {
            "id": doc.id,
            "index": doc.index_name,
            "content": doc.content,
            "metadata": (
                doc.metadata.model_dump()
                if hasattr(doc.metadata, "model_dump")
                else dict(doc.metadata)
            ),
            "has_embedding": doc.has_embedding,
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))
    except Exception as e:
        return fail(f"Failed to retrieve document: {e}")


async def _mcp_tool_kb_search(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _embeddings or not _storage:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    (
        normalized_search,
        search_notes,
        search_error,
    ) = _normalize_kb_search_configuration(args)
    if search_error:
        return fail(search_error)

    query = str(normalized_search["query"])
    index_name = (
        normalized_search["index_name"]
        if isinstance(normalized_search.get("index_name"), str)
        else None
    )
    limit = int(normalized_search["limit"])
    min_score = float(normalized_search["min_score"])
    group = normalized_search["group"] if isinstance(normalized_search.get("group"), str) else None
    domain = (
        normalized_search["domain"] if isinstance(normalized_search.get("domain"), str) else None
    )
    subgroup = (
        normalized_search["subgroup"]
        if isinstance(normalized_search.get("subgroup"), str)
        else None
    )
    source_repo = (
        normalized_search["source_repo"]
        if isinstance(normalized_search.get("source_repo"), str)
        else None
    )
    summarize = bool(normalized_search["summarize"])
    full_content = bool(normalized_search["full_content"])
    offset = int(normalized_search["offset"])
    include_archive = bool(normalized_search.get("include_archive", False))

    if search_notes:
        logger.info(
            "kb_search_safeguards_applied",
            query=query,
            notes=search_notes,
            index_name=index_name,
            group=group,
            domain=domain,
            subgroup=subgroup,
            source_repo=source_repo,
            limit=limit,
            min_score=min_score,
            offset=offset,
            include_archive=include_archive,
        )

    try:
        query_embedding = await asyncio.wait_for(
            _get_query_embedding(query), timeout=_QUERY_EMBED_TIMEOUT_SECONDS
        )
    except (TimeoutError, asyncio.TimeoutError):
        return fail("Embedding timed out")
    mode_arg = args.get("mode") if isinstance(args.get("mode"), str) else None
    alpha_arg = args.get("hybrid_alpha", args.get("vector_weight"))
    hybrid_alpha = None
    if alpha_arg is not None:
        hybrid_alpha = _coerce_float(alpha_arg, default=0.7, minimum=0.0, maximum=1.0)
    results = await _search_with_routing(
        query_embedding=query_embedding,
        query_text=query,
        limit=limit + offset,  # Request extra results for pagination
        min_score=min_score,
        filters=None,
        index_name=index_name,
        group=group,
        domain=domain,
        subgroup=subgroup,
        source_repo=source_repo,
        offset=offset,
        include_archive=include_archive,
        mode=mode_arg,
        hybrid_alpha=hybrid_alpha,
    )

    # Apply pagination offset
    paginated_results = results[offset : offset + limit]
    safety_lines = (
        ["Applied kb_search safeguards:"] + [f"- {note}" for note in search_notes] + [""]
        if search_notes
        else []
    )

    if summarize:
        if not paginated_results:
            return _mcp_text(
                "\n".join(safety_lines + [f"No results found for '{query}' at offset {offset}."])
            )
        lines = safety_lines + [
            f"Top {len(paginated_results)} result(s) for '{query}' (offset {offset}):",
            "",
        ]
        for index, search_result in enumerate(paginated_results, 1):
            title = search_result.document.metadata.title or search_result.document.id
            snippet = search_result.document.content.strip().replace("\n", " ")[:160]
            lines.append(f"{index}. [{search_result.score:.2f}] {title} — {snippet}")
        return _mcp_text("\n".join(lines))

    result_text = f"Found {len(results)} total result(s) for '{query}' (showing {len(paginated_results)} at offset {offset}):\n\n"
    for i, search_result in enumerate(paginated_results, 1):
        if full_content:
            content = search_result.document.content
        else:
            content = search_result.document.content[:200]
        result_text += f"{i}. [{search_result.score:.2f}] {content}...\n\n"
    if safety_lines:
        result_text = "\n".join(safety_lines) + result_text

    return _mcp_text(result_text)


async def _mcp_tool_kb_index_list(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    indices = await _storage.list_indices()
    result_text = f"Available indices ({len(indices)}):\n\n"
    for idx in indices:
        result_text += f"- {idx.name}: {idx.document_count} documents\n"

    return _mcp_text(result_text)


async def _mcp_tool_kb_index_create(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    name_value = args.get("name")
    name = name_value.strip() if isinstance(name_value, str) else ""
    if not name:
        return fail(_ERR_MISSING_PARAM_NAME)

    await _storage.create_index(name)
    return _mcp_text(f"Index '{name}' created successfully.")


async def _mcp_tool_kb_index_delete(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    name_value = args.get("name")
    name = name_value.strip() if isinstance(name_value, str) else ""
    if not name:
        return fail(_ERR_MISSING_PARAM_NAME)

    await _storage.delete_index(name)
    return _mcp_text(f"Index '{name}' deleted successfully.")


async def _mcp_tool_kb_add_document_or_kb_add_file(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage or not _embeddings:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    if tool_name == "kb_add_document":
        doc_id_value = args.get("id")
        doc_id = doc_id_value.strip() if isinstance(doc_id_value, str) else ""
        content_value = args.get("content")
        content = content_value if isinstance(content_value, str) else ""
        index_name = _resolve_index_argument(args) or "knowledgebase"
        title = doc_id
        source_path_value = args.get("path")
        source_path: str | None = source_path_value if isinstance(source_path_value, str) else None
    else:
        path_value = args.get("path")
        raw_path = path_value.strip() if isinstance(path_value, str) else ""
        if not raw_path:
            return fail(_ERR_MISSING_PARAM_PATH)
        file_path = Path(raw_path).expanduser()
        if not file_path.exists() or not file_path.is_file():
            return fail(f"File not found: {file_path}")
        content = _read_text_content(file_path)
        index_name_value = _resolve_index_argument(args)
        if not index_name_value:
            return fail("Missing required parameter: index")
        index_name = index_name_value
        doc_id = file_path.stem
        title_value = args.get("title")
        title = title_value if isinstance(title_value, str) and title_value else file_path.name
        source_path = str(file_path.resolve())

    if not doc_id:
        return fail("Missing required parameter: id")
    if not content.strip():
        return fail("Document content is empty")

    # Phase 5: Async write path behind OpenFeature flag (kb.write.async)
    from knowledgebase.core.feature_flags import is_feature_enabled

    async_writes_enabled = is_feature_enabled("kb.write.async", default=False)

    # Prefer full IndexingPipeline when requested (push-multi / explicit clients).
    full_index = bool(args.get("full_index", True if tool_name == "kb_add_document" else False))
    chunk = bool(args.get("chunk", True))
    metadata_extra: dict[str, Any] = {}
    raw_metadata = args.get("metadata")
    if isinstance(raw_metadata, dict):
        metadata_extra = dict(raw_metadata)

    if full_index:
        try:
            pipeline = IndexingPipeline(storage=_storage, embeddings=_embeddings)
            pipeline_metadata: dict[str, Any] = {
                "title": title,
                "path": source_path,
                "source_type": "file" if tool_name == "kb_add_file" else "api",
                **metadata_extra,
            }
            indexed_docs = await asyncio.wait_for(
                pipeline.index_text(
                    content=content,
                    doc_id=doc_id,
                    index_name=index_name,
                    metadata=pipeline_metadata,
                    chunk=chunk,
                ),
                timeout=_DOCUMENT_EMBED_TIMEOUT_SECONDS,
            )
        except (TimeoutError, asyncio.TimeoutError):
            return fail(_ERR_DOCUMENT_EMBEDDING_TIMED_OUT)
        except Exception as e:
            return fail(f"Full indexing pipeline failed: {e}")
        if not indexed_docs or not indexed_docs[0].has_embedding:
            return fail("Full indexing pipeline completed without embeddings")
        return _mcp_text(
            json.dumps(
                {
                    "success": True,
                    "id": doc_id,
                    "index_name": index_name,
                    "has_embedding": True,
                    "chunks": len(indexed_docs),
                    "full_index": True,
                },
                indent=2,
                default=str,
            )
        )

    if async_writes_enabled:
        # Async path: upsert catalog with index_status=pending, return immediately
        # TODO: Implement full catalog upsert at .infraOS/state/knowledge-catalog.json
        # For now, just add to index without embedding (will be generated on next sync)
        document = Document(
            id=doc_id,
            content=content,
            embedding=None,  # Deferred to next sync tick
            index_name=index_name,
            metadata=DocumentMetadata(
                title=title,
                path=source_path,
                source_type="file" if tool_name == "kb_add_file" else "api",
                extra={"index_status": "pending", "async_write": True},
            ),
        )
        await _storage.add_document(document)
        return _mcp_text(
            f"Queued document '{doc_id}' for async indexing in '{index_name}' "
            "(embedding will be generated on next sync)."
        )
    else:
        # Legacy synchronous path (default)
        try:
            embedding = await _get_document_embedding(content)
        except (TimeoutError, asyncio.TimeoutError):
            return fail(_ERR_DOCUMENT_EMBEDDING_TIMED_OUT)
        document = Document(
            id=doc_id,
            content=content,
            embedding=embedding,
            index_name=index_name,
            metadata=DocumentMetadata(
                title=title,
                path=source_path,
                source_type="file" if tool_name == "kb_add_file" else "api",
            ),
        )
        await _storage.add_document(document)
        return _mcp_text(
            json.dumps(
                {
                    "success": True,
                    "id": doc_id,
                    "index_name": index_name,
                    "has_embedding": True,
                    "full_index": False,
                },
                indent=2,
                default=str,
            )
        )


async def _mcp_tool_kb_remove_document(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    doc_id_value = args.get("doc_id")
    doc_id = doc_id_value.strip() if isinstance(doc_id_value, str) else ""
    if not doc_id:
        return fail("Missing required parameter: doc_id")

    index_name = _resolve_index_argument(args)
    if index_name:
        deleted = await _storage.delete_document(doc_id, index_name)
        if not deleted:
            return fail(f"Document '{doc_id}' not found in index '{index_name}'.")
        return _mcp_text(f"Removed document '{doc_id}' from index '{index_name}'.")

    # No index provided, try all indices.
    indices = await _storage.list_indices()
    for idx in indices:
        deleted = await _storage.delete_document(doc_id, idx.name)
        if deleted:
            return _mcp_text(f"Removed document '{doc_id}' from index '{idx.name}'.")
    return fail(f"Document '{doc_id}' was not found in any index.")


async def _mcp_tool_kb_sync_all(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    target_value = str(args.get("target") or "local").strip().lower()

    if target_value == "local":
        if not _storage or not _embeddings:
            return fail(_ERR_SERVICE_NOT_INITIALIZED)
        local_report = await _sync_local_indices()
        return _mcp_text(json.dumps(local_report.to_dict(), indent=2, default=str))

    if target_value == "dev":
        dev_result = await _sync_dev_indices()
        if isinstance(dev_result, str):
            return fail(dev_result)
        return _mcp_text(json.dumps(dev_result.to_dict(), indent=2, default=str))

    return fail(f"Unknown sync target: '{target_value}'. Use 'local' or 'dev'.")


async def _mcp_tool_docs_kb_list(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    root_path = _knowledgebase_root()
    extension_value = args.get("extension", ".md")
    extension = extension_value if isinstance(extension_value, str) else ".md"
    if extension and not extension.startswith("."):
        extension = f".{extension}"
    limit = _coerce_positive_int(args.get("limit", 50), default=50)
    path_value = args.get("path")
    subpath = path_value if isinstance(path_value, str) else ""
    target_path = _resolve_docs_subpath(subpath)
    if target_path is None:
        return fail(_ERR_INVALID_PATH_KNOWLEDGEBASE)
    if not target_path.exists():
        return fail(f"Path not found: {target_path}")

    files: list[dict[str, Any]] = []
    for file_path in target_path.rglob(f"*{extension}"):
        if len(files) >= limit:
            break
        rel_path = file_path.relative_to(root_path)
        files.append(
            {
                "name": file_path.name,
                "path": str(rel_path),
                "size": file_path.stat().st_size,
            }
        )

    output = {
        "path": str(target_path),
        "extension": extension,
        "count": len(files),
        "truncated": len(files) >= limit,
        "files": files,
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_docs_kb_search(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    pattern_value = args.get("pattern")
    pattern = pattern_value.strip() if isinstance(pattern_value, str) else ""
    if not pattern:
        return fail("Missing required parameter: pattern")

    root_path = _knowledgebase_root()
    path_value = args.get("path")
    subpath = path_value if isinstance(path_value, str) else ""
    target_path = _resolve_docs_subpath(subpath)
    if target_path is None:
        return fail(_ERR_INVALID_PATH_KNOWLEDGEBASE)
    if not target_path.exists():
        return fail(f"Path not found: {target_path}")

    pattern_lower = pattern.lower()
    matches: list[dict[str, Any]] = []
    for file_path in target_path.rglob("*"):
        if file_path.is_file() and pattern_lower in file_path.name.lower():
            rel_path = file_path.relative_to(root_path)
            matches.append(
                {
                    "name": file_path.name,
                    "path": str(rel_path),
                    "size": file_path.stat().st_size,
                }
            )

    output = {
        "pattern": pattern,
        "path": str(target_path),
        "count": len(matches),
        "matches": matches[:100],
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_docs_read_meta(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    path_value = args.get("path")
    relative_path = path_value.strip() if isinstance(path_value, str) else ""
    if not relative_path:
        return fail(_ERR_MISSING_PARAM_PATH)

    root_path = _knowledgebase_root()
    doc_path = _resolve_docs_subpath(relative_path)
    if doc_path is None:
        return fail(_ERR_INVALID_PATH_KNOWLEDGEBASE)
    if not doc_path.exists() or not doc_path.is_file():
        return fail(f"Document not found: {relative_path}")

    stat = doc_path.stat()
    content = _read_text_content(doc_path)
    output = {
        "path": str(doc_path.relative_to(root_path)),
        "name": doc_path.name,
        "extension": doc_path.suffix,
        "size_bytes": stat.st_size,
        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "frontmatter": _extract_frontmatter(content),
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_docs_read_content(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    path_value = args.get("path")
    relative_path = path_value.strip() if isinstance(path_value, str) else ""
    if not relative_path:
        return fail(_ERR_MISSING_PARAM_PATH)

    root_path = _knowledgebase_root()
    doc_path = _resolve_docs_subpath(relative_path)
    if doc_path is None:
        return fail(_ERR_INVALID_PATH_KNOWLEDGEBASE)
    if not doc_path.exists() or not doc_path.is_file():
        return fail(f"Document not found: {relative_path}")

    # Get size limit (default 1MB, max 10MB)
    size_limit_bytes = (
        _coerce_positive_int(args.get("size_limit_kb", 1024), default=1024, minimum=1) * 1024
    )
    max_size_bytes = 10 * 1024 * 1024  # 10MB hard limit
    if size_limit_bytes > max_size_bytes:
        size_limit_bytes = max_size_bytes

    try:
        stat = doc_path.stat()
        if stat.st_size > size_limit_bytes:
            return fail(
                f"Document too large: {stat.st_size} bytes exceeds limit of {size_limit_bytes} bytes. "
                f"Use size_limit_kb parameter to increase the limit."
            )

        content = _read_text_content(doc_path)
        output = {
            "path": str(doc_path.relative_to(root_path)),
            "name": doc_path.name,
            "size_bytes": stat.st_size,
            "content": content,
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))
    except Exception as e:
        return fail(f"Failed to read document: {e}")


async def _mcp_tool_docs_kb_info(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    root_path = _knowledgebase_root()
    if not root_path.exists():
        output = {
            "root_path": str(root_path),
            "exists": False,
            "file_count": 0,
            "directory_count": 0,
            "extensions": {},
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))

    file_count = 0
    directory_count = 0
    extensions: dict[str, int] = {}
    for candidate in root_path.rglob("*"):
        if candidate.is_dir():
            directory_count += 1
            continue
        if candidate.is_file():
            file_count += 1
            extension = candidate.suffix.lower() or "<none>"
            extensions[extension] = extensions.get(extension, 0) + 1

    output = {
        "root_path": str(root_path),
        "exists": True,
        "file_count": file_count,
        "directory_count": directory_count,
        "extensions": dict(sorted(extensions.items())),
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_docs_list_dirs(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    limit = _coerce_positive_int(args.get("limit", 200), default=200)
    path_value = args.get("path")
    subpath = path_value if isinstance(path_value, str) else ""

    root_path = _knowledgebase_root()
    target_path = _resolve_docs_subpath(subpath)
    if target_path is None:
        return fail(_ERR_INVALID_PATH_KNOWLEDGEBASE)
    if not target_path.exists() or not target_path.is_dir():
        return fail(f"Path not found: {target_path}")

    all_dirs = [target_path]
    all_dirs.extend(candidate for candidate in target_path.rglob("*") if candidate.is_dir())

    directories: list[str] = []
    for directory in sorted(all_dirs):
        rel_path = directory.relative_to(root_path)
        relative = str(rel_path) if str(rel_path) else "."
        directories.append(relative)
        if len(directories) >= limit:
            break

    output = {
        "path": str(target_path),
        "count": len(directories),
        "truncated": len(all_dirs) > limit,
        "directories": directories,
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_kb_health(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    health_data = await health_check()
    return _mcp_text(f"Status: {health_data.status}\nVersion: {health_data.version}")


async def _mcp_tool_kb_stats(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _system_service:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    stats = await _system_service.get_system_stats()
    return _mcp_text(
        "Documents: "
        f"{stats.total_documents}\n"
        f"Indices: {stats.total_indices}\n"
        f"Uptime: {stats.uptime_seconds:.0f}s"
    )


async def _mcp_tool_kb_search_config_get(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    hybrid = _hybrid_search
    alpha = hybrid.hybrid_alpha if hybrid else float(getattr(settings.search, "hybrid_alpha", 0.7))
    mode = hybrid.default_mode if hybrid else resolve_search_mode(os.getenv("KB_SEARCH_MODE"), "hybrid")
    output = {
        "mode": mode,
        "bm25_weight": round(1.0 - alpha, 4),
        "vector_weight": round(alpha, 4),
        "hybrid_alpha": round(alpha, 4),
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_kb_search_config_set(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    global _hybrid_search
    mode = resolve_search_mode(
        args.get("mode") if isinstance(args.get("mode"), str) else None,
        default="hybrid",
    )
    if "vector_weight" in args or "hybrid_alpha" in args:
        vector_weight = _coerce_float(
            args.get("vector_weight", args.get("hybrid_alpha", 0.7)),
            default=0.7,
            minimum=0.0,
            maximum=1.0,
        )
    elif "bm25_weight" in args:
        bm25_weight = _coerce_float(args.get("bm25_weight", 0.3), default=0.3, minimum=0.0, maximum=1.0)
        vector_weight = max(0.0, min(1.0, 1.0 - bm25_weight))
    else:
        vector_weight = _hybrid_search.hybrid_alpha if _hybrid_search else 0.7
    bm25_weight = max(0.0, min(1.0, 1.0 - vector_weight))
    if _storage is None:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)
    _hybrid_search = HybridSearchService(
        _storage,
        default_mode=mode,
        hybrid_alpha=vector_weight,
    )
    output = {
        "mode": mode,
        "bm25_weight": bm25_weight,
        "vector_weight": vector_weight,
        "hybrid_alpha": vector_weight,
        "status": "Configuration updated (in-memory only; persists only in current session)",
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_kb_taxonomy_list(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    # Extract distinct taxonomy values from configuration
    config = _load_knowledgebase_config()
    raw_indices = config.get("indices", [])
    if not isinstance(raw_indices, list):
        return fail("Invalid knowledgebase configuration")

    groups = set()
    domains = set()
    subgroups = set()

    for entry in raw_indices:
        if not isinstance(entry, dict):
            continue
        taxonomy = _extract_index_taxonomy(entry)
        if taxonomy.get("top_group"):
            groups.add(taxonomy["top_group"])
        if taxonomy.get("domain"):
            domains.add(taxonomy["domain"])
        if taxonomy.get("subgroup"):
            subgroups.add(taxonomy["subgroup"])

    output = {
        "groups": sorted(groups),
        "domains": sorted(domains),
        "subgroups": sorted(subgroups),
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_kb_index_info(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    name_value = args.get("name")
    index_name = name_value.strip() if isinstance(name_value, str) else ""
    if not index_name:
        return fail(_ERR_MISSING_PARAM_NAME)

    try:
        indices = await _storage.list_indices()
        matching = [idx for idx in indices if idx.name == index_name]
        if not matching:
            return fail(f"Index not found: {index_name}")

        idx = matching[0]
        config = _load_knowledgebase_config()
        raw_indices = config.get("indices", [])
        index_config = next(
            (e for e in raw_indices if isinstance(e, dict) and e.get("name") == index_name),
            {},
        )
        taxonomy = _extract_index_taxonomy(index_config)

        output = {
            "name": idx.name,
            "document_count": idx.document_count,
            "metadata_schema": getattr(idx, "metadata_schema", {}),
            "taxonomy": taxonomy,
            "tags": _coerce_string_list(index_config.get("tags", [])),
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))
    except Exception as e:
        return fail(f"Failed to retrieve index info: {e}")


async def _mcp_tool_kb_embedding_info(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _embeddings:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    try:
        # Return embedding provider information
        output = {
            "provider": _embeddings.__class__.__name__,
            "model": getattr(_embeddings, "model_name", "unknown"),
            "dimensions": getattr(_embeddings, "embedding_dimensions", None),
            "status": "operational",
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))
    except Exception as e:
        return fail(f"Failed to retrieve embedding info: {e}")


async def _mcp_tool_kb_rag_config_get(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    # Return current RAG configuration
    config = _load_rag_config()  # type: ignore[assignment]
    output = {
        "top_k": config.top_k,  # type: ignore[attr-defined]
        "min_score": config.min_score,  # type: ignore[attr-defined]
        "default_index": config.default_index,  # type: ignore[attr-defined]
        "max_context_tokens": config.max_context_tokens,  # type: ignore[attr-defined]
        "max_answer_tokens": config.max_answer_tokens,  # type: ignore[attr-defined]
        "include_sources": config.include_sources,  # type: ignore[attr-defined]
        "use_reranker": config.use_reranker,  # type: ignore[attr-defined]
        "return_debug_metadata": config.return_debug_metadata,  # type: ignore[attr-defined]
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_kb_rag_config_set(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    # Set RAG configuration parameters
    config = _load_rag_config()  # type: ignore[assignment]
    top_k = _coerce_positive_int(args.get("top_k", config.top_k), default=config.top_k, minimum=1)  # type: ignore[attr-defined]
    min_score = _coerce_float(args.get("min_score", config.min_score), default=config.min_score)  # type: ignore[attr-defined]
    use_reranker = bool(args.get("use_reranker", config.use_reranker))  # type: ignore[attr-defined]

    # Create updated config
    updated = RagConfig(
        top_k=top_k,
        min_score=min_score,
        default_index=config.default_index,  # type: ignore[attr-defined]
        max_context_tokens=config.max_context_tokens,  # type: ignore[attr-defined]
        max_answer_tokens=config.max_answer_tokens,  # type: ignore[attr-defined]
        include_sources=config.include_sources,  # type: ignore[attr-defined]
        use_reranker=use_reranker,
        return_debug_metadata=config.return_debug_metadata,  # type: ignore[attr-defined]
    )
    _save_rag_config(updated)

    output = {
        "status": "Configuration updated",
        "top_k": updated.top_k,
        "min_score": updated.min_score,
        "use_reranker": updated.use_reranker,
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_runbook_search(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    # Search runbooks by name/content relevance.

    query_value = args.get("query", "")
    query = query_value.strip() if isinstance(query_value, str) else ""
    if not query:
        return fail("Missing required parameter: query")

    limit = _coerce_positive_int(args.get("limit", 10), default=10)

    try:
        # Import and use runbook module if available
        from knowledgebase.runbooks.service import RunbookService

        rb_service = RunbookService()
        # List all runbooks and score by relevance
        rb_data = rb_service.list_runbooks()
        runbooks = rb_data.get("runbooks", [])

        if not runbooks:
            output = {"query": query, "results": [], "matches": [], "count": 0}
            return _mcp_text(json.dumps(output, indent=2, default=str))
        query_lower = query.lower()
        scored: list[tuple[str, float]] = []
        for rb in runbooks:
            rb_name_value = rb.get("name")
            rb_name = rb_name_value.strip() if isinstance(rb_name_value, str) else ""
            if not rb_name:
                continue
            rb_record = rb_service.get_runbook(rb_name) or {}
            content_value = rb_record.get("content", "")
            content = content_value.lower() if isinstance(content_value, str) else ""
            name = rb_name.lower()
            score = 0.0
            if name == query_lower:
                score += 2.0
            elif query_lower in name:
                score += 1.0
            if query_lower in content:
                score += 0.75
            if score > 0:
                scored.append((rb_name, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        top_matches = scored[:limit]

        output = {
            "query": query,
            "results": [name for name, _ in top_matches],
            "matches": [{"name": name, "score": round(score, 3)} for name, score in top_matches],
            "count": len(top_matches),
            "total_matches": len(scored),
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))
    except Exception as e:
        return fail(f"Runbook search failed: {e}")


async def _mcp_tool_kb_index_directory(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage or not _embeddings:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    path_value = args.get("path")
    path = path_value.strip() if isinstance(path_value, str) else ""
    if not path:
        return fail(_ERR_MISSING_PARAM_PATH)

    index_name = _resolve_index_argument(args)
    if not index_name:
        return fail("Missing required parameter: index")

    pattern = args.get("pattern", "*.md") if isinstance(args.get("pattern"), str) else "*.md"
    max_files = _coerce_positive_int(
        args.get("max_files", _KB_INDEX_DIRECTORY_DEFAULT_MAX_FILES),
        default=_KB_INDEX_DIRECTORY_DEFAULT_MAX_FILES,
    )
    if max_files > _KB_INDEX_DIRECTORY_MAX_FILES_CAP:
        max_files = _KB_INDEX_DIRECTORY_MAX_FILES_CAP
    time_budget_seconds = _coerce_positive_int(
        args.get(
            "time_budget_seconds",
            _KB_INDEX_DIRECTORY_DEFAULT_TIME_BUDGET_SECONDS,
        ),
        default=_KB_INDEX_DIRECTORY_DEFAULT_TIME_BUDGET_SECONDS,
    )
    max_time_budget = max(
        5,
        int(_MCP_TOOL_TIMEOUT_SECONDS) - 1,
    )
    if time_budget_seconds > max_time_budget:
        time_budget_seconds = max_time_budget

    try:
        dir_path = Path(path).expanduser()
        if not dir_path.exists() or not dir_path.is_dir():
            return fail(f"Directory not found: {dir_path}")
        scan_start = time.time()

        files_indexed = 0
        files_scanned = 0
        truncated = False
        errors: list[str] = []

        for file_path in dir_path.rglob(pattern):
            if not file_path.is_file():
                continue
            files_scanned += 1
            if files_scanned > max_files:
                truncated = True
                break
            if (time.time() - scan_start) >= time_budget_seconds:
                truncated = True
                break
            try:
                content = _read_text_content(file_path)
                if not content.strip():
                    continue
                embedding = await _get_document_embedding(content)
                doc_id = file_path.stem
                document = Document(
                    id=doc_id,
                    content=content,
                    embedding=embedding,
                    index_name=index_name,
                    metadata=DocumentMetadata(
                        title=file_path.name,
                        path=str(file_path.resolve()),
                        source_type="file",
                    ),
                )
                await _storage.add_document(document)
                files_indexed += 1
            except Exception as file_error:
                errors.append(str(file_error))

        output = {
            "path": str(dir_path),
            "pattern": pattern,
            "max_files": max_files,
            "time_budget_seconds": time_budget_seconds,
            "files_scanned": files_scanned,
            "files_indexed": files_indexed,
            "truncated": truncated,
            "errors": errors if errors else None,
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))
    except Exception as e:
        return fail(f"Failed to index directory: {e}")


async def _mcp_tool_kb_upsert_document(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage or not _embeddings:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    doc_id_value = args.get("id")
    doc_id = doc_id_value.strip() if isinstance(doc_id_value, str) else ""
    content_value = args.get("content")
    content = content_value if isinstance(content_value, str) else ""
    index_name = _resolve_index_argument(args) or "knowledgebase"

    # Phase 9.4: Extract federation metadata
    title_value = args.get("title")
    title = title_value.strip() if isinstance(title_value, str) and title_value else doc_id
    source_repo_value = args.get("source_repo")
    source_repo = (
        source_repo_value.strip()
        if isinstance(source_repo_value, str) and source_repo_value
        else None
    )
    source_vcs_value = args.get("source_vcs")
    source_vcs = (
        source_vcs_value.strip()
        if isinstance(source_vcs_value, str) and source_vcs_value
        else "github"
    )
    upsert_path_value = args.get("path")
    upsert_path: str | None = (
        upsert_path_value.strip()
        if isinstance(upsert_path_value, str) and upsert_path_value
        else None
    )

    if not doc_id:
        return fail("Missing required parameter: id")
    if not content.strip():
        return fail("Document content is empty")

    try:
        # Delete if exists
        await _storage.delete_document(doc_id, index_name)
        # Add new version with federation metadata
        embedding = await _get_document_embedding(content)

        # Build extra metadata dict for federation
        extra_metadata: dict[str, str] = {}
        if source_repo:
            extra_metadata["source_repo"] = source_repo
        if source_vcs:
            extra_metadata["source_vcs"] = source_vcs

        document = Document(
            id=doc_id,
            content=content,
            embedding=embedding,
            index_name=index_name,
            metadata=DocumentMetadata(
                title=title,
                repository=source_repo,  # Use native repository field
                source_type="api",
                path=upsert_path,
                extra=extra_metadata,
            ),
        )
        await _storage.add_document(document)

        # Build response message with attribution
        response_msg = f"Document '{doc_id}' upserted successfully in index '{index_name}'"
        if source_repo:
            response_msg += f" (source: {source_repo})"
        return _mcp_text(response_msg)
    except Exception as e:
        return fail(f"Failed to upsert document: {e}")


async def _mcp_tool_kb_add_documents_batch(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage or not _embeddings:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    docs_value = args.get("documents")
    if not isinstance(docs_value, list):
        return fail("Missing required parameter: documents (must be array)")

    if len(docs_value) > 50:
        return fail(f"Batch size {len(docs_value)} exceeds limit of 50 documents")

    index_name = _resolve_index_argument(args) or "knowledgebase"
    added_count = 0
    errors = []

    try:
        for doc_spec in docs_value:
            if not isinstance(doc_spec, dict):
                errors.append("Invalid document specification")
                continue

            doc_id = doc_spec.get("id")  # type: ignore[assignment]
            doc_content = doc_spec.get("content")

            if not doc_id or not doc_content:
                errors.append("Document missing id or content")
                continue

            try:
                embedding = await _get_document_embedding(str(doc_content))
                document = Document(
                    id=str(doc_id),
                    content=str(doc_content),
                    embedding=embedding,
                    index_name=index_name,
                    metadata=DocumentMetadata(
                        title=str(doc_spec.get("title", doc_id)),
                        source_type="api",
                    ),
                )
                await _storage.add_document(document)
                added_count += 1
            except Exception as doc_error:
                errors.append(f"Error adding {doc_id}: {doc_error}")

        output = {
            "added": added_count,
            "total": len(docs_value),
            "errors": errors if errors else None,
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))
    except Exception as e:
        return fail(f"Batch add failed: {e}")


async def _mcp_tool_kb_index_reindex(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    if not _storage or not _embeddings:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)

    name_value = args.get("name")
    index_name = name_value.strip() if isinstance(name_value, str) else ""
    if not index_name:
        return fail(_ERR_MISSING_PARAM_NAME)

    try:
        # Page through ALL documents in the index. The previous
        # implementation only fetched a single page
        # (offset=0, limit=10000) and silently ignored any documents
        # beyond that -- on the "knowledge" index (30k+ documents)
        # this meant a "reindex" only ever touched the first 10,000
        # docs and reported a misleadingly-labeled "total" for the
        # full index size while "reindexed" stalled at 10000 forever
        # on repeat calls (see feedback_mcp_status_check_bugs memory).
        reindexed = 0
        errors = []
        offset = 0
        page_size = 500
        total = 0

        while True:
            docs, total = await _storage.list_documents(index_name, offset=offset, limit=page_size)

            for doc in docs:
                try:
                    # Re-embed each document
                    embedding = await _get_document_embedding(doc.content)
                    doc.embedding = embedding
                    await _storage.add_document(doc)
                    reindexed += 1
                except Exception as doc_error:
                    errors.append(str(doc_error))

            # Advance by the fixed page window (not len(docs)):
            # list_documents may now silently skip individual
            # unreadable files within a page (see local.py's
            # list_documents), so len(docs) can be less than
            # page_size even when more valid documents remain
            # further in the file list. Advancing by page_size and
            # only stopping once we've walked past the full file
            # count keeps pagination aligned regardless of skips.
            offset += page_size
            if offset >= total:
                break

        output = {
            "index": index_name,
            "reindexed": reindexed,
            "total": total,
            "errors": errors if errors else None,
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))
    except Exception as e:
        return fail(f"Reindex failed: {e}")


async def _mcp_tool_kb_search_analytics(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    # Return search analytics (placeholder - in-memory tracking not yet implemented)
    limit = _coerce_positive_int(args.get("limit", 20), default=20)
    order_by = args.get("order_by", "recent") if isinstance(args.get("order_by"), str) else "recent"

    output = {
        "status": "analytics_tracking_not_yet_enabled",
        "message": "Search analytics will track queries once AegisCMCP is restarted with analytics enabled",
        "limit": limit,
        "order_by": order_by,
        "recent_queries": [],
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_infraos_ping(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    output = {
        "status": "pong",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "1NMCP",
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_infraos_context(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    now = datetime.now()
    cwd = os.getcwd()
    output = {
        "time": {
            "iso": now.isoformat(),
            "unix": now.timestamp(),
            "readable": now.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "cwd": cwd,
        "version": {
            "name": "1-Nation MCP",
            "version": __version__,
            "python": sys.version,
        },
        "system": {
            "platform": platform.system(),
            "hostname": platform.node(),
        },
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_infraos_echo(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    message_value = args.get("message")
    message = message_value if isinstance(message_value, str) else ""
    if not message:
        return fail("Missing required parameter: message")
    output = {"message": message, "length": len(message)}
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_infraos_env_get(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    name_value = args.get("name")
    name = name_value if isinstance(name_value, str) else ""
    if not name:
        return fail(_ERR_MISSING_PARAM_NAME)
    value = os.environ.get(name)
    output = {"name": name, "value": value, "exists": value is not None}
    return _mcp_text(json.dumps(output, indent=2, default=str))


async def _mcp_tool_infraos_env_list(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    prefix_value = args.get("prefix", "")
    prefix = prefix_value if isinstance(prefix_value, str) else ""
    include_values = bool(args.get("values", False))
    redact = bool(args.get("redact", settings.security.redact_secrets))

    # Secret patterns to redact
    secret_patterns = ["token", "key", "secret", "password", "api", "auth"]

    variables: dict[str, str] = {}
    for key, value in sorted(os.environ.items()):
        if prefix and not key.startswith(prefix):
            continue
        if not include_values:
            variables[key] = "[hidden]"
        elif redact and any(pattern in key.lower() for pattern in secret_patterns):
            variables[key] = "[redacted]"
        else:
            variables[key] = value

    output = {
        "prefix": prefix or "(all)",
        "count": len(variables),
        "redacted": redact,
        "variables": variables,
    }
    return _mcp_text(json.dumps(output, indent=2, default=str))


# Runbook tool handlers


async def _mcp_tool_runbook_list(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    global _runbook_module
    if not _runbook_module:
        from knowledgebase.runbooks.service import RunbookService

        _runbook_module = RunbookService()
    result = _runbook_module.list_runbooks()
    return _mcp_text(json.dumps(result, indent=2, default=str))


async def _mcp_tool_runbook_get(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    global _runbook_module
    name = args.get("name") if args else None  # type: ignore[assignment]
    if not name or not isinstance(name, str):
        return fail(_ERR_MISSING_PARAM_NAME)
    if not _runbook_module:
        from knowledgebase.runbooks.service import RunbookService

        _runbook_module = RunbookService()
    result_raw = _runbook_module.get_runbook(name)
    if not result_raw:
        return fail(f"Runbook '{name}' not found")
    return _mcp_text(json.dumps(result_raw, indent=2, default=str))


async def _mcp_tool_runbook_create(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    global _runbook_module
    name = args.get("name") if args else None  # type: ignore[assignment]
    if not name or not isinstance(name, str):
        return fail(_ERR_MISSING_PARAM_NAME)
    if not _runbook_module:
        from knowledgebase.runbooks.service import RunbookService

        _runbook_module = RunbookService()
    result = _runbook_module.create_runbook(name, args.get("content", "") or "", args.get("file"))
    return _mcp_text(json.dumps(result, indent=2, default=str))


async def _mcp_tool_runbook_delete(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    global _runbook_module
    name = args.get("name") if args else None  # type: ignore[assignment]
    if not name or not isinstance(name, str):
        return fail(_ERR_MISSING_PARAM_NAME)
    if not _runbook_module:
        from knowledgebase.runbooks.service import RunbookService

        _runbook_module = RunbookService()
    result = _runbook_module.delete_runbook(name, args.get("force", False) or False)
    return _mcp_text(json.dumps(result, indent=2, default=str))


async def _mcp_tool_runbook_reindex(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    global _runbook_module
    if not _runbook_module:
        from knowledgebase.runbooks.service import RunbookService

        _runbook_module = RunbookService()
    result = _runbook_module.reindex_runbooks()
    return _mcp_text(json.dumps(result, indent=2, default=str))


async def _mcp_tool_runbook_get_prompt(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    global _runbook_module
    name = args.get("name") if args else None  # type: ignore[assignment]
    if not name or not isinstance(name, str):
        return fail(_ERR_MISSING_PARAM_NAME)
    vars_str = str(args.get("vars", "") if args else "")
    if not _runbook_module:
        from knowledgebase.runbooks.service import RunbookService

        _runbook_module = RunbookService()
    try:
        prompt_result = _runbook_module.get_prompt(name, vars_str)
        lines = [f"Prompt from runbook: {prompt_result.runbook_name}", ""]
        lines.append(prompt_result.prompt_text)
        return _mcp_text("\n".join(lines))
    except Exception as e:
        return fail(str(e))


async def _mcp_tool_runbook_log_create(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    global _runbook_module
    name = args.get("name") if args else None  # type: ignore[assignment]
    if not name or not isinstance(name, str):
        return fail(_ERR_MISSING_PARAM_NAME)
    content = (args.get("content") or "") if args and isinstance(args, dict) else ""
    if not content:
        return fail("Missing content or file for log entry")
    if not _runbook_module:
        from knowledgebase.runbooks.service import RunbookService

        _runbook_module = RunbookService()
    result = _runbook_module.create_log(name, content)
    return _mcp_text(json.dumps(result, indent=2, default=str))


async def _mcp_tool_kb_status_full(
    tool_name: str, args: dict[str, Any], fail: Callable[[str], dict[str, Any]]
) -> dict[str, Any]:
    # Get comprehensive status diagnostics from status service
    if not _system_service:
        return fail(_ERR_SERVICE_NOT_INITIALIZED)
    try:
        from knowledgebase.services.status_service import StatusService

        status_service = StatusService(settings)
        await status_service.initialize()
        try:
            full_status = await status_service.get_full_status()
        finally:
            await status_service.cleanup()

        endpoints_passed = sum(
            1
            for endpoint in full_status.endpoints
            if isinstance(endpoint.status_code, int) and endpoint.status_code < 400
        )
        endpoints_failed = len(full_status.endpoints) - endpoints_passed
        output = {
            "overall_status": full_status.overall_status,
            "timestamp": full_status.timestamp,
            "tools_count": len(full_status.tools),
            "tools_passed": sum(1 for t in full_status.tools if t.status == "pass"),
            "tools_failed": sum(1 for t in full_status.tools if t.status == "fail"),
            "endpoints_count": len(full_status.endpoints),
            "endpoints_passed": endpoints_passed,
            "endpoints_failed": endpoints_failed,
            "sync_status": {
                "last_sync_time": str(full_status.sync.last_sync_time or "never"),
                "indices_synced": full_status.sync.indices_synced,
                "documents_synced": full_status.sync.documents_synced,
                "sync_errors": full_status.sync.sync_errors,
            },
            "stats": {
                "total_documents": full_status.stats.total_documents,
                "total_indices": full_status.stats.total_indices,
                "uptime_formatted": full_status.stats.uptime_formatted,
                "memory_usage_mb": full_status.stats.memory_usage_mb,
            },
            "diagnostics": {
                "tools_passed": full_status.diagnostics.tools_passed,
                "tools_failed": full_status.diagnostics.tools_failed,
                "endpoints_passed": full_status.diagnostics.endpoints_passed,
                "endpoints_failed": full_status.diagnostics.endpoints_failed,
            },
        }
        return _mcp_text(json.dumps(output, indent=2, default=str))
    except Exception as e:
        return fail(f"Failed to get full status: {e}")


_MCP_TOOL_HANDLERS: dict[
    str, Callable[[str, dict[str, Any], Callable[[str], dict[str, Any]]], Any]
] = {
    "kb_get_document": _mcp_tool_kb_get_document,
    "kb_search": _mcp_tool_kb_search,
    "kb_index_list": _mcp_tool_kb_index_list,
    "kb_index_create": _mcp_tool_kb_index_create,
    "kb_index_delete": _mcp_tool_kb_index_delete,
    "kb_add_document": _mcp_tool_kb_add_document_or_kb_add_file,
    "kb_add_file": _mcp_tool_kb_add_document_or_kb_add_file,
    "kb_remove_document": _mcp_tool_kb_remove_document,
    "kb_sync_all": _mcp_tool_kb_sync_all,
    "docs_kb_list": _mcp_tool_docs_kb_list,
    "docs_kb_search": _mcp_tool_docs_kb_search,
    "docs_read_meta": _mcp_tool_docs_read_meta,
    "docs_read_content": _mcp_tool_docs_read_content,
    "docs_kb_info": _mcp_tool_docs_kb_info,
    "docs_list_dirs": _mcp_tool_docs_list_dirs,
    "kb_health": _mcp_tool_kb_health,
    "kb_stats": _mcp_tool_kb_stats,
    "kb_search_config_get": _mcp_tool_kb_search_config_get,
    "kb_search_config_set": _mcp_tool_kb_search_config_set,
    "kb_taxonomy_list": _mcp_tool_kb_taxonomy_list,
    "kb_index_info": _mcp_tool_kb_index_info,
    "kb_embedding_info": _mcp_tool_kb_embedding_info,
    "kb_rag_config_get": _mcp_tool_kb_rag_config_get,
    "kb_rag_config_set": _mcp_tool_kb_rag_config_set,
    "runbook_search": _mcp_tool_runbook_search,
    "kb_index_directory": _mcp_tool_kb_index_directory,
    "kb_upsert_document": _mcp_tool_kb_upsert_document,
    "kb_add_documents_batch": _mcp_tool_kb_add_documents_batch,
    "kb_index_reindex": _mcp_tool_kb_index_reindex,
    "kb_search_analytics": _mcp_tool_kb_search_analytics,
    "infraos_ping": _mcp_tool_infraos_ping,
    "infraos_context": _mcp_tool_infraos_context,
    "infraos_echo": _mcp_tool_infraos_echo,
    "infraos_env_get": _mcp_tool_infraos_env_get,
    "infraos_env_list": _mcp_tool_infraos_env_list,
    "runbook_list": _mcp_tool_runbook_list,
    "runbook_get": _mcp_tool_runbook_get,
    "runbook_create": _mcp_tool_runbook_create,
    "runbook_delete": _mcp_tool_runbook_delete,
    "runbook_reindex": _mcp_tool_runbook_reindex,
    "runbook_get_prompt": _mcp_tool_runbook_get_prompt,
    "runbook_log_create": _mcp_tool_runbook_log_create,
    "kb_status_full": _mcp_tool_kb_status_full,
}


_MCP_TOOL_HANDLERS.update({
    name.replace("infraos_", "aegis_", 1): handler
    for name, handler in list(_MCP_TOOL_HANDLERS.items()) if name.startswith("infraos_")
})

async def _execute_mcp_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute an MCP tool and return the result."""
    import time

    start_time = time.time()
    tool_success = True

    def fail(message: str) -> dict[str, Any]:
        nonlocal tool_success
        tool_success = False
        return _mcp_error(message)

    try:
        handler = _MCP_TOOL_HANDLERS.get(tool_name)
        if handler is not None:
            return await handler(tool_name, args, fail)

        return fail(f"Unknown tool: {tool_name}")

    except Exception as e:
        tool_success = False
        logger.error("Tool execution failed", tool=tool_name, error=str(e))
        return _mcp_error(f"Error: {str(e)}")

    finally:
        if _mcp_service:
            took_ms = (time.time() - start_time) * 1000
            await _mcp_service.record_tool_call(
                agent="MCP-Client",
                tool_name=tool_name,
                query=str(args),
                success=tool_success,
                response_time_ms=took_ms,
            )


# ============================================================================
# MCP Integration Endpoints (Analytics)
# ============================================================================


@app.get(
    "/api/v1/mcp/status",
    tags=["MCP"],
    responses={
        503: {"description": "MCP service not initialized"},
        500: {"description": "Failed to get MCP server status"},
    },
)
async def get_mcp_server_status() -> MCPServerStatus:
    """
    Return MCP server status and tool information.

    Provides comprehensive information about MCP tool availability,
    agent activity, and usage statistics.
    """
    if not _mcp_service:
        raise HTTPException(status_code=503, detail="MCP service not initialized")

    try:
        return await _mcp_service.get_server_status()
    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to get MCP server status", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get MCP server status: {e}") from e


class MCPToolCallRequest(BaseModel):
    """Request model for recording MCP tool calls."""

    agent: str = Field(..., description="Agent identifier")
    tool_name: str = Field(..., description="Tool name")
    query: str = Field(..., description="Query or parameters")
    success: bool = Field(True, description="Whether the call was successful")
    response_time_ms: float = Field(0.0, description="Response time in milliseconds")


@app.post(
    "/api/v1/mcp/tool-call",
    tags=["MCP"],
    responses={
        503: {"description": "MCP service not initialized"},
        500: {"description": "Failed to record tool call"},
    },
)
async def record_mcp_tool_call(request: MCPToolCallRequest) -> MessageResponse:
    """
    Record an MCP tool call for tracking and analytics.

    This endpoint is used by MCP tools to report their usage for monitoring.
    """
    if not _mcp_service:
        raise HTTPException(status_code=503, detail="MCP service not initialized")

    try:
        await _mcp_service.record_tool_call(
            agent=request.agent,
            tool_name=request.tool_name,
            query=request.query,
            success=request.success,
            response_time_ms=request.response_time_ms,
        )

        return MessageResponse(message="Tool call recorded successfully", success=True)

    except Exception as e:  # pragma: no cover - defensive catch-all for unexpected errors
        logger.error("Failed to record MCP tool call", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to record tool call: {e}") from e


@app.post("/mcp/message", tags=["MCP Protocol"])
@app.post("/mcp", tags=["MCP Protocol"])
async def mcp_message_endpoint(request: MCPJsonRpcRequest) -> JSONResponse:
    """
    MCP JSON-RPC message endpoint.

    Handles MCP protocol messages including:
    - initialize: Protocol initialization
    - tools/list: List available tools
    - tools/call: Execute a tool
    """
    try:
        return await _handle_mcp_rpcs_request(request.method, request.params, request.id)
    except Exception as e:
        logger.error("MCP request failed", error=str(e), method=request.method)
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32603, "message": str(e)},
                "id": request.id,
            }
        )


# ============================================================================
# Enhanced Search Endpoint with MCP Integration
# ============================================================================


async def _record_search_activity(
    request: SearchRequest, took_ms: float, result_count: int
) -> None:
    """
    Internal helper to record search activity for MCP tracking.

    This function is invoked after every search operation to log usage
    analytics. It records the search as an MCP tool call and updates system-
    level search counters.

    Any failures that occur while recording this activity are intentionally
    non-blocking: exceptions are caught and logged as warnings so that search
    responses are never affected by MCP or metrics recording issues.
    """
    if _mcp_service and _system_service:
        try:
            # Record in MCP service for agent tracking
            await _mcp_service.record_tool_call(
                agent="API",
                tool_name="kb_search",
                query=request.query,
                success=result_count > 0,
                response_time_ms=took_ms,
            )

            # Increment search counter in system service
            _system_service.increment_search_count()

        except Exception as e:
            logger.warning("Failed to record search activity", error=str(e))
