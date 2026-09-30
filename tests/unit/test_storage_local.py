"""Unit tests for the LocalStorageBackend.

These tests exercise the file-based storage backend using a temporary
directory so they do not touch real project data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledgebase.core.models import Document, DocumentMetadata
from knowledgebase.storage.local import LocalStorageBackend


@pytest.mark.unit
class TestLocalStorageBackend:
    """Tests for the local file-based storage backend."""

    @pytest.mark.asyncio
    async def test_create_index_and_list_indices(self, tmp_path: Path) -> None:
        """create_index should create an index that appears in list_indices."""

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        await backend.create_index("kb")

        indices = await backend.list_indices()
        names = {i.name for i in indices}

        assert "kb" in names

    @pytest.mark.asyncio
    async def test_add_get_and_delete_document(self, tmp_path: Path) -> None:
        """Documents added to an index should be retrievable and deletable."""

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        doc = Document(
            id="doc-1",
            content="Hello world",
            embedding=None,
            index_name="kb",
            metadata=DocumentMetadata(title="Title", path="/tmp/doc-1.md"),
        )

        await backend.add_document(doc)

        fetched = await backend.get_document("doc-1", "kb")
        assert fetched is not None
        assert fetched.id == "doc-1"
        assert fetched.content == "Hello world"
        assert fetched.metadata.title == "Title"

        deleted = await backend.delete_document("doc-1", "kb")
        assert deleted is True

        # Deleting again should return False (document no longer exists)
        deleted_again = await backend.delete_document("doc-1", "kb")
        assert deleted_again is False

    @pytest.mark.asyncio
    async def test_search_with_embeddings_and_filters(self, tmp_path: Path) -> None:
        """search should return only documents with embeddings that meet score and filter criteria."""

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        # Two simple 2D embeddings with clear cosine similarity behaviour.
        doc1 = Document(
            id="doc-a",
            content="Alpha",
            embedding=[1.0, 0.0],
            index_name="kb",
            metadata=DocumentMetadata(title="Alpha", tags=["group-a"]),
        )
        doc2 = Document(
            id="doc-b",
            content="Beta",
            embedding=[0.0, 1.0],
            index_name="kb",
            metadata=DocumentMetadata(title="Beta", tags=["group-b"]),
        )

        await backend.add_document(doc1)
        await backend.add_document(doc2)

        # Query close to doc1's embedding
        query_embedding = [1.0, 0.0]

        # Without filters we should see both documents, ordered by similarity.
        results = await backend.search(
            query_embedding=query_embedding,
            index_name="kb",
            limit=10,
            min_score=0.0,
            filters=None,
        )

        assert {r.document.id for r in results} == {"doc-a", "doc-b"}
        assert results[0].document.id == "doc-a"

        # With a filter only doc2 should be returned. The LocalStorageBackend
        # filter implementation expects simple equality for list-valued
        # metadata, so we filter on the exact list value.
        filtered_results = await backend.search(
            query_embedding=query_embedding,
            index_name="kb",
            limit=10,
            min_score=0.0,
            filters={"tags": [["group-b"]]},
        )

        assert [r.document.id for r in filtered_results] == ["doc-b"]

    @pytest.mark.asyncio
    async def test_list_documents_pagination(self, tmp_path: Path) -> None:
        """list_documents should honour offset and limit and return total count."""

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        # Create several documents
        for i in range(5):
            await backend.add_document(
                Document(
                    id=f"doc-{i}",
                    content=f"Content {i}",
                    embedding=None,
                    index_name="kb",
                    metadata=DocumentMetadata(title=f"Doc {i}"),
                )
            )

        page, total = await backend.list_documents("kb", offset=1, limit=2)

        assert total == 5
        assert len(page) == 2

    @pytest.mark.asyncio
    async def test_health_check_reports_basic_status(self, tmp_path: Path) -> None:
        """health_check should report local backend health and document statistics."""

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        # Create a small index with one document to ensure counts are non-zero.
        doc = Document(
            id="doc-health",
            content="Health check",
            embedding=None,
            index_name="kb",
            metadata=DocumentMetadata(title="Health"),
        )

        await backend.add_document(doc)

        health = await backend.health_check()

        assert health["backend"] == "local"
        assert isinstance(health["document_count"], int)
        # Default health path skips expensive document enumeration.
        assert health["document_count"] == -1
        assert health.get("document_count_mode") == "skipped_for_health_latency"
        assert health.get("index_count", 0) >= 1
        assert isinstance(health["latency_ms"], (float, int))
        assert "healthy" in health

    @pytest.mark.asyncio
    async def test_get_storage_usage_bytes_and_list_cache(self, tmp_path: Path) -> None:
        """Storage size should reflect index files and list_indices should cache counts."""

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        await backend.add_document(
            Document(
                id="doc-size",
                content="x" * 2048,
                embedding=None,
                index_name="kb",
                metadata=DocumentMetadata(title="Size"),
            )
        )

        size_bytes = await backend.get_storage_usage_bytes(force_refresh=True)
        assert size_bytes > 0

        indices = await backend.list_indices()
        assert len(indices) == 1
        assert indices[0].document_count == 1

        # Second list should hit TTL cache (same count) without error.
        indices_again = await backend.list_indices()
        assert indices_again[0].document_count == 1
        assert backend._storage_size_cache_bytes == size_bytes

    @pytest.mark.asyncio
    async def test_cosine_similarity_edge_cases(self) -> None:
        """Test cosine similarity function edge cases."""
        from knowledgebase.storage.local import cosine_similarity

        # Test dimension mismatch
        with pytest.raises(ValueError, match="Vector dimensions must match"):
            cosine_similarity([1.0], [1.0, 2.0])

        # Test zero vectors
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
        assert cosine_similarity([1.0, 1.0], [0.0, 0.0]) == 0.0

        # Test identical vectors (allow for floating point precision)
        assert abs(cosine_similarity([1.0, 1.0], [1.0, 1.0]) - 1.0) < 1e-10

        # Test orthogonal vectors
        assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-10

    @pytest.mark.asyncio
    async def test_initialize_error_handling(self, tmp_path: Path) -> None:
        """Test error handling during initialization."""
        from knowledgebase.storage.base import StorageError

        # Create a backend pointing to a file instead of directory
        bad_file = tmp_path / "file.txt"
        bad_file.write_text("content")

        backend = LocalStorageBackend(base_path=str(bad_file / "subpath"))

        with pytest.raises(StorageError, match="Failed to initialize local storage"):
            await backend.initialize()

    @pytest.mark.asyncio
    async def test_create_index_error_handling(self, tmp_path: Path) -> None:
        """Test error handling during index creation."""
        import os

        from knowledgebase.storage.base import StorageError

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        # Create a scenario that will cause failure during index creation
        # by making a directory read-only
        if os.name != "nt":  # Skip on Windows as chmod behaves differently
            os.chmod(tmp_path / "indices", 0o444)  # Read-only

            with pytest.raises(StorageError, match="Failed to create index"):
                await backend.create_index("test-index")

            # Restore permissions for cleanup
            os.chmod(tmp_path / "indices", 0o755)

    @pytest.mark.asyncio
    async def test_delete_index_error_handling(self, tmp_path: Path) -> None:
        """Test error handling during index deletion."""

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        # Create an index first
        await backend.create_index("test-index")

        # Test deleting non-existent index (should not raise)
        await backend.delete_index("non-existent")

        # Test successful deletion
        await backend.delete_index("test-index")

        # Verify it's gone
        indices = await backend.list_indices()
        assert not any(i.name == "test-index" for i in indices)

    @pytest.mark.asyncio
    async def test_list_indices_error_conditions(self, tmp_path: Path) -> None:
        """Test list_indices with various error conditions."""
        backend = LocalStorageBackend(base_path=str(tmp_path / "nonexistent"))

        # Should return empty list for non-existent base path
        indices = await backend.list_indices()
        assert indices == []

        # Test with corrupted metadata
        await backend.initialize()
        await backend.create_index("good-index")

        # Create a directory that looks like an index but has corrupted metadata
        bad_index_path = backend._get_index_path("bad-index")
        bad_index_path.mkdir(parents=True, exist_ok=True)
        (bad_index_path / "metadata.json").write_text("invalid json")

        # Should still work and skip the corrupted index
        from knowledgebase.storage.base import StorageError

        with pytest.raises(StorageError, match="Failed to list indices"):
            await backend.list_indices()

    @pytest.mark.asyncio
    async def test_document_operations_error_handling(self, tmp_path: Path) -> None:
        """Test error handling in document operations."""

        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        doc = Document(
            id="test-doc",
            content="Test content",
            embedding=None,
            index_name="test-index",
            metadata=DocumentMetadata(title="Test"),
        )

        # Test get_document with non-existent document
        result = await backend.get_document("non-existent", "non-existent-index")
        assert result is None

        # Test delete_document with non-existent document
        deleted = await backend.delete_document("non-existent", "non-existent-index")
        assert deleted is False

        # Test add_documents bulk operation
        docs = [
            doc,
            Document(
                id="test-doc-2",
                content="Test content 2",
                embedding=None,
                index_name="test-index",
                metadata=DocumentMetadata(title="Test 2"),
            ),
        ]

        await backend.add_documents(docs)

        # Verify both documents were added
        retrieved1 = await backend.get_document("test-doc", "test-index")
        retrieved2 = await backend.get_document("test-doc-2", "test-index")
        assert retrieved1 is not None
        assert retrieved2 is not None

    @pytest.mark.asyncio
    async def test_search_error_conditions(self, tmp_path: Path) -> None:
        """Test search with various error conditions and edge cases."""
        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        # Test search with no indices
        results = await backend.search([1.0, 0.0], index_name="non-existent")
        assert results == []

        # Test search across all indices (none exist)
        results = await backend.search([1.0, 0.0], index_name=None)
        assert results == []

        # Create documents with and without embeddings
        doc_with_embedding = Document(
            id="doc-with-emb",
            content="Content with embedding",
            embedding=[1.0, 0.0],
            index_name="test-index",
            metadata=DocumentMetadata(title="With Embedding", language="en"),
        )

        doc_without_embedding = Document(
            id="doc-without-emb",
            content="Content without embedding",
            embedding=None,
            index_name="test-index",
            metadata=DocumentMetadata(title="Without Embedding"),
        )

        await backend.add_document(doc_with_embedding)
        await backend.add_document(doc_without_embedding)

        # Search should skip documents without embeddings
        results = await backend.search([1.0, 0.0], index_name="test-index", min_score=0.0)
        assert len(results) == 1
        assert results[0].document.id == "doc-with-emb"

        # Test filtering
        results = await backend.search(
            [1.0, 0.0], index_name="test-index", filters={"language": ["en"]}
        )
        assert len(results) == 1
        assert results[0].document.id == "doc-with-emb"

        # Test filtering with no matches
        results = await backend.search(
            [1.0, 0.0], index_name="test-index", filters={"language": ["fr"]}
        )
        assert results == []

        # Test min_score filtering
        results = await backend.search([1.0, 0.0], index_name="test-index", min_score=0.99)
        assert len(results) == 1  # Should find the exact match

        results = await backend.search([1.0, 0.0], index_name="test-index", min_score=1.1)
        assert results == []  # No results above impossible threshold

    @pytest.mark.asyncio
    async def test_filter_matching(self, tmp_path: Path) -> None:
        """Test the _matches_filters method with various scenarios."""
        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))

        metadata = {
            "title": "Test Document",
            "tags": ["python", "testing"],
            "language": "en",
            "score": 0.95,
        }

        # Test exact match
        assert backend._matches_filters(metadata, {"language": "en"})

        # Test list membership
        assert backend._matches_filters(metadata, {"language": ["en", "fr"]})
        assert not backend._matches_filters(metadata, {"language": ["fr", "de"]})

        # Test missing key
        assert not backend._matches_filters(metadata, {"missing_key": "value"})

        # Test multiple filters (all must match)
        assert backend._matches_filters(metadata, {"language": "en", "score": 0.95})
        assert not backend._matches_filters(metadata, {"language": "en", "score": 0.90})

    @pytest.mark.asyncio
    async def test_health_check_error_conditions(self, tmp_path: Path) -> None:
        """Test health check with error conditions."""
        # Test with non-existent path
        backend = LocalStorageBackend(base_path=str(tmp_path / "nonexistent"))

        health = await backend.health_check()
        assert health["healthy"] is False
        assert health["exists"] is False
        assert health["writable"] is False
        assert health["document_count"] == -1  # skipped unless KB_HEALTH_INCLUDE_DOC_COUNTS=true
        assert "latency_ms" in health

    @pytest.mark.asyncio
    async def test_close_operation(self, tmp_path: Path) -> None:
        """Test the close operation."""
        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        assert backend._initialized is True

        await backend.close()

        assert backend._initialized is False

    @pytest.mark.asyncio
    async def test_vectorized_search_parity_with_legacy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Vectorized search should preserve legacy ranking and score parity."""
        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()
        await backend.add_document(
            Document(
                id="doc-1",
                content="Alpha",
                embedding=[1.0, 0.0],
                index_name="kb",
                metadata=DocumentMetadata(title="A"),
            )
        )
        await backend.add_document(
            Document(
                id="doc-2",
                content="Beta",
                embedding=[0.2, 0.8],
                index_name="kb",
                metadata=DocumentMetadata(title="B"),
            )
        )

        monkeypatch.setenv("KB_FEATURE_FLAGS__KB_SEARCH_VECTORIZED", "false")
        legacy = await backend.search([1.0, 0.0], index_name="kb", min_score=0.0, limit=10)

        monkeypatch.setenv("KB_FEATURE_FLAGS__KB_SEARCH_VECTORIZED", "true")
        vectorized = await backend.search([1.0, 0.0], index_name="kb", min_score=0.0, limit=10)

        assert [item.document.id for item in vectorized] == [item.document.id for item in legacy]
        for lhs, rhs in zip(vectorized, legacy):
            assert lhs.score == pytest.approx(rhs.score, rel=1e-6, abs=1e-6)

    @pytest.mark.asyncio
    async def test_vector_cache_invalidation_on_add_delete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Vector cache should refresh when documents are added or removed."""
        monkeypatch.setenv("KB_FEATURE_FLAGS__KB_SEARCH_VECTORIZED", "true")
        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()

        await backend.add_document(
            Document(
                id="doc-a",
                content="A",
                embedding=[1.0, 0.0],
                index_name="kb",
                metadata=DocumentMetadata(title="A"),
            )
        )

        first = await backend.search([1.0, 0.0], index_name="kb", min_score=0.0, limit=10)
        assert [r.document.id for r in first] == ["doc-a"]
        assert "kb" in backend._vector_cache

        await backend.add_document(
            Document(
                id="doc-b",
                content="B",
                embedding=[0.0, 1.0],
                index_name="kb",
                metadata=DocumentMetadata(title="B"),
            )
        )
        assert "kb" not in backend._vector_cache
        second = await backend.search([0.0, 1.0], index_name="kb", min_score=0.0, limit=10)
        assert second[0].document.id == "doc-b"

        await backend.delete_document("doc-b", "kb")
        assert "kb" not in backend._vector_cache
        third = await backend.search([0.0, 1.0], index_name="kb", min_score=0.0, limit=10)
        assert all(result.document.id != "doc-b" for result in third)

    @pytest.mark.asyncio
    async def test_vectorized_flag_off_uses_legacy_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When vectorized flag is disabled, legacy path should be used."""
        monkeypatch.setenv("KB_FEATURE_FLAGS__KB_SEARCH_VECTORIZED", "false")
        backend = LocalStorageBackend(base_path=str(tmp_path / "indices"))
        await backend.initialize()
        await backend.add_document(
            Document(
                id="doc-a",
                content="A",
                embedding=[1.0, 0.0],
                index_name="kb",
                metadata=DocumentMetadata(title="A"),
            )
        )

        results = await backend.search([1.0, 0.0], index_name="kb", min_score=0.0, limit=10)
        assert [r.document.id for r in results] == ["doc-a"]
        assert backend._vector_cache == {}
