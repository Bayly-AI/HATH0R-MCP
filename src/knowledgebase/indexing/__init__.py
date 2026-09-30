"""
Document indexing module for KnowledgeBase Engine.

Provides document processing:
- Chunking (splitting large documents)
- Metadata extraction
- Indexing pipeline
"""

from knowledgebase.indexing.chunker import Chunk, DocumentChunker, create_chunker
from knowledgebase.indexing.metadata import MetadataExtractor, extract_metadata
from knowledgebase.indexing.pipeline import IndexingPipeline, create_pipeline

__all__ = [
    "Chunk",
    "DocumentChunker",
    "create_chunker",
    "MetadataExtractor",
    "extract_metadata",
    "IndexingPipeline",
    "create_pipeline",
]
