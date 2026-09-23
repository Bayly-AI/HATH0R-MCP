"""
Core module for KnowledgeBase Engine.

Contains configuration, models, and shared utilities.
"""

from knowledgebase.core.config import Settings, get_settings
from knowledgebase.core.models import Document, SearchResult

__all__ = [
    "Settings",
    "get_settings",
    "Document",
    "SearchResult",
]
