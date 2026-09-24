"""Unit tests for the embeddings base abstractions.

These tests validate the default behaviour implemented in
:mod:`knowledgebase.embeddings.base`, in particular the ``embed_query``
helper and the :class:`EmbeddingError` string representation.
"""

from __future__ import annotations

from typing import Any

import pytest

from knowledgebase.embeddings.base import EmbeddingError, EmbeddingProvider


class DummyEmbeddingProvider(EmbeddingProvider):
    """Concrete test implementation of :class:`EmbeddingProvider`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @property
    def model_name(self) -> str:  # pragma: no cover - trivial
        return "dummy-model"

    @property
    def dimensions(self) -> int:  # pragma: no cover - trivial
        return 3

    async def embed_text(self, text: str) -> list[float]:
        self.calls.append(("embed_text", text))
        # Return a tiny deterministic vector for assertions.
        return [float(len(text)), 1.0, 0.0]

    async def embed_texts(
        self, texts: list[str]
    ) -> list[list[float]]:  # pragma: no cover - unused here
        return [await self.embed_text(t) for t in texts]

    async def health_check(self) -> dict[str, Any]:  # pragma: no cover - not exercised here
        return {"healthy": True, "provider": "dummy", "model": self.model_name}


@pytest.mark.unit
class TestEmbeddingProviderBase:
    """Tests for shared behaviour of the EmbeddingProvider base class."""

    @pytest.mark.asyncio
    async def test_embed_query_delegates_to_embed_text(self) -> None:
        """The default ``embed_query`` implementation should call ``embed_text``."""

        provider = DummyEmbeddingProvider()

        result = await provider.embed_query("hello")

        # Ensure embed_text was called with the original query text.
        assert ("embed_text", "hello") in provider.calls
        # And the returned vector matches what embed_text produced.
        assert result == [5.0, 1.0, 0.0]


@pytest.mark.unit
class TestEmbeddingError:
    """Tests for the EmbeddingError exception formatting."""

    def test_str_includes_provider_when_present(self) -> None:
        """__str__ should prefix the message with the provider in brackets."""

        err = EmbeddingError("boom", provider="openai")

        assert str(err) == "[openai] boom"

    def test_str_omits_provider_when_not_set(self) -> None:
        """__str__ should return just the message when provider is None."""

        err = EmbeddingError("something went wrong")

        assert str(err) == "something went wrong"

    def test_stores_original_error(self) -> None:
        """EmbeddingError should preserve the original exception."""
        original = RuntimeError("root cause")
        err = EmbeddingError("wrapper", provider="test", original_error=original)

        assert err.original_error is original
        assert err.message == "wrapper"
        assert err.provider == "test"
