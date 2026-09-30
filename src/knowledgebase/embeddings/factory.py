"""
Factory for creating embedding providers.

Provides a unified interface for instantiating embedding providers
based on configuration settings.
"""

from __future__ import annotations

import asyncio

import os
from typing import Literal

import structlog
from dotenv import dotenv_values

from knowledgebase.core.config import EmbeddingSettings, get_settings
from knowledgebase.embeddings.base import EmbeddingProvider
from knowledgebase.embeddings.bedrock import BedrockEmbeddingProvider
from knowledgebase.embeddings.ollama import OllamaEmbeddingProvider
from knowledgebase.embeddings.openai import OpenAIEmbeddingProvider

logger = structlog.get_logger(__name__)


def resolve_embedding_provider(
    settings: EmbeddingSettings | None = None,
) -> Literal["openai", "ollama", "bedrock"]:
    """
    Resolve the embedding provider with precedence order.

    Precedence (highest to lowest):
    1. Explicit settings.provider (if not None)
    2. INFRAOS_ENVIRONMENT mapping:
       - "local" → "ollama"
       - "development", "staging", "testing", "production" → "bedrock"
    3. Fallback to "ollama" for unknown environments

    Args:
        settings: Embedding settings. If None, uses default settings.

    Returns:
        Resolved provider type.
    """
    if settings is None:
        settings = get_settings().embedding

    # Highest precedence: explicit provider setting
    if settings.provider is not None:
        logger.info("Using explicit embedding provider", provider=settings.provider)
        return settings.provider

    # Medium precedence: auto-resolve based on INFRAOS_ENVIRONMENT
    app_settings = get_settings()
    infraos_env = app_settings.infraos_environment

    if infraos_env == "local":
        logger.info("Auto-resolving embedding provider", environment="local", provider="ollama")
        return "ollama"
    elif infraos_env in ("development", "staging", "testing", "production"):
        logger.info(
            "Auto-resolving embedding provider", environment=infraos_env, provider="bedrock"
        )
        return "bedrock"
    else:
        # Unknown environment, fallback to ollama with warning
        logger.warning(
            "Unknown INFRAOS_ENVIRONMENT, falling back to ollama",
            environment=infraos_env,
            provider="ollama",
        )
        return "ollama"


def get_embedding_provider(
    provider: Literal["openai", "ollama", "bedrock"] | None = None,
    settings: EmbeddingSettings | None = None,
) -> EmbeddingProvider:
    """
    Get an embedding provider instance based on configuration.

    Precedence for provider selection:
    1. Explicit function argument (highest)
    2. Auto-resolution via resolve_embedding_provider() (uses INFRAOS_ENVIRONMENT)
    3. Fallback to "ollama"

    Args:
        provider: Provider type override. If provided, takes highest precedence.
        settings: Embedding settings. If None, uses default settings.

    Returns:
        EmbeddingProvider: Configured embedding provider instance.

    Raises:
        ValueError: If the provider type is not supported.
    """
    if settings is None:
        settings = get_settings().embedding

    # Explicit function argument takes highest precedence
    # Use resolver for precedence: explicit setting > INFRAOS_ENVIRONMENT > fallback
    provider_type = provider if provider is not None else resolve_embedding_provider(settings)

    logger.info("Creating embedding provider", provider=provider_type)

    if provider_type == "bedrock":
        # Use Bedrock region from settings, fall back to AWS_REGION env var
        region = settings.bedrock_region or os.getenv("AWS_REGION")
        # Get AWS credentials from environment if available
        aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        return BedrockEmbeddingProvider(
            model=(
                settings.model
                if settings.model.startswith(("amazon.", "cohere."))
                else "amazon.titan-embed-text-v2:0"
            ),
            region=region,
            dimensions=settings.dimensions,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )
    elif provider_type == "openai":
        # Prefer explicit embedding settings value, but fall back to raw
        # OPENAI_API_KEY from the environment or .env so existing configs
        # continue to work even if the pydantic env prefix changes.
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if api_key is None:
            env_values = dotenv_values(".env")
            api_key = env_values.get("OPENAI_API_KEY")
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            model=(
                settings.model
                if settings.model.startswith("text-embedding")
                else "text-embedding-3-small"
            ),
            dimensions=settings.dimensions,
        )
    elif provider_type == "ollama":
        # For Ollama, rewrite model if it's an OpenAI or Bedrock default model
        # Also handle dimension conversion for Ollama's typical 768-dim model
        model = settings.model
        if model in ("text-embedding-3-small", "amazon.titan-embed-text-v2:0"):
            model = "nomic-embed-text"
        # Use settings dimensions if provided and reasonable, but ensure
        # that nomic-embed-text always uses its actual dimension (768)
        dimensions = settings.dimensions
        if model == "nomic-embed-text" or dimensions not in (768, 1024):
            dimensions = 768
        return OllamaEmbeddingProvider(
            model=model,
            endpoint=settings.ollama_endpoint,
            dimensions=dimensions,
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider_type}")


