"""Unit tests for AegisCMCPSyncService.

Exercises file discovery/exclude patterns, local sync (chunked, via a real
LocalStorageBackend + fake embeddings), and dev sync (chunked HTTP push
against a fake httpx.AsyncClient) -- all self-contained, no network calls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from knowledgebase.indexing.pipeline import IndexingPipeline
from knowledgebase.storage.local import LocalStorageBackend
from knowledgebase.sync.service import AegisCMCPSyncService, SyncTarget


class FakeEmbeddingProvider:
    """Deterministic embedding double -- no external API calls."""

    def __init__(self, dimensions: int = 4) -> None:
        self._dimensions = dimensions

    @property
    def model_name(self) -> str:
        return "fake-embedding-model"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_text(self, text: str) -> list[float]:
        return [float(len(text) % 7)] * self._dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_text(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        return await self.embed_text(query)

    async def health_check(self) -> dict[str, Any]:
        return {"healthy": True, "provider": "fake"}


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None


class _FakeAsyncClient:
    """Records POSTed requests instead of making real HTTP calls."""

    instances: list["_FakeAsyncClient"] = []

    def __init__(self, timeout: float | None = None, headers: dict[str, str] | None = None) -> None:
        self.timeout = timeout
        self.headers = headers or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        _FakeAsyncClient.instances.append(self)

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
        self.calls.append((url, json))
        return _FakeResponse()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _config(sync_source: Path, exclude_patterns: list[str] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": "knowledge",
        "sync_source": str(sync_source),
        "file_patterns": ["*.md"],
        "tags": ["knowledge"],
        "taxonomy": {"domain": "knowledge", "top_group": "knowledge", "lifecycle_state": "active"},
    }
    if exclude_patterns:
        entry["exclude_patterns"] = exclude_patterns
    return {"indices": [entry]}


@pytest.mark.unit
class TestDiscoverFiles:
    def test_discovers_matching_files_and_skips_excluded(self, tmp_path: Path) -> None:
        source = tmp_path / "canonical" / "knowledge"
        _write(source / "keep.md", "keep me")
        _write(source / "skip.md", "skip me")
        _write(source / "notes.txt", "not markdown")

        config = _config(source, exclude_patterns=["skip.md"])
        service = AegisCMCPSyncService()
        plans = service._resolve_plans(config, indices=None)
        assert len(plans) == 1

        files = service.discover_files(plans[0])
        names = {f.name for f in files}
        assert names == {"keep.md"}

    def test_filters_to_requested_index(self, tmp_path: Path) -> None:
        source = tmp_path / "canonical" / "knowledge"
        _write(source / "a.md", "a")
        config = _config(source)
        config["indices"].append(
            {"name": "runbooks", "sync_source": str(tmp_path / "canonical" / "runbooks")}
        )

        service = AegisCMCPSyncService()
        plans = service._resolve_plans(config, indices=["runbooks"])
        assert [p.index_config_name for p in plans] == ["runbooks"]


@pytest.mark.unit
class TestSyncLocal:
    @pytest.mark.asyncio
    async def test_large_file_is_chunked_into_multiple_documents(self, tmp_path: Path) -> None:
        source = tmp_path / "canonical" / "knowledge"
        large_content = "Paragraph one.\n\n" + ("word " * 1000)
        _write(source / "big.md", large_content)
        _write(source / "small.md", "short content")

        storage = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await storage.initialize()
        pipeline = IndexingPipeline(storage=storage, embeddings=FakeEmbeddingProvider())

        service = AegisCMCPSyncService(pipeline=pipeline)
        config = _config(source)
        service._load_config = lambda: config  # type: ignore[method-assign]

        report = await service.sync_local()

        assert report.target == SyncTarget.LOCAL.value
        assert report.index_results[0].files_discovered == 2
        # The large file alone must produce more than one stored chunk document.
        assert report.documents_synced > 2

        docs, total = await storage.list_documents(index_name="knowledge", limit=100)
        assert total == report.documents_synced
        assert any(doc.total_chunks > 1 for doc in docs)

    @pytest.mark.asyncio
    async def test_missing_sync_source_is_reported_as_error(self, tmp_path: Path) -> None:
        storage = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await storage.initialize()
        pipeline = IndexingPipeline(storage=storage, embeddings=FakeEmbeddingProvider())

        service = AegisCMCPSyncService(pipeline=pipeline)
        config = _config(tmp_path / "does-not-exist")
        service._load_config = lambda: config  # type: ignore[method-assign]

        report = await service.sync_local()

        assert report.documents_synced == 0
        assert report.errors
        assert "does not exist" in report.errors[0]


@pytest.mark.unit
class TestSyncDev:
    @pytest.mark.asyncio
    async def test_posts_chunks_with_auth_header(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _FakeAsyncClient.instances.clear()
        monkeypatch.setattr("knowledgebase.sync.service.httpx.AsyncClient", _FakeAsyncClient)

        source = tmp_path / "canonical" / "knowledge"
        large_content = "Paragraph one.\n\n" + ("word " * 1000)
        _write(source / "big.md", large_content)

        service = AegisCMCPSyncService()
        config = _config(source)
        service._load_config = lambda: config  # type: ignore[method-assign]

        report = await service.sync_dev(base_url="https://dev.example.com/", api_key="secret-token")

        client = _FakeAsyncClient.instances[-1]
        assert client.headers == {"Authorization": "Bearer secret-token"}
        assert len(client.calls) > 1  # large file split into multiple chunk posts
        assert len(client.calls) == report.documents_synced

        url, payload = client.calls[0]
        assert url == "https://dev.example.com/api/v1/documents"
        assert payload["index_name"] == "knowledge"
        assert payload["metadata"]["extra"]["total_chunks"] > 1

    @pytest.mark.asyncio
    async def test_omits_auth_header_when_no_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _FakeAsyncClient.instances.clear()
        monkeypatch.setattr("knowledgebase.sync.service.httpx.AsyncClient", _FakeAsyncClient)

        source = tmp_path / "canonical" / "knowledge"
        _write(source / "small.md", "short content")

        service = AegisCMCPSyncService()
        config = _config(source)
        service._load_config = lambda: config  # type: ignore[method-assign]

        await service.sync_dev(base_url="https://dev.example.com")

        client = _FakeAsyncClient.instances[-1]
        assert client.headers == {}
