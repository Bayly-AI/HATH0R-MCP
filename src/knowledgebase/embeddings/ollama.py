"""
Ollama embedding provider implementation.

Provides embeddings using locally-hosted Ollama models.
"""

from __future__ import annotations


import os
import time
from typing import Any

import httpx
import structlog
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_exponential

from knowledgebase.embeddings.base import EmbeddingError, EmbeddingProvider

logger = structlog.get_logger(__name__)


# Bulk KB sync routinely needs >10s per embed when Ollama is cold or contended.
# Override via OLLAMA_EMBED_TIMEOUT_SECONDS (seconds).
def _ollama_http_timeout() -> float:
    try:
        return max(5.0, float(os.getenv("OLLAMA_EMBED_TIMEOUT_SECONDS", "60")))
    except (TypeError, ValueError):
        return 60.0


class OllamaEmbeddingProvider(EmbeddingProvider):
    """
    Embedding provider using Ollama's local embedding API.

    Supports models:
    - nomic-embed-text (768 dimensions)
    - mxbai-embed-large (1024 dimensions)
    - all-minilm (384 dimensions)

    Attributes:
        model: The Ollama model to use for embeddings.
        endpoint: The Ollama API endpoint URL.
    """

    # Common model dimensions (may vary by model version)
    MODEL_DIMENSIONS = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "all-minilm": 384,
        "all-minilm:latest": 384,
    }

    def __init__(
        self,
        model: str = "nomic-embed-text",
        endpoint: str = "http://localhost:11434",
        dimensions: int | None = None,
    ) -> None:
        """
        Initialize the Ollama embedding provider.

        Args:
            model: Model name to use for embeddings.
            endpoint: Ollama API endpoint URL.
            dimensions: Override dimensions for the model.
        """
        self._model = model
        self._endpoint = endpoint.rstrip("/")
        base = model.split(":")[0]
        self._dimensions = dimensions or self.MODEL_DIMENSIONS.get(model) or self.MODEL_DIMENSIONS.get(base, 768)

        logger.info(
            "Initialized Ollama embedding provider",
            model=self._model,
            endpoint=self._endpoint,
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
        stop=stop_after_attempt(4) | stop_after_delay(90),
        wait=wait_exponential(multiplier=1, min=1, max=8),
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
            async with httpx.AsyncClient(timeout=_ollama_http_timeout()) as client:
                response = await client.post(
                    f"{self._endpoint}/api/embeddings",
                    json={
                        "model": self._model,
                        "prompt": text,
                    },
                )
                response.raise_for_status()
                data = response.json()
                embedding_raw = data.get("embedding")
                if not isinstance(embedding_raw, list):
                    raise EmbeddingError(
                        message="Ollama response missing 'embedding' list",
                        provider="ollama",
                    )
                # Ollama returns a JSON array of numbers; perform a
                # best-effort conversion to floats.
                embedding: list[float] = [float(v) for v in embedding_raw]
                return embedding

        except httpx.HTTPStatusError as e:
            logger.error(
                "Ollama API error",
                status_code=e.response.status_code,
                model=self._model,
            )
            raise EmbeddingError(
                message=f"Ollama API error: {e.response.status_code}",
                provider="ollama",
                original_error=e,
            ) from e
        except Exception as e:
            logger.error("Failed to generate embedding", error=str(e), model=self._model)
            raise EmbeddingError(
                message=f"Failed to generate embedding: {e}",
                provider="ollama",
                original_error=e,
            ) from e

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple text strings.

        Ollama has no true batch API; fan out concurrent single-embed calls
        bounded by OLLAMA_EMBED_CONCURRENCY (default 8).

        Args:
            texts: List of texts to embed.

        Returns:
            list[list[float]]: List of embedding vectors.

        Raises:
            EmbeddingError: If embedding generation fails.
        """
        if not texts:
            return []

        import asyncio
        import os

        limit = max(1, int(os.getenv("OLLAMA_EMBED_CONCURRENCY", "8")))
        sem = asyncio.Semaphore(limit)

        async def _one(text: str) -> list[float]:
            async with sem:
                return await self.embed_text(text)

        return list(await asyncio.gather(*[_one(t) for t in texts]))

    async def health_check(self) -> dict[str, Any]:
        """
        Check the health/availability of the Ollama API.

        Returns:
            dict: Health status information.
        """
        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=_ollama_http_timeout()) as client:
                # Check if Ollama is running
                response = await client.get(f"{self._endpoint}/api/tags")
                response.raise_for_status()
                models = response.json().get("models", [])

                # Check if our model is available
                model_available = any(m.get("name", "").startswith(self._model) for m in models)

                latency_ms = (time.time() - start_time) * 1000

                return {
                    "healthy": model_available,
                    "provider": "ollama",
                    "model": self._model,
                    "model_available": model_available,
                    "dimensions": self._dimensions,
                    "latency_ms": round(latency_ms, 2),
                    "available_models": [m.get("name") for m in models[:10]],
                }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "healthy": False,
                "provider": "ollama",
                "model": self._model,
                "error": str(e),
                "latency_ms": round(latency_ms, 2),
            }
