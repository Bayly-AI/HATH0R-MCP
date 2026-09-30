"""
FastAPI-based REST API for KnowledgeBase Engine.

Provides endpoints for:
- Health checks
- Document search
- Document CRUD operations
- Index management
"""

from knowledgebase.api.main import app

__all__ = ["app"]
