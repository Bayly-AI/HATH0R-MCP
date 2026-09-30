"""
AWS Bedrock embedding provider implementation.

Provides embeddings using AWS Bedrock's embedding models.
"""

from __future__ import annotations

import asyncio

import json
import os
import time
from typing import Any

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, stop_after_delay, wait_exponential

from knowledgebase.embeddings.base import EmbeddingError, EmbeddingProvider

logger = structlog.get_logger(__name__)

DEFAULT_TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"


class BedrockEmbeddingProvider(EmbeddingProvider):
    """
    Embedding provider using AWS Bedrock's embedding API.

    Supports models:
    - amazon.titan-embed-text-v2:0 (1024 dimensions, configurable)
    - amazon.titan-embed-text-v1 (1536 dimensions)
    - cohere.embed-english-v3 (1024 dimensions)
    - cohere.embed-multilingual-v3 (1024 dimensions)

    Attributes:
        model: The Bedrock model ID to use for embeddings.
        client: Boto3 bedrock-runtime client instance.
    """

    # Model dimensions mapping
    MODEL_DIMENSIONS = {
        DEFAULT_TITAN_MODEL_ID: 1024,
        "amazon.titan-embed-text-v1": 1536,
        "cohere.embed-english-v3": 1024,
        "cohere.embed-multilingual-v3": 1024,
    }

    # Models that support configurable dimensions
    CONFIGURABLE_DIMENSION_MODELS = {DEFAULT_TITAN_MODEL_ID}

    def __init__(
        self,
        model: str = DEFAULT_TITAN_MODEL_ID,
        region: str | None = None,
        dimensions: int | None = None,
        invoke_timeout_seconds: float | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ) -> None:
        """
        Initialize the Bedrock embedding provider.

        Args:
            model: Bedrock model ID to use for embeddings.
            region: AWS region. If None, uses default boto3 configuration.
            dimensions: Override dimensions (only for Titan v2).
            aws_access_key_id: AWS access key ID. If None, uses default credentials.
            aws_secret_access_key: AWS secret access key. If None, uses default credentials.

        Raises:
            ValueError: If the model is not supported.
        """
        if model not in self.MODEL_DIMENSIONS:
            supported = ", ".join(self.MODEL_DIMENSIONS.keys())
            raise ValueError(f"Unsupported model: {model}. Supported: {supported}")

        self._model = model
        self._region = region
        self._invoke_timeout_seconds = self._resolve_invoke_timeout(invoke_timeout_seconds)

        # Handle dimensions
        if dimensions is not None:
            if model not in self.CONFIGURABLE_DIMENSION_MODELS:
                logger.warning(
                    "Model does not support configurable dimensions, using default",
                    model=model,
                    requested_dimensions=dimensions,
                    default_dimensions=self.MODEL_DIMENSIONS[model],
                )
                self._dimensions = self.MODEL_DIMENSIONS[model]
            else:
                self._dimensions = dimensions
        else:
            self._dimensions = self.MODEL_DIMENSIONS[model]

        # Configure boto3 client
        config = Config(
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=15,
        )

        client_kwargs: dict[str, Any] = {"config": config}
        if region:
            client_kwargs["region_name"] = region
        if aws_access_key_id and aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = aws_access_key_id
            client_kwargs["aws_secret_access_key"] = aws_secret_access_key

        self._client = boto3.client("bedrock-runtime", **client_kwargs)

        logger.info(
            "Initialized Bedrock embedding provider",
            model=self._model,
            region=region or "default",
            dimensions=self._dimensions,
            invoke_timeout_seconds=self._invoke_timeout_seconds,
        )

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self._model

    @property
    def dimensions(self) -> int:
        """Get the embedding dimensions."""
        return self._dimensions

    @staticmethod
    def _resolve_invoke_timeout(invoke_timeout_seconds: float | None) -> float:
        """Resolve invoke timeout with environment fallback and safe bounds."""
        if isinstance(invoke_timeout_seconds, (int, float)) and float(invoke_timeout_seconds) > 0:
            return float(invoke_timeout_seconds)

        try:
            env_timeout = float(os.getenv("KB_BEDROCK_INVOKE_TIMEOUT_SECONDS", "15"))
        except (TypeError, ValueError):
            env_timeout = 15.0

        if env_timeout <= 0:
            return 15.0
        return env_timeout

    def _build_request_body(self, text: str) -> dict[str, Any]:
        """
        Build the request body for the embedding API.

        Args:
            text: The text to embed.

        Returns:
            dict: Request body formatted for the specific model.
        """
        if self._model.startswith("amazon.titan"):
            body: dict[str, Any] = {"inputText": text}
            if self._model in self.CONFIGURABLE_DIMENSION_MODELS:
                body["dimensions"] = self._dimensions
                body["normalize"] = True
            return body
        elif self._model.startswith("cohere"):
            return {
                "texts": [text],
                "input_type": "search_document",
                "truncate": "END",
            }
        else:
            return {"inputText": text}

    def _build_batch_request_body(self, texts: list[str]) -> dict[str, Any]:
        """
        Build the request body for batch embedding (Cohere only).

        Args:
            texts: The texts to embed.

        Returns:
            dict: Request body formatted for the specific model.
        """
        if self._model.startswith("cohere"):
            return {
                "texts": texts,
                "input_type": "search_document",
                "truncate": "END",
            }
        # Titan doesn't support batch in the same call
        raise NotImplementedError("Batch embedding not supported for this model")

    def _parse_response(self, response_body: dict[str, Any]) -> list[float]:
        """
        Parse the embedding from the response body.

        Args:
            response_body: The response body from Bedrock.

        Returns:
            list[float]: The embedding vector.
        """
        if self._model.startswith("amazon.titan"):
            embedding = response_body.get("embedding")
            if not isinstance(embedding, list):
                raise EmbeddingError(
                    message="Bedrock Titan response missing 'embedding' list",
                    provider="bedrock",
                )
            return [float(v) for v in embedding]
        elif self._model.startswith("cohere"):
            embeddings = response_body.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) == 0:
                raise EmbeddingError(
                    message="Bedrock Cohere response missing 'embeddings' list",
                    provider="bedrock",
                )
            return [float(v) for v in embeddings[0]]
        else:
            embedding = response_body.get("embedding")
            if not isinstance(embedding, list):
                raise EmbeddingError(
                    message="Bedrock response missing 'embedding' list",
                    provider="bedrock",
                )
            return [float(v) for v in embedding]

    def _parse_batch_response(self, response_body: dict[str, Any]) -> list[list[float]]:
        """
        Parse batch embeddings from the response body (Cohere only).

        Args:
            response_body: The response body from Bedrock.

        Returns:
            list[list[float]]: List of embedding vectors.
        """
        if self._model.startswith("cohere"):
            embeddings = response_body.get("embeddings")
            if not isinstance(embeddings, list):
                raise EmbeddingError(
                    message="Bedrock Cohere response missing 'embeddings' list",
                    provider="bedrock",
                )
            return [[float(v) for v in emb] for emb in embeddings]
        raise NotImplementedError("Batch response parsing not supported for this model")

    async def _invoke_model_async(self, body: dict[str, Any]) -> dict[str, Any]:
        """Invoke Bedrock in a worker thread to avoid blocking the event loop."""
        request_body = json.dumps(body)

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.invoke_model,
                    modelId=self._model,
                    body=request_body,
                    contentType="application/json",
                    accept="application/json",
                ),
                timeout=self._invoke_timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError) as e:
            raise EmbeddingError(
                message=(
                    f"Bedrock invoke_model timed out after {self._invoke_timeout_seconds:.1f}s"
                ),
                provider="bedrock",
                original_error=e,
            ) from e

        response_body_stream = response.get("body")
        if response_body_stream is None:
            raise EmbeddingError(
                message="Bedrock response missing body stream",
                provider="bedrock",
            )

        try:
            return json.loads(response_body_stream.read())
        except Exception as e:
            raise EmbeddingError(
                message=f"Failed to parse Bedrock response: {e}",
                provider="bedrock",
                original_error=e,
            ) from e

    @retry(
        stop=stop_after_attempt(5) | stop_after_delay(20),
        wait=wait_exponential(multiplier=1, min=1, max=10),
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
            # Truncate text if too long (Bedrock has token limits)
            text = text[:8000] if len(text) > 8000 else text

            body = self._build_request_body(text)
            response_body = await self._invoke_model_async(body)
            return self._parse_response(response_body)
        except EmbeddingError:
            raise

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                "Bedrock API error",
                error_code=error_code,
                error_message=error_message,
                model=self._model,
            )
            raise EmbeddingError(
                message=f"Bedrock API error ({error_code}): {error_message}",
                provider="bedrock",
                original_error=e,
            ) from e
        except Exception as e:
            logger.error("Failed to generate embedding", error=str(e), model=self._model)
            raise EmbeddingError(
                message=f"Failed to generate embedding: {e}",
                provider="bedrock",
                original_error=e,
            ) from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
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

            # Cohere supports batch embedding
            if self._model.startswith("cohere"):
                batch_size = 96  # Cohere max batch size
                all_embeddings: list[list[float]] = []

                for i in range(0, len(truncated_texts), batch_size):
                    batch = truncated_texts[i : i + batch_size]
                    body = self._build_batch_request_body(batch)
                    response_body = await self._invoke_model_async(body)
                    all_embeddings.extend(self._parse_batch_response(response_body))

                return all_embeddings
            else:
                # Titan doesn't support batch - process sequentially
                embeddings: list[list[float]] = []
                for text in truncated_texts:
                    embedding = await self.embed_text(text)
                    embeddings.append(embedding)
                return embeddings

        except EmbeddingError:
            raise
        except Exception as e:
            logger.error(
                "Failed to generate embeddings",
                error=str(e),
                model=self._model,
                count=len(texts),
            )
            raise EmbeddingError(
                message=f"Failed to generate embeddings: {e}",
                provider="bedrock",
                original_error=e,
            ) from e

    async def embed_query(self, query: str) -> list[float]:
        """
        Generate an embedding for a search query.

        For Cohere models, uses 'search_query' input type instead of 'search_document'.

        Args:
            query: The search query text.

        Returns:
            list[float]: The query embedding vector.
        """
        if self._model.startswith("cohere"):
            try:
                query = query[:8000] if len(query) > 8000 else query
                body = {
                    "texts": [query],
                    "input_type": "search_query",
                    "truncate": "END",
                }
                response_body = await self._invoke_model_async(body)
                return self._parse_response(response_body)
            except EmbeddingError:
                raise
            except Exception as e:
                logger.error("Failed to generate query embedding", error=str(e))
                raise EmbeddingError(
                    message=f"Failed to generate query embedding: {e}",
                    provider="bedrock",
                    original_error=e,
                ) from e
        else:
            embedding: list[float] = await self.embed_text(query)
            return embedding

    async def health_check(self) -> dict[str, Any]:
        """
        Check the health/availability of the Bedrock API.

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
                "provider": "bedrock",
                "model": self._model,
                "dimensions": self._dimensions,
                "region": self._region or "default",
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "healthy": False,
                "provider": "bedrock",
                "model": self._model,
                "region": self._region or "default",
                "error": str(e),
                "latency_ms": round(latency_ms, 2),
            }
