"""
Abstract base class for storage backends.

Defines the interface that all storage backends must implement.
"""

from __future__ import annotations


from abc import ABC, abstractmethod
from typing import Any

from knowledgebase.core.models import Document, IndexInfo, SearchResult


class StorageBackend(ABC):
    """
    Abstract base class for vector storage backends.

    All storage backends must implement this interface to ensure
    consistent behavior across different backends (local, OpenSearch, etc.).
    """

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize the storage backend.

        This may include creating directories, connecting to services,
        or setting up indices.

        Raises:
            StorageError: If initialization fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def close(self) -> None:
        """
        Close the storage backend and release resources.

        Raises:
            StorageError: If closing fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def create_index(self, name: str, metadata_schema: dict[str, str] | None = None) -> None:
        """
        Create a new index.

        Args:
            name: Index name.
            metadata_schema: Optional schema for metadata fields.

        Raises:
            StorageError: If index creation fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def delete_index(self, name: str) -> None:
        """
        Delete an index and all its documents.

        Args:
            name: Index name.

        Raises:
            StorageError: If index deletion fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def list_indices(self) -> list[IndexInfo]:
        """
        List all available indices.

        Returns:
            list[IndexInfo]: List of index information.

        Raises:
            StorageError: If listing fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def add_document(self, document: Document) -> None:
        """
        Add or update a document in the storage.

        Args:
            document: The document to add/update.

        Raises:
            StorageError: If adding fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def add_documents(self, documents: list[Document]) -> None:
        """
        Add or update multiple documents in bulk.

        Args:
            documents: List of documents to add/update.

        Raises:
            StorageError: If adding fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def get_document(self, doc_id: str, index_name: str) -> Document | None:
        """
        Retrieve a document by ID.

        Args:
            doc_id: Document identifier.
            index_name: Index to search in.

        Returns:
            Document if found, None otherwise.

        Raises:
            StorageError: If retrieval fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def delete_document(self, doc_id: str, index_name: str) -> bool:
        """
        Delete a document by ID.

        Args:
            doc_id: Document identifier.
            index_name: Index to delete from.

        Returns:
            True if document was deleted, False if not found.

        Raises:
            StorageError: If deletion fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        index_name: str | None = None,
        limit: int = 10,
        min_score: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Search for documents similar to the query embedding.

        Args:
            query_embedding: Query vector embedding.
            index_name: Index to search in (None for all indices).
            limit: Maximum number of results.
            min_score: Minimum similarity score threshold.
            filters: Metadata filters to apply.

        Returns:
            list[SearchResult]: Matching documents with scores.

        Raises:
            StorageError: If search fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Check the health/availability of the storage backend.

        Returns:
            dict: Health status information.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def list_documents(
        self,
        index_name: str,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Document], int]:
        """List documents for an index with simple pagination.

        Args:
            index_name: Name of the index.
            offset: Result offset for pagination.
            limit: Maximum number of documents to return.

        Returns:
            A tuple of (documents, total_count).
        """
        pass  # pragma: no cover


class StorageError(Exception):
    """
    Exception raised when storage operations fail.

    Attributes:
        message: Error description.
        backend: Name of the backend that failed.
        operation: The operation that failed.
        original_error: The underlying exception, if any.
    """

    def __init__(
        self,
        message: str,
        backend: str | None = None,
        operation: str | None = None,
        original_error: Exception | None = None,
    ) -> None:
        """
        Initialize the storage error.

        Args:
            message: Error description.
            backend: Name of the backend that failed.
            operation: The operation that failed.
            original_error: The underlying exception, if any.
        """
        self.message = message
        self.backend = backend
        self.operation = operation
        self.original_error = original_error
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return string representation of the error."""
        parts = []
        if self.backend:
            parts.append(f"[{self.backend}]")
        if self.operation:
            parts.append(f"({self.operation})")
        parts.append(self.message)
        return " ".join(parts)
