"""API tests for document, index, and search endpoints.

These tests use in-memory fake storage and embedding providers so they do
not require external services.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledgebase.api.main import app
from knowledgebase.core.models import Document, IndexInfo, SearchResult


class FakeStorage:
    """In-memory fake storage implementing the subset of the storage interface used by the API."""

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], Document] = {}
        self._indices: set[str] = set()
        self.search_calls = 0
        self.last_search_kwargs: dict[str, Any] | None = None

    # Lifecycle -------------------------------------------------------------

    async def initialize(self) -> None:  # pragma: no cover - trivial for fake
        return None

    async def close(self) -> None:  # pragma: no cover - trivial for fake
        return None

    # Index management ------------------------------------------------------

    async def create_index(
        self, name: str, metadata_schema: dict[str, str] | None = None
    ) -> None:  # noqa: ARG002
        self._indices.add(name)

    async def delete_index(self, name: str) -> None:
        self._indices.discard(name)
        # Remove all documents for this index
        self._docs = {k: v for k, v in self._docs.items() if k[0] != name}

    async def list_indices(self) -> list[IndexInfo]:
        indices: list[IndexInfo] = []
        for idx in sorted(self._indices):
            count = sum(1 for (name, _), _doc in self._docs.items() if name == idx)
            indices.append(
                IndexInfo(
                    name=idx,
                    description="",
                    document_count=count,
                )
            )
        return indices

    # Document operations ---------------------------------------------------

    async def add_document(self, document: Document) -> None:
        key = (document.index_name, document.id)
        self._indices.add(document.index_name)
        self._docs[key] = document

    async def get_document(self, doc_id: str, index_name: str) -> Document | None:
        return self._docs.get((index_name, doc_id))

    async def delete_document(self, doc_id: str, index_name: str) -> bool:
        key = (index_name, doc_id)
        if key in self._docs:
            del self._docs[key]
            return True
        return False

    async def list_documents(
        self,
        index_name: str,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Document], int]:
        docs = [doc for (idx, _), doc in sorted(self._docs.items()) if idx == index_name]
        total = len(docs)
        return docs[offset : offset + limit], total

    async def search(
        self,
        query_embedding: list[float],  # noqa: ARG002
        index_name: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,  # noqa: ARG002
        filters: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> list[SearchResult]:
        self.search_calls += 1
        self.last_search_kwargs = {
            "index_name": index_name,
            "limit": limit,
            "min_score": min_score,
            "filters": filters,
        }
        # For testing we ignore the embedding value and simply return all
        # documents in the requested index as perfect matches.
        target_indices = [index_name] if index_name else sorted(self._indices)

        results: list[SearchResult] = []
        for idx in target_indices:
            for (name, _), doc in self._docs.items():
                if name != idx:
                    continue
                results.append(SearchResult(document=doc, score=1.0, vector_score=1.0))

        return results[:limit]


class FakeEmbeddings:
    """Simple fake embedding provider for tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._model_name = "fake-model"
        self._dimensions = 1

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_text(self, text: str) -> list[float]:
        self.calls.append("embed_text")
        # Use the text length as a trivial embedding.
        return [float(len(text))]

    async def embed_query(self, query: str) -> list[float]:
        self.calls.append("embed_query")
        return [float(len(query))]

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - not used here
        return {"healthy": True, "provider": "fake"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create a TestClient bound to the API app using fake backends.

    The fixture constructs a TestClient first (so the FastAPI lifespan
    runs), then overwrites the global `_storage` and `_embeddings`
    references used by the endpoints so that no real backends are
    required.
    """

    storage = FakeStorage()
    embeddings = FakeEmbeddings()

    client = TestClient(app)

    monkeypatch.setattr("knowledgebase.api.main._storage", storage)
    monkeypatch.setattr("knowledgebase.api.main._embeddings", embeddings)
    monkeypatch.setattr("knowledgebase.api.main._SEARCH_RESULT_CACHE", {})
    monkeypatch.setattr("knowledgebase.api.main._EMBEDDING_CACHE", {})

    return client


@pytest.mark.api
class TestDocumentAndIndexEndpoints:
    """End-to-end tests for document and index CRUD and search."""

    def test_add_get_and_delete_document(self, client: TestClient) -> None:
        """Verify the basic document CRUD flow via the REST API."""

        payload = {
            "id": "doc-1",
            "content": "Hello from API",
            "index_name": "kb",
            "metadata": {"title": "API Doc"},
        }

        # Create document
        create_resp = client.post("/api/v1/documents", json=payload)
        assert create_resp.status_code == 200
        data = create_resp.json()
        assert data["id"] == "doc-1"
        assert data["index_name"] == "kb"
        assert data["has_embedding"] is True

        # Retrieve document
        get_resp = client.get("/api/v1/documents/kb/doc-1")
        assert get_resp.status_code == 200
        retrieved = get_resp.json()
        assert retrieved["id"] == "doc-1"
        assert retrieved["content"] == "Hello from API"
        assert retrieved["metadata"]["title"] == "API Doc"

        # Delete document
        del_resp = client.delete("/api/v1/documents/kb/doc-1")
        assert del_resp.status_code == 200
        del_data = del_resp.json()
        assert del_data["success"] is True

        # Subsequent GET should return 404
        missing_resp = client.get("/api/v1/documents/kb/doc-1")
        assert missing_resp.status_code == 404

    def test_search_documents_returns_results(self, client: TestClient) -> None:
        """The search endpoint should surface results produced by the storage backend."""

        # First, add a document via the API so it is present in fake storage.
        payload = {
            "id": "doc-search",
            "content": "Searchable content",
            "index_name": "kb",
            "metadata": {"title": "Search Doc"},
        }
        assert client.post("/api/v1/documents", json=payload).status_code == 200

        # Then perform a search.
        search_body = {
            "query": "Searchable",
            "index_name": "kb",
            "limit": 5,
            "min_score": 0.0,
            "filters": {},
        }

        resp = client.post("/api/v1/search", json=search_body)
        assert resp.status_code == 200
        data = resp.json()

        assert data["query"] == "Searchable"
        assert data["total"] >= 1
        ids = [item["document"]["id"] for item in data["results"]]
        assert "doc-search" in ids

    def test_search_accepts_legacy_top_k_and_index_fields(self, client: TestClient) -> None:
        """Legacy payload fields should map to current API fields for compatibility."""
        payload = {
            "id": "doc-legacy-search",
            "content": "Legacy-searchable content",
            "index_name": "kb",
            "metadata": {"title": "Legacy Search Doc"},
        }
        assert client.post("/api/v1/documents", json=payload).status_code == 200

        search_body = {
            "query": "Legacy-searchable",
            "index": "kb",
            "top_k": 1,
            "min_score": 0.0,
        }
        response = client.post("/api/v1/search", json=search_body)
        assert response.status_code == 200

        import knowledgebase.api.main as api_main

        assert api_main._storage is not None
        assert api_main._storage.last_search_kwargs is not None
        assert api_main._storage.last_search_kwargs["index_name"] == "kb"
        # Hybrid retrieval oversamples candidates; top_k bounds the public result.
        assert len(response.json()["results"]) == 1
        assert api_main.SearchRequest(**search_body).limit == 1

    def test_full_index_uses_pipeline_and_embeds(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """full_index=true routes through IndexingPipeline and returns has_embedding."""
        import knowledgebase.api.main as api_main

        class TrackingPipeline:
            def __init__(self, storage, embeddings):
                self.storage = storage
                self.embeddings = embeddings
                self.calls = 0

            async def index_text(
                self, content, doc_id, index_name="knowledgebase", metadata=None, chunk=True
            ):
                self.calls += 1
                emb = await self.embeddings.embed_text(content)
                from knowledgebase.core.models import Document, DocumentMetadata

                doc = Document(
                    id=doc_id,
                    content=content,
                    embedding=emb,
                    index_name=index_name,
                    metadata=DocumentMetadata(**(metadata or {})),
                )
                await self.storage.add_document(doc)
                return [doc]

        tracker = {"pipe": None}

        def factory(storage, embeddings):
            pipe = TrackingPipeline(storage, embeddings)
            tracker["pipe"] = pipe
            return pipe

        monkeypatch.setattr(api_main, "IndexingPipeline", factory)

        payload = {
            "id": "doc-full-index",
            "content": "Full index pipeline content for Engage360 verification",
            "index_name": "kb",
            "metadata": {"title": "Full Index Doc"},
            "full_index": True,
            "chunk": True,
        }
        resp = client.post("/api/v1/documents", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == "doc-full-index"
        assert data["has_embedding"] is True
        assert tracker["pipe"] is not None and tracker["pipe"].calls == 1

        # Document is retrievable with embedding flag
        get_resp = client.get("/api/v1/documents/kb/doc-full-index")
        assert get_resp.status_code == 200
        assert get_resp.json()["has_embedding"] is True

    def test_indices_crud_flow(self, client: TestClient) -> None:
        """Create, list, and delete indices via the REST API."""

        # Initially there may be zero indices; we don't assert on that.

        # Create an index
        create_body = {
            "name": "kb-index",
            "description": "Test index",
            "metadata_schema": {},
        }
        create_resp = client.post("/api/v1/indices", json=create_body)
        assert create_resp.status_code == 200
        assert create_resp.json()["success"] is True

        # List indices should now include kb-index
        list_resp = client.get("/api/v1/indices")
        assert list_resp.status_code == 200
        indices = list_resp.json()
        names = {idx["name"] for idx in indices}
        assert "kb-index" in names

        # Delete index
        delete_resp = client.delete("/api/v1/indices/kb-index")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["success"] is True

        # After deletion, the index should no longer appear in the list
        list_after = client.get("/api/v1/indices")
        assert list_after.status_code == 200
        names_after = {idx["name"] for idx in list_after.json()}
        assert "kb-index" not in names_after

    def test_result_cache_flag_off_calls_storage_each_time(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With result cache disabled, repeated requests should hit storage each time."""
        monkeypatch.setenv("KB_FEATURE_FLAGS__KB_SEARCH_RESULT_CACHE", "false")
        payload = {
            "id": "doc-cache-off",
            "content": "cache test",
            "index_name": "kb",
            "metadata": {"title": "Cache Off"},
        }
        assert client.post("/api/v1/documents", json=payload).status_code == 200
        search_body = {
            "query": "cache",
            "index_name": "kb",
            "limit": 5,
            "min_score": 0.0,
            "filters": {},
        }
        assert client.post("/api/v1/search", json=search_body).status_code == 200
        assert client.post("/api/v1/search", json=search_body).status_code == 200

        import knowledgebase.api.main as api_main

        assert api_main._storage is not None
        assert api_main._storage.search_calls == 2

    def test_result_cache_flag_on_reuses_storage_results(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With result cache enabled, repeated identical requests should reuse cached results."""
        monkeypatch.setenv("KB_FEATURE_FLAGS__KB_SEARCH_RESULT_CACHE", "true")
        payload = {
            "id": "doc-cache-on",
            "content": "cache enabled",
            "index_name": "kb",
            "metadata": {"title": "Cache On"},
        }
        assert client.post("/api/v1/documents", json=payload).status_code == 200
        search_body = {
            "query": "cache",
            "index_name": "kb",
            "limit": 5,
            "min_score": 0.0,
            "filters": {},
        }
        assert client.post("/api/v1/search", json=search_body).status_code == 200
        assert client.post("/api/v1/search", json=search_body).status_code == 200

        import knowledgebase.api.main as api_main

        assert api_main._storage is not None
        assert api_main._storage.search_calls == 1

    def test_query_embedding_cache_reuses_embedding_for_same_query(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Repeated same query should reuse cached query embedding."""
        monkeypatch.setenv("KB_FEATURE_FLAGS__KB_SEARCH_RESULT_CACHE", "false")
        payload = {
            "id": "doc-embed-cache",
            "content": "embedding cache",
            "index_name": "kb",
            "metadata": {"title": "Embed Cache"},
        }
        assert client.post("/api/v1/documents", json=payload).status_code == 200
        search_body = {
            "query": "embedding cache",
            "index_name": "kb",
            "limit": 5,
            "min_score": 0.0,
            "filters": {},
        }
        assert client.post("/api/v1/search", json=search_body).status_code == 200
        assert client.post("/api/v1/search", json=search_body).status_code == 200

        import knowledgebase.api.main as api_main

        assert api_main._embeddings is not None
        assert api_main._embeddings.calls.count("embed_query") == 1

    def test_list_documents_endpoint_returns_paginated_results(self, client: TestClient) -> None:
        """/api/v1/documents/list should return a paginated document list."""

        # Seed a few documents into the fake storage via the public API.
        for i in range(3):
            payload = {
                "id": f"doc-{i}",
                "content": f"Content {i}",
                "index_name": "kb",
                "metadata": {"title": f"Doc {i}"},
            }
            resp = client.post("/api/v1/documents", json=payload)
            assert resp.status_code == 200

        list_body = {"index_name": "kb", "offset": 1, "limit": 1}
        resp = client.post("/api/v1/documents/list", json=list_body)
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] == 3
        assert data["offset"] == 1
        assert data["limit"] == 1
        assert len(data["items"]) == 1
        # Ensure the shape of the returned item matches expectations
        item = data["items"][0]
        assert item["id"].startswith("doc-")
        assert item["index_name"] == "kb"
        assert "metadata" in item

    def test_search_service_not_initialized_returns_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Search should return 503 when storage or embeddings are missing."""

        monkeypatch.setattr("knowledgebase.api.main._storage", None)
        monkeypatch.setattr("knowledgebase.api.main._embeddings", None)

        search_body = {
            "query": "anything",
            "index_name": "kb",
            "limit": 1,
            "min_score": 0.0,
            "filters": {},
        }

        resp = client.post("/api/v1/search", json=search_body)
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Service not initialized"

    def test_add_document_service_not_initialized_returns_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adding a document should return 503 when backends are not ready."""

        monkeypatch.setattr("knowledgebase.api.main._storage", None)
        monkeypatch.setattr("knowledgebase.api.main._embeddings", None)

        payload = {
            "id": "doc-x",
            "content": "content",
            "index_name": "kb",
            "metadata": {},
        }

        resp = client.post("/api/v1/documents", json=payload)
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Service not initialized"

    def test_list_indices_service_not_initialized_returns_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Listing indices should return 503 when storage backend is missing."""

        monkeypatch.setattr("knowledgebase.api.main._storage", None)

        resp = client.get("/api/v1/indices")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "Service not initialized"


@pytest.mark.api
class TestAsyncIndexingFeatureFlag:
    """Tests for the kb.async-indexing OpenFeature flag (cr-015)."""

    def test_sync_path_default_returns_has_embedding_true(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the flag disabled (default), add_document returns has_embedding=True."""
        # Ensure the flag is explicitly off
        monkeypatch.delenv("KB_FEATURE_FLAGS__KB_ASYNC_INDEXING", raising=False)

        payload = {
            "id": "doc-sync",
            "content": "Sync path content",
            "index_name": "kb",
            "metadata": {"title": "Sync Doc"},
        }
        resp = client.post("/api/v1/documents", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_embedding"] is True
        assert data["id"] == "doc-sync"

        # Verify the stored document actually has an embedding
        import knowledgebase.api.main as api_main

        assert api_main._embeddings is not None
        assert "embed_text" in api_main._embeddings.calls

    def test_async_path_returns_has_embedding_false(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With kb.async-indexing enabled, add_document returns has_embedding=False immediately."""
        monkeypatch.setenv("KB_FEATURE_FLAGS__KB_ASYNC_INDEXING", "true")

        payload = {
            "id": "doc-async",
            "content": "Async path content",
            "index_name": "kb",
            "metadata": {"title": "Async Doc"},
        }
        resp = client.post("/api/v1/documents", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_embedding"] is False
        assert data["id"] == "doc-async"

    def test_async_path_stores_placeholder_document(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With async-indexing, the document is stored immediately (without embedding)."""
        monkeypatch.setenv("KB_FEATURE_FLAGS__KB_ASYNC_INDEXING", "true")

        payload = {
            "id": "doc-async-stored",
            "content": "Stored immediately",
            "index_name": "kb",
            "metadata": {"title": "Stored"},
        }
        resp = client.post("/api/v1/documents", json=payload)
        assert resp.status_code == 200

        # The document should be retrievable immediately via GET
        get_resp = client.get("/api/v1/documents/kb/doc-async-stored")
        assert get_resp.status_code == 200
        assert get_resp.json()["content"] == "Stored immediately"
