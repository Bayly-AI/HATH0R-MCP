"""
Pytest configuration and shared fixtures.

Configures the test environment to prevent real API calls
and ensures proper mocking of external dependencies.
"""

import os
import shutil
import tempfile
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True, scope="session")
def setup_test_environment():
    """Set up test environment variables to prevent real API calls."""
    # Set test environment variables
    test_env = {
        "KB_EMBEDDING_PROVIDER": "openai",
        "KB_EMBEDDING_MODEL": "text-embedding-3-small",
        "KB_STORAGE_BACKEND": "local",
        "KB_LOG_LEVEL": "INFO",
        # Explicitly unset OpenAI API key to ensure tests don't make real API calls
        "OPENAI_API_KEY": "",
        # Set fake AWS credentials for testing
        "AWS_ACCESS_KEY_ID": "test-access-key",
        "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        "AWS_DEFAULT_REGION": "us-east-1",
    }

    # Store original environment
    original_env = {}
    for key, value in test_env.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = value

    yield

    # Restore original environment
    for key, original_value in original_env.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


@pytest.fixture(autouse=True)
def reset_global_services():
    """Reset global service instances between tests."""
    # Reset embedding service singleton
    # Note: Commented out due to missing services module
    # import knowledgebase.services.embedding.service
    # knowledgebase.services.embedding.service._embedding_service = None

    yield


@pytest.fixture
def mock_openai_provider():
    """Create a mock OpenAI embedding provider."""
    provider = AsyncMock()
    provider.embed_text.return_value = [0.1, 0.2, 0.3, 0.4, 0.5]
    provider.embed_texts.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    provider.health_check.return_value = {"healthy": True, "provider": "openai"}
    provider.model = "text-embedding-3-small"
    provider.dimensions = 1536
    provider.model_name = "text-embedding-3-small"
    return provider


@pytest.fixture
def mock_ollama_provider():
    """Create a mock Ollama embedding provider."""
    provider = AsyncMock()
    provider.embed_text.return_value = [0.7, 0.8, 0.9]
    provider.embed_texts.return_value = [[0.7, 0.8, 0.9], [0.1, 0.2, 0.3]]
    provider.health_check.return_value = {"healthy": True, "provider": "ollama"}
    provider.model = "nomic-embed-text"
    provider.dimensions = 768
    provider.model_name = "nomic-embed-text"
    return provider


@pytest.fixture
def mock_embedding_factory(monkeypatch, mock_openai_provider, mock_ollama_provider):
    """Mock the embedding provider factory to return test providers."""

    def mock_get_provider(provider_type=None):
        if provider_type == "ollama":
            return mock_ollama_provider
        return mock_openai_provider

    # Mock both import paths that might be used
    monkeypatch.setattr("knowledgebase.embeddings.get_embedding_provider", mock_get_provider)
    monkeypatch.setattr(
        "knowledgebase.embeddings.factory.get_embedding_provider", mock_get_provider
    )

    return mock_get_provider


@pytest.fixture
def temp_storage_path():
    """Create a temporary directory for storage tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_document():
    """Create a sample document for testing."""
    from knowledgebase.core.models import Document, DocumentMetadata

    return Document(
        id="test-doc-1",
        content="This is a test document with some sample content for testing.",
        embedding=[0.1] * 1536,  # Fake embedding
        index_name="test-index",
        metadata=DocumentMetadata(
            title="Test Document",
            path="/test/doc.md",
            source_type="file",
            tags=["test", "sample"],
        ),
    )


@pytest.fixture
def sample_documents():
    """Create multiple sample documents for testing."""
    from knowledgebase.core.models import Document, DocumentMetadata

    documents = []
    for i in range(5):
        doc = Document(
            id=f"test-doc-{i}",
            content=f"Test document number {i} with unique content.",
            embedding=[0.1 + (i * 0.01)] * 1536,
            index_name="test-index",
            metadata=DocumentMetadata(
                title=f"Test Document {i}",
                tags=["test"],
            ),
        )
        documents.append(doc)
    return documents