def _has_openai_credentials(settings: EmbeddingSettings) -> bool:
    """Return True when an OpenAI API key is available from settings or env."""
    if getattr(settings, "openai_api_key", None):
        return True
    if os.getenv("OPENAI_API_KEY"):
        return True
    try:
        env_values = dotenv_values(".env")
        return bool(env_values.get("OPENAI_API_KEY"))
    except Exception:
        return False


def _provider_candidate_order(
    settings: EmbeddingSettings,
    default_provider: Literal["openai", "ollama", "bedrock"],
) -> list[str]:
    """
    Build provider try-order.

    Policy (bulk archive / ops default):
    1. OpenAI first when credentials exist (fast path when funded)
    2. Configured/default provider (typically Ollama in-cluster)
    3. Remaining backends

    Health probes fail fast on OpenAI quota/auth so fallback is automatic.
    """
    order: list[str] = []
    # Always try OpenAI first when a key is present, even if default is ollama.
    if _has_openai_credentials(settings):
        order.append("openai")
    if default_provider not in order:
        order.append(default_provider)
    # Prefer ollama as the durable default fallback before bedrock.
    for name in ("ollama", "bedrock", "openai"):
        if name not in order:
            order.append(name)
    return order


async def _probe_provider(
    provider_name: str,
    settings: EmbeddingSettings,
    *,
    timeout_seconds: float = 8.0,
) -> tuple[EmbeddingProvider | None, str | None]:
    """Health-check a provider. Returns (instance, None) or (None, error)."""
    try:
        candidate = get_embedding_provider(provider=provider_name, settings=settings)  # type: ignore[arg-type]
        # OpenAI quota/auth failures should fail the probe quickly (no long retry).
        timeout = 6.0 if provider_name == "openai" else timeout_seconds
        health = await asyncio.wait_for(candidate.health_check(), timeout=timeout)
        if health.get("healthy"):
            return candidate, None
        return None, str(health.get("error") or "unhealthy")
    except Exception as e:
        # asyncio.TimeoutError often stringifies to empty; normalize it.
        err = str(e).strip() or type(e).__name__
        return None, err


async def get_embedding_provider_with_fallback(
    settings: EmbeddingSettings | None = None,
) -> EmbeddingProvider:
    """
    Get an embedding provider with automatic failover.

    Selection order:
    1. OpenAI — when credentials are present and a live health check passes
    2. Configured/default provider (``settings.provider`` or env mapping)
    3. Remaining backends (ollama, bedrock, openai)

    Explicit ``settings.provider`` still defines the *default* provider, but no
    longer blocks failover when that backend is unhealthy (e.g. OpenAI quota
    exhausted). This keeps MCP embeddings initialized whenever any healthy
    provider is reachable.

    Args:
        settings: Embedding settings. If None, uses default settings.

    Returns:
        EmbeddingProvider: A healthy embedding provider instance.

    Raises:
        RuntimeError: If no healthy provider is available.
    """
    if settings is None:
        settings = get_settings().embedding

    explicit = settings.provider is not None and str(settings.provider).strip() != ""
    default_provider = resolve_embedding_provider(settings)
    candidates = _provider_candidate_order(settings, default_provider)

    logger.info(
        "Resolving embedding provider with failover",
        default_provider=default_provider,
        explicit=explicit,
        candidates=candidates,
        openai_credentials_present=_has_openai_credentials(settings),
    )

    errors: list[str] = []
    for name in candidates:
        # OpenAI probes can retry internally; allow a bit more time than local ollama.
        timeout = 12.0 if name == "openai" else 8.0
        provider, error = await _probe_provider(name, settings, timeout_seconds=timeout)
        if provider is not None:
            if name == default_provider and name == candidates[0]:
                logger.info(
                    "Using embedding provider",
                    provider=name,
                    role="default",
                    explicit=explicit,
                )
            elif name == "openai" and name != default_provider:
                logger.info(
                    "Using OpenAI embedding provider (preferred when healthy)",
                    provider=name,
                    default_provider=default_provider,
                )
            elif name != default_provider:
                logger.warning(
                    "Falling back to secondary embedding provider",
                    provider=name,
                    default_provider=default_provider,
                    prior_errors=errors,
                )
            else:
                logger.info(
                    "Using embedding provider",
                    provider=name,
                    role="default_after_preferred_failed",
                    prior_errors=errors,
                )
            return provider
        errors.append(f"{name}: {error}")
        logger.warning(
            "Embedding provider unavailable",
            provider=name,
            error=error,
        )

    raise RuntimeError("No healthy embedding provider available; tried: " + "; ".join(errors))
