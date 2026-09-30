"""
BM25 search implementation for local keyword-based search.

Provides efficient, incremental BM25 index management for hybrid search modes.
"""

from __future__ import annotations


import structlog
from rank_bm25 import BM25Okapi

logger = structlog.get_logger(__name__)


class BM25Index:
    """Local BM25 index for keyword-based search with incremental updates.

    Maintains a searchable index of documents using BM25 scoring.
    Supports efficient incremental updates via add/remove operations.
    """

    def __init__(self) -> None:
        """Initialize empty BM25 index."""
        self.documents: dict[str, str] = {}  # doc_id -> content
        self.corpus: list[list[str]] = []  # tokenized documents for BM25
        self.bm25: BM25Okapi | None = None
        self.doc_ids: list[str] = []  # parallel list tracking doc_id per corpus entry

    def add_document(self, doc_id: str, content: str, *, rebuild: bool = True) -> None:
        """Add or update a document in the BM25 index.

        Incrementally rebuilds the BM25 index to reflect the new document.

        Args:
            doc_id: Unique document identifier
            content: Document text content
        """
        self.documents[doc_id] = content
        if rebuild:
            self._rebuild_index()
        logger.debug("Added document to BM25 index", doc_id=doc_id, content_length=len(content))

    def add_documents_bulk(self, documents: dict[str, str] | list[tuple[str, str]]) -> None:
        """Bulk-load documents and rebuild the BM25 index once."""
        items = documents.items() if isinstance(documents, dict) else documents
        for doc_id, content in items:
            self.add_document(doc_id, content, rebuild=False)
        self._rebuild_index()
        logger.debug("Bulk-loaded BM25 documents", count=len(self.documents))

    def remove_document(self, doc_id: str) -> bool:
        """Remove a document from the BM25 index.

        Returns True if document was removed, False if not found.

        Args:
            doc_id: Unique document identifier

        Returns:
            True if document was removed, False otherwise
        """
        if doc_id not in self.documents:
            return False

        del self.documents[doc_id]
        self._rebuild_index()
        logger.debug("Removed document from BM25 index", doc_id=doc_id)
        return True

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Search the BM25 index and return ranked results.

        Args:
            query: Search query text
            limit: Maximum number of results to return

        Returns:
            List of (doc_id, score) tuples, ranked by BM25 score (highest first)
        """
        if not self.bm25 or not query.strip():
            return []

        # Tokenize query (simple whitespace split)
        tokenized_query = query.lower().split()

        try:
            # Get scores for all documents
            scores = self.bm25.get_scores(tokenized_query)

            # Pair with doc_ids and sort by score (descending)
            results = [
                (doc_id, float(score))
                for doc_id, score in zip(self.doc_ids, scores)
                if score > 0  # Only include documents with positive scores
            ]
            results.sort(key=lambda x: x[1], reverse=True)

            logger.debug(
                "BM25 search completed",
                query=query,
                results_count=len(results),
                returned_count=min(len(results), limit),
            )
            return results[:limit]
        except Exception as e:
            logger.error("BM25 search failed", error=str(e), query=query)
            return []

    def _rebuild_index(self) -> None:
        """Rebuild the BM25 index from current documents.

        Called after document additions/removals to maintain index consistency.
        """
        self.corpus = []
        self.doc_ids = []

        for doc_id, content in self.documents.items():
            # Simple tokenization: lowercase and split on whitespace
            tokens = content.lower().split()
            self.corpus.append(tokens)
            self.doc_ids.append(doc_id)

        if self.corpus:
            self.bm25 = BM25Okapi(self.corpus)
            logger.debug(
                "BM25 index rebuilt",
                corpus_size=len(self.corpus),
                document_count=len(self.documents),
            )
        else:
            self.bm25 = None
            logger.debug("BM25 index emptied (no documents)")

    def get_stats(self) -> dict[str, int]:
        """Return statistics about the current BM25 index.

        Returns:
            Dictionary with document_count and corpus_size
        """
        return {
            "document_count": len(self.documents),
            "corpus_size": len(self.corpus),
        }
