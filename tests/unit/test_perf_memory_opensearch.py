"""Performance/memory optimizations for OpenSearch + health caches."""

from __future__ import annotations

import sys
import types
import time
from typing import Any

import pytest


# Minimal opensearchpy stub for import.
class _DummyOpenSearch:  # pragma: no cover
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


sys.modules.setdefault(
    "opensearchpy",
    types.SimpleNamespace(OpenSearch=_DummyOpenSearch, RequestsHttpConnection=object),
)

from knowledgebase.storage.opensearch import OpenSearchStorageBackend  # noqa: E402
from knowledgebase.api import main as api_main  # noqa: E402


@pytest.mark.unit
@pytest.mark.asyncio
async def test_opensearch_search_uses_lean_source_and_truncates_content() -> None:
    class ClientStub:
        def __init__(self) -> None:
            self.last_body: dict[str, Any] | None = None

        def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
            self.last_body = body
            return {
                "hits": {
                    "hits": [
                        {
                            "_id": "auto-1",
                            "_score": 0.91,
                            "_source": {
                                "id": "doc-1",
                                "content_text": "x" * 5000,
                                "index_name": "knowledge",
                                "title": "t",
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
    backend._search_content_max_chars = 100
    backend._client = ClientStub()  # type: ignore[assignment]

    results = await backend.search(query_embedding=[0.1, 0.2], index_name="knowledge", limit=3)
    assert backend._client.last_body is not None  # type: ignore[union-attr]
    source = backend._client.last_body["_source"]  # type: ignore[index]
    assert "includes" in source
    assert backend.VECTOR_FIELD not in source.get("includes", [])
    assert backend._client.last_body["query"]["knn"][backend.VECTOR_FIELD]["k"] >= 3  # type: ignore[index]
    assert len(results) == 1
    assert len(results[0].document.content) == 100


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_indices_cache_avoids_second_cat_call() -> None:
    class Cat:
        def __init__(self) -> None:
            self.calls = 0

        def indices(self, format: str = "json") -> list[dict[str, Any]]:
            self.calls += 1
            return [{"index": "kb-knowledge", "docs.count": "2"}]

    class ClientStub:
        def __init__(self) -> None:
            self.cat = Cat()

    backend = OpenSearchStorageBackend(
        endpoint="https://search.example.com",
        index_prefix="kb-",
        use_sigv4=False,
    )
    backend._indices_cache_ttl_seconds = 60
    backend._client = ClientStub()  # type: ignore[assignment]

    first = await backend.list_indices()
    second = await backend.list_indices()
    assert backend._client.cat.calls == 1  # type: ignore[union-attr]
    assert [i.name for i in first] == ["knowledge"]
    assert [i.name for i in second] == ["knowledge"]

    # Force refresh
    third = await backend.list_indices(use_cache=False)
    assert backend._client.cat.calls == 2  # type: ignore[union-attr]
    assert [i.name for i in third] == ["knowledge"]


@pytest.mark.unit
def test_cache_put_evicts_when_over_max() -> None:
    cache: dict[str, tuple[float, str]] = {}
    for i in range(5):
        api_main._cache_put(cache, f"k{i}", f"v{i}", max_entries=3)
    assert len(cache) == 3
    assert "k0" not in cache
    assert "k4" in cache


@pytest.mark.unit
def test_cache_get_expires() -> None:
    cache = {"k": (time.time() - 100, {"ok": True})}
    assert api_main._cache_get(cache, "k", ttl=1) is None
    assert "k" not in cache
