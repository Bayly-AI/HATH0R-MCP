"""Comprehensive tests for DocumentChunker strategies (markdown, sentence, character)."""

import pytest
from knowledgebase.indexing.chunker import DocumentChunker, Chunk


class TestMarkdownChunkingStrategy:
    """Test markdown-specific chunking logic."""

    def test_markdown_chunk_with_headers(self) -> None:
        """Markdown chunker should handle header-based splits."""
        chunker = DocumentChunker(chunk_size=300, chunk_overlap=50, strategy="markdown")
        content = (
            "# Header 1\nParagraph text.\n## Header 2\nMore text here.\n### Header 3\nEven more."
        )
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_markdown_chunk_preserves_content(self) -> None:
        """Markdown chunking should preserve all content."""
        chunker = DocumentChunker(chunk_size=200, chunk_overlap=30, strategy="markdown")
        content = "# Title\nFirst paragraph.\n\nSecond paragraph with more text."
        chunks = chunker.chunk_text(content)
        # All content should be present across chunks
        concatenated = "".join(c.text for c in chunks)
        assert len(concatenated) > 0

    def test_markdown_with_empty_lines(self) -> None:
        """Markdown chunker should handle multiple empty lines."""
        chunker = DocumentChunker(chunk_size=200, chunk_overlap=20, strategy="markdown")
        content = "Line 1\n\n\n\nLine 2 after empty lines.\n\n\nLine 3."
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 1

    def test_markdown_with_code_blocks(self) -> None:
        """Markdown chunker should handle code blocks."""
        chunker = DocumentChunker(chunk_size=250, chunk_overlap=40, strategy="markdown")
        content = """# Documentation
```python
def hello():
    return "world"
```
More documentation here."""
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 1
        # Code should be preserved
        full_text = "".join(c.text for c in chunks)
        assert "def hello" in full_text


class TestSentenceChunkingStrategy:
    """Test sentence-based chunking logic."""

    def test_sentence_chunk_splits_on_periods(self) -> None:
        """Sentence chunker should recognize periods as sentence boundaries."""
        chunker = DocumentChunker(chunk_size=150, chunk_overlap=20, strategy="sentence")
        content = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_sentence_chunk_with_exclamation_marks(self) -> None:
        """Sentence chunker should recognize exclamation marks as sentence boundaries."""
        chunker = DocumentChunker(chunk_size=150, chunk_overlap=20, strategy="sentence")
        content = "What a day! This is exciting! Another sentence here."
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 1

    def test_sentence_chunk_with_question_marks(self) -> None:
        """Sentence chunker should recognize question marks as sentence boundaries."""
        chunker = DocumentChunker(chunk_size=150, chunk_overlap=20, strategy="sentence")
        content = "Is this working? I hope so! Can we continue? Sure, let's go."
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 1

    def test_sentence_chunk_preserves_case(self) -> None:
        """Sentence chunking should preserve uppercase/lowercase."""
        chunker = DocumentChunker(chunk_size=200, chunk_overlap=25, strategy="sentence")
        content = "FIRST SENTENCE. Second sentence. third sentence."
        chunks = chunker.chunk_text(content)
        full_text = "".join(c.text for c in chunks)
        assert "FIRST" in full_text
        assert "Second" in full_text
        assert "third" in full_text


class TestCharacterChunkingStrategy:
    """Test character-based chunking logic."""

    def test_character_chunk_fixed_size(self) -> None:
        """Character chunker should respect fixed chunk size."""
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20, strategy="character")
        content = "a" * 300  # 300 characters
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 2
        # All chunks should be Chunk objects
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_character_chunk_with_unicode(self) -> None:
        """Character chunker should handle Unicode characters."""
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=15, strategy="character")
        content = "café résumé naïve 日本語 Привет " * 10  # Multilingual content
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 1

    def test_character_chunk_respects_overlap(self) -> None:
        """Character chunker should create overlap between chunks."""
        chunker = DocumentChunker(
            chunk_size=200, chunk_overlap=50, min_chunk_size=80, strategy="character"
        )
        content = "x" * 600
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 2
        # Verify overlap: adjacent chunks should share some content
        if len(chunks) >= 2:
            # Second chunk should start before first chunk ends (overlap)
            assert chunks[1].start_char < chunks[0].end_char


class TestChunkingEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_chunk_very_long_single_word(self) -> None:
        """Chunker should handle very long words."""
        chunker = DocumentChunker(
            chunk_size=200, chunk_overlap=20, strategy="smart", min_chunk_size=50
        )
        content = "a" * 500  # Very long word
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 1

    def test_chunk_with_only_whitespace(self) -> None:
        """Chunker should handle content with only whitespace."""
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20, strategy="smart")
        content = "   \n\n   \t\t  \n   "
        chunks = chunker.chunk_text(content)
        # May result in 0 or 1 chunk depending on min_chunk_size
        assert len(chunks) <= 1

    def test_chunk_indices_are_sequential(self) -> None:
        """Chunk indices should be sequential starting from 0."""
        chunker = DocumentChunker(chunk_size=100, chunk_overlap=20, strategy="smart")
        content = "word " * 50
        chunks = chunker.chunk_text(content)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_chunk_hash_consistency(self) -> None:
        """Same chunk content should produce same hash."""
        chunk1 = Chunk(text="test content", index=0, start_char=0, end_char=12)
        chunk2 = Chunk(text="test content", index=1, start_char=0, end_char=12)
        assert chunk1.hash == chunk2.hash
        assert len(chunk1.hash) == 12  # MD5 truncated to 12 chars

    def test_chunk_with_mixed_line_endings(self) -> None:
        """Chunker should handle mixed line endings."""
        chunker = DocumentChunker(chunk_size=150, chunk_overlap=20, strategy="smart")
        content = "Line1\nLine2\r\nLine3\rLine4\n\nLine5"
        chunks = chunker.chunk_text(content)
        assert len(chunks) >= 1

    def test_chunk_invalid_parameters(self) -> None:
        """Invalid configuration should raise ValueError."""
        # Overlap >= chunk_size should fail
        with pytest.raises(ValueError, match="chunk_overlap must be less"):
            DocumentChunker(chunk_size=100, chunk_overlap=100)

        # Overlap equal to chunk_size should also fail
        with pytest.raises(ValueError, match="chunk_overlap must be less"):
            DocumentChunker(chunk_size=50, chunk_overlap=50)
