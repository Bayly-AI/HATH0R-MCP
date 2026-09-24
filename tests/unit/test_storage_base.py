"""Unit tests for the storage base abstractions.

These tests focus on :class:`StorageError` string formatting, ensuring that
backend and operation context is included when available.
"""

from __future__ import annotations

from knowledgebase.storage.base import StorageError


def test_storage_error_str_includes_backend_and_operation() -> None:
    """__str__ should include backend and operation prefixes when provided."""

    err = StorageError(
        message="failed to create index",
        backend="opensearch",
        operation="create_index",
    )

    text = str(err)
    assert "[opensearch]" in text
    assert "(create_index)" in text
    assert "failed to create index" in text


def test_storage_error_str_handles_minimal_information() -> None:
    """__str__ should fall back to just the message when no context is given."""

    err = StorageError("oops")

    assert str(err) == "oops"


def test_storage_error_init_attributes() -> None:
    """StorageError attributes should be accessible after initialization."""
    original = ValueError("root cause")
    err = StorageError(
        message="storage operation failed",
        backend="local",
        operation="add_document",
        original_error=original,
    )
    assert err.message == "storage operation failed"
    assert err.backend == "local"
    assert err.operation == "add_document"
    assert err.original_error is original


def test_storage_error_str_with_only_backend() -> None:
    """__str__ should include only the backend when operation is omitted."""
    err = StorageError(message="connection error", backend="opensearch")
    text = str(err)
    assert text.startswith("[opensearch]")
    assert "connection error" in text


def test_storage_error_str_with_only_operation() -> None:
    """__str__ should include only operation when backend is omitted."""
    err = StorageError(message="timeout", operation="search")
    text = str(err)
    assert text.startswith("(search)")
    assert "timeout" in text


def test_storage_error_is_exception() -> None:
    """StorageError should inherit from Exception."""
    err = StorageError("test")
    assert isinstance(err, Exception)


def test_storage_error_with_all_fields() -> None:
    """StorageError with all fields should format correctly."""
    orig = RuntimeError("original")
    err = StorageError(
        message="failed", backend="opensearch", operation="delete", original_error=orig
    )
    text = str(err)
    assert "[opensearch]" in text
    assert "(delete)" in text
    assert "failed" in text
    assert err.original_error is orig
