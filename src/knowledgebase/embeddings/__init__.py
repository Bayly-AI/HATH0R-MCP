"""
Embedding generation module for KnowledgeBase Engine.

Provides interfaces to multiple embedding providers:
- Bedrock (amazon.titan-embed-text-v2, cohere.embed-english-v3)
- OpenAI (text-embedding-3-small, ada-002)
- Ollama (nomic-embed-text, local models)
"""

from knowledgebase.embeddings.base import EmbeddingProvider
from knowledgebase.embeddings.bedrock import BedrockEmbeddingProvider
from knowledgebase.embeddings.factory import (
    get_embedding_provider,
    get_embedding_provider_with_fallback,
)
from knowledgebase.embeddings.openai import OpenAIEmbeddingProvider

__all__ = [
    "BedrockEmbeddingProvider",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "get_embedding_provider",
    "get_embedding_provider_with_fallback",
]
