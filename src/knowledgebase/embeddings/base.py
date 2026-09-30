"""
Abstract base class for embedding providers.

Defines the interface that all embedding providers must implement.
"""

from __future__ import annotations


from abc import ABC, abstractmethod
from typing import Any


class EmbeddingProvider(ABC):
    """
    Abstract base class for embedding providers.

    All embedding providers must implement this interface to ensure
    consistent behavior across different backends (OpenAI, Ollama, etc.).
    """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """
        Get the name of the embedding model.

        Returns:
            str: Model identifier (e.g., 'text-embedding-3-small').
        """
        pass  # pragma: no cover

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """
        Get the dimensionality of embeddings produced by this provider.

        Returns:
            int: Number of dimensions in the embedding vector.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """
        Generate an embedding for a single text string.

        Args:
            text: The text to embed.

        Returns:
            list[float]: The embedding vector.

        Raises:
            EmbeddingError: If embedding generation fails.
        """
        pass  # pragma: no cover

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple text strings.

        Args:
            texts: List of texts to embed.

        Returns:
            list[list[float]]: List of embedding vectors.

        Raises:
            EmbeddingError: If embedding generation fails.
        """
        pass  # pragma: no cover

    async def embed_query(self, query: str) -> list[float]:
        """
        Generate an embedding for a search query.

        Some providers use different models or parameters for queries vs documents.
        Default implementation uses embed_text.

        Args:
            query: The search query text.

        Returns:
            list[float]: The query embedding vector.
        """
        return await self.embed_text(query)

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Check the health/availability of the embedding provider.

        Returns:
            dict: Health status information including:
                - healthy (bool): Whether the provider is available.
                - provider (str): Provider name.
                - model (str): Model name.
                - latency_ms (float): Response latency in milliseconds.
        """
        pass  # pragma: no cover


class EmbeddingError(Exception):
    """
    Exception raised when embedding generation fails.

    Attributes:
        message: Error description.
        provider: Name of the provider that failed.
        original_error: The underlying exception, if any.
    """

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        original_error: Exception | None = None,
    ) -> None:
        """
        Initialize the embedding error.

        Args:
            message: Error description.
            provider: Name of the provider that failed.
            original_error: The underlying exception, if any.
        """
        self.message = message
        self.provider = provider
        self.original_error = original_error
        super().__init__(self.message)

    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.provider:
            return f"[{self.provider}] {self.message}"
        return self.message
