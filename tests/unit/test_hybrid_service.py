"""Tests for HybridSearchService orchestration."""

from __future__ import annotations

from typing import Any

import pytest

from knowledgebase.core.models import Document, DocumentMetadata, SearchResult
from knowledgebase.search.hybrid_service import HybridSearchService, resolve_search_mode


def _doc(doc_id: str, content: str, index_name: str = "knowledge") -> Document:
    return Document(
        id=doc_id,
        content=content,
        index_name=index_name,
        metadata=DocumentMetadata(title=doc_id),
        embedding=[0.1, 0.2, 0.3],
    )


class _FakeStorage:
    def __init__(self, docs: list[Document]) -> None:
        self.docs = docs

    async def search(
        self,
        query_embedding: list[float],
        index_name: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        results = []
        for idx, doc in enumerate(self.docs):
            if index_name and doc.index_name != index_name:
                continue
            score = max(0.1, 1.0 - (idx * 0.1))
            if score < min_score:
                continue
            results.append(SearchResult(document=doc, score=score, vector_score=score))
        return results[:limit]

    async def list_documents(
        self, index_name: str, offset: int = 0, limit: int = 20
    ) -> tuple[list[Document], int]:
        items = [d for d in self.docs if d.index_name == index_name]
        return items[offset : offset + limit], len(items)

    async def get_document(self, doc_id: str, index_name: str) -> Document | None:
        for doc in self.docs:
            if doc.id == doc_id and doc.index_name == index_name:
                return doc
        return None


@pytest.mark.asyncio
async def test_hybrid_mode_fuses_modalities() -> None:
    docs = [
        _doc("alpha", "kubernetes hybrid search retrieval knn bm25"),
        _doc("beta", "unrelated cooking recipes and pasta"),
        _doc("gamma", "vector embeddings and knn similarity search"),
    ]
    service = HybridSearchService(_FakeStorage(docs), default_mode="hybrid", hybrid_alpha=0.5)
    results = await service.search(
        query_text="hybrid knn bm25 search",
        query_embedding=[0.1, 0.2, 0.3],
        index_names=["knowledge"],
        limit=3,
        min_score=0.0,
        mode="hybrid",
    )
    assert results
    assert all(isinstance(r.score, float) for r in results)
    ids = [r.document.id for r in results]
    assert "alpha" in ids or "gamma" in ids


@pytest.mark.asyncio
async def test_bm25_only_mode() -> None:
    docs = [
        _doc("exact", "hybrid knn bm25 retrieval pipeline appears here"),
        _doc("other", "nothing matching in this document"),
        _doc("noise", "cooking pasta recipes and desserts"),
    ]
    service = HybridSearchService(_FakeStorage(docs), default_mode="bm25")
    results = await service.search(
        query_text="hybrid knn bm25 retrieval",
        query_embedding=[0.0, 0.0, 0.0],
        index_names=["knowledge"],
        limit=5,
        mode="bm25",
    )
    assert results
    assert results[0].document.id == "exact"
    assert results[0].bm25_score is not None


def test_resolve_search_mode() -> None:
    assert resolve_search_mode("knn") == "vector"
    assert resolve_search_mode("keyword") == "bm25"
    assert resolve_search_mode("hybrid_knn_bm25") == "hybrid"
    assert resolve_search_mode(None) == "hybrid"
