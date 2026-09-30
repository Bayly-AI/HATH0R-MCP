"""
OpenSearch Serverless storage backend.

Provides vector storage using AWS OpenSearch Serverless.
"""

from __future__ import annotations


import os
import time
from datetime import datetime, timezone
from typing import Any

import structlog
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests.auth import AuthBase
from requests_aws4auth import AWS4Auth

from knowledgebase.core.models import Document, DocumentMetadata, IndexInfo, SearchResult
from knowledgebase.storage.base import StorageBackend, StorageError

logger = structlog.get_logger(__name__)

CLIENT_NOT_INITIALIZED_MESSAGE = "Client not initialized"


class _RefreshableAOSSAuth(AuthBase):
    """SigV4 auth that refreshes IRSA credentials on every request.

    ``AWS4Auth`` freezes access key/secret/session token at construction time.
    EKS IRSA session tokens expire (~1h), so a long-lived OpenSearch client
    initialized once at process start eventually starts getting 403s from AOSS.
    Rebuilding the signer from the current boto3 credential chain on each
    request keeps the pod healthy across credential rotation.
    """

    def __init__(
        self,
        *,
        region: str,
        aws_access_key: str | None = None,
        aws_secret_key: str | None = None,
    ) -> None:
        self._region = region
        self._aws_access_key = aws_access_key
        self._aws_secret_key = aws_secret_key

    def _fresh_aws4auth(self) -> AWS4Auth:
        import boto3

        if self._aws_access_key and self._aws_secret_key:
            session = boto3.Session(
                aws_access_key_id=self._aws_access_key,
                aws_secret_access_key=self._aws_secret_key,
            )
        else:
            session = boto3.Session()

        credentials = session.get_credentials()
        if credentials is None:
            raise StorageError(
                message="No AWS credentials available for OpenSearch SigV4 auth",
                backend="opensearch",
                operation="auth",
            )
        frozen = credentials.get_frozen_credentials()
        return AWS4Auth(
            frozen.access_key,
            frozen.secret_key,
            self._region,
            "aoss",
            session_token=frozen.token,
        )

    def __call__(self, request: Any) -> Any:
        return self._fresh_aws4auth()(request)


