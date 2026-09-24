"""
Sync pipelines for KnowledgeBase Engine.

Syncs the local canonical knowledgebase into this AegisCMCP instance's own
storage, or pushes it to another AegisCMCP instance over its own REST API.
"""

from knowledgebase.sync.service import (
    AegisCMCPSyncService,
    SyncFileError,
    SyncIndexResult,
    SyncReport,
    SyncTarget,
    load_sync_targets,
)

__all__ = [
    "AegisCMCPSyncService",
    "SyncFileError",
    "SyncIndexResult",
    "SyncReport",
    "SyncTarget",
    "load_sync_targets",
]
