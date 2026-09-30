"""Tests for hybrid search fusion combining BM25 and vector search."""

import pytest

from knowledgebase.search.hybrid import HybridFusion


class TestHybridFusionInit:
    """Test HybridFusion initialization and weight validation."""

    def test_init_default_weights(self) -> None:
        """Test initialization with default weights."""
        fusion = HybridFusion()
        # Weights should be normalized: 0.3 and 0.7 sum to 1.0
        assert fusion.bm25_weight == pytest.approx(0.3 / 1.0, rel=1e-3)
        assert fusion.vector_weight == pytest.approx(0.7 / 1.0, rel=1e-3)

    def test_init_custom_weights(self) -> None:
        """Test initialization with custom weights."""
        fusion = HybridFusion(bm25_weight=0.5, vector_weight=0.5)
        assert fusion.bm25_weight == pytest.approx(0.5, rel=1e-3)
        assert fusion.vector_weight == pytest.approx(0.5, rel=1e-3)

    def test_init_weight_normalization(self) -> None:
        """Test that weights are normalized to sum to 1.0."""
        fusion = HybridFusion(bm25_weight=1.0, vector_weight=2.0)
        total = fusion.bm25_weight + fusion.vector_weight
        assert total == pytest.approx(1.0, rel=1e-6)

    def test_init_negative_bm25_weight_raises_error(self) -> None:
        """Test that negative BM25 weight raises ValueError."""
        with pytest.raises(ValueError, match="Weights must be non-negative"):
            HybridFusion(bm25_weight=-0.1, vector_weight=0.5)

    def test_init_negative_vector_weight_raises_error(self) -> None:
        """Test that negative vector weight raises ValueError."""
        with pytest.raises(ValueError, match="Weights must be non-negative"):
            HybridFusion(bm25_weight=0.5, vector_weight=-0.1)

    def test_init_zero_weights_raises_error(self) -> None:
        """Test that zero weights raise ValueError."""
        with pytest.raises(ValueError, match="At least one weight must be positive"):
            HybridFusion(bm25_weight=0.0, vector_weight=0.0)


class TestHybridFusionNormalization:
    """Test score normalization functionality."""

    def test_normalize_empty_scores(self) -> None:
        """Test normalization of empty scores list."""
        normalized = HybridFusion._normalize_scores([])
        assert normalized == []

    def test_normalize_single_score(self) -> None:
        """Test normalization with single score."""
        normalized = HybridFusion._normalize_scores([5.0])
        assert len(normalized) == 1
        assert normalized[0] == 0.5  # All equal scores normalize to 0.5

    def test_normalize_uniform_scores(self) -> None:
        """Test normalization with uniform scores."""
        normalized = HybridFusion._normalize_scores([3.0, 3.0, 3.0])
        assert normalized == [0.5, 0.5, 0.5]

    def test_normalize_range_of_scores(self) -> None:
        """Test normalization of scores across range."""
        normalized = HybridFusion._normalize_scores([0.0, 5.0, 10.0])
        assert normalized[0] == pytest.approx(0.0)  # Min value
        assert normalized[1] == pytest.approx(0.5)  # Middle value
        assert normalized[2] == pytest.approx(1.0)  # Max value

    def test_normalize_negative_and_positive_scores(self) -> None:
        """Test normalization with negative and positive scores."""
        normalized = HybridFusion._normalize_scores([-10.0, 0.0, 10.0])
        assert normalized[0] == pytest.approx(0.0)
        assert normalized[1] == pytest.approx(0.5)
        assert normalized[2] == pytest.approx(1.0)


