"""
OpenAI embedding provider implementation.

Provides embeddings using OpenAI's text-embedding models.
"""

from __future__ import annotations


import os
import time
from typing import Any

import structlog
from openai import (
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
)

from knowledgebase.embeddings.base import EmbeddingError, EmbeddingProvider

logger = structlog.get_logger(__name__)

# Permanent / billing failures should not burn the tenacity budget — factory
# failover (OpenAI → Ollama/default) needs a fast unhealthy signal.
_NON_RETRYABLE_MARKERS = (
    "insufficient_quota",
    "credit_balance_exhausted",
    "you have no credits remaining",
    "billing",
    "token_invalidated",
    "invalid_api_key",
    "incorrect api key",
    "invalid_request_error",
)


def _is_non_retryable_openai_error(exc: BaseException) -> bool:
    """Return True for auth/quota/permission errors that retries cannot fix."""
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return True
    if isinstance(exc, RateLimitError):
        text = str(exc).lower()
        # Transient rate limits are retryable; quota exhaustion is not.
        return any(marker in text for marker in _NON_RETRYABLE_MARKERS)
    if isinstance(exc, APIStatusError):
        status = getattr(exc, "status_code", None)
        if status in {401, 402, 403}:
            return True
        if status == 429:
            text = str(exc).lower()
            return any(marker in text for marker in _NON_RETRYABLE_MARKERS)
    text = str(exc).lower()
    return any(marker in text for marker in _NON_RETRYABLE_MARKERS)


def _should_retry_openai_exception(exc: BaseException) -> bool:
    """Tenacity predicate: retry only transient failures."""
    # Unwrap EmbeddingError so health/embed paths share one policy.
    original = getattr(exc, "original_error", None)
    candidate = original if isinstance(original, BaseException) else exc
    if _is_non_retryable_openai_error(candidate) or _is_non_retryable_openai_error(exc):
        return False
    return True


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Embedding provider using OpenAI's embedding API.

    Supports models:
    - text-embedding-3-small (1536 dimensions, recommended)
    - text-embedding-3-large (3072 dimensions)
    - text-embedding-ada-002 (1536 dimensions, legacy)

    Attributes:
        model: The OpenAI model to use for embeddings.
        client: AsyncOpenAI client instance.
    """

    # Model dimensions mapping
    MODEL_DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        dimensions: int | None = None,
    ) -> None:
        """
        Initialize the OpenAI embedding provider.

        Args:
            api_key: OpenAI API key. If None, uses OPENAI_API_KEY env var.
            model: Model name to use for embeddings.
            dimensions: Override dimensions (only for text-embedding-3-* models).

        Raises:
            ValueError: If the model is not supported.
        """
        if model not in self.MODEL_DIMENSIONS:
            supported = ", ".join(self.MODEL_DIMENSIONS.keys())
            raise ValueError(f"Unsupported model: {model}. Supported: {supported}")

        self._model = model
        self._dimensions = dimensions or self.MODEL_DIMENSIONS[model]
        # Allow override for slower networks; default 30s (was 10s) so healthy
        # OpenAI calls are not false-failed into Ollama failover under load.
        timeout_seconds = float(os.getenv("OPENAI_EMBED_TIMEOUT_SECONDS", "30") or "30")
        self._client = (
            AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
            if api_key
            else AsyncOpenAI(timeout=timeout_seconds)
        )

        logger.info(
            "Initialized OpenAI embedding provider",
            model=self._model,
            dimensions=self._dimensions,
        )

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self._model

    @property
    def dimensions(self) -> int:
        """Get the embedding dimensions."""
        return self._dimensions

    @retry(
        retry=retry_if_exception(_should_retry_openai_exception),
        stop=stop_after_attempt(5) | stop_after_delay(20),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
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
        try:
            # Truncate text if too long (OpenAI has token limits)
            text = text[:8000] if len(text) > 8000 else text

            # Only pass an explicit dimensions argument for the
            # text-embedding-3-* family where it is supported.
            kwargs: dict[str, Any] = {"input": text, "model": self._model}
            if "text-embedding-3" in self._model:
                kwargs["dimensions"] = self._dimensions

            response = await self._client.embeddings.create(**kwargs)
            embedding: list[float] = response.data[0].embedding
            return embedding

        except Exception as e:
            # Do not retry permanent quota/auth failures — surface quickly so
            # get_embedding_provider_with_fallback can switch to default/Ollama.
            if _is_non_retryable_openai_error(e):
                logger.warning(
                    "OpenAI embedding non-retryable failure",
                    error=str(e),
                    model=self._model,
                )
            else:
                logger.error("Failed to generate embedding", error=str(e), model=self._model)
            raise EmbeddingError(
                message=f"Failed to generate embedding: {e}",
                provider="openai",
                original_error=e,
            ) from e

    @retry(
        retry=retry_if_exception(_should_retry_openai_exception),
        stop=stop_after_attempt(5) | stop_after_delay(20),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
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
        if not texts:
            return []

        try:
            # Truncate texts if too long
            truncated_texts = [t[:8000] if len(t) > 8000 else t for t in texts]

            # OpenAI allows batching up to 2048 inputs
            batch_size = 2048
            all_embeddings: list[list[float]] = []

            for i in range(0, len(truncated_texts), batch_size):
                batch = truncated_texts[i : i + batch_size]

                kwargs: dict[str, Any] = {"input": batch, "model": self._model}
                if "text-embedding-3" in self._model:
                    kwargs["dimensions"] = self._dimensions

                response = await self._client.embeddings.create(**kwargs)
                # Sort by index to maintain order
                sorted_data = sorted(response.data, key=lambda x: x.index)
                all_embeddings.extend([d.embedding for d in sorted_data])

            return all_embeddings

        except Exception as e:
            if _is_non_retryable_openai_error(e):
                logger.warning(
                    "OpenAI batch embedding non-retryable failure",
                    error=str(e),
                    model=self._model,
                    count=len(texts),
                )
            else:
                logger.error(
                    "Failed to generate embeddings",
                    error=str(e),
                    model=self._model,
                    count=len(texts),
                )
            raise EmbeddingError(
                message=f"Failed to generate embeddings: {e}",
                provider="openai",
                original_error=e,
            ) from e

    async def health_check(self) -> dict[str, Any]:
        """
        Check the health/availability of the OpenAI API.

        Returns:
            dict: Health status information.
        """
        start_time = time.time()
        try:
            # Generate a test embedding
            await self.embed_text("health check")
            latency_ms = (time.time() - start_time) * 1000

            return {
                "healthy": True,
                "provider": "openai",
                "model": self._model,
                "dimensions": self._dimensions,
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "healthy": False,
                "provider": "openai",
                "model": self._model,
                "error": str(e),
                "latency_ms": round(latency_ms, 2),
            }
