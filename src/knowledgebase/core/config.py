"""
Configuration management for KnowledgeBase Engine.

Provides settings loaded from environment variables and configuration files.
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional, cast

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingSettings(BaseSettings):
    """Settings for embedding providers."""

    model_config = SettingsConfigDict(
        extra="ignore",
        populate_by_name=True,
    )

    provider: Optional[Literal["openai", "ollama", "bedrock"]] = None
    model: str = "nomic-embed-text"
    dimensions: int = 768
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    # Accept common env names used by compose/k8s. Without these aliases the
    # Docker OLLAMA_HOST=http://host.docker.internal:11434 was ignored and the
    # provider kept defaulting to http://localhost:11434 inside the container
    # (connection refused → embeddings "Not initialized").
    ollama_endpoint: str = Field(
        default="http://localhost:11434",
        validation_alias=AliasChoices(
            "ollama_endpoint",
            "OLLAMA_HOST",
            "OLLAMA_BASE_URL",
            "KB_EMBEDDING__OLLAMA_ENDPOINT",
        ),
    )
    bedrock_region: Optional[str] = Field(default=None, alias="AWS_REGION")


class StorageSettings(BaseSettings):
    """Settings for storage backends."""

    # Allow population by both field name (opensearch_region) and alias
    # (AWS_REGION). This ensures that nested settings loaded via
    # KB_STORAGE__OPENSEARCH_REGION work correctly while still supporting
    # direct construction with AWS_REGION, as used in unit tests.
    model_config = SettingsConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    backend: Literal["local", "opensearch"] = "local"
    local_path: str = Field(
        default_factory=lambda: os.getenv("KB_STORAGE__LOCAL_PATH", "./data/indices")
    )
    opensearch_endpoint: Optional[str] = Field(default=None, alias="OPENSEARCH_ENDPOINT")
    opensearch_region: str = Field(default="us-east-1", alias="AWS_REGION")
    opensearch_use_sigv4: bool = True
    index_prefix: str = "1n-mcp-"


class SearchSettings(BaseSettings):
    """Settings for search behavior."""

    default_limit: int = 10
    max_limit: int = 100
    min_score: float = 0.5
    hybrid_alpha: float = 0.7  # Weight for vector vs BM25 (1.0 = pure vector)


class ChunkingSettings(BaseSettings):
    """Settings for document chunking."""

    default_size: int = 1500
    default_overlap: int = 200
    max_size: int = 2000
    strategy: Literal["smart", "character", "markdown", "sentence"] = "smart"
    # smart: Tries paragraphs, sentences, lines, then words (default)
    # character: Fixed character-based chunking
    # markdown: Split on markdown headers
    # sentence: Split on sentence boundaries


class SecuritySettings(BaseSettings):
    """Settings for security and access control."""

    cors_origins: str = "*"  # Comma-separated list or "*" for allow-all
    redact_secrets: bool = True  # Redact secrets in env-list by default

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse CORS origins as a list."""
        if self.cors_origins == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


class RunbookSettings(BaseSettings):
    """Settings for runbook storage and search."""

    runbooks_dir: str = "./knowledgebase/canonical/runbooks"
    logs_dir: str = "./data/runbook-logs"
    index_dir: Optional[str] = None  # local lexical index, optional
    search_mode: Literal["exact", "vector", "hybrid"] = "vector"


class Settings(BaseSettings):
    """
    Main application settings.

    Settings are loaded from environment variables with the KB_ prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="KB_",
        env_nested_delimiter="__",
        env_file=None if os.getenv("KB_TEST_MODE") == "1" else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Application metadata
    app_name: str = "1n-mcp"
    version: str = "0.1.0"
    env: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"

    # API settings
    api_host: str = "0.0.0.0"  # nosec B104 - configurable via environment for API server
    api_port: int = 8083

    # Configuration paths
    config_dir: Path = Path("cfg")
    data_dir: Path = Path("data")

    # AWS settings
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    aws_access_key_id: Optional[str] = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")

    # Environment detection for auto-resolution
    infraos_environment: str = Field(default="local", alias="INFRAOS_ENVIRONMENT")
    # Preferred Aegis alias (also accepts AEGIS_ENVIRONMENT / ENVIRONMENT).
    aegis_environment: str = Field(
        default="local",
        validation_alias=AliasChoices("AEGIS_ENVIRONMENT", "ENVIRONMENT", "aegis_environment"),
    )

    # Component settings
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    runbooks: RunbookSettings = Field(default_factory=RunbookSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)

    def load_config_file(self, filename: str) -> dict[str, Any]:
        """
        Load a JSON configuration file from the config directory.

        Args:
            filename: Name of the configuration file.

        Returns:
            Configuration dictionary.

        Raises:
            FileNotFoundError: If the configuration file does not exist.
            json.JSONDecodeError: If the file contains invalid JSON.
        """
        config_path = self.config_dir / filename
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        with open(config_path) as f:
            data = json.load(f)

        # The configuration files for this service are expected to contain
        # JSON objects at the top level. We defensively type-cast here so
        # callers always see a mapping with string keys.
        return cast(dict[str, Any], data)

    @model_validator(mode="after")
    def _align_environment_aliases(self) -> "Settings":
        """Keep Aegis and legacy environment fields coherent."""
        # Prefer explicit Aegis/ENVIRONMENT values when non-default; otherwise mirror INFRAOS.
        if self.aegis_environment in ("", "local") and self.infraos_environment not in ("", "local"):
            self.aegis_environment = self.infraos_environment
        elif self.infraos_environment in ("", "local") and self.aegis_environment not in ("", "local"):
            self.infraos_environment = self.aegis_environment
        return self

    @property
    def is_local(self) -> bool:
        """Check if running in local environment (for embedding provider auto-resolution)."""
        return self.infraos_environment == "local" or self.aegis_environment == "local"

    @property
    def is_cloud(self) -> bool:
        """Check if running in a cloud environment (dev/staging/testing/prod)."""
        return self.infraos_environment in ("development", "staging", "testing", "production")

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.env == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.env == "development"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings.

    Returns:
        Settings: Application settings instance.
    """
    return Settings()
