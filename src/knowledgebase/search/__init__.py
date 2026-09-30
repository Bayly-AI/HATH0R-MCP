"""
Search module for KnowledgeBase Engine.

Provides search functionality:
- Hybrid search (kNN + BM25)
- BM25 lexical index
- Hybrid fusion ranking
- Metadata filtering / archive policy
"""

from knowledgebase.search.bm25 import BM25Index
from knowledgebase.search.hybrid import HybridFusion
from knowledgebase.search.hybrid_service import HybridSearchService, resolve_search_mode

__all__ = [
    "BM25Index",
    "HybridFusion",
    "HybridSearchService",
    "resolve_search_mode",
]
