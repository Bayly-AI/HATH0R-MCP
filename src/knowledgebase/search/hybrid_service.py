"""Hybrid search orchestration (vector/kNN + BM25 fusion).

Combines storage-backed semantic retrieval with a local BM25 lexical index
and ranks results via :class:`HybridFusion`.
"""

from __future__ import annotations

import os
import time
from typing import Any, Literal

import structlog

from knowledgebase.core.models import Document, SearchResult
from knowledgebase.search.bm25 import BM25Index
from knowledgebase.search.hybrid import HybridFusion
from knowledgebase.storage.base import StorageBackend

logger = structlog.get_logger(__name__)

SearchMode = Literal["vector", "bm25", "hybrid"]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class HybridSearchService:
    """Run vector, BM25, or fused hybrid search against a storage backend."""

    def __init__(
        self,
        storage: StorageBackend,
        *,
        default_mode: SearchMode = "hybrid",
        hybrid_alpha: float = 0.7,
        bm25_cache_ttl_seconds: float | None = None,
        bm25_max_docs: int | None = None,
    ) -> None:
        self._storage = storage
        self.default_mode = default_mode
        # hybrid_alpha: weight for vector (1.0 = pure vector, 0.0 = pure BM25)
        self.hybrid_alpha = max(0.0, min(1.0, float(hybrid_alpha)))
        self._bm25_cache_ttl = (
            float(bm25_cache_ttl_seconds)
            if bm25_cache_ttl_seconds is not None
            else _env_float("KB_BM25_CACHE_TTL_SECONDS", 300.0)
        )
        self._bm25_max_docs = (
            int(bm25_max_docs)
            if bm25_max_docs is not None
            else max(100, _env_int("KB_BM25_MAX_DOCS", 5000))
        )
        self._bm25_by_index: dict[str, BM25Index] = {}
        self._bm25_built_at: dict[str, float] = {}
        self._doc_by_key: dict[tuple[str, str], Document] = {}

    def invalidate(self, index_name: str | None = None) -> None:
        """Drop BM25 caches (all indices or one index)."""
        if index_name is None:
            self._bm25_by_index.clear()
            self._bm25_built_at.clear()
            self._doc_by_key.clear()
            return
        self._bm25_by_index.pop(index_name, None)
        self._bm25_built_at.pop(index_name, None)
        stale = [key for key in self._doc_by_key if key[0] == index_name]
        for key in stale:
            self._doc_by_key.pop(key, None)

    async def search(
        self,
        *,
        query_text: str,
        query_embedding: list[float],
        index_names: list[str],
        limit: int = 10,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
        mode: SearchMode | None = None,
        hybrid_alpha: float | None = None,
    ) -> list[SearchResult]:
        """Execute search for one or more indices and return ranked results."""
        resolved_mode = mode or self.default_mode
        alpha = self.hybrid_alpha if hybrid_alpha is None else max(0.0, min(1.0, float(hybrid_alpha)))
        if not index_names:
            return []

        if resolved_mode == "vector":
            return await self._vector_search(
                query_embedding=query_embedding,
                index_names=index_names,
                limit=limit,
                min_score=min_score,
                filters=filters,
            )

        if resolved_mode == "bm25":
            return await self._bm25_search(
                query_text=query_text,
                index_names=index_names,
                limit=limit,
                min_score=min_score,
            )

        # hybrid: fuse BM25 + vector
        vector_results = await self._vector_search(
            query_embedding=query_embedding,
            index_names=index_names,
            limit=max(limit * 2, limit),
            min_score=0.0,
            filters=filters,
        )
        bm25_results = await self._bm25_search(
            query_text=query_text,
            index_names=index_names,
            limit=max(limit * 2, limit),
            min_score=0.0,
        )

        fusion = HybridFusion(bm25_weight=1.0 - alpha, vector_weight=alpha)
        vector_pairs = [
            (self._result_key(result), float(result.vector_score or result.score))
            for result in vector_results
        ]
        bm25_pairs = [
            (self._result_key(result), float(result.bm25_score or result.score))
            for result in bm25_results
        ]
        fused = fusion.fuse_results(bm25_pairs, vector_pairs, limit=limit)

        by_key: dict[str, SearchResult] = {}
        for result in vector_results:
            by_key[self._result_key(result)] = result
        for result in bm25_results:
            key = self._result_key(result)
            if key not in by_key:
                by_key[key] = result
            else:
                existing = by_key[key]
                if existing.bm25_score is None and result.bm25_score is not None:
                    existing.bm25_score = result.bm25_score

        output: list[SearchResult] = []
        for key, fused_score in fused:
            base = by_key.get(key)
            if base is None:
                continue
            if fused_score < min_score:
                continue
            output.append(
                SearchResult(
                    document=base.document,
                    score=float(fused_score),
                    vector_score=base.vector_score,
                    bm25_score=base.bm25_score,
                    highlights=list(base.highlights or []),
                )
            )
        logger.debug(
            "hybrid_search_complete",
            mode=resolved_mode,
            alpha=alpha,
            vector_count=len(vector_results),
            bm25_count=len(bm25_results),
            returned=len(output),
        )
        return output

    async def _vector_search(
        self,
        *,
        query_embedding: list[float],
        index_names: list[str],
        limit: int,
        min_score: float,
        filters: dict[str, Any] | None,
    ) -> list[SearchResult]:
        merged: list[SearchResult] = []
        for index_name in index_names:
            results = await self._storage.search(
                query_embedding=query_embedding,
                index_name=index_name,
                limit=limit,
                min_score=min_score,
                filters=filters,
            )
            for result in results:
                if result.vector_score is None:
                    result.vector_score = result.score
                merged.append(result)
        return self._dedupe_rank(merged, limit=limit)

    async def _bm25_search(
        self,
        *,
        query_text: str,
        index_names: list[str],
        limit: int,
        min_score: float,
    ) -> list[SearchResult]:
        if not query_text.strip():
            return []
        merged: list[SearchResult] = []
        for index_name in index_names:
            bm25 = await self._ensure_bm25_index(index_name)
            hits = bm25.search(query_text, limit=limit)
            if not hits:
                continue
            max_raw = max(score for _, score in hits) or 1.0
            for doc_id, raw_score in hits:
                normalized = float(raw_score) / float(max_raw) if max_raw else 0.0
                if normalized < min_score:
                    continue
                doc = self._doc_by_key.get((index_name, doc_id))
                if doc is None:
                    doc = await self._storage.get_document(doc_id, index_name)
                    if doc is None:
                        continue
                    self._doc_by_key[(index_name, doc_id)] = doc
                merged.append(
                    SearchResult(
                        document=doc,
                        score=normalized,
                        bm25_score=normalized,
                    )
                )
        return self._dedupe_rank(merged, limit=limit)

    async def _ensure_bm25_index(self, index_name: str) -> BM25Index:
        now = time.time()
        existing = self._bm25_by_index.get(index_name)
        built_at = self._bm25_built_at.get(index_name, 0.0)
        if existing is not None and (now - built_at) <= self._bm25_cache_ttl:
            return existing

        index = BM25Index()
        documents: dict[str, str] = {}
        offset = 0
        page_size = min(200, self._bm25_max_docs)
        while offset < self._bm25_max_docs:
            page, total = await self._storage.list_documents(
                index_name=index_name,
                offset=offset,
                limit=page_size,
            )
            if not page:
                break
            for doc in page:
                content = (doc.content or "").strip()
                if not content:
                    continue
                documents[doc.id] = content
                self._doc_by_key[(index_name, doc.id)] = doc
            offset += len(page)
            if offset >= total or len(page) < page_size:
                break
            if len(documents) >= self._bm25_max_docs:
                break

        if documents:
            index.add_documents_bulk(documents)
        self._bm25_by_index[index_name] = index
        self._bm25_built_at[index_name] = now
        logger.debug(
            "bm25_index_ready",
            index_name=index_name,
            document_count=len(documents),
        )
        return index

    @staticmethod
    def _result_key(result: SearchResult) -> str:
        return f"{result.document.index_name}::{result.document.id}"

    @staticmethod
    def _dedupe_rank(results: list[SearchResult], *, limit: int) -> list[SearchResult]:
        best: dict[str, SearchResult] = {}
        for result in results:
            key = HybridSearchService._result_key(result)
            existing = best.get(key)
            if existing is None or result.score > existing.score:
                best[key] = result
        ranked = sorted(best.values(), key=lambda item: item.score, reverse=True)
        return ranked[:limit]


def resolve_search_mode(raw: str | None, default: SearchMode = "hybrid") -> SearchMode:
    """Normalize a search mode string to a supported value."""
    if not raw:
        return default
    value = raw.strip().lower()
    if value in {"vector", "semantic", "knn"}:
        return "vector"
    if value in {"bm25", "lexical", "keyword", "exact"}:
        return "bm25"
    if value in {"hybrid", "fused", "hybrid_knn_bm25"}:
        return "hybrid"
    return default
