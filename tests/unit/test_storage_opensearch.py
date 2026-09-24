"""Unit tests for the OpenSearch storage backend.

These tests use a stub OpenSearch client and do not talk to a real
OpenSearch cluster.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from knowledgebase.core.models import Document, DocumentMetadata, IndexInfo

# ---------------------------------------------------------------------------
# Provide a minimal opensearchpy stub so the backend module can be imported
# without needing the real opensearch-py package installed.
# ---------------------------------------------------------------------------


class _DummyOpenSearch:  # pragma: no cover - used only for import wiring
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


opensearch_stub = types.SimpleNamespace(
    OpenSearch=_DummyOpenSearch,
    RequestsHttpConnection=object,
)
sys.modules.setdefault("opensearchpy", opensearch_stub)


from knowledgebase.storage.opensearch import OpenSearchStorageBackend  # noqa: E402


@pytest.mark.unit
class TestOpenSearchStorageBackend:
    """Tests for configuration and basic behaviour of OpenSearch backend."""

    def test_refreshable_aoss_auth_rebuilds_signer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_RefreshableAOSSAuth should build a fresh AWS4Auth on each call."""

        from knowledgebase.storage.opensearch import _RefreshableAOSSAuth

        class Creds:
            access_key = "AKIA"
            secret_key = "SECRET"
            token = "TOKEN"

        class Frozen:
            def get_frozen_credentials(self) -> Creds:
                return Creds()

        class Session:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.args = args
                self.kwargs = kwargs

            def get_credentials(self) -> Frozen:
                return Frozen()

        class FakeAWS4Auth:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.args = args
                self.kwargs = kwargs
                self.calls = 0

            def __call__(self, request: Any) -> Any:
                self.calls += 1
                request.headers = getattr(request, "headers", {})
                request.headers["x-amz-test"] = "1"
                return request

        built: list[FakeAWS4Auth] = []

        def fake_aws4auth(*args: Any, **kwargs: Any) -> FakeAWS4Auth:
            auth = FakeAWS4Auth(*args, **kwargs)
            built.append(auth)
            return auth

        monkeypatch.setattr("boto3.Session", Session)
        monkeypatch.setattr("knowledgebase.storage.opensearch.AWS4Auth", fake_aws4auth)

        auth = _RefreshableAOSSAuth(region="us-east-2")

        class Req:
            headers: dict[str, str] = {}

        req1 = Req()
        req2 = Req()
        out1 = auth(req1)
        out2 = auth(req2)
        assert out1.headers["x-amz-test"] == "1"
        assert out2.headers["x-amz-test"] == "1"
        assert len(built) == 2
        assert built[0].kwargs["session_token"] == "TOKEN"
        assert built[0].args[2] == "us-east-2"
        assert built[0].args[3] == "aoss"

    def test_get_full_index_name_applies_prefix(self) -> None:
        """_get_full_index_name should apply the index_prefix when missing."""

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )

        assert backend._get_full_index_name("docs") == "kb-docs"  # type: ignore[attr-defined]
        # If the name is already prefixed, it should be returned unchanged.
        assert backend._get_full_index_name("kb-logs") == "kb-logs"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_create_index_creates_when_missing(self) -> None:
        """create_index should call the client's indices.create when index is absent."""

        class IndicesStub:
            def __init__(self) -> None:
                self.exists_calls: list[str] = []
                self.create_calls: list[tuple[str, dict[str, Any]]] = []

            def exists(self, index: str) -> bool:
                self.exists_calls.append(index)
                return False

            def create(self, index: str, body: dict[str, Any]) -> None:
                self.create_calls.append((index, body))

        class ClientStub:
            def __init__(self) -> None:
                self.indices = IndicesStub()

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        await backend.create_index("docs")

        indices = backend._client.indices  # type: ignore[attr-defined]
        assert indices.exists_calls == ["kb-docs"]
        assert len(indices.create_calls) == 1
        created_index, mapping = indices.create_calls[0]
        assert created_index == "kb-docs"
        assert "mappings" in mapping
        # Default vector_dimension (1536) when the caller doesn't configure one.
        vector_field = mapping["mappings"]["properties"][OpenSearchStorageBackend.VECTOR_FIELD]
        assert vector_field["dimension"] == 1536

    @pytest.mark.asyncio
    async def test_create_index_uses_configured_vector_dimension(self) -> None:
        """create_index should size the vector field to match the configured embedding provider."""

        class IndicesStub:
            def __init__(self) -> None:
                self.create_calls: list[tuple[str, dict[str, Any]]] = []

            def exists(self, index: str) -> bool:
                return False

            def create(self, index: str, body: dict[str, Any]) -> None:
                self.create_calls.append((index, body))

        class ClientStub:
            def __init__(self) -> None:
                self.indices = IndicesStub()

        # e.g. Ollama's nomic-embed-text (768) or Bedrock's titan-embed-text-v2 (1024) --
        # anything other than the 1536 default.
        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
            vector_dimension=768,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        await backend.create_index("docs")

        _, mapping = backend._client.indices.create_calls[0]  # type: ignore[attr-defined]
        vector_field = mapping["mappings"]["properties"][OpenSearchStorageBackend.VECTOR_FIELD]
        assert vector_field["dimension"] == 768

    @pytest.mark.asyncio
    async def test_list_indices_parses_cat_indices_response(self) -> None:
        """list_indices should map cat indices output into IndexInfo objects."""

        class ClientStub:
            def __init__(self) -> None:
                class Cat:
                    def indices(self, format: str = "json") -> list[dict[str, Any]]:  # type: ignore[override]
                        _ = format  # satisfy ruff about the unused parameter
                        return [
                            {"index": "kb-foo", "docs.count": "5"},
                            {"index": "other", "docs.count": "2"},
                        ]

                self.cat = Cat()

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        indices = await backend.list_indices()

        assert len(indices) == 1
        assert indices[0].name == "foo"  # prefix stripped
        assert indices[0].document_count == 5

    @pytest.mark.asyncio
    async def test_search_builds_results_from_hits(self) -> None:
        """search should convert OpenSearch hits into SearchResult objects."""

        class ClientStub:
            def __init__(self) -> None:
                self.last_body: dict[str, Any] | None = None

            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index  # satisfy ruff about the unused parameter
                self.last_body = body
                return {
                    "hits": {
                        "hits": [
                            {
                                "_id": "doc-1",
                                "_score": 0.9,
                                "_source": {
                                    "id": "doc-1",
                                    "content_text": "Hello from OpenSearch",
                                    "index_name": "kb",
                                    "chunk_index": 0,
                                    "total_chunks": 1,
                                    "metadata": {"title": "Title"},
                                },
                            }
                        ]
                    }
                }

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        results = await backend.search(
            query_embedding=[0.1, 0.2, 0.3],
            index_name="kb",
            limit=5,
            min_score=0.0,
            filters={"language": ["python"]},
        )

        assert len(results) == 1
        res = results[0]
        assert res.document.id == "doc-1"
        assert res.document.content == "Hello from OpenSearch"
        assert res.document.index_name == "kb"
        assert res.document.metadata.title == "Title"
        assert 0.0 <= res.score <= 1.0

    @pytest.mark.asyncio
    async def test_search_ignores_exclude_archive_policy_key(self) -> None:
        """``_exclude_archive`` must not be emitted as a term filter (zeros all hits)."""

        captured: dict[str, Any] = {}

        class ClientStub:
            def search(self, index: str, body: dict[str, Any]):  # noqa: ARG002
                captured["body"] = body
                return {
                    "hits": {
                        "hits": [
                            {
                                "_id": "canary-1",
                                "_score": 0.95,
                                "_source": {
                                    "id": "canary-1",
                                    "content_text": "Engage360 full_index canary",
                                    "index_name": "knowledge",
                                    "source_type": "api",
                                    "metadata": {"title": "canary", "source_type": "api"},
                                },
                            },
                            {
                                "_id": "archive__knowledge__foo",
                                "_score": 0.9,
                                "_source": {
                                    "id": "archive__knowledge__foo",
                                    "content_text": "archive dump",
                                    "index_name": "knowledge",
                                    "source_type": "archive",
                                    "metadata": {
                                        "title": "arch",
                                        "source_type": "archive",
                                        "path": "/Volumes/BaylyAI-External/knowledge-archive/x.md",
                                    },
                                },
                            },
                        ]
                    }
                }

        backend = OpenSearchStorageBackend(endpoint="https://example.invalid")
        backend._client = ClientStub()  # type: ignore[assignment]

        results = await backend.search(
            query_embedding=[0.1, 0.2],
            index_name="knowledge",
            limit=10,
            min_score=0.0,
            filters={"_exclude_archive": True},
        )

        body = captured["body"]
        # Policy key must not appear as a term filter field.
        body_s = str(body)
        assert (
            '"_exclude_archive"' not in body_s
            or "term" not in body_s.split("_exclude_archive")[0][-40:]
        )
        # Prefer: ensure filter clauses do not include _exclude_archive key
        q = body.get("query", {})
        bool_q = q.get("bool", {})
        for clause in bool_q.get("filter") or []:
            assert "_exclude_archive" not in str(clause)
        # Archive doc dropped post-filter; canary kept
        ids = [r.document.id for r in results]
        assert "canary-1" in ids
        assert "archive__knowledge__foo" not in ids

    @pytest.mark.asyncio
    async def test_list_documents_handles_total_dict(self) -> None:
        """list_documents should handle the ES-style total object in hits."""

        class ClientStub:
            def __init__(self) -> None:
                self.last_body: dict[str, Any] | None = None

                def search(index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                    _ = index  # satisfy ruff about the unused parameter
                    self.last_body = body
                    return {
                        "hits": {
                            "total": {"value": 3, "relation": "eq"},
                            "hits": [
                                {
                                    "_id": "doc-1",
                                    "_source": {
                                        "id": "doc-1",
                                        "content_text": "Body",
                                        "index_name": "kb",
                                        "chunk_index": 0,
                                        "total_chunks": 1,
                                        "metadata": {"title": "Doc"},
                                    },
                                }
                            ],
                        }
                    }

                self.search = search

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        docs, total = await backend.list_documents("kb", offset=0, limit=10)

        assert total == 3
        assert len(docs) == 1
        assert docs[0].id == "doc-1"
        assert docs[0].metadata.title == "Doc"
        # Lean _source includes content field by default; never pull vectors.
        body = backend._client.last_body  # type: ignore[attr-defined]
        assert body is not None
        assert "includes" in body["_source"]
        assert OpenSearchStorageBackend.VECTOR_FIELD not in body["_source"]["includes"]
        assert OpenSearchStorageBackend.CONTENT_FIELD in body["_source"]["includes"]

    @pytest.mark.asyncio
    async def test_list_documents_truncates_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """list_documents should truncate content_text to LIST_CONTENT_MAX_CHARS."""
        monkeypatch.setenv("KB_OPENSEARCH_LIST_CONTENT_MAX_CHARS", "8")

        class ClientStub:
            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index, body
                return {
                    "hits": {
                        "total": {"value": 1, "relation": "eq"},
                        "hits": [
                            {
                                "_id": "doc-long",
                                "_source": {
                                    "id": "doc-long",
                                    "content_text": "ABCDEFGHIJKLMNOP",
                                    "index_name": "kb",
                                    "metadata": {"title": "Long"},
                                },
                            }
                        ],
                    }
                }

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        docs, total = await backend.list_documents("kb", offset=0, limit=5)
        assert total == 1
        assert docs[0].content == "ABCDEFGH"

    @pytest.mark.asyncio
    async def test_list_documents_retries_without_sort_on_mapping_error(self) -> None:
        """When updated_at sort fails, list_documents retries without sort."""

        class ClientStub:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                self.calls.append(body)
                if "sort" in body:
                    raise Exception("No mapping found for [updated_at] in order to sort on")
                return {
                    "hits": {
                        "total": 1,
                        "hits": [
                            {
                                "_id": "doc-2",
                                "_source": {
                                    "id": "doc-2",
                                    "content_text": "ok",
                                    "index_name": "kb",
                                    "metadata": {},
                                },
                            }
                        ],
                    }
                }

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        docs, total = await backend.list_documents("kb", offset=0, limit=5)
        assert total == 1
        assert docs[0].id == "doc-2"
        assert len(backend._client.calls) == 2  # type: ignore[attr-defined]
        assert "sort" in backend._client.calls[0]  # type: ignore[attr-defined]
        assert "sort" not in backend._client.calls[1]  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_delete_index_deletes_when_index_exists(self) -> None:
        """delete_index should call indices.delete when the index is present."""

        class IndicesStub:
            def __init__(self) -> None:
                self.exists_calls: list[str] = []
                self.delete_calls: list[str] = []

            def exists(self, index: str) -> bool:
                self.exists_calls.append(index)
                return True

            def delete(self, index: str) -> None:
                self.delete_calls.append(index)

        class ClientStub:
            def __init__(self) -> None:
                self.indices = IndicesStub()

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        await backend.delete_index("docs")

        indices = backend._client.indices  # type: ignore[attr-defined]
        assert indices.exists_calls == ["kb-docs"]
        assert indices.delete_calls == ["kb-docs"]

    @pytest.mark.asyncio
    async def test_add_and_get_document_round_trip(self) -> None:
        """add_document should index a document that can be retrieved by get_document.

        AOSS rejects application-supplied document IDs, so add_document
        indexes without an id (auto-generated by OpenSearch) and
        get_document looks documents up by their "id" field via search
        instead of a direct by-_id fetch.
        """

        class IndicesStub:
            def __init__(self) -> None:
                self.exists_calls: list[str] = []

            def exists(self, index: str) -> bool:
                self.exists_calls.append(index)
                return True

        class ClientStub:
            def __init__(self) -> None:
                self.indices = IndicesStub()
                self.index_calls: list[dict[str, Any]] = []
                self.delete_calls: list[str] = []
                self._next_real_id = 1
                self._stored: dict[str, dict[str, Any]] = {}

            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                term = body["query"]["term"]["id"]
                hits = [
                    {"_id": real_id, "_source": doc}
                    for real_id, doc in self._stored.items()
                    if doc.get("id") == term
                ]
                return {"hits": {"hits": hits}}

            def index(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                real_id = f"auto-{self._next_real_id}"
                self._next_real_id += 1
                self.index_calls.append(body)
                self._stored[real_id] = body
                return {"_id": real_id, "result": "created"}

            def delete(self, index: str, id: str) -> None:  # type: ignore[override]
                _ = index
                self.delete_calls.append(id)
                self._stored.pop(id, None)

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        doc = Document(
            id="doc-1",
            content="Hello from OpenSearch",
            embedding=[0.1, 0.2, 0.3],
            index_name="docs",
            metadata=DocumentMetadata(title="Title", path="/tmp/doc.txt"),
            chunk_index=0,
            total_chunks=1,
        )

        await backend.add_document(doc)

        client = backend._client  # type: ignore[attr-defined]
        assert client.index_calls  # type: ignore[truthy-function]
        stored_body = client.index_calls[0]
        assert stored_body["id"] == "doc-1"
        assert stored_body["index_name"] == "docs"
        assert stored_body["title"] == "Title"
        assert stored_body["path"] == "/tmp/doc.txt"
        # No existing document yet, so nothing should have been deleted.
        assert client.delete_calls == []

        # Ensure get_document reconstructs a Document from the stored source.
        fetched = await backend.get_document("doc-1", "docs")
        assert fetched is not None
        assert fetched.id == "doc-1"
        assert fetched.content == "Hello from OpenSearch"
        assert fetched.metadata.title == "Title"

    @pytest.mark.asyncio
    async def test_add_document_overwrite_deletes_existing_by_real_id(self) -> None:
        """Re-adding the same app-level ID should delete the prior document first.

        AOSS has no upsert-by-id and no _delete_by_query, so overwrite is
        approximated by searching for the existing document (by its "id"
        field) and deleting it by its real, OpenSearch-assigned _id before
        indexing the new version.
        """

        class IndicesStub:
            def exists(self, index: str) -> bool:
                _ = index
                return True

        class ClientStub:
            def __init__(self) -> None:
                self.indices = IndicesStub()
                self.delete_calls: list[str] = []
                self._next_real_id = 1
                self._stored: dict[str, dict[str, Any]] = {}

            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                term = body["query"]["term"]["id"]
                hits = [
                    {"_id": real_id, "_source": doc}
                    for real_id, doc in self._stored.items()
                    if doc.get("id") == term
                ]
                return {"hits": {"hits": hits}}

            def index(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                real_id = f"auto-{self._next_real_id}"
                self._next_real_id += 1
                self._stored[real_id] = body
                return {"_id": real_id, "result": "created"}

            def delete(self, index: str, id: str) -> None:  # type: ignore[override]
                _ = index
                self.delete_calls.append(id)
                self._stored.pop(id, None)

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        client = ClientStub()
        backend._client = client  # type: ignore[attr-defined]

        first = Document(id="doc-1", content="version one", index_name="docs")
        await backend.add_document(first)
        assert client.delete_calls == []
        assert len(client._stored) == 1

        second = Document(id="doc-1", content="version two", index_name="docs")
        await backend.add_document(second)

        # The first version's real _id should have been deleted before the
        # second version was indexed.
        assert len(client.delete_calls) == 1
        assert len(client._stored) == 1
        remaining = next(iter(client._stored.values()))
        assert remaining[OpenSearchStorageBackend.CONTENT_FIELD] == "version two"

    @pytest.mark.asyncio
    async def test_add_documents_bulk_indexes_multiple(self) -> None:
        """add_documents should issue a bulk request with paired actions and bodies."""

        class IndicesStub:
            def __init__(self) -> None:
                self.exists_calls: list[str] = []

            def exists(self, index: str) -> bool:
                self.exists_calls.append(index)
                return True

        class ClientStub:
            def __init__(self) -> None:
                self.indices = IndicesStub()
                self.bulk_calls: list[dict[str, Any]] = []

            def bulk(self, body: list[dict[str, Any]]) -> dict[str, Any]:  # type: ignore[override]
                self.bulk_calls.append({"body": body})
                return {"errors": False}

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        docs = [
            Document(
                id=f"doc-{i}",
                content=f"Content {i}",
                embedding=[float(i)],
                index_name="docs",
                metadata=DocumentMetadata(title=f"Title {i}"),
            )
            for i in range(2)
        ]

        await backend.add_documents(docs)

        client = backend._client  # type: ignore[attr-defined]
        assert client.bulk_calls  # type: ignore[truthy-function]
        bulk_body = client.bulk_calls[0]["body"]
        # We expect an action and a document body for each document.
        assert len(bulk_body) == 2 * len(docs)
        # Action dicts must not carry an _id -- AOSS rejects
        # application-supplied document IDs on write.
        action_dicts = bulk_body[0::2]
        for action in action_dicts:
            assert "_id" not in action["index"]

    @pytest.mark.asyncio
    async def test_health_check_uses_client_and_indices(self) -> None:
        """health_check should report aggregated index statistics when a client is set.

        OpenSearch Serverless (AOSS) doesn't support cluster.health(), so
        health_check derives reachability and stats purely from
        list_indices() — this stub client just needs to exist, not respond
        to any particular method.
        """

        class ClientStub:
            pass

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        async def fake_list_indices(*, use_cache: bool = True) -> list[IndexInfo]:  # type: ignore[override]
            _ = use_cache
            return [
                IndexInfo(name="docs", description="", document_count=2),
                IndexInfo(name="logs", description="", document_count=3),
            ]

        backend.list_indices = fake_list_indices  # type: ignore[assignment]

        status = await backend.health_check()

        assert status["healthy"] is True
        assert status["backend"] == "opensearch"
        assert status["document_count"] == 5

    @pytest.mark.asyncio
    async def test_health_check_reports_unhealthy_when_client_missing(self) -> None:
        """health_check should return an unhealthy status when no client is set."""

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )

        status = await backend.health_check()

        assert status["healthy"] is False
        assert status["backend"] == "opensearch"
        assert "Client not initialized" in status["error"]

    @pytest.mark.asyncio
    async def test_get_document_returns_none_when_search_finds_no_hits(self) -> None:
        """get_document should return None when the id-field search finds no hits.

        AOSS doesn't support fetching by an application-supplied ID, so
        "not found" is now signaled by an empty hits list rather than a
        NotFoundError exception.
        """

        class ClientStub:
            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                _ = body
                return {"hits": {"hits": []}}

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        doc = await backend.get_document("missing-id", "kb")

        assert doc is None

    @pytest.mark.asyncio
    async def test_get_document_returns_none_when_index_not_yet_visible_to_search(self) -> None:
        """get_document should return None if _search 404s with index_not_found_exception.

        A brand-new index can 404 on _search for a short window right after
        creation even though indices.exists() already reports it present
        (confirmed live) -- indistinguishable here from "no matching
        document".
        """

        class IndexNotFoundError(Exception):
            """Stub error type whose stringified type contains 'NotFoundError'."""

        class ClientStub:
            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                _ = body
                raise IndexNotFoundError("index_not_found_exception")

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        doc = await backend.get_document("doc-1", "kb")

        assert doc is None

    @pytest.mark.asyncio
    async def test_delete_document_returns_false_when_search_finds_no_hits(self) -> None:
        """delete_document should return False when the id-field search finds no hits.

        AOSS supports neither delete-by-application-ID nor
        _delete_by_query, so "nothing to delete" is now signaled by an
        empty hits list rather than a NotFoundError exception.
        """

        class ClientStub:
            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                _ = body
                return {"hits": {"hits": []}}

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        deleted = await backend.delete_document("missing-id", "kb")

        assert deleted is False

    @pytest.mark.asyncio
    async def test_delete_document_returns_false_when_index_not_yet_visible_to_search(
        self,
    ) -> None:
        """delete_document should return False if _search 404s with index_not_found_exception.

        This is exactly the race add_document hits in practice: it calls
        create_index() then immediately delete_document() for a brand-new
        index, and indices.exists() can report the index present before
        _search actually sees it (confirmed live).
        """

        class IndexNotFoundError(Exception):
            """Stub error type whose stringified type contains 'NotFoundError'."""

        class ClientStub:
            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                _ = body
                raise IndexNotFoundError("index_not_found_exception")

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        backend._client = ClientStub()  # type: ignore[attr-defined]

        deleted = await backend.delete_document("doc-1", "kb")

        assert deleted is False

    @pytest.mark.asyncio
    async def test_delete_document_deletes_by_real_id_when_found(self) -> None:
        """delete_document should delete by the real _id of each matching hit."""

        class ClientStub:
            def __init__(self) -> None:
                self.delete_calls: list[str] = []

            def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:  # type: ignore[override]
                _ = index
                _ = body
                return {
                    "hits": {
                        "hits": [
                            {"_id": "auto-1", "_source": {"id": "doc-1"}},
                        ]
                    }
                }

            def delete(self, index: str, id: str) -> None:  # type: ignore[override]
                _ = index
                self.delete_calls.append(id)

        backend = OpenSearchStorageBackend(
            endpoint="https://search.example.com",
            index_prefix="kb-",
            use_sigv4=False,
        )
        client = ClientStub()
        backend._client = client  # type: ignore[attr-defined]

        deleted = await backend.delete_document("doc-1", "kb")

        assert deleted is True
        assert client.delete_calls == ["auto-1"]
