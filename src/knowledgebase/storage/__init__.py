"""
Storage backends for KnowledgeBase Engine.

Provides interfaces to multiple storage backends:
- Local file-based storage (development)
- OpenSearch Serverless (production)
"""

from knowledgebase.storage.base import StorageBackend
from knowledgebase.storage.factory import get_storage_backend
from knowledgebase.storage.local import LocalStorageBackend

__all__ = [
    "StorageBackend",
    "LocalStorageBackend",
    "get_storage_backend",
]
