"""Unit tests for the IndexingPipeline.

These tests use in-memory fakes for the storage backend and embedding provider
so they run quickly and deterministically without external services.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from knowledgebase.core.models import Document, DocumentMetadata
from knowledgebase.embeddings.base import EmbeddingProvider
from knowledgebase.indexing.chunker import DocumentChunker
from knowledgebase.indexing.pipeline import IndexingPipeline, create_pipeline
from knowledgebase.storage.base import StorageBackend


class InMemoryStorage(StorageBackend):
    """Simple in-memory StorageBackend implementation for tests."""

    def __init__(self) -> None:
        self.indices: dict[str, dict[str, Document]] = {}

    async def initialize(self) -> None:  # pragma: no cover - trivial
        return None

    async def close(self) -> None:  # pragma: no cover - trivial
        return None

    async def create_index(
        self,
        name: str,
        metadata_schema: dict[str, str] | None = None,  # noqa: ARG002
    ) -> None:  # type: ignore[override]
        if name not in self.indices:
            self.indices[name] = {}

    async def delete_index(self, name: str) -> None:
        self.indices.pop(name, None)

    async def list_indices(self) -> list[Any]:  # pragma: no cover - not used in these tests
        from knowledgebase.core.models import IndexInfo

        return [
            IndexInfo(name=name, description="", document_count=len(docs))
            for name, docs in self.indices.items()
        ]

    async def add_document(self, document: Document) -> None:
        if document.index_name not in self.indices:
            self.indices[document.index_name] = {}
        self.indices[document.index_name][document.id] = document

    async def add_documents(
        self, documents: list[Document]
    ) -> None:  # pragma: no cover - simple loop
        for doc in documents:
            await self.add_document(doc)

    async def get_document(self, doc_id: str, index_name: str) -> Document | None:
        return self.indices.get(index_name, {}).get(doc_id)

    async def delete_document(self, doc_id: str, index_name: str) -> bool:
        docs = self.indices.get(index_name)
        if docs is None or doc_id not in docs:
            return False
        del docs[doc_id]
        return True

    async def search(
        self,
        query_embedding: list[float],  # noqa: ARG002
        index_name: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,  # noqa: ARG002
        filters: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> list[Any]:  # pragma: no cover - searching is covered by LocalStorageBackend tests
        from knowledgebase.core.models import SearchResult

        results: list[SearchResult] = []
        indices = [index_name] if index_name else list(self.indices.keys())
        for name in indices:
            for doc in self.indices.get(name, {}).values():
                results.append(SearchResult(document=doc, score=1.0))
        return results[:limit]

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - trivial
        return {"healthy": True, "backend": "in-memory"}

    async def list_documents(
        self,
        index_name: str,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Document], int]:  # pragma: no cover - not needed here
        docs = list(self.indices.get(index_name, {}).values())
        total = len(docs)
        return docs[offset : offset + limit], total


class DummyEmbeddingProvider(EmbeddingProvider):
    """Deterministic embedding provider for tests."""

    @property
    def model_name(self) -> str:
        return "dummy-embedding-model"

    @property
    def dimensions(self) -> int:
        return 3

    async def embed_text(self, text: str) -> list[float]:
        length = float(len(text))
        return [length, 1.0, 0.0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_text(t) for t in texts]

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - trivial
        return {"healthy": True, "provider": "dummy", "model": self.model_name}


@pytest.mark.unit
class TestIndexingPipeline:
    """Unit tests for the IndexingPipeline core flows."""

    @pytest.mark.asyncio
    async def test_index_text_without_chunking_creates_single_document(self) -> None:
        """index_text with chunk=False should create a single document with metadata applied."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=10_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        docs = await pipeline.index_text(
            content="hello world",
            doc_id="doc-1",
            index_name="kb",
            metadata={"source": "unit-test"},
            chunk=False,
        )

        assert len(docs) == 1
        doc = docs[0]
        assert doc.id == "doc-1"
        assert doc.index_name == "kb"
        assert doc.content == "hello world"
        assert isinstance(doc.metadata, DocumentMetadata)
        assert doc.metadata.source == "unit-test"

        stored = await storage.get_document("doc-1", "kb")
        assert stored is not None
        assert stored.content == "hello world"

    @pytest.mark.asyncio
    async def test_index_text_with_chunking_creates_multiple_documents(self) -> None:
        """index_text with chunk=True and long content should create multiple chunk documents."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        # Small chunk size to force multiple chunks
        chunker = DocumentChunker(chunk_size=20, chunk_overlap=5, min_chunk_size=5)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        content = "Sentence one. Sentence two. Sentence three. Sentence four."

        docs = await pipeline.index_text(
            content=content,
            doc_id="doc-2",
            index_name="kb",
            metadata={"category": "test"},
            chunk=True,
        )

        assert len(docs) > 1

        total_chunks = len(docs)
        for idx, doc in enumerate(docs):
            assert doc.id == f"doc-2-chunk-{idx}"
            assert doc.chunk_index == idx
            assert doc.total_chunks == total_chunks
            assert doc.metadata.extra["parent_doc_id"] == "doc-2"
            assert doc.metadata.extra["start_char"] >= 0
            assert doc.metadata.extra["end_char"] > doc.metadata.extra["start_char"]

    @pytest.mark.asyncio
    async def test_reindex_document_replaces_existing_content(self) -> None:
        """reindex_document should delete the old document and write a new one with updated content."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=1_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        # Initial index
        original_docs = await pipeline.index_text(
            content="original content",
            doc_id="doc-3",
            index_name="kb",
            metadata={"version": 1},
            chunk=False,
        )
        assert len(original_docs) == 1

        # Re-index with new content
        updated_docs = await pipeline.reindex_document(
            doc_id="doc-3",
            index_name="kb",
            content="updated content",
        )

        assert len(updated_docs) == 1
        updated = updated_docs[0]
        assert updated.content == "updated content"

        stored = await storage.get_document("doc-3", "kb")
        assert stored is not None
        assert stored.content == "updated content"

    @pytest.mark.asyncio
    async def test_reindex_document_without_content_uses_existing(self) -> None:
        """reindex_document should reuse existing content when none is provided."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=1_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        await pipeline.index_text(
            content="keep this content",
            doc_id="doc-4",
            index_name="kb",
            metadata={"version": 1},
            chunk=False,
        )

        docs = await pipeline.reindex_document(doc_id="doc-4", index_name="kb")

        assert len(docs) == 1
        assert docs[0].content == "keep this content"

    @pytest.mark.asyncio
    async def test_reindex_document_raises_for_missing_document(self) -> None:
        """reindex_document should raise when the target document does not exist."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=1_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        with pytest.raises(ValueError):
            await pipeline.reindex_document(doc_id="missing-doc", index_name="kb")

    @pytest.mark.asyncio
    async def test_index_file_reads_from_disk_and_generates_id(self, tmp_path: Path) -> None:
        """index_file should read the file and generate a stable document id when not provided."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=10_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        file_path = tmp_path / "doc.txt"
        file_path.write_text("file-based content", encoding="utf-8")

        docs = await pipeline.index_file(
            file_path=str(file_path), index_name="kb", doc_id=None, chunk=False
        )

        assert len(docs) == 1
        doc = docs[0]
        assert doc.id.startswith("doc-")
        stored = await storage.get_document(doc.id, "kb")
        assert stored is not None
        assert stored.content == "file-based content"

    @pytest.mark.asyncio
    async def test_index_directory_yields_documents_for_matching_files(
        self, tmp_path: Path
    ) -> None:
        """index_directory should yield (Path, [Document]) tuples for matching files."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=10_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        file_md = docs_dir / "a.md"
        file_md.write_text("markdown", encoding="utf-8")
        file_txt = docs_dir / "b.txt"
        file_txt.write_text("text", encoding="utf-8")

        seen_paths: list[Path] = []
        seen_docs: list[Document] = []

        async for path, result in pipeline.index_directory(
            directory=docs_dir,
            index_name="kb",
            patterns=["*.md"],
            recursive=False,
        ):
            assert isinstance(path, Path)
            seen_paths.append(path)
            assert isinstance(result, list)
            assert all(isinstance(d, Document) for d in result)
            seen_docs.extend(result)

        assert file_md in seen_paths
        assert file_txt not in seen_paths
        assert any(d.index_name == "kb" for d in seen_docs)

    @pytest.mark.asyncio
    async def test_index_file_missing_raises_file_not_found(self, tmp_path: Path) -> None:
        """index_file should raise FileNotFoundError when the file does not exist."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=10_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        missing_path = str(tmp_path / "missing.txt")

        with pytest.raises(FileNotFoundError):
            await pipeline.index_file(file_path=missing_path, index_name="kb")

    @pytest.mark.asyncio
    async def test_index_directory_missing_directory_raises(self) -> None:
        """index_directory should raise FileNotFoundError for a missing directory."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=10_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        with pytest.raises(FileNotFoundError):
            async for _path, _docs in pipeline.index_directory(
                directory="/non-existent-dir-for-indexing-tests",
                index_name="kb",
            ):
                pass

    @pytest.mark.asyncio
    async def test_index_directory_yields_exception_when_index_file_fails(
        self, tmp_path: Path
    ) -> None:
        """index_directory should yield an Exception when index_file raises for a file."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=10_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        docs_dir = tmp_path / "docs-error"
        docs_dir.mkdir()
        file_md = docs_dir / "a.md"
        file_md.write_text("markdown", encoding="utf-8")

        async def failing_index_file(
            *args: Any, **kwargs: Any
        ) -> list[Document]:  # noqa: D401, ARG001
            """Always raise to exercise the error-handling branch in index_directory."""

            raise RuntimeError("index failure")

        pipeline.index_file = failing_index_file  # type: ignore[assignment]

        seen_results: list[tuple[Path, Exception]] = []
        async for path, result in pipeline.index_directory(
            directory=docs_dir,
            index_name="kb",
            patterns=["*.md"],
            recursive=False,
        ):
            assert path == file_md
            assert isinstance(result, Exception)
            seen_results.append((path, result))

        assert seen_results
        assert any("index failure" in str(exc) for _path, exc in seen_results)

    def test_generate_doc_id_is_stable_and_prefixed(self) -> None:
        """_generate_doc_id should be stable for the same input and use a doc- prefix."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()
        chunker = DocumentChunker(chunk_size=10_000, chunk_overlap=100, min_chunk_size=10)
        pipeline = IndexingPipeline(storage=storage, embeddings=embeddings, chunker=chunker)

        doc_id1 = pipeline._generate_doc_id("/tmp/example-1")  # type: ignore[attr-defined]
        doc_id2 = pipeline._generate_doc_id("/tmp/example-1")  # type: ignore[attr-defined]
        doc_id3 = pipeline._generate_doc_id("/tmp/example-2")  # type: ignore[attr-defined]

        assert doc_id1 == doc_id2
        assert doc_id1.startswith("doc-")
        assert doc_id3.startswith("doc-")
        assert doc_id1 != doc_id3


