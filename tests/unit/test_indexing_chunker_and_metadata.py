"""Unit tests for indexing chunker and metadata extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledgebase.indexing.chunker import Chunk, DocumentChunker
from knowledgebase.indexing.metadata import MetadataExtractor, extract_metadata


@pytest.mark.unit
class TestDocumentChunker:
    """Tests for the DocumentChunker and Chunk helpers."""

    def test_chunk_text_short_input_returns_single_chunk(self) -> None:
        """A short string should be returned as a single chunk without modification."""

        chunker = DocumentChunker(chunk_size=100, chunk_overlap=10, min_chunk_size=1)
        text = "short text"

        chunks = chunker.chunk_text(text)

        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.text == text
        assert chunk.index == 0
        assert chunk.start_char == 0
        assert chunk.end_char == len(text)

    def test_chunk_text_long_input_uses_overlap_and_respects_min_size(self) -> None:
        """Long input should be split into overlapping chunks at natural boundaries when possible."""

        paragraph = "This is a sentence. " * 50
        chunker = DocumentChunker(chunk_size=200, chunk_overlap=50, min_chunk_size=50)

        chunks = chunker.chunk_text(paragraph)

        # Should produce chunks that are at least the minimum size
        assert len(chunks) >= 1
        assert all(len(c.text) >= 50 for c in chunks)

        # If there is more than one chunk, later chunks should start before the previous end
        if len(chunks) > 1:
            for first, second in zip(chunks, chunks[1:]):
                assert second.start_char < first.end_char

    def test_chunk_document_yields_expected_metadata(self) -> None:
        """chunk_document should yield dictionaries with chunk metadata and indices."""

        text = "Line one. Line two. Line three. Line four."
        chunker = DocumentChunker(chunk_size=20, chunk_overlap=5, min_chunk_size=5)

        chunks = list(
            chunker.chunk_document(
                content=text,
                doc_id="doc-1",
                metadata={"source": "unit-test"},
            )
        )

        assert chunks, "Expected at least one chunk to be produced."

        total_chunks = len(chunks)
        for idx, payload in enumerate(chunks):
            assert payload["id"].startswith("doc-1-chunk-")
            assert payload["chunk_index"] == idx
            assert payload["total_chunks"] == total_chunks

            meta = payload["metadata"]
            assert meta["parent_doc_id"] == "doc-1"
            assert meta["chunk_index"] == idx
            assert meta["total_chunks"] == total_chunks
            assert meta["source"] == "unit-test"

    def test_chunk_hash_is_stable_for_same_text(self) -> None:
        """The Chunk.hash property should be deterministic for the same text."""

        c1 = Chunk(text="hello", index=0, start_char=0, end_char=5)
        c2 = Chunk(text="hello", index=1, start_char=10, end_char=15)

        assert c1.hash == c2.hash


@pytest.mark.unit
class TestMetadataExtractor:
    """Tests for MetadataExtractor and the extract_metadata helper."""

    def test_extract_from_file_populates_basic_fields(self, tmp_path: Path) -> None:
        """extract_from_file should return path, filename, extension, and filesystem metadata when possible."""

        file_path = tmp_path / "example.md"
        file_path.write_text("# Title\n\nBody")

        extractor = MetadataExtractor()
        meta = extractor.extract_from_file(file_path)

        assert meta["path"].endswith("example.md")
        assert meta["filename"] == "example.md"
        assert meta["extension"] == ".md"
        assert meta["source_type"] == "file"
        assert meta["size_bytes"] > 0
        assert "created_at" in meta
        assert "updated_at" in meta
        assert meta["language"] == "markdown"

    def test_extract_from_content_markdown_frontmatter_and_title(self) -> None:
        """Markdown content with YAML frontmatter should populate metadata fields and title."""

        content = (
            "---\nTitle: Test Doc\nauthor: Example\n---\n\n# Heading Title\n\nBody text here.\n"
        )

        extractor = MetadataExtractor()
        meta = extractor.extract_from_content(content, file_path="test.md")

        assert meta["title"] == "Test Doc"
        assert meta["author"] == "Example"
        assert meta["extension"] == ".md"
        assert meta["language"] == "markdown"

    def test_extract_from_content_code_metadata(self) -> None:
        """Code content should record functions, classes, and description from a docstring."""

        code = (
            '"""Module docstring. First line describes the module."""\n\n'
            "class MyClass:\n"
            "    def method(self):\n"
            "        pass\n\n\n"
            "def top_level(x, y):\n"
            "    return x + y\n"
        )

        extractor = MetadataExtractor()
        meta = extractor.extract_from_content(code, file_path="module.py")

        assert meta["description"] == "Module docstring. First line describes the module."
        assert "MyClass" in meta.get("classes", [])
        assert "top_level" in meta.get("functions", [])
        assert meta["language"] == "python"

    def test_extract_metadata_helper_uses_extractor(self) -> None:
        """extract_metadata convenience wrapper should return the same metadata as the class API."""

        content = "# Title from heading\n\nSome body text."
        meta_via_helper = extract_metadata(content, file_path="notes.md")

        extractor = MetadataExtractor()
        meta_direct = extractor.extract_from_content(content, "notes.md")

        assert meta_via_helper == meta_direct
