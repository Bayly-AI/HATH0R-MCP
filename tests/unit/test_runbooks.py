"""Unit tests for runbook models, repository, templating, and service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from knowledgebase.core.config import RunbookSettings, Settings
from knowledgebase.runbooks import service as runbook_service_module
from knowledgebase.runbooks.models import (
    RunbookEnvConfig,
    RunbookLogEntry,
    RunbookMetadata,
    RunbookRecord,
    RunbookResolutionResult,
)
from knowledgebase.runbooks.repository import RunbookRepository
from knowledgebase.runbooks.templating import TemplateEngine


def _build_settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.runbooks = RunbookSettings(
        runbooks_dir=str(tmp_path / "runbooks"),
        logs_dir=str(tmp_path / "runbook-logs"),
    )
    return settings


def test_runbook_models_defaults_and_basic_construction() -> None:
    metadata = RunbookMetadata()
    assert metadata.safety_level == "safe"
    assert metadata.version == "1"
    assert metadata.variables_used == []

    record = RunbookRecord(name="deploy", content="run this")
    assert record.name == "deploy"
    assert record.metadata.tags == []

    env_cfg = RunbookEnvConfig()
    assert env_cfg.env == {}

    resolution = RunbookResolutionResult(type="not_found", hint="try another keyword")
    assert resolution.type == "not_found"
    assert resolution.record is None
    assert resolution.hint == "try another keyword"


def test_template_engine_substitution_paths() -> None:
    template = "Env={env[token]} User={var.user}"
    rendered = TemplateEngine.substitute(
        template=template,
        env_map={"token": "abc123"},
        var_map={"user": "ray"},
    )
    assert rendered == "Env=abc123 User=ray"

    assert TemplateEngine.substitute_env("unchanged", {}) == "unchanged"
    assert TemplateEngine.substitute_vars("unchanged", {}) == "unchanged"


def test_runbook_repository_crud_flow(tmp_path: Path) -> None:
    repo = RunbookRepository(runbooks_dir=str(tmp_path / "runbooks"))

    assert repo.list_runbooks() == []
    assert repo.get_runbook_by_name("missing") is None
    assert repo.runbook_exists("missing") is False
    assert repo.delete_runbook("missing") is False

    created = repo.create_runbook("deploy", "# Deploy")
    assert created.name == "deploy"
    assert repo.runbook_exists("deploy") is True

    fetched = repo.get_runbook_by_name("deploy")
    assert fetched is not None
    assert fetched.content == "# Deploy"

    listed = repo.list_runbooks()
    assert len(listed) == 1
    assert listed[0].name == "deploy"

    assert repo.delete_runbook("deploy") is True
    assert repo.runbook_exists("deploy") is False


def test_runbook_repository_create_log_entry_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    repo = RunbookRepository(runbooks_dir=str(tmp_path / "runbooks"))
    timestamp = datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc)
    entry = RunbookLogEntry(
        runbook_name="deploy",
        timestamp=timestamp,
        status="completed",
        execution_log="done",
    )

    created = repo.create_log_entry(entry)
    assert created == entry

    logs_year_dir = tmp_path / ".infraOS" / "knowledgebase" / "runbook-logs" / "2026"
    files = list(logs_year_dir.glob("deploy_2026-02-20_120000_*"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == "done"


def test_runbook_service_create_list_get_delete_and_file_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _build_settings(tmp_path)
    monkeypatch.setattr(runbook_service_module, "get_settings", lambda: settings)
    service = runbook_service_module.RunbookService()

    empty = service.list_runbooks()
    assert empty["count"] == 0

    created = service.create_runbook("deploy", "from-content")
    assert created["created"] is True

    source_file = tmp_path / "source.md"
    source_file.write_text("from-file", encoding="utf-8")
    created_from_file = service.create_runbook(
        "deploy-file", "ignored-content", file_path=str(source_file)
    )
    assert created_from_file["created"] is True

    listed = service.list_runbooks()
    assert listed["count"] == 2

    found = service.get_runbook("deploy")
    assert found is not None
    assert found["name"] == "deploy"
    assert found["content"] == "from-content"

    assert service.get_runbook("missing") is None

    deleted = service.delete_runbook("deploy")
    assert deleted["deleted"] is True

    missing_delete = service.delete_runbook("missing")
    assert missing_delete["deleted"] is False


@pytest.mark.asyncio
async def test_runbook_service_reindex_counts_existing_runbooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _build_settings(tmp_path)
    monkeypatch.setattr(runbook_service_module, "get_settings", lambda: settings)
    service = runbook_service_module.RunbookService()
    service.create_runbook("a", "A")
    service.create_runbook("b", "B")

    result = service.reindex_runbooks()
    assert result["reindexed"] is True
    assert result["count"] == 2


def test_runbook_service_prompt_resolution_env_and_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _build_settings(tmp_path)
    monkeypatch.setattr(runbook_service_module, "get_settings", lambda: settings)
    service = runbook_service_module.RunbookService()

    runbooks_dir = Path(settings.runbooks.runbooks_dir)
    runbooks_dir.mkdir(parents=True, exist_ok=True)
    (runbooks_dir / "env.yaml").write_text("token: abc123\nowner: team-x\n", encoding="utf-8")

    service.create_runbook("deploy-service", "Token={env[token]} User={var.user}")

    response = service.get_prompt("deploy", "user=ray")
    assert response.runbook_name == "deploy-service"
    assert response.prompt_text == "Token=abc123 User=ray"
    assert response.variables["token"] == "abc123"
    assert response.variables["user"] == "ray"


def test_runbook_service_prompt_not_found_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _build_settings(tmp_path)
    monkeypatch.setattr(runbook_service_module, "get_settings", lambda: settings)
    service = runbook_service_module.RunbookService()

    with pytest.raises(ValueError, match="No runbook found"):
        service.get_prompt("missing", "")


def test_runbook_service_load_env_config_with_invalid_yaml_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _build_settings(tmp_path)
    monkeypatch.setattr(runbook_service_module, "get_settings", lambda: settings)
    service = runbook_service_module.RunbookService()

    runbooks_dir = Path(settings.runbooks.runbooks_dir)
    runbooks_dir.mkdir(parents=True, exist_ok=True)
    (runbooks_dir / "env.yaml").write_text(":\n  - bad", encoding="utf-8")

    env_cfg = service._load_env_config()
    assert env_cfg.env == {}


def test_runbook_service_create_log_invokes_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _build_settings(tmp_path)
    monkeypatch.setattr(runbook_service_module, "get_settings", lambda: settings)
    service = runbook_service_module.RunbookService()

    captured: dict[str, RunbookLogEntry] = {}

    def fake_create_log_entry(entry: RunbookLogEntry) -> RunbookLogEntry:
        captured["entry"] = entry
        return entry

    monkeypatch.setattr(service._repo, "create_log_entry", fake_create_log_entry)

    timestamp = datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc)
    result = service.create_log("deploy", "completed", timestamp=timestamp)

    assert result["created"] == "True"
    assert result["runbook_name"] == "deploy"
    assert result["timestamp"] == timestamp.isoformat()
    assert captured["entry"].runbook_name == "deploy"