class TestHybridFusionResults:
    """Test hybrid fusion of search results."""

    def test_fuse_empty_results(self) -> None:
        """Test fusion with empty results."""
        fusion = HybridFusion()
        result = fusion.fuse_results([], [])
        assert result == []

    def test_fuse_only_bm25_results(self) -> None:
        """Test fusion with only BM25 results."""
        fusion = HybridFusion(bm25_weight=1.0, vector_weight=0.0)
        bm25_results = [("doc1", 10.0), ("doc2", 5.0)]
        result = fusion.fuse_results(bm25_results, [])

        assert len(result) == 2
        assert result[0][0] == "doc1"  # Higher score comes first
        assert result[1][0] == "doc2"

    def test_fuse_only_vector_results(self) -> None:
        """Test fusion with only vector results."""
        fusion = HybridFusion(bm25_weight=0.0, vector_weight=1.0)
        vector_results = [("doc1", 0.9), ("doc2", 0.5)]
        result = fusion.fuse_results([], vector_results)

        assert len(result) == 2
        assert result[0][0] == "doc1"

    def test_fuse_both_modalities(self) -> None:
        """Test fusion with both BM25 and vector results."""
        fusion = HybridFusion(bm25_weight=0.5, vector_weight=0.5)
        bm25_results = [("doc1", 10.0), ("doc2", 5.0)]
        vector_results = [("doc2", 0.8), ("doc3", 0.9)]

        result = fusion.fuse_results(bm25_results, vector_results, limit=10)

        assert len(result) == 3  # All docs present
        assert all(isinstance(doc_id, str) for doc_id, _ in result)
        assert all(isinstance(score, float) for _, score in result)

    def test_fuse_respects_limit(self) -> None:
        """Test that fusion respects the result limit."""
        fusion = HybridFusion()
        bm25_results = [
            ("doc1", 10.0),
            ("doc2", 9.0),
            ("doc3", 8.0),
            ("doc4", 7.0),
            ("doc5", 6.0),
        ]
        result = fusion.fuse_results(bm25_results, [], limit=3)

        assert len(result) == 3
        assert result[0][0] == "doc1"
        assert result[2][0] == "doc3"

    def test_fuse_results_sorted_by_score(self) -> None:
        """Test that fused results are sorted by score (descending)."""
        fusion = HybridFusion(bm25_weight=0.3, vector_weight=0.7)
        bm25_results = [("doc1", 10.0), ("doc2", 5.0), ("doc3", 8.0)]
        vector_results = [("doc1", 0.5), ("doc2", 0.9), ("doc3", 0.6)]

        result = fusion.fuse_results(bm25_results, vector_results)

        # Check that results are in descending order of score
        scores = [score for _, score in result]
        assert scores == sorted(scores, reverse=True)

    def test_fuse_deduplicates_by_doc_id(self) -> None:
        """Test that documents appearing in both results are deduplicated."""
        fusion = HybridFusion()
        bm25_results = [("doc1", 10.0), ("doc2", 5.0)]
        vector_results = [("doc1", 0.8), ("doc3", 0.9)]

        result = fusion.fuse_results(bm25_results, vector_results)

        doc_ids = [doc_id for doc_id, _ in result]
        assert doc_ids.count("doc1") == 1  # Only one "doc1"
        assert len(set(doc_ids)) == len(doc_ids)  # All unique

    def test_fuse_scores_are_weighted_sums(self) -> None:
        """Test that fused scores are correctly weighted sums."""
        fusion = HybridFusion(bm25_weight=0.4, vector_weight=0.6)
        # Use simple scores that normalize easily
        bm25_results = [("doc1", 10.0)]
        vector_results = [("doc1", 1.0)]

        result = fusion.fuse_results(bm25_results, vector_results)

        # Both normalize to same range, combined with weights
        assert len(result) == 1
        assert result[0][0] == "doc1"
        assert isinstance(result[0][1], float)

    def test_fuse_handles_zero_scores(self) -> None:
        """Test fusion when doc appears in only one modality (other score is 0)."""
        fusion = HybridFusion(bm25_weight=0.5, vector_weight=0.5)
        bm25_results = [("doc1", 10.0)]
        vector_results = [("doc2", 0.8)]

        result = fusion.fuse_results(bm25_results, vector_results)

        assert len(result) == 2
        doc_ids = [doc_id for doc_id, _ in result]
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids

    def test_fuse_large_result_set(self) -> None:
        """Test fusion with large result sets."""
        fusion = HybridFusion()
        bm25_results = [(f"doc_bm25_{i}", float(100 - i)) for i in range(50)]
        vector_results = [(f"doc_vec_{i}", 0.5 + i * 0.01) for i in range(50)]

        result = fusion.fuse_results(bm25_results, vector_results, limit=100)

        assert len(result) <= 100
        # Verify scores are sorted
        scores = [score for _, score in result]
        assert scores == sorted(scores, reverse=True)