class OpenSearchStorageBackend(StorageBackend):
    """
    Storage backend using AWS OpenSearch Serverless.

    Provides scalable vector storage with support for:
    - kNN vector search
    - Hybrid search (vector + BM25)
    - Metadata filtering

    Attributes:
        endpoint: OpenSearch Serverless endpoint URL.
        region: AWS region.
        index_prefix: Prefix for index names.
    """

    # Vector field configuration
    VECTOR_DIMENSION = 1536
    VECTOR_FIELD = "content_vector"
    CONTENT_FIELD = "content_text"

    def __init__(
        self,
        endpoint: str,
        region: str = "us-east-1",
        use_sigv4: bool = True,
        index_prefix: str = "vectra-",
        aws_access_key: str | None = None,
        aws_secret_key: str | None = None,
        vector_dimension: int = VECTOR_DIMENSION,
    ) -> None:
        """
        Initialize the OpenSearch storage backend.

        Args:
            endpoint: OpenSearch Serverless endpoint URL.
            region: AWS region.
            use_sigv4: Whether to use SigV4 authentication.
            index_prefix: Prefix for index names.
            aws_access_key: Optional AWS access key (uses env vars if not provided).
            aws_secret_key: Optional AWS secret key (uses env vars if not provided).
            vector_dimension: Dimension of the configured embedding provider's
                vectors. Must match whatever embedding model is actually in
                use (e.g. 768 for Ollama nomic-embed-text, 1024 for Bedrock
                titan-embed-text-v2, 1536 for OpenAI text-embedding-3-small)
                -- indices created with a mismatched dimension will fail to
                accept documents from that provider.
        """
        self._endpoint = endpoint.rstrip("/")
        self._region = region
        self._use_sigv4 = use_sigv4
        self._index_prefix = index_prefix
        self._aws_access_key = aws_access_key
        self._aws_secret_key = aws_secret_key
        self._vector_dimension = vector_dimension
        self._client: OpenSearch | None = None
        # Short TTL cache for cat.indices used by health/list paths (AOSS is slow).
        self._indices_cache: list[IndexInfo] | None = None
        self._indices_cache_at: float = 0.0
        self._indices_cache_ttl_seconds = float(
            os.getenv("KB_OPENSEARCH_INDICES_CACHE_TTL_SECONDS", "15")
        )
        # Search payload controls (memory + AOSS transfer cost).
        self._search_include_content = os.getenv(
            "KB_OPENSEARCH_SEARCH_INCLUDE_CONTENT", "true"
        ).strip().lower() not in {"0", "false", "no", "off"}
        self._search_content_max_chars = int(
            os.getenv("KB_OPENSEARCH_SEARCH_CONTENT_MAX_CHARS", "1200")
        )
        # List payload controls: full content_text + metadata blobs on large
        # indices (knowledge) previously caused ALB/client timeouts under AOSS.
        self._list_include_content = os.getenv(
            "KB_OPENSEARCH_LIST_INCLUDE_CONTENT", "true"
        ).strip().lower() not in {"0", "false", "no", "off"}
        self._list_content_max_chars = int(
            os.getenv("KB_OPENSEARCH_LIST_CONTENT_MAX_CHARS", "1200")
        )

        logger.info(
            "Initialized OpenSearch storage backend",
            endpoint=self._endpoint,
            region=self._region,
            index_prefix=self._index_prefix,
        )

    def _get_full_index_name(self, name: str) -> str:
        """Get the full index name with prefix."""
        if name.startswith(self._index_prefix):
            return name
        return f"{self._index_prefix}{name}"

    def _get_auth(self) -> AuthBase | None:
        """Get AWS SigV4 authentication that refreshes IRSA tokens."""
        if not self._use_sigv4:
            return None

        return _RefreshableAOSSAuth(
            region=self._region,
            aws_access_key=self._aws_access_key,
            aws_secret_key=self._aws_secret_key,
        )

    async def initialize(self) -> None:
        """Initialize the OpenSearch client."""
        try:
            # Parse endpoint - stripping the scheme prefix here only extracts the
            # bare host for the client's `hosts` param; the actual connection
            # below always uses use_ssl=True, so this is not an insecure request.
            host = self._endpoint.replace("https://", "").replace("http://", "")  # NOSONAR

            self._client = OpenSearch(
                hosts=[{"host": host, "port": 443}],
                http_auth=self._get_auth(),
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
            )

            # Test connection. OpenSearch Serverless (AOSS) doesn't implement
            # the traditional cluster `info()` API (returns 404 — confirmed
            # against the real evergreen-kb-dev collection), so cat.indices
            # is used instead: it's the same call list_indices() already
            # relies on, and is supported by AOSS.
            self._client.cat.indices(format="json")
            logger.info("Connected to OpenSearch", endpoint=self._endpoint)

        except Exception as e:  # pragma: no cover - network/configuration failure path
            raise StorageError(
                message=f"Failed to initialize OpenSearch: {e}",
                backend="opensearch",
                operation="initialize",
                original_error=e,
            ) from e

    async def close(self) -> None:
        """Close the OpenSearch client."""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("OpenSearch connection closed")

    def _get_index_mapping(self, dimensions: int = VECTOR_DIMENSION) -> dict[str, Any]:
        """Get the index mapping for vector search."""
        return {
            "settings": {
                "index": {
                    "knn": True,
                    "knn.algo_param.ef_search": 100,
                }
            },
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    self.VECTOR_FIELD: {
                        "type": "knn_vector",
                        "dimension": dimensions,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "nmslib",
                            "parameters": {
                                "ef_construction": 128,
                                "m": 24,
                            },
                        },
                    },
                    self.CONTENT_FIELD: {"type": "text"},
                    "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "path": {"type": "keyword"},
                    "source_type": {"type": "keyword"},
                    "repository": {"type": "keyword"},
                    "space": {"type": "keyword"},
                    "tags": {"type": "keyword"},
                    "language": {"type": "keyword"},
                    "index_name": {"type": "keyword"},
                    "chunk_index": {"type": "integer"},
                    "total_chunks": {"type": "integer"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "metadata": {"type": "object", "enabled": False},
                },
            },
        }

    async def create_index(self, name: str, _metadata_schema: dict[str, str] | None = None) -> None:
        """Create a new OpenSearch index."""
        if not self._client:
            raise StorageError(CLIENT_NOT_INITIALIZED_MESSAGE, backend="opensearch")

        full_name = self._get_full_index_name(name)

        try:
            # Check if index exists
            if self._client.indices.exists(index=full_name):
                logger.info("Index already exists", index=full_name)
                return

            # Create index with mapping, sized for the actual configured
            # embedding provider's vector dimension.
            self._client.indices.create(
                index=full_name,
                body=self._get_index_mapping(self._vector_dimension),
            )
            self._indices_cache = None
            logger.info("Created index", index=full_name)

        except Exception as e:  # pragma: no cover - network/index creation failure path
            raise StorageError(
                message=f"Failed to create index: {e}",
                backend="opensearch",
                operation="create_index",
                original_error=e,
            ) from e

    async def delete_index(self, name: str) -> None:
        """Delete an OpenSearch index."""
        if not self._client:
            raise StorageError(CLIENT_NOT_INITIALIZED_MESSAGE, backend="opensearch")

        full_name = self._get_full_index_name(name)

        try:
            if self._client.indices.exists(index=full_name):
                self._client.indices.delete(index=full_name)
                self._indices_cache = None
                logger.info("Deleted index", index=full_name)
            else:
                logger.warning("Index not found for deletion", index=full_name)

        except Exception as e:  # pragma: no cover - network/index deletion failure path
            raise StorageError(
                message=f"Failed to delete index: {e}",
                backend="opensearch",
                operation="delete_index",
                original_error=e,
            ) from e

    async def list_indices(self, *, use_cache: bool = True) -> list[IndexInfo]:
        """List all indices with the configured prefix.

        ``use_cache`` enables a short in-process TTL cache so health/status
        probes do not pay a full AOSS ``cat.indices`` round-trip every time.
        """
        if not self._client:
            raise StorageError(CLIENT_NOT_INITIALIZED_MESSAGE, backend="opensearch")

        now = time.time()
        if (
            use_cache
            and self._indices_cache is not None
            and (now - self._indices_cache_at) <= self._indices_cache_ttl_seconds
        ):
            return list(self._indices_cache)

        try:
            # Get all indices
            response = self._client.cat.indices(format="json")
            indices: list[IndexInfo] = []

            for idx in response:
                idx_name = idx.get("index", "")
                if idx_name.startswith(self._index_prefix):
                    # Get document count
                    doc_count = int(idx.get("docs.count", 0) or 0)

                    # Remove prefix for display
                    display_name = idx_name[len(self._index_prefix) :]

                    indices.append(
                        IndexInfo(
                            name=display_name,
                            document_count=doc_count,
                        )
                    )

            self._indices_cache = list(indices)
            self._indices_cache_at = now
            return indices

        except Exception as e:  # pragma: no cover - index listing failure path
            raise StorageError(
                message=f"Failed to list indices: {e}",
                backend="opensearch",
                operation="list_indices",
                original_error=e,
            ) from e

    async def add_document(self, document: Document) -> None:
        """Add or update a document in OpenSearch."""
        if not self._client:
            raise StorageError(CLIENT_NOT_INITIALIZED_MESSAGE, backend="opensearch")

        full_index = self._get_full_index_name(document.index_name)

        try:
            # Ensure index exists
            if not self._client.indices.exists(index=full_index):
                await self.create_index(document.index_name)

            # OpenSearch Serverless (AOSS) rejects application-supplied
            # document IDs on write and has no _delete_by_query (both
            # confirmed live: 400 "Document ID is not supported..." / 404).
            # True upsert is approximated by deleting any existing document
            # matching this app-level ID first -- delete_document() finds
            # it via search and removes it by its real, OpenSearch-assigned
            # _id, which AOSS does support deleting by.
            #
            # CAVEAT: AOSS's search index updates asynchronously and
            # refresh can't be forced (refresh=true is also rejected), so a
            # document rewritten within roughly the same window it was
            # first written may not be found by this delete step yet -- in
            # that narrow race, both versions can end up in the index
            # instead of a clean replace. This is a platform limitation,
            # not something fixable here.
            await self.delete_document(document.id, document.index_name)

            # Prepare document body
            body = {
                "id": document.id,
                self.CONTENT_FIELD: document.content,
                "index_name": document.index_name,
                "chunk_index": document.chunk_index,
                "total_chunks": document.total_chunks,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            # Add embedding if present
            if document.embedding:
                body[self.VECTOR_FIELD] = document.embedding

            # Add metadata fields
            if document.metadata:
                meta = document.metadata.model_dump()
                for key in [
                    "title",
                    "path",
                    "source_type",
                    "repository",
                    "space",
                    "tags",
                    "language",
                ]:
                    if key in meta and meta[key]:
                        body[key] = meta[key]
                body["metadata"] = meta

            # Index without an explicit id -- OpenSearch assigns one; AOSS
            # rejects application-supplied IDs on write (see above).
            self._client.index(index=full_index, body=body)

            logger.debug("Added document", doc_id=document.id, index=full_index)

        except Exception as e:  # pragma: no cover - document indexing failure path
            raise StorageError(
                message=f"Failed to add document: {e}",
                backend="opensearch",
                operation="add_document",
                original_error=e,
            ) from e

    async def add_documents(self, documents: list[Document]) -> None:
        """Add multiple documents in bulk."""
        if not self._client:
            raise StorageError(CLIENT_NOT_INITIALIZED_MESSAGE, backend="opensearch")

        if not documents:
            return

        try:
            # Prepare bulk actions
            actions = []
            for doc in documents:
                full_index = self._get_full_index_name(doc.index_name)

                # Ensure index exists
                if not self._client.indices.exists(index=full_index):
                    await self.create_index(doc.index_name)

                # No explicit _id: AOSS rejects application-supplied
                # document IDs on write (see add_document). This means bulk
                # writes here are insert-only -- unlike add_document, this
                # method doesn't attempt upsert (no delete-existing pass
                # per document), since it has no callers anywhere in the
                # codebase today. Revisit if that changes.
                action = {"index": {"_index": full_index}}
                body = {
                    "id": doc.id,
                    self.CONTENT_FIELD: doc.content,
                    "index_name": doc.index_name,
                    "chunk_index": doc.chunk_index,
                    "total_chunks": doc.total_chunks,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }

                if doc.embedding:
                    body[self.VECTOR_FIELD] = doc.embedding

                if doc.metadata:
                    meta = doc.metadata.model_dump()
                    for key in [
                        "title",
                        "path",
                        "source_type",
                        "repository",
                        "space",
                        "tags",
                        "language",
                    ]:
                        if key in meta and meta[key]:
                            body[key] = meta[key]
                    body["metadata"] = meta

                actions.extend([action, body])

            # Execute bulk request (no refresh param -- AOSS rejects
            # refresh=true, "true refresh policy is not supported").
            response = self._client.bulk(body=actions)

            if response.get("errors"):
                logger.warning("Some documents failed to index", response=response)

            logger.info("Bulk indexed documents", count=len(documents))

        except Exception as e:  # pragma: no cover - bulk indexing failure path
            raise StorageError(
                message=f"Failed to bulk add documents: {e}",
                backend="opensearch",
                operation="add_documents",
                original_error=e,
            ) from e

    async def get_document(self, doc_id: str, index_name: str) -> Document | None:
        """Retrieve a document by ID."""
        if not self._client:
            raise StorageError(CLIENT_NOT_INITIALIZED_MESSAGE, backend="opensearch")

        full_index = self._get_full_index_name(index_name)

        try:
            # AOSS doesn't support fetching by an application-supplied ID
            # (confirmed live: 400 "Document ID is not supported..."), so
            # documents are looked up by their "id" field via search
            # instead.
            #
            # A brand-new index can also 404 ("index_not_found_exception")
            # on _search for a short window right after creation -- even
            # though indices.exists() already reports it present -- because
            # AOSS's indexing and search layers aren't synchronous (confirmed
            # live: indices.exists() returned True immediately while the very
            # next _search still 404'd). That's indistinguishable here from
            # "no matching document", so it's handled the same way.
            try:
                response = self._client.search(
                    index=full_index,
                    body={"query": {"term": {"id": doc_id}}, "size": 1},
                )
            except Exception as search_error:
                if "NotFoundError" in str(type(search_error)):
                    return None
                raise

            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                return None
            source = hits[0].get("_source", {})

            return Document(
                id=source.get("id", doc_id),
                content=source.get(self.CONTENT_FIELD, ""),
                embedding=source.get(self.VECTOR_FIELD),
                index_name=source.get("index_name", index_name),
                chunk_index=source.get("chunk_index", 0),
                total_chunks=source.get("total_chunks", 1),
                metadata=DocumentMetadata(**source.get("metadata", {})),
            )

        except Exception as e:  # pragma: no cover - transport/client failure path
            raise StorageError(
                message=f"Failed to get document: {e}",
                backend="opensearch",
                operation="get_document",
                original_error=e,
            ) from e

    async def delete_document(self, doc_id: str, index_name: str) -> bool:
        """Delete a document by ID."""
        if not self._client:
            raise StorageError(CLIENT_NOT_INITIALIZED_MESSAGE, backend="opensearch")

        full_index = self._get_full_index_name(index_name)

        try:
            # AOSS supports neither delete-by-application-ID nor
            # _delete_by_query (confirmed live: 400 / 404 respectively), so
            # matching documents are found by their "id" field via search
            # first, then deleted individually by their real, OpenSearch-
            # assigned _id -- which AOSS does support deleting by. size=100
            # catches multiple documents if the eventual-consistency race
            # described below ever leaves duplicates behind.
            #
            # A brand-new index can also 404 ("index_not_found_exception")
            # on _search for a short window right after creation -- even
            # though indices.exists() already reports it present -- because
            # AOSS's indexing and search layers aren't synchronous (confirmed
            # live). This matters here specifically because add_document
            # calls delete_document immediately after create_index for a
            # fresh index; treat that race the same as "nothing to delete".
            try:
                response = self._client.search(
                    index=full_index,
                    body={"query": {"term": {"id": doc_id}}, "size": 100},
                )
            except Exception as search_error:
                if "NotFoundError" in str(type(search_error)):
                    return False
                raise

            hits = response.get("hits", {}).get("hits", [])
            if not hits:
                return False

            deleted_any = False
            for hit in hits:
                hit_id = hit.get("_id")
                if not hit_id:
                    continue
                try:
                    self._client.delete(index=full_index, id=hit_id)
                    deleted_any = True
                except Exception as delete_error:
                    # AOSS eventual consistency: a hit can disappear between
                    # search and delete. Treat not-found as already-gone.
                    err_name = type(delete_error).__name__
                    err_text = str(delete_error)
                    if "NotFoundError" in err_name or "not_found" in err_text or "404" in err_text:
                        logger.debug(
                            "Delete target already gone",
                            doc_id=doc_id,
                            hit_id=hit_id,
                            index=full_index,
                        )
                        continue
                    raise

            logger.debug(
                "Deleted document", doc_id=doc_id, index=full_index, deleted_any=deleted_any
            )
            return True

        except Exception as e:  # pragma: no cover - transport/client failure path
            err_name = type(e).__name__
            err_text = str(e)
            if "NotFoundError" in err_name or "not_found" in err_text:
                return False
            raise StorageError(
                message=f"Failed to delete document: {e}",
                backend="opensearch",
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
        """Search for documents using kNN vector search."""
        if not self._client:
            raise StorageError(CLIENT_NOT_INITIALIZED_MESSAGE, backend="opensearch")

        # Determine which index/indices to search
        if index_name:
            target_index = self._get_full_index_name(index_name)
        else:
            target_index = f"{self._index_prefix}*"

        try:
            # Build query
            # Fetch only fields needed for ranking/display. Full content is
            # optional/truncated to cut AOSS payload size and API RSS.
            source_includes = [
                "id",
                "index_name",
                "chunk_index",
                "total_chunks",
                "title",
                "path",
                "source_type",
                "repository",
                "tags",
                "metadata",
            ]
            if self._search_include_content:
                source_includes.append(self.CONTENT_FIELD)

            # Oversample k slightly for post-filter min_score without huge payloads.
            knn_k = max(limit, min(limit * 2, 40))
            query_body: dict[str, Any] = {
                "size": limit,
                "query": {
                    "knn": {
                        self.VECTOR_FIELD: {
                            "vector": query_embedding,
                            "k": knn_k,
                        }
                    }
                },
                "_source": {
                    "includes": source_includes,
                },
            }

            # Add filters. Internal Phase-4 policy keys prefixed with ``_``
            # (e.g. ``_exclude_archive``) and the boolean ``include_archive``
            # flag are API/policy hints — not indexed document fields.
            # Emitting them as term filters matches nothing and zeros all hits
            # (confirmed against Dev AOSS: default search total=0, while the
            # same query with include_archive=true returns canaries + Engage360).
            if filters:
                filter_clauses: list[dict[str, Any]] = []
                must_not_clauses: list[dict[str, Any]] = []
                exclude_archive = bool(filters.get("_exclude_archive", False)) and not bool(
                    filters.get("_include_archive") or filters.get("include_archive")
                )
                for key, value in filters.items():
                    if key.startswith("_") or key == "include_archive":
                        continue
                    if isinstance(value, list):
                        filter_clauses.append({"terms": {key: value}})
                    else:
                        filter_clauses.append({"term": {key: value}})

                # Soft archive denylist when policy requests exclusion and the
                # field is present on archive bulk docs (source_type=archive).
                if exclude_archive:
                    must_not_clauses.append(
                        {
                            "terms": {
                                "source_type": [
                                    "archive",
                                    "archived",
                                    "mirror",
                                    "legacy-archive",
                                    "knowledge-archive",
                                ]
                            }
                        }
                    )

                if filter_clauses or must_not_clauses:
                    bool_query: dict[str, Any] = {"must": [query_body["query"]]}
                    if filter_clauses:
                        bool_query["filter"] = filter_clauses
                    if must_not_clauses:
                        bool_query["must_not"] = must_not_clauses
                    query_body["query"] = {"bool": bool_query}

            # Execute search
            response = self._client.search(index=target_index, body=query_body)

            # Process results
            from knowledgebase.search.archive_policy import should_exclude_archive_document

            exclude_archive_post = bool(filters and filters.get("_exclude_archive")) and not bool(
                filters and (filters.get("_include_archive") or filters.get("include_archive"))
            )

            results: list[SearchResult] = []
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                score = hit.get("_score", 0)

                # Normalize score to 0-1 range (OpenSearch kNN scores are already similarity)
                normalized_score = min(max(score, 0), 1)

                if normalized_score >= min_score:
                    content = source.get(self.CONTENT_FIELD, "") or ""
                    if (
                        content
                        and self._search_content_max_chars > 0
                        and len(content) > self._search_content_max_chars
                    ):
                        content = content[: self._search_content_max_chars]
                    meta_raw = source.get("metadata") or {}
                    if not isinstance(meta_raw, dict):
                        meta_raw = {}
                    # Prefer top-level sparse fields when metadata blob absent/heavy.
                    if not meta_raw:
                        for key in ("title", "path", "source_type", "repository", "tags"):
                            if key in source and source[key] is not None:
                                meta_raw[key] = source[key]
                    # Top-level source_type often carries archive marker even when
                    # the metadata blob is sparse/disabled.
                    if "source_type" in source and source["source_type"] is not None:
                        meta_raw.setdefault("source_type", source["source_type"])

                    doc_id = source.get("id", hit.get("_id"))
                    if exclude_archive_post and should_exclude_archive_document(
                        metadata=meta_raw,
                        doc_id=str(doc_id) if doc_id is not None else None,
                        include_archive=False,
                    ):
                        continue

                    doc = Document(
                        id=doc_id,
                        content=content,
                        embedding=None,
                        index_name=source.get("index_name", ""),
                        chunk_index=source.get("chunk_index", 0),
                        total_chunks=source.get("total_chunks", 1),
                        metadata=DocumentMetadata(**meta_raw),
                    )
                    results.append(
                        SearchResult(
                            document=doc,
                            score=normalized_score,
                            vector_score=normalized_score,
                        )
                    )

            return results[:limit]

        except Exception as e:  # pragma: no cover - search transport failure path
            raise StorageError(
                message=f"Search failed: {e}",
                backend="opensearch",
                operation="search",
                original_error=e,
            ) from e

    async def health_check(self) -> dict[str, Any]:
        """Check the health of the OpenSearch cluster."""
        start_time = time.time()

        if not self._client:
            return {
                "healthy": False,
                "backend": "opensearch",
                "error": CLIENT_NOT_INITIALIZED_MESSAGE,
            }

        try:
            # OpenSearch Serverless (AOSS) doesn't implement the traditional
            # cluster.health() API (returns 404 — confirmed against the real
            # evergreen-kb-dev collection), so reachability + stats both come
            # from list_indices() (cat.indices, which AOSS does support).
            indices = await self.list_indices(use_cache=True)
            latency_ms = (time.time() - start_time) * 1000
            total_docs = sum(i.document_count for i in indices)

            return {
                "healthy": True,
                "backend": "opensearch",
                "endpoint": self._endpoint,
                "index_count": len(indices),
                "document_count": total_docs,
                "latency_ms": round(latency_ms, 2),
            }

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "healthy": False,
                "backend": "opensearch",
                "error": str(e),
                "latency_ms": round(latency_ms, 2),
            }

    def _build_list_source_spec(self) -> dict[str, Any]:
        """Return a lean _source filter for list_documents queries."""
        includes = [
            "id",
            "index_name",
            "chunk_index",
            "total_chunks",
            "title",
            "path",
            "source_type",
            "repository",
            "tags",
            "metadata",
            "updated_at",
            "created_at",
        ]
        if self._list_include_content:
            includes.append(self.CONTENT_FIELD)
        return {"includes": includes}

    def _document_from_list_hit(self, hit: dict[str, Any], index_name: str) -> Document:
        """Map an OpenSearch list hit into a Document with truncated content."""
        source = hit.get("_source", {}) or {}
        content = source.get(self.CONTENT_FIELD, "") or ""
        if (
            content
            and self._list_content_max_chars > 0
            and len(content) > self._list_content_max_chars
        ):
            content = content[: self._list_content_max_chars]

        meta_raw = source.get("metadata") or {}
        if not isinstance(meta_raw, dict):
            meta_raw = {}
        if not meta_raw:
            for key in ("title", "path", "source_type", "repository", "tags"):
                if key in source and source[key] is not None:
                    meta_raw[key] = source[key]
        elif "source_type" in source and source["source_type"] is not None:
            meta_raw.setdefault("source_type", source["source_type"])

        return Document(
            id=source.get("id", hit.get("_id")),
            content=content if self._list_include_content else "",
            embedding=None,
            index_name=source.get("index_name", index_name),
            chunk_index=source.get("chunk_index", 0),
            total_chunks=source.get("total_chunks", 1),
            metadata=DocumentMetadata(**meta_raw),
        )

    async def list_documents(
        self,
        index_name: str,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Document], int]:
        """List documents from an index without returning embeddings.

        Uses a lean ``_source`` include list (same shape as search) so AOSS
        does not transfer full document bodies + vectors. Content is optional
        and truncated via ``KB_OPENSEARCH_LIST_*`` settings. Sort prefers
        ``updated_at`` and falls back to score-only when that field is missing.
        """
        if not self._client:
            raise StorageError(CLIENT_NOT_INITIALIZED_MESSAGE, backend="opensearch")

        full_index = self._get_full_index_name(index_name)

        try:
            source_spec = self._build_list_source_spec()
            base_body: dict[str, Any] = {
                "from": offset,
                "size": limit,
                "query": {"match_all": {}},
                "_source": source_spec,
                # Cap total hits work; UI/sync only need approximate totals.
                "track_total_hits": min(max(offset + limit, 1000), 10000),
            }

            try:
                body = {**base_body, "sort": [{"updated_at": {"order": "desc"}}]}
                response = self._client.search(index=full_index, body=body)
            except Exception as sort_error:
                # Indices without updated_at (or unmapped) should still list.
                err_text = str(sort_error).lower()
                if (
                    "updated_at" in err_text
                    or "no mapping" in err_text
                    or "search_phase_execution" in err_text
                ):
                    logger.warning(
                        "list_documents updated_at sort failed; retrying without sort",
                        index=full_index,
                        error=str(sort_error),
                    )
                    response = self._client.search(index=full_index, body=base_body)
                else:
                    raise

            hits_info = response.get("hits", {})
            hits = hits_info.get("hits", [])

            total_raw = hits_info.get("total")
            if isinstance(total_raw, dict) and "value" in total_raw:
                total = int(total_raw["value"])
            elif isinstance(total_raw, int):
                total = total_raw
            else:
                total = len(hits)

            documents = [self._document_from_list_hit(hit, index_name) for hit in hits]
            return documents, total

        except Exception as e:  # pragma: no cover - document listing failure path
            raise StorageError(
                message=f"Failed to list documents: {e}",
                backend="opensearch",
                operation="list_documents",
                original_error=e,
            ) from e
