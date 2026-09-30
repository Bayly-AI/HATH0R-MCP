"""Unit tests for core configuration settings utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledgebase.core.config import Settings, StorageSettings


def test_load_config_file_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`load_config_file` should load JSON from the configured config directory."""

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "example.json"
    payload: dict[str, Any] = {"key": "value", "number": 1}
    cfg_path.write_text(json.dumps(payload), encoding="utf-8")

    settings = Settings(config_dir=cfg_dir)

    data = settings.load_config_file("example.json")

    assert data == payload


def test_load_config_file_missing_raises(tmp_path: Path) -> None:
    """`load_config_file` should raise FileNotFoundError when the file is absent."""

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()

    settings = Settings(config_dir=cfg_dir)

    with pytest.raises(FileNotFoundError):
        settings.load_config_file("missing.json")


def test_environment_flags_for_settings() -> None:
    """Settings helpers should correctly reflect the environment flags."""

    dev_settings = Settings(env="development")
    prod_settings = Settings(env="production")

    assert dev_settings.is_development is True
    assert dev_settings.is_production is False

    assert prod_settings.is_production is True
    assert prod_settings.is_development is False


@pytest.mark.unit
class TestInfraosEnvironmentSettings:
    """Tests for INFRAOS_ENVIRONMENT field and auto-resolution helpers."""

    def test_aegis_environment_defaults_to_local(self) -> None:
        """aegis_environment should default to 'local' when not specified."""

        settings = Settings()

        assert settings.aegis_environment == "local"
        assert settings.is_local is True
        assert settings.is_cloud is False

    def test_aegis_environment_can_be_set_explicitly(self) -> None:
        """aegis_environment can be set to any valid environment string."""

        settings_dev = Settings(INFRAOS_ENVIRONMENT="development")  # type: ignore[arg-type]
        settings_prod = Settings(INFRAOS_ENVIRONMENT="production")  # type: ignore[arg-type]
        settings_staging = Settings(INFRAOS_ENVIRONMENT="staging")  # type: ignore[arg-type]

        assert settings_dev.aegis_environment == "development"
        assert settings_prod.aegis_environment == "production"
        assert settings_staging.aegis_environment == "staging"

    def test_is_local_property(self) -> None:
        """is_local should return True only when aegis_environment is 'local'."""

        local_settings = Settings(INFRAOS_ENVIRONMENT="local")  # type: ignore[arg-type]
        cloud_settings = Settings(INFRAOS_ENVIRONMENT="development")  # type: ignore[arg-type]

        assert local_settings.is_local is True
        assert cloud_settings.is_local is False

    def test_is_cloud_property(self) -> None:
        """is_cloud should return True for development, staging, testing, and production."""

        local_settings = Settings(INFRAOS_ENVIRONMENT="local")  # type: ignore[arg-type]
        dev_settings = Settings(INFRAOS_ENVIRONMENT="development")  # type: ignore[arg-type]
        staging_settings = Settings(INFRAOS_ENVIRONMENT="staging")  # type: ignore[arg-type]
        testing_settings = Settings(INFRAOS_ENVIRONMENT="testing")  # type: ignore[arg-type]
        prod_settings = Settings(INFRAOS_ENVIRONMENT="production")  # type: ignore[arg-type]

        assert local_settings.is_cloud is False
        assert dev_settings.is_cloud is True
        assert staging_settings.is_cloud is True
        assert testing_settings.is_cloud is True
        assert prod_settings.is_cloud is True

    def test_aegis_environment_explicit_values(self) -> None:
        """aegis_environment can be set to various environment strings."""
        # Test direct construction to verify field behavior
        settings_staging = Settings(aegis_environment="staging")  # type: ignore[arg-type]
        settings_prod = Settings(aegis_environment="production")  # type: ignore[arg-type]
        settings_testing = Settings(aegis_environment="testing")  # type: ignore[arg-type]

        # Verify explicit values override defaults
        assert settings_staging.aegis_environment == "staging"
        assert settings_prod.aegis_environment == "production"
        assert settings_testing.aegis_environment == "testing"

    def test_embedding_provider_is_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EmbeddingSettings.provider should default to None for auto-resolution."""
        from knowledgebase.core.config import EmbeddingSettings, get_settings

        # Remove any env vars that could override the default
        monkeypatch.delenv("KB_EMBEDDING_PROVIDER", raising=False)
        monkeypatch.delenv("KB_EMBEDDING__PROVIDER", raising=False)

        get_settings.cache_clear()  # Clear the lru_cache

        # Test the EmbeddingSettings class directly to verify the default is None
        emb = EmbeddingSettings()
        assert emb.provider is None

    def test_embedding_provider_can_be_explicitly_set(self) -> None:
        """EmbeddingSettings.provider can be explicitly set to a specific provider."""
        # Note: pydantic nested delimiter is "__" so KB_EMBEDDING__PROVIDER sets provider
        from knowledgebase.core.config import EmbeddingSettings

        emb_openai = EmbeddingSettings(provider="openai")  # type: ignore[arg-type]
        emb_ollama = EmbeddingSettings(provider="ollama")  # type: ignore[arg-type]
        emb_bedrock = EmbeddingSettings(provider="bedrock")  # type: ignore[arg-type]

        assert emb_openai.provider == "openai"
        assert emb_ollama.provider == "ollama"
        assert emb_bedrock.provider == "bedrock"

    def test_storage_local_path_prefers_env_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """StorageSettings.local_path should default from KB_STORAGE__LOCAL_PATH when set."""
        override = tmp_path / "mounted-index"
        monkeypatch.setenv("KB_STORAGE__LOCAL_PATH", str(override))
        storage = StorageSettings()
        assert storage.local_path == str(override)
