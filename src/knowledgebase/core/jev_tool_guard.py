"""JEV tool-guard control loop for AegisCMCP MCP tools.

Maps consequential MCP tools to side-effect metadata, calls JEV, and returns
a block/allow decision for the agent tool execution path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import structlog

from knowledgebase.core.jev_client import (
    JevClient,
    ToolGuardRequest,
    ToolGuardResult,
    get_jev_client,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ToolRiskProfile:
    """Static risk metadata for a guarded MCP tool."""

    action_template: str
    side_effects: tuple[str, ...]
    safeguards: tuple[str, ...]
    policy: tuple[str, ...]
    reversibility: str  # reversible | partially_reversible | irreversible


# Tools that mutate knowledge state or external systems. Read-only tools are
# intentionally omitted so the guard stays off the hot search path.
GUARDED_TOOL_PROFILES: dict[str, ToolRiskProfile] = {
    "kb_index_create": ToolRiskProfile(
        action_template="Create knowledge index {name}",
        side_effects=("Creates a new search index", "Changes catalog state"),
        safeguards=("Index names validated by service schema",),
        policy=("Index create is a mutating control-plane action",),
        reversibility="reversible",
    ),
    "kb_index_delete": ToolRiskProfile(
        action_template="Delete knowledge index {name}",
        side_effects=("Deletes an index and its documents", "Irreversible data loss if no backup"),
        safeguards=("force flag required for populated indices when configured",),
        policy=("Index delete requires human approval in production", "Prefer backup before delete"),
        reversibility="irreversible",
    ),
    "kb_add_document": ToolRiskProfile(
        action_template="Add document {id} to index",
        side_effects=("Writes document content into the knowledgebase",),
        safeguards=("Document IDs scoped to target index",),
        policy=("Writes must not include secrets or credentials",),
        reversibility="reversible",
    ),
    "kb_add_file": ToolRiskProfile(
        action_template="Ingest local file into index",
        side_effects=("Reads a local filesystem path", "Writes document content into the knowledgebase"),
        safeguards=("Path must be reachable by the service process",),
        policy=("Do not ingest paths outside approved knowledge roots", "No secrets in content"),
        reversibility="reversible",
    ),
    "kb_remove_document": ToolRiskProfile(
        action_template="Remove document {doc_id} from knowledgebase",
        side_effects=("Deletes document content", "May break citations that reference the ID"),
        safeguards=("Optional index restriction narrows blast radius",),
        policy=("Document delete requires confirmation when content is canonical",),
        reversibility="partially_reversible",
    ),
    "kb_sync_all": ToolRiskProfile(
        action_template="Trigger full knowledgebase sync to {target}",
        side_effects=("Bulk writes across indices", "May push to remote MCP targets", "High load"),
        safeguards=("Sync targets come from cfg/sync.json", "Timeouts bound long runs"),
        policy=("Full sync is a high-impact operator action", "Prefer check/prune before force sync"),
        reversibility="partially_reversible",
    ),
    "kb_search_config_set": ToolRiskProfile(
        action_template="Update search configuration",
        side_effects=("Changes retrieval behavior for subsequent agent searches",),
        safeguards=("Values coerced to safe numeric bounds where applicable",),
        policy=("Runtime search config changes should be reviewed",),
        reversibility="reversible",
    ),
    "kb_rag_config_set": ToolRiskProfile(
        action_template="Update RAG configuration",
        side_effects=("Changes top_k/min_score/reranker behavior",),
        safeguards=("Bounded numeric parameters",),
        policy=("RAG config affects answer quality and cost",),
        reversibility="reversible",
    ),
    "kb_index_directory": ToolRiskProfile(
        action_template="Recursively index directory into knowledgebase",
        side_effects=("Bulk filesystem read", "Bulk document writes", "Potentially large ingest"),
        safeguards=("max_files and time_budget_seconds can bound the scan",),
        policy=("Directory ingest must stay within approved roots",),
        reversibility="partially_reversible",
    ),
    "kb_upsert_document": ToolRiskProfile(
        action_template="Upsert document {id}",
        side_effects=("Creates or overwrites document content",),
        safeguards=("Explicit document id required",),
        policy=("Overwrites must preserve provenance metadata when provided",),
        reversibility="partially_reversible",
    ),
    "kb_add_documents_batch": ToolRiskProfile(
        action_template="Batch-add documents to knowledgebase",
        side_effects=("Bulk writes (up to service max batch size)",),
        safeguards=("Batch size capped by tool schema",),
        policy=("Batch writes should not include secrets",),
        reversibility="reversible",
    ),
    "kb_index_reindex": ToolRiskProfile(
        action_template="Reindex index {name}",
        side_effects=("Rebuilds embeddings/search structures", "CPU and embedding cost spike"),
        safeguards=("Targets a single named index",),
        policy=("Reindex is an operator maintenance action",),
        reversibility="reversible",
    ),
    "runbook_create": ToolRiskProfile(
        action_template="Create runbook",
        side_effects=("Writes runbook content",),
        safeguards=("Runbook service path constraints",),
        policy=("Runbooks are operational procedures; review before publish",),
        reversibility="reversible",
    ),
    "runbook_delete": ToolRiskProfile(
        action_template="Delete runbook",
        side_effects=("Deletes runbook content",),
        safeguards=("Named runbook targeting",),
        policy=("Runbook delete requires confirmation",),
        reversibility="partially_reversible",
    ),
    "runbook_reindex": ToolRiskProfile(
        action_template="Reindex runbooks",
        side_effects=("Rebuilds runbook search index",),
        safeguards=("Scoped to runbook corpus",),
        policy=("Maintenance action",),
        reversibility="reversible",
    ),
    "runbook_log_create": ToolRiskProfile(
        action_template="Create runbook execution log",
        side_effects=("Writes operational log records",),
        safeguards=("Logs stored under configured logs_dir",),
        policy=("Do not log secrets",),
        reversibility="reversible",
    ),
}


def is_guarded_tool(tool_name: str) -> bool:
    """Return True when the tool is in the mutating/consequential set."""
    return tool_name in GUARDED_TOOL_PROFILES


def _summarize_args(args: Mapping[str, Any], *, limit: int = 12) -> list[str]:
    """Build a compact, secret-safe argument summary for JEV state."""
    summary: list[str] = []
    for key in sorted(args.keys()):
        if len(summary) >= limit:
            summary.append(f"...({len(args) - limit} more keys omitted)")
            break
        value = args[key]
        key_l = str(key).casefold()
        if any(tok in key_l for tok in ("password", "secret", "token", "api_key", "authorization")):
            summary.append(f"{key}=[REDACTED]")
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = str(value)
            if len(text) > 160:
                text = text[:157] + "..."
            summary.append(f"{key}={text}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            summary.append(f"{key}=list(len={len(value)})")
        elif isinstance(value, Mapping):
            summary.append(f"{key}=object(keys={len(value)})")
        else:
            summary.append(f"{key}={type(value).__name__}")
    return summary


def build_tool_guard_request(tool_name: str, args: Mapping[str, Any]) -> Optional[ToolGuardRequest]:
    """Construct a ToolGuardRequest for a known guarded tool, else None."""
    profile = GUARDED_TOOL_PROFILES.get(tool_name)
    if profile is None:
        return None

    format_args = {
        key: args.get(key, "")
        for key in ("name", "id", "doc_id", "target", "path", "index", "index_name")
    }
    try:
        action = profile.action_template.format_map(format_args)
    except Exception:  # noqa: BLE001
        action = profile.action_template

    return ToolGuardRequest(
        tool=tool_name,
        action=action,
        arguments_summary=_summarize_args(args),
        side_effects=profile.side_effects,
        safeguards=profile.safeguards,
        policy=profile.policy,
        reversibility=profile.reversibility,
    )


async def evaluate_tool_guard(
    tool_name: str,
    args: Mapping[str, Any],
    *,
    client: Optional[JevClient] = None,
) -> Optional[ToolGuardResult]:
    """Run JEV tool-guard when enabled and the tool is consequential.

    Returns:
        None when the guard is disabled or the tool is not guarded.
        ToolGuardResult otherwise (caller checks ``blocked``).
    """
    jev = client or get_jev_client()
    if not jev.enabled:
        return None
    request = build_tool_guard_request(tool_name, args)
    if request is None:
        return None

    result = await jev.guard_tool_call(request)
    logger.info(
        "jev_tool_guard_evaluated",
        tool=tool_name,
        decision=result.decision,
        confidence=result.confidence,
        blocked=result.blocked,
        source=result.source,
    )
    return result


def format_block_message(tool_name: str, result: ToolGuardResult) -> str:
    """Human/agent-readable block payload for MCP isError responses."""
    payload = {
        "error": "jev_tool_guard_blocked",
        "tool": tool_name,
        "jev": result.to_public_dict(),
        "next_step": (
            "Do not retry the same mutating call automatically. "
            "Obtain human approval, narrow the blast radius, or use a read-only alternative."
        ),
    }
    return json.dumps(payload, indent=2, sort_keys=True)
