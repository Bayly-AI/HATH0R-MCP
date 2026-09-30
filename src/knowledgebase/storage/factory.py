"""
Factory for creating storage backends.

Provides a unified interface for instantiating storage backends
based on configuration settings.
"""

from __future__ import annotations


from typing import Literal

import structlog

from knowledgebase.core.config import StorageSettings, get_settings
from knowledgebase.storage.base import StorageBackend
from knowledgebase.storage.local import LocalStorageBackend

logger = structlog.get_logger(__name__)


def get_storage_backend(
    backend: Literal["local", "opensearch"] | None = None,
    settings: StorageSettings | None = None,
) -> StorageBackend:
    """
    Get a storage backend instance based on configuration.

    Args:
        backend: Backend type override. If None, uses settings.
        settings: Storage settings. If None, uses default settings.

    Returns:
        StorageBackend: Configured storage backend instance.

    Raises:
        ValueError: If the backend type is not supported.
    """
    all_settings = get_settings()
    if settings is None:
        settings = all_settings.storage

    backend_type = backend or settings.backend

    logger.info("Creating storage backend", backend=backend_type)

    if backend_type == "local":
        return LocalStorageBackend(base_path=settings.local_path)
    elif backend_type == "opensearch":
        # Import here to avoid dependency issues if opensearch is not needed
        from knowledgebase.storage.opensearch import OpenSearchStorageBackend

        return OpenSearchStorageBackend(
            endpoint=settings.opensearch_endpoint or "",
            region=settings.opensearch_region,
            use_sigv4=settings.opensearch_use_sigv4,
            index_prefix=settings.index_prefix,
            # Must match the configured embedding provider's actual output
            # dimension (e.g. 768 for Ollama, 1024 for Bedrock titan-embed-
            # text-v2, 1536 for OpenAI) -- indices created with a mismatched
            # dimension will reject documents from that provider.
            vector_dimension=all_settings.embedding.dimensions,
        )
    else:
        raise ValueError(f"Unsupported storage backend: {backend_type}")
