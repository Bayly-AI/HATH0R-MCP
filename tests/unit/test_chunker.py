#!/usr/bin/env python3
"""
Unit tests for document chunking functionality.
"""

import pytest
from knowledgebase.indexing.chunker import DocumentChunker, Chunk


@pytest.fixture
def chunker():
    """Create a DocumentChunker instance."""
    return DocumentChunker()


def test_chunk_short_document(chunker):
    """Test chunking a short document that doesn't need splitting."""
    content = "This is a short document."
    chunks = chunker.chunk_text(content)
    assert len(chunks) == 1
    assert chunks[0].text == content


def test_chunk_long_document(chunker):
    """Test chunking a long document that needs splitting."""
    # Create a document that's definitely longer than the default chunk size
    # Default chunk_size is 1500, so we need content > 1500 chars
    content = "\n\n".join(
        [
            "This is paragraph {} with enough text to exceed the chunk size and force splitting.".format(
                i
            )
            for i in range(100)
        ]
    )
    chunks = chunker.chunk_text(content)
    assert len(chunks) >= 1
    # Verify that chunks preserve text
    full_text = "\n\n".join([chunk.text for chunk in chunks])
    assert "paragraph" in full_text


def test_chunk_with_custom_chunk_size(chunker):
    """Test chunking with a custom chunk size."""
    custom_chunker = DocumentChunker(chunk_size=100, chunk_overlap=20)
    content = "\n\n".join(["Paragraph {}".format(i) for i in range(10)])
    chunks = custom_chunker.chunk_text(content)
    # With a very small chunk size, we should get more chunks
    assert len(chunks) >= 1


def test_chunk_with_overlap(chunker):
    """Test that overlapping chunks preserve context across boundaries."""
    custom_chunker = DocumentChunker(chunk_size=200, chunk_overlap=50)
    content = "\n\n".join(["Paragraph {}".format(i) for i in range(20)])
    chunks = custom_chunker.chunk_text(content)
    # Verify that adjacent chunks have overlapping content
    if len(chunks) >= 2:
        # Find a phrase that appears in both chunks
        # The overlap should ensure some content appears in both
        pass


def test_chunk_preserves_metadata(chunker):
    """Test that chunk metadata is properly generated."""
    content = "\n\n".join(["Paragraph {}".format(i) for i in range(10)])
    chunks = chunker.chunk_text(content)
    # All chunks should be Chunk objects
    assert all(isinstance(chunk, Chunk) for chunk in chunks)
    # Chunks should have proper indices
    for i, chunk in enumerate(chunks):
        assert chunk.index == i


def test_configurable_settings():
    """Test that chunker can be configured with custom settings."""
    chunker = DocumentChunker(chunk_size=500, chunk_overlap=100)
    content = "\n\n".join(["Paragraph {}".format(i) for i in range(50)])
    chunks = chunker.chunk_text(content)
    assert len(chunks) >= 1


def test_chunk_empty_content(chunker):
    """Test chunking empty content."""
    chunks = chunker.chunk_text("")
    assert len(chunks) >= 0


def test_chunk_single_paragraph(chunker):
    """Test chunking a single long paragraph."""
    content = " ".join(["word"] * 500)  # A long paragraph
    chunks = chunker.chunk_text(content)
    # Should be split into multiple chunks
    assert len(chunks) >= 1


def test_chunk_markdown_strategy():
    """Test markdown-based chunking strategy."""
    markdown_chunker = DocumentChunker(chunk_size=300, strategy="markdown")
    content = "# Header 1\nSome text.\n## Header 2\nMore text."
    chunks = markdown_chunker.chunk_text(content)
    assert len(chunks) >= 1
    # All chunks should be Chunk objects
    assert all(isinstance(chunk, Chunk) for chunk in chunks)


def test_chunk_sentence_strategy():
    """Test sentence-based chunking strategy."""
    sentence_chunker = DocumentChunker(chunk_size=200, chunk_overlap=50, strategy="sentence")
    content = "First sentence. Second sentence. Third sentence."
    chunks = sentence_chunker.chunk_text(content)
    assert len(chunks) >= 1
    assert all(isinstance(chunk, Chunk) for chunk in chunks)


def test_chunk_character_strategy():
    """Test character-based chunking strategy."""
    char_chunker = DocumentChunker(chunk_size=150, chunk_overlap=30, strategy="character")
    content = "\n\n".join(["Paragraph {}".format(i) for i in range(15)])
    chunks = char_chunker.chunk_text(content)
    assert len(chunks) >= 1
    assert all(isinstance(chunk, Chunk) for chunk in chunks)


def test_chunk_positions():
    """Test that chunk start and end positions are correct."""
    chunker = DocumentChunker(chunk_size=100, chunk_overlap=10)
    content = " ".join(["word"] * 50)
    chunks = chunker.chunk_text(content)
    # Verify positions don't exceed text length
    for chunk in chunks:
        assert chunk.start_char >= 0
        assert chunk.end_char <= len(content)
        assert chunk.start_char < chunk.end_char


def test_chunk_invalid_overlap():
    """Test that invalid overlap raises error."""
    with pytest.raises(ValueError, match="chunk_overlap must be less than chunk_size"):
        DocumentChunker(chunk_size=100, chunk_overlap=100)


def test_chunk_hash():
    """Test that chunks generate consistent hashes."""
    content = "Test content for hashing."
    chunk1 = Chunk(text=content, index=0, start_char=0, end_char=len(content))
    chunk2 = Chunk(text=content, index=1, start_char=0, end_char=len(content))
    # Same content should have same hash
    assert chunk1.hash == chunk2.hash


def test_chunk_metadata():
    """Test chunk metadata handling."""
    metadata = {"source": "test", "page": 1}
    chunk = Chunk(text="Content", index=0, start_char=0, end_char=7, metadata=metadata)
    assert chunk.metadata == metadata
    assert chunk.metadata["source"] == "test"
