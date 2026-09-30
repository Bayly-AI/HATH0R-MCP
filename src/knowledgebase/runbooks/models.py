"""Runbook domain models for AegisCMCP.

Defines data models for runbooks, prompts, execution logs, and search results.
"""

from __future__ import annotations


from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RunbookMetadata(BaseModel):
    """Metadata associated with a runbook."""

    playbook_type: str | None = None
    variables_used: list[str] = Field(default_factory=list)
    external_systems: list[str] = Field(default_factory=list)
    safety_level: str = "safe"  # safe, elevated, critical
    version: str = "1"  # runbook format version
    source_path: str | None = None
    updated_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)


class RunbookRecord(BaseModel):
    """A runbook record (source content and metadata)."""

    name: str
    content: str
    metadata: RunbookMetadata = Field(default_factory=RunbookMetadata)


class RunbookEnvConfig(BaseModel):
    """Environment variables defined for runbooks (env.yaml equivalent)."""

    env: dict[str, Any] = Field(default_factory=dict)


class PromptRequest(BaseModel):
    """Request to generate a runnable prompt from a runbook."""

    runbook_search_keyword: str
    vars_str: str  # comma-separated key=value pairs


class PromptResponse(BaseModel):
    """Runnable prompt generated from a runbook."""

    runbook_name: str
    prompt_text: str
    variables: dict[str, str]


class RunbookLogEntry(BaseModel):
    """Execution log entry for a runbook."""

    runbook_name: str
    timestamp: datetime
    status: str  # pending, running, completed, failed
    execution_log: str | None = None
    duration_ms: float = 0.0
    redaction_applied: bool = False


class RunbookSearchResult(BaseModel):
    """Runbook search result."""

    name: str
    path: str
    snippet: str | None = None
    score: float = 0.0


class RunbookResolutionResult(BaseModel):
    """Resolution result (exact match or fuzzy)."""

    type: str  # exact, fuzzy, not_found
    record: RunbookRecord | None = None
    hint: str | None = None
