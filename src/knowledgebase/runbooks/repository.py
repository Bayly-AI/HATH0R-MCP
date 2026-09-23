"""Runbook repository for file-backed CRUD operations.

Provides create, read, update, delete, and enumeration of runbook files.
"""

from __future__ import annotations


import logging
from pathlib import Path

from knowledgebase.runbooks.models import (
    RunbookLogEntry,
    RunbookRecord,
)

logger = logging.getLogger(__name__)


class RunbookRepository:
    """File-backed repository for runbooks."""

    def __init__(self, runbooks_dir: str = "./.infraOS/knowledgebase/runbooks"):
        self._runbooks_dir = Path(runbooks_dir).resolve()
        self._ensure_dir_exists()

    def _ensure_dir_exists(self) -> None:
        if not self._runbooks_dir.exists():
            self._runbooks_dir.mkdir(parents=True, exist_ok=True)

    def _get_runbook_path(self, name: str) -> Path:
        """Get the path to a runbook file with path traversal protection."""
        # Sanitize name: extract only the base filename to prevent directory traversal
        safe_name = Path(name).name
        if not safe_name or safe_name in (".", ".."):
            raise ValueError(f"Invalid runbook name: {name!r}")
        # Construct path and ensure it stays within the runbooks directory
        result = (self._runbooks_dir / f"{safe_name}.md").resolve()
        if not str(result).startswith(str(self._runbooks_dir)):
            raise ValueError(f"Path traversal detected: {name!r}")
        return result

    def list_runbooks(self) -> list[RunbookRecord]:
        """List all runbooks in the directory."""
        records: list[RunbookRecord] = []
        if not self._runbooks_dir.exists():
            return records

        for file_path in self._runbooks_dir.glob("*.md"):
            name = file_path.stem
            content = file_path.read_text(encoding="utf-8")
            # Basic metadata inference from file name; can be enriched later
            records.append(RunbookRecord(name=name, content=content))
        return records

    def get_runbook_by_name(self, name: str) -> RunbookRecord | None:
        """Get a runbook by exact name."""
        file_path = self._get_runbook_path(name)
        if not file_path.exists():
            return None
        content = file_path.read_text(encoding="utf-8")
        return RunbookRecord(name=name, content=content)

    def create_runbook(self, name: str, content: str) -> RunbookRecord:
        """Create a new runbook. Overwrites if exists (idempotent)."""
        self._ensure_dir_exists()
        # _get_runbook_path sanitizes name and validates the path stays in the runbooks directory
        file_path = self._get_runbook_path(name)  # NOSONAR path is validated
        file_path.write_text(content, encoding="utf-8")  # NOSONAR path is validated above
        return RunbookRecord(name=name, content=content)

    def delete_runbook(self, name: str) -> bool:
        """Delete a runbook by name. Returns True if deleted, False if not found."""
        file_path = self._get_runbook_path(name)
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def runbook_exists(self, name: str) -> bool:
        """Check whether a runbook exists by name."""
        return self._get_runbook_path(name).exists()

    def create_log_entry(self, entry: RunbookLogEntry) -> RunbookLogEntry:
        """Create a new log entry (append-only, naming managed by caller)."""
        prefix = "".join(
            [
                entry.runbook_name,
                "_",
                entry.timestamp.strftime("%Y-%m-%d_%H%M%S"),
                "_.log",
            ]
        )
        log_file = Path(entry.timestamp.strftime("%Y")) / f"{prefix[:-4]}"
        log_parent_dir = Path("./.infraOS/knowledgebase/runbook-logs")
        log_parent_dir.mkdir(parents=True, exist_ok=True)

        log_entry_path = f"./.infraOS/knowledgebase/runbook-logs/{log_file}"
        full_path = Path(log_entry_path).resolve()
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(entry.execution_log or "")
        return entry