@pytest.mark.unit
class TestCreatePipeline:
    """Unit tests for the create_pipeline helper."""

    @pytest.mark.asyncio
    async def test_create_pipeline_uses_default_backends(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_pipeline should obtain and initialize default storage and embeddings."""

        storage = InMemoryStorage()
        embeddings = DummyEmbeddingProvider()

        # Track whether initialize was called on the storage instance returned
        # by the storage factory.
        initialized: dict[str, bool] = {"value": False}

        async def fake_initialize() -> None:  # noqa: D401
            """Mark the storage as initialized without side effects."""

            initialized["value"] = True

        import knowledgebase.embeddings as embeddings_module
        import knowledgebase.storage as storage_module

        monkeypatch.setattr(storage, "initialize", fake_initialize, raising=False)
        monkeypatch.setattr(storage_module, "get_storage_backend", lambda: storage)
        monkeypatch.setattr(embeddings_module, "get_embedding_provider", lambda: embeddings)

        # Call create_pipeline with no explicit arguments so that it exercises
        # the default "get_storage_backend" and "get_embedding_provider" paths.
        pipeline = await create_pipeline()

        assert isinstance(pipeline, IndexingPipeline)
        assert pipeline.storage is storage
        assert pipeline.embeddings is embeddings
        assert initialized["value"] is True
