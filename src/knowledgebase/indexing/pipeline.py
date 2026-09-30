"""
Document indexing pipeline for KnowledgeBase Engine.

Orchestrates the full indexing process: read, chunk, embed, store.
"""

from __future__ import annotations


import hashlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import structlog

from knowledgebase.core.models import Document, DocumentMetadata
from knowledgebase.embeddings.base import EmbeddingProvider
from knowledgebase.indexing.chunker import DocumentChunker, create_chunker
from knowledgebase.indexing.metadata import MetadataExtractor
from knowledgebase.storage.base import StorageBackend

logger = structlog.get_logger(__name__)


class IndexingPipeline:
    """
    Pipeline for indexing documents into the knowledgebase.

    Handles the complete workflow:
    1. Read document content
    2. Extract metadata
    3. Chunk into smaller pieces
    4. Generate embeddings
    5. Store in backend

    Attributes:
        storage: Storage backend for persisting documents.
        embeddings: Embedding provider for generating vectors.
        chunker: Document chunker for splitting content.
        metadata_extractor: Metadata extractor for document analysis.
    """

    def __init__(
        self,
        storage: StorageBackend,
        embeddings: EmbeddingProvider,
        chunker: DocumentChunker | None = None,
    ) -> None:
        """
        Initialize the indexing pipeline.

        Args:
            storage: Storage backend instance.
            embeddings: Embedding provider instance.
            chunker: Optional custom chunker (creates default if not provided).
        """
        self.storage = storage
        self.embeddings = embeddings
        self.chunker = chunker or create_chunker()
        self.metadata_extractor = MetadataExtractor()

        logger.info("Initialized indexing pipeline")

    async def index_text(
        self,
        content: str,
        doc_id: str,
        index_name: str = "knowledgebase",
        metadata: dict[str, Any] | None = None,
        chunk: bool = True,
    ) -> list[Document]:
        """
        Index a text string.

        Args:
            content: Text content to index.
            doc_id: Unique document identifier.
            index_name: Target index name.
            metadata: Optional metadata dict.
            chunk: Whether to chunk the content.

        Returns:
            list[Document]: List of indexed documents (one per chunk).
        """
        documents: list[Document] = []

        # Extract metadata from content
        extracted_metadata: dict[str, Any] = self.metadata_extractor.extract_from_content(content)
        combined_metadata: dict[str, Any] = {**extracted_metadata, **(metadata or {})}

        if chunk and len(content) > self.chunker.chunk_size:
            # Process as chunks
            chunks = self.chunker.chunk_text(content)
            total_chunks = len(chunks)

            # Batch embed all chunks
            chunk_texts = [c.text for c in chunks]
            embeddings = await self.embeddings.embed_texts(chunk_texts)

            for i, (chunk_obj, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_id = f"{doc_id}-chunk-{i}"
                chunk_metadata: dict[str, Any] = {
                    **combined_metadata,
                    "extra": {
                        **combined_metadata.get("extra", {}),
                        "parent_doc_id": doc_id,
                        "start_char": chunk_obj.start_char,
                        "end_char": chunk_obj.end_char,
                    },
                }
                doc = Document(
                    id=chunk_id,
                    content=chunk_obj.text,
                    embedding=embedding,
                    index_name=index_name,
                    chunk_index=i,
                    total_chunks=total_chunks,
                    metadata=DocumentMetadata(**chunk_metadata),
                )
                await self.storage.add_document(doc)
                documents.append(doc)

            logger.info(
                "Indexed chunked document",
                doc_id=doc_id,
                num_chunks=total_chunks,
                index=index_name,
            )
        else:
            # Process as single document
            embedding = await self.embeddings.embed_text(content)
            doc = Document(
                id=doc_id,
                content=content,
                embedding=embedding,
                index_name=index_name,
                metadata=DocumentMetadata(**combined_metadata),
            )
            await self.storage.add_document(doc)
            documents.append(doc)

            logger.info("Indexed document", doc_id=doc_id, index=index_name)

        return documents

    async def index_file(
        self,
        file_path: str | Path,
        index_name: str = "knowledgebase",
        doc_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        chunk: bool = True,
    ) -> list[Document]:
        """
        Index a file from the filesystem.

        Args:
            file_path: Path to the file.
            index_name: Target index name.
            doc_id: Optional document ID (defaults to file path hash).
            metadata: Optional additional metadata.
            chunk: Whether to chunk the content.

        Returns:
            list[Document]: List of indexed documents.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Read content (be tolerant of minor encoding issues so a single
        # problematic file does not break the whole indexing pipeline)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_bytes().decode("utf-8", errors="ignore")

        # Generate doc_id from path if not provided
        if not doc_id:
            doc_id = self._generate_doc_id(str(path.absolute()))

        # Extract file metadata
        file_metadata: dict[str, Any] = self.metadata_extractor.extract_from_file(path)
        combined_metadata: dict[str, Any] = {**file_metadata, **(metadata or {})}

        return await self.index_text(
            content=content,
            doc_id=doc_id,
            index_name=index_name,
            metadata=combined_metadata,
            chunk=chunk,
        )

    async def index_directory(
        self,
        directory: str | Path,
        index_name: str = "knowledgebase",
        patterns: list[str] | None = None,
        recursive: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[tuple[Path, list[Document] | Exception]]:
        """
        Index all files in a directory.

        Args:
            directory: Path to the directory.
            index_name: Target index name.
            patterns: File patterns to match (e.g., ["*.md", "*.txt"]).
            recursive: Whether to recurse into subdirectories.
            metadata: Optional metadata to add to all documents.

        Yields:
            tuple[Path, list[Document] | Exception]: File path and indexed documents or exception.
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        patterns = patterns or ["*.md", "*.txt", "*.json"]

        for pattern in patterns:
            glob_func = dir_path.rglob if recursive else dir_path.glob
            for file_path in glob_func(pattern):
                if file_path.is_file():
                    try:
                        documents = await self.index_file(
                            file_path=file_path,
                            index_name=index_name,
                            metadata=metadata,
                        )
                        yield file_path, documents
                    except Exception as e:
                        logger.error(
                            "Failed to index file",
                            file=str(file_path),
                            error=str(e),
                        )
                        yield file_path, e

    async def reindex_document(
        self,
        doc_id: str,
        index_name: str,
        content: str | None = None,
    ) -> list[Document]:
        """
        Re-index an existing document.

        Deletes existing document/chunks and re-indexes with new content.

        Args:
            doc_id: Document ID to re-index.
            index_name: Index containing the document.
            content: New content (fetches existing if not provided).

        Returns:
            list[Document]: Newly indexed documents.
        """
        # Get existing document
        existing = await self.storage.get_document(doc_id, index_name)

        if content is None:
            if existing is None:
                raise ValueError(f"Document not found: {doc_id}")
            content = existing.content

        # Delete existing
        await self.storage.delete_document(doc_id, index_name)

        # Also delete any chunks
        for i in range(100):  # Reasonable max chunks
            chunk_id = f"{doc_id}-chunk-{i}"
            deleted = await self.storage.delete_document(chunk_id, index_name)
            if not deleted:
                break

        # Re-index
        metadata = existing.metadata.model_dump() if existing else {}
        return await self.index_text(
            content=content,
            doc_id=doc_id,
            index_name=index_name,
            metadata=metadata,
        )

    def _generate_doc_id(self, identifier: str) -> str:
        """
        Generate a document ID from an identifier string.

        Args:
            identifier: String to generate ID from (e.g., file path).

        Returns:
            str: Generated document ID.
        """
        hash_value = hashlib.md5(identifier.encode(), usedforsecurity=False).hexdigest()[:12]
        return f"doc-{hash_value}"


async def create_pipeline(
    storage: StorageBackend | None = None,
    embeddings: EmbeddingProvider | None = None,
) -> IndexingPipeline:
    """
    Create an indexing pipeline with default components.

    Args:
        storage: Optional storage backend (creates default if not provided).
        embeddings: Optional embedding provider (creates default if not provided).

    Returns:
        IndexingPipeline: Configured pipeline instance.
    """
    from knowledgebase.embeddings import get_embedding_provider
    from knowledgebase.storage import get_storage_backend

    if storage is None:
        storage = get_storage_backend()
        await storage.initialize()

    if embeddings is None:
        embeddings = get_embedding_provider()

    return IndexingPipeline(storage=storage, embeddings=embeddings)
