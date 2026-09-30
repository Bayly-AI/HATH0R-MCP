"""
Hybrid search fusion combining BM25 (keyword) and vector (semantic) search.

Implements score normalization and fusion strategies for combining
multiple search modalities into a single ranked result set.
"""

from __future__ import annotations


import structlog

logger = structlog.get_logger(__name__)


class HybridFusion:
    """Fuse results from BM25 and vector search using weighted scoring.

    Normalizes scores from different search modalities (0-1 range) and
    combines them with configurable weights for final ranking.
    """

    def __init__(
        self,
        bm25_weight: float = 0.3,
        vector_weight: float = 0.7,
    ) -> None:
        """Initialize hybrid fusion with configurable weights.

        Args:
            bm25_weight: Weight for BM25 scores (0-1). Default 0.3 (favor semantic).
            vector_weight: Weight for vector scores (0-1). Default 0.7 (favor semantic).

        Raises:
            ValueError: If weights don't sum to valid range or are negative
        """
        if bm25_weight < 0 or vector_weight < 0:
            raise ValueError("Weights must be non-negative")

        total = bm25_weight + vector_weight
        if total == 0:
            raise ValueError("At least one weight must be positive")

        # Normalize weights to sum to 1.0
        self.bm25_weight = bm25_weight / total
        self.vector_weight = vector_weight / total

        logger.debug(
            "Hybrid fusion initialized",
            bm25_weight=round(self.bm25_weight, 3),
            vector_weight=round(self.vector_weight, 3),
        )

    def fuse_results(
        self,
        bm25_results: list[tuple[str, float]],
        vector_results: list[tuple[str, float]],
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        """Fuse BM25 and vector search results into single ranked list.

        Normalizes scores from both modalities to 0-1 range, applies weights,
        and merges results by document ID.

        Args:
            bm25_results: List of (doc_id, bm25_score) tuples
            vector_results: List of (doc_id, vector_score) tuples
            limit: Maximum results to return

        Returns:
            List of (doc_id, fused_score) tuples, ranked by fused score (highest first)
        """
        if not bm25_results and not vector_results:
            return []

        # Normalize BM25 scores to 0-1 range
        bm25_normalized = self._normalize_scores([score for _, score in bm25_results])
        bm25_map = {
            doc_id: norm_score for (doc_id, _), norm_score in zip(bm25_results, bm25_normalized)
        }

        # Normalize vector scores to 0-1 range
        vector_normalized = self._normalize_scores([score for _, score in vector_results])
        vector_map = {
            doc_id: norm_score for (doc_id, _), norm_score in zip(vector_results, vector_normalized)
        }

        # Collect all unique doc_ids
        all_doc_ids = set(bm25_map.keys()) | set(vector_map.keys())

        # Compute fused scores
        fused: list[tuple[str, float]] = []
        for doc_id in all_doc_ids:
            bm25_score = bm25_map.get(doc_id, 0.0)
            vector_score = vector_map.get(doc_id, 0.0)
            fused_score = self.bm25_weight * bm25_score + self.vector_weight * vector_score
            fused.append((doc_id, fused_score))

        # Sort by fused score (descending)
        fused.sort(key=lambda x: x[1], reverse=True)

        logger.debug(
            "Hybrid fusion completed",
            bm25_count=len(bm25_results),
            vector_count=len(vector_results),
            unique_docs=len(all_doc_ids),
            returned_count=min(len(fused), limit),
        )

        return fused[:limit]

    @staticmethod
    def _normalize_scores(scores: list[float]) -> list[float]:
        """Normalize scores to 0-1 range using min-max normalization.

        Args:
            scores: List of raw scores

        Returns:
            List of normalized scores (0-1)
        """
        if not scores:
            return []

        min_score = min(scores)
        max_score = max(scores)

        if min_score == max_score:
            # All scores are the same; return uniform normalization
            return [0.5] * len(scores)

        # Min-max normalization: (x - min) / (max - min)
        normalized = [(score - min_score) / (max_score - min_score) for score in scores]
        return normalized
