"""
Document chunking for KnowledgeBase Engine.

Splits large documents into smaller chunks for embedding and search.
"""

from __future__ import annotations


import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class Chunk:
    """
    A chunk of text from a document.

    Attributes:
        text: The chunk text content.
        index: Zero-based index of this chunk within the document.
        start_char: Starting character position in the original document.
        end_char: Ending character position in the original document.
        metadata: Additional metadata for the chunk.
    """

    text: str
    index: int
    start_char: int
    end_char: int
    metadata: dict[str, Any] | None = None

    @property
    def hash(self) -> str:
        """Generate a hash of the chunk content."""
        return hashlib.md5(self.text.encode(), usedforsecurity=False).hexdigest()[:12]


class DocumentChunker:
    """
    Splits documents into overlapping chunks for embedding.

    Uses a sliding window approach with configurable chunk size and overlap.
    Attempts to split at natural boundaries (paragraphs, sentences) when possible.

    Attributes:
        chunk_size: Target size for each chunk in characters.
        chunk_overlap: Number of characters to overlap between chunks.
        min_chunk_size: Minimum chunk size (chunks smaller than this are merged).
    """

    # Patterns for finding natural split points
    PARAGRAPH_PATTERN = re.compile(r"\n\s*\n")
    SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
    LINE_PATTERN = re.compile(r"\n")

    def __init__(
        self,
        chunk_size: int = 1500,
        chunk_overlap: int = 200,
        min_chunk_size: int = 100,
        strategy: str = "smart",
    ) -> None:
        """
        Initialize the document chunker.

        Args:
            chunk_size: Target size for each chunk in characters.
            chunk_overlap: Number of characters to overlap between chunks.
            min_chunk_size: Minimum chunk size to create.
            strategy: Chunking strategy (smart, character, markdown, sentence).

        Raises:
            ValueError: If chunk_overlap >= chunk_size.
        """
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self.strategy = strategy

        logger.debug(
            "Initialized chunker",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strategy=strategy,
        )

    def chunk_text(self, text: str) -> list[Chunk]:
        """
        Split text into overlapping chunks using configured strategy.

        Args:
            text: The text to chunk.

        Returns:
            list[Chunk]: List of text chunks with metadata.
        """
        if self.strategy == "character":
            return self._chunk_character(text)
        elif self.strategy == "markdown":
            return self._chunk_markdown(text)
        elif self.strategy == "sentence":
            return self._chunk_sentence(text)
        else:  # smart (default)
            return self._chunk_smart(text)

    def _chunk_smart(self, text: str) -> list[Chunk]:
        """
        Smart chunking: tries natural break points (paragraphs, sentences, lines, words).
        """
        if not text or len(text) <= self.chunk_size:
            return [Chunk(text=text, index=0, start_char=0, end_char=len(text))]

        chunks: list[Chunk] = []
        start = 0
        index = 0

        while start < len(text):
            # Calculate end position
            end = min(start + self.chunk_size, len(text))

            # If not at the end, try to find a natural break point
            if end < len(text):
                end = self._find_break_point(text, start, end)

            # Extract chunk text
            chunk_text = text[start:end].strip()

            # Only add non-empty chunks that meet minimum size
            if chunk_text and len(chunk_text) >= self.min_chunk_size:
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        index=index,
                        start_char=start,
                        end_char=end,
                    )
                )
                index += 1

            # Move start position with overlap
            if end >= len(text):
                break
            start = end - self.chunk_overlap

            # Prevent infinite loop
            if start >= end:
                start = end

        logger.debug(
            "Chunked text (smart)",
            input_length=len(text),
            num_chunks=len(chunks),
        )
        return chunks

    def _chunk_character(self, text: str) -> list[Chunk]:
        """
        Character-based chunking: fixed size chunks with overlap.
        """
        if not text or len(text) <= self.chunk_size:
            return [Chunk(text=text, index=0, start_char=0, end_char=len(text))]

        chunks: list[Chunk] = []
        start = 0
        index = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end].strip()
            if chunk_text and len(chunk_text) >= self.min_chunk_size:
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        index=index,
                        start_char=start,
                        end_char=end,
                    )
                )
                index += 1
            if end >= len(text):
                break
            start = end - self.chunk_overlap
            if start >= end:
                start = end

        logger.debug(
            "Chunked text (character)",
            input_length=len(text),
            num_chunks=len(chunks),
        )
        return chunks

    def _chunk_markdown(self, text: str) -> list[Chunk]:
        """
        Markdown-aware chunking: splits on markdown headers.
        """
        header_pattern = re.compile(r"^#{1,6}\s+", re.MULTILINE)
        chunks: list[Chunk] = []
        parts = header_pattern.split(text)

        # First part might not have a header, process normally
        current_chunk = ""
        index = 0

        for part in parts:
            if not part.strip():
                continue
            # Try to keep chunks under size by grouping headers
            if len(current_chunk) + len(part) < self.chunk_size:
                current_chunk += part
            else:
                if current_chunk.strip():
                    chunks.append(
                        Chunk(
                            text=current_chunk.strip(),
                            index=index,
                            start_char=0,
                            end_char=len(current_chunk),
                        )
                    )
                    index += 1
                current_chunk = part
        # Add final chunk
        if current_chunk.strip():
            chunks.append(
                Chunk(
                    text=current_chunk.strip(),
                    index=index,
                    start_char=0,
                    end_char=len(current_chunk),
                )
            )

        logger.debug(
            "Chunked text (markdown)",
            input_length=len(text),
            num_chunks=len(chunks),
        )
        return chunks if chunks else [Chunk(text=text, index=0, start_char=0, end_char=len(text))]

    def _chunk_sentence(self, text: str) -> list[Chunk]:
        """
        Sentence-based chunking: splits on sentence boundaries.
        """
        # Simple sentence splitter
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[Chunk] = []
        current_chunk = ""
        index = 0

        for sentence in sentences:
            if not sentence.strip():
                continue
            if len(current_chunk) + len(sentence) < self.chunk_size:
                current_chunk += " " + sentence if current_chunk else sentence
            else:
                if current_chunk.strip():
                    chunks.append(
                        Chunk(
                            text=current_chunk.strip(),
                            index=index,
                            start_char=0,
                            end_char=len(current_chunk),
                        )
                    )
                    index += 1
                current_chunk = sentence
        # Add final chunk
        if current_chunk.strip():
            chunks.append(
                Chunk(
                    text=current_chunk.strip(),
                    index=index,
                    start_char=0,
                    end_char=len(current_chunk),
                )
            )

        logger.debug(
            "Chunked text (sentence)",
            input_length=len(text),
            num_chunks=len(chunks),
        )
        return chunks if chunks else [Chunk(text=text, index=0, start_char=0, end_char=len(text))]

    def _find_break_point(self, text: str, start: int, end: int) -> int:
        """
        Find a natural break point near the end position.

        Tries to break at paragraphs, then sentences, then lines, then words.

        Args:
            text: The full text.
            start: Start position of the current chunk.
            end: Proposed end position.

        Returns:
            int: Adjusted end position at a natural break point.
        """
        search_start = max(start + self.min_chunk_size, end - self.chunk_overlap)
        search_text = text[search_start:end]

        # Try to find a paragraph break
        matches = list(self.PARAGRAPH_PATTERN.finditer(search_text))
        if matches:
            return search_start + matches[-1].end()

        # Try to find a sentence break
        matches = list(self.SENTENCE_PATTERN.finditer(search_text))
        if matches:
            return search_start + matches[-1].end()

        # Try to find a line break
        matches = list(self.LINE_PATTERN.finditer(search_text))
        if matches:
            return search_start + matches[-1].end()

        # Try to find a word break (space)
        last_space = search_text.rfind(" ")
        if last_space > 0:
            return search_start + last_space + 1

        # No good break point found, use original end
        return end

    def chunk_document(
        self,
        content: str,
        doc_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Chunk a document and yield chunk dictionaries.

        Args:
            content: Document content to chunk.
            doc_id: Base document ID.
            metadata: Metadata to include with each chunk.

        Yields:
            dict: Chunk data including id, content, and metadata.
        """
        chunks = self.chunk_text(content)
        total_chunks = len(chunks)

        for chunk in chunks:
            chunk_id = f"{doc_id}-chunk-{chunk.index}"
            chunk_metadata: dict[str, Any] = {
                **(metadata or {}),
                "chunk_index": chunk.index,
                "total_chunks": total_chunks,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "parent_doc_id": doc_id,
            }

            yield {
                "id": chunk_id,
                "content": chunk.text,
                "metadata": chunk_metadata,
                "chunk_index": chunk.index,
                "total_chunks": total_chunks,
            }


def create_chunker(
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    strategy: str | None = None,
) -> DocumentChunker:
    """
    Create a document chunker with optional custom settings.

    Args:
        chunk_size: Target chunk size (default from settings).
        chunk_overlap: Overlap size (default from settings).
        strategy: Chunking strategy (default from settings).

    Returns:
        DocumentChunker: Configured chunker instance.
    """
    from knowledgebase.core.config import get_settings

    settings = get_settings()
    return DocumentChunker(
        chunk_size=chunk_size or settings.chunking.default_size,
        chunk_overlap=chunk_overlap or settings.chunking.default_overlap,
        strategy=strategy or settings.chunking.strategy,
    )
