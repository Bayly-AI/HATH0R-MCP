"""
Unit tests for core data models.
"""

from knowledgebase.core.models import (
    Document,
    DocumentMetadata,
    IndexInfo,
    SearchQuery,
    SearchResult,
)


class TestDocumentMetadata:
    """Tests for DocumentMetadata model."""

    def test_default_values(self):
        """Test that default values are set correctly."""
        metadata = DocumentMetadata()
        assert metadata.path is None
        assert metadata.title is None
        assert metadata.tags == []
        assert metadata.extra == {}

    def test_with_values(self):
        """Test creating metadata with values."""
        metadata = DocumentMetadata(
            path="/test/path.md",
            title="Test Document",
            source_type="file",
            tags=["test", "example"],
        )
        assert metadata.path == "/test/path.md"
        assert metadata.title == "Test Document"
        assert metadata.source_type == "file"
        assert metadata.tags == ["test", "example"]


class TestDocument:
    """Tests for Document model."""

    def test_minimal_document(self):
        """Test creating a minimal document."""
        doc = Document(id="test-1", content="Test content")
        assert doc.id == "test-1"
        assert doc.content == "Test content"
        assert doc.embedding is None
        assert doc.index_name == "knowledgebase"
        assert doc.chunk_index == 0
        assert doc.total_chunks == 1

    def test_document_with_embedding(self):
        """Test document with embedding."""
        embedding = [0.1, 0.2, 0.3]
        doc = Document(id="test-2", content="Test", embedding=embedding)
        assert doc.embedding == embedding
        assert doc.has_embedding is True

    def test_document_without_embedding(self):
        """Test has_embedding property when no embedding."""
        doc = Document(id="test-3", content="Test")
        assert doc.has_embedding is False

    def test_document_with_metadata(self):
        """Test document with metadata."""
        metadata = DocumentMetadata(title="Test Title")
        doc = Document(id="test-4", content="Test", metadata=metadata)
        assert doc.metadata.title == "Test Title"


class TestSearchResult:
    """Tests for SearchResult model."""

    def test_search_result(self):
        """Test creating a search result."""
        doc = Document(id="test-1", content="Test content")
        result = SearchResult(document=doc, score=0.85)
        assert result.document.id == "test-1"
        assert result.score == 0.85
        assert result.vector_score is None
        assert result.highlights == []

    def test_search_result_with_scores(self):
        """Test search result with multiple scores."""
        doc = Document(id="test-2", content="Test")
        result = SearchResult(
            document=doc,
            score=0.9,
            vector_score=0.92,
            bm25_score=0.88,
        )
        assert result.score == 0.9
        assert result.vector_score == 0.92
        assert result.bm25_score == 0.88


class TestSearchQuery:
    """Tests for SearchQuery model."""

    def test_minimal_query(self):
        """Test creating a minimal search query."""
        query = SearchQuery(query="test search")
        assert query.query == "test search"
        assert query.index_name is None
        assert query.limit == 10
        assert query.min_score == 0.5
        assert query.filters == {}

    def test_query_with_options(self):
        """Test query with all options."""
        query = SearchQuery(
            query="test",
            index_name="code",
            limit=5,
            min_score=0.7,
            filters={"language": "python"},
            hybrid_alpha=0.8,
        )
        assert query.index_name == "code"
        assert query.limit == 5
        assert query.min_score == 0.7
        assert query.filters == {"language": "python"}
        assert query.hybrid_alpha == 0.8


class TestIndexInfo:
    """Tests for IndexInfo model."""

    def test_index_info(self):
        """Test creating index info."""
        info = IndexInfo(
            name="test-index",
            description="Test index",
            document_count=100,
        )
        assert info.name == "test-index"
        assert info.description == "Test index"
        assert info.document_count == 100
        assert info.sync_source is None
        assert info.last_sync is None
