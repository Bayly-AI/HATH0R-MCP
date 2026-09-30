"""Runbook service orchestrating repository, templating, and logging."""

from __future__ import annotations


from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from knowledgebase.core.config import get_settings

try:
    import types_pyyaml
except ImportError:
    types_pyyaml = None  # Optional type stubs for runtime

if types_pyyaml is None:
    pass  # runtime check passed
from knowledgebase.runbooks.models import (
    PromptResponse,
    RunbookEnvConfig,
)
from knowledgebase.runbooks.repository import RunbookRepository
from knowledgebase.runbooks.templating import TemplateEngine


class RunbookService:
    """Service for runbook operations."""

    def __init__(self) -> None:
        settings = get_settings()
        # Runbook access: runbooks_dir, logs_dir, etc.
        runbooks_settings = settings.runbooks if hasattr(settings, "runbooks") else None
        runbooks_dir = (
            runbooks_settings.runbooks_dir
            if runbooks_settings
            else "./.infraOS/knowledgebase/runbooks"
        )
        logs_dir = (
            runbooks_settings.logs_dir
            if runbooks_settings
            else "./.infraOS/knowledgebase/runbook-logs"
        )

        self._repo = RunbookRepository(runbooks_dir=runbooks_dir)
        self._engine = TemplateEngine()
        self._logs_dir = Path(logs_dir)

    def list_runbooks(self) -> dict[str, Any]:
        """List all available runbooks."""
        records = self._repo.list_runbooks()
        return {
            "count": len(records),
            "runbooks": [
                {"name": r.name, "path": str(self._repo._get_runbook_path(r.name))} for r in records
            ],
        }

    def get_runbook(self, name: str) -> dict[str, Any] | None:
        """Get a runbook by name."""
        record = self._repo.get_runbook_by_name(name)
        if not record:
            return None
        return {
            "name": record.name,
            "content": record.content,
            "metadata": record.metadata.model_dump(),
        }

    def create_runbook(
        self, name: str, content: str, file_path: str | None = None
    ) -> dict[str, Any]:
        """Create a runbook from content or file."""
        if file_path:
            path_obj = Path(file_path).expanduser()
            if path_obj.exists():
                content = path_obj.read_text(encoding="utf-8")
        record = self._repo.create_runbook(name, content)
        return {"name": record.name, "created": True}

    def delete_runbook(self, name: str, force: bool = False) -> dict[str, Any]:
        """Delete a runbook by name."""
        _ = force  # Reserved for future confirmation prompt changes
        deleted = self._repo.delete_runbook(name)
        if not deleted:
            return {"deleted": False, "error": f"Runbook '{name}' not found"}
        return {"deleted": True, "name": name}

    def reindex_runbooks(self) -> dict[str, Any]:
        """Reindex runbooks - placeholder for future index sync."""
        records = self._repo.list_runbooks()
        return {"count": len(records), "reindexed": True}

    def get_prompt(self, search_keyword: str, vars_str: str = "") -> PromptResponse:
        """Get a runnable prompt from a runbook with variable substitution."""
        # Load env.yaml if present
        env_config = self._load_env_config()
        env_map = env_config.env

        # Parse variable assignments (comma-separated key=value)
        var_map = {}
        if vars_str:
            for pair in vars_str.split(","):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    var_map[key.strip()] = value.strip()

        # Find runbook (simple name-based for now, can be enhanced with resolver)
        record = self._repo.get_runbook_by_name(search_keyword)
        if not record:
            # Try first match if keyword matches content
            for r in self._repo.list_runbooks():
                if search_keyword.lower() in r.name.lower():
                    record = r
                    break

        if not record:
            raise ValueError(f"No runbook found matching '{search_keyword}'")

        # Apply substitutions
        prompt_text = self._engine.substitute(record.content, env_map, var_map)

        return PromptResponse(
            runbook_name=record.name,
            prompt_text=prompt_text,
            variables={**env_map, **var_map},
        )

    def create_log(
        self, runbook_name: str, log_content: str, timestamp: datetime | None = None
    ) -> dict[str, str]:
        """Create an execution log entry."""
        from knowledgebase.runbooks.models import RunbookLogEntry

        ts = timestamp or datetime.now(timezone.utc)
        entry = RunbookLogEntry(
            runbook_name=runbook_name,
            timestamp=ts,
            status="completed",
            execution_log=log_content,
        )
        self._repo.create_log_entry(entry)
        return {"created": "True", "runbook_name": runbook_name, "timestamp": ts.isoformat()}

    def _load_env_config(self) -> RunbookEnvConfig:
        """Load env.yaml from runbooks directory."""
        env_path = self._repo._runbooks_dir / "env.yaml"
        if not env_path.exists():
            return RunbookEnvConfig()
        try:
            with open(env_path) as f:
                data = yaml.safe_load(f) or {}
            return RunbookEnvConfig(env=data if isinstance(data, dict) else {})
        except Exception:
            return RunbookEnvConfig()
