"""Additional tests for storage base class to improve coverage."""

from __future__ import annotations


import pytest

from knowledgebase.storage.base import StorageBackend, StorageError


class TestStorageError:
    """Test StorageError exception class."""

    def test_storage_error_creation_minimal(self) -> None:
        """Test creating StorageError with minimal parameters."""
        error = StorageError("Test error")

        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.backend is None
        assert error.operation is None
        assert error.original_error is None

    def test_storage_error_creation_full(self) -> None:
        """Test creating StorageError with all parameters."""
        original_error = ValueError("Original error")
        error = StorageError(
            message="Test error",
            backend="test-backend",
            operation="test-operation",
            original_error=original_error,
        )

        # The StorageError includes backend and operation in string representation
        assert "Test error" in str(error)
        assert error.message == "Test error"
        assert error.backend == "test-backend"
        assert error.operation == "test-operation"
        assert error.original_error is original_error


class MockStorageBackend(StorageBackend):
    """Mock implementation of StorageBackend for testing abstract methods."""

    def __init__(self):
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def create_index(
        self, _name: str, _metadata_schema: dict[str, str] | None = None
    ) -> None:
        pass

    async def delete_index(self, _name: str) -> None:
        pass

    async def list_indices(self):
        return []

    async def add_document(self, _document) -> None:
        pass

    async def add_documents(self, _documents) -> None:
        pass

    async def get_document(self, _doc_id: str, _index_name: str):
        return None

    async def delete_document(self, _doc_id: str, _index_name: str) -> bool:
        return False

    async def search(
        self, _query_embedding, _index_name=None, _limit=10, _min_score=0.0, _filters=None
    ):
        return []

    async def health_check(self):
        return {"healthy": True}

    async def list_documents(self, _index_name: str, _offset: int = 0, _limit: int = 20):
        return [], 0


class TestStorageBackend:
    """Test StorageBackend base class."""

    @pytest.mark.asyncio
    async def test_storage_backend_initialization(self) -> None:
        """Test storage backend initialization and cleanup."""
        backend = MockStorageBackend()

        assert not backend.initialized
        assert not backend.closed

        # Test initialization
        await backend.initialize()
        assert backend.initialized

        # Test closing
        await backend.close()
        assert backend.closed
