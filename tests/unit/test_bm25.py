#!/usr/bin/env python3
"""
Unit tests for BM25 search functionality.
"""

import pytest
from knowledgebase.search.bm25 import BM25Index
from knowledgebase.core.models import Document, DocumentMetadata


@pytest.fixture
def documents():
    """Sample documents for testing."""
    return [
        Document(
            id="doc1",
            content="The quick brown fox jumps over the lazy dog.",
            index_name="test",
            metadata=DocumentMetadata(title="Document 1"),
        ),
        Document(
            id="doc2",
            content="A fast brown fox runs across the field.",
            index_name="test",
            metadata=DocumentMetadata(title="Document 2"),
        ),
        Document(
            id="doc3",
            content="The lazy dog sleeps all day.",
            index_name="test",
            metadata=DocumentMetadata(title="Document 3"),
        ),
    ]


def test_bm25_indexer_creation(documents):
    """Test creating a BM25 index from documents."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    assert len(indexer.documents) == 3


def test_bm25_indexer_empty():
    """Test creating a BM25 index with no documents."""
    indexer = BM25Index()
    assert len(indexer.documents) == 0


def test_bm25_search_single_term(documents):
    """Test searching for a single term."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    results = indexer.search("fox")
    assert len(results) >= 1
    # Results are (doc_id, score) tuples
    if len(results) >= 2:
        assert results[0][1] >= results[1][1]


def test_bm25_search_multiple_terms(documents):
    """Test searching for multiple terms."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    results = indexer.search("brown fox")
    assert len(results) >= 1


def test_bm25_search_no_results(documents):
    """Test searching for terms that don't exist."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    results = indexer.search("elephant")
    assert len(results) == 0 or results[0].score == 0


def test_bm25_search_empty_query(documents):
    """Test searching with an empty query."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    results = indexer.search("")
    # Should handle empty query gracefully by returning no results
    assert len(results) == 0


def test_bm25_search_case_insensitive(documents):
    """Test that search is case insensitive."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    # Search with upper case should match lower case content
    results = indexer.search("FOX")
    assert len(results) >= 1


def test_bm25_scoring_consistency(documents):
    """Test that scoring is consistent across multiple searches."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    results1 = indexer.search("fox")
    results2 = indexer.search("fox")

    if len(results1) > 0 and len(results2) > 0:
        # Results are (doc_id, score) tuples
        assert results1[0][1] == results2[0][1]


def test_bm25_add_document():
    """Test adding a document to an existing index."""
    indexer = BM25Index()
    indexer.add_document("doc4", "A new document for testing.")
    assert len(indexer.documents) == 1


def test_bm25_remove_document(documents):
    """Test removing a document from the index."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    result = indexer.remove_document("doc1")
    assert result is True
    assert len(indexer.documents) == 2
    result = indexer.remove_document("doc_nonexistent")
    assert result is False


def test_bm25_search_whitespace_query(documents):
    """Test searching with whitespace-only query."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    results = indexer.search("   ")
    assert results == []


def test_bm25_search_with_limit(documents):
    """Test search respects limit parameter."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    results = indexer.search("the", limit=1)
    assert len(results) <= 1


def test_bm25_get_stats(documents):
    """Test getting statistics from the index."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    stats = indexer.get_stats()
    assert stats["document_count"] == 3
    assert stats["corpus_size"] == 3


def test_bm25_search_empty_index():
    """Test searching an empty index."""
    indexer = BM25Index()
    results = indexer.search("anything")
    assert results == []


def test_bm25_update_document(documents):
    """Test updating an existing document."""
    indexer = BM25Index()
    for doc in documents:
        indexer.add_document(doc.id, doc.content)
    indexer.add_document("doc1", "completely different content about elephants")
    assert len(indexer.documents) == 3
    results = indexer.search("elephants")
    assert any(doc_id == "doc1" for doc_id, _ in results)


def test_bm25_bulk_add_rebuilds_once(documents, monkeypatch):
    """Bulk load should rebuild index once while preserving search behavior."""
    indexer = BM25Index()
    rebuild_count = 0
    original_rebuild = indexer._rebuild_index

    def wrapped_rebuild():
        nonlocal rebuild_count
        rebuild_count += 1
        return original_rebuild()

    monkeypatch.setattr(indexer, "_rebuild_index", wrapped_rebuild)
    indexer.add_documents_bulk([(doc.id, doc.content) for doc in documents])

    assert rebuild_count == 1
    assert len(indexer.documents) == len(documents)
    assert indexer.search("fox")
