"""Shared MCP tool catalog for service registration and API schema lookup."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MCPToolSpec:
    """Definition for a default MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]


_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def _schema(
    properties: dict[str, Any] | None = None, required: list[str] | None = None
) -> dict[str, Any]:
    """Build a JSON schema object for MCP tool input."""
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = required
    return schema


# Shared description literals reused across multiple tool schemas.
ALIAS_FOR_INDEX_DESC = "Alias for index"
DOCUMENT_ID_DESC = "Document ID"
TARGET_INDEX_NAME_DESC = "Target index name"
RUNBOOK_NAME_DESC = "Runbook name"


DEFAULT_MCP_TOOL_SPECS: tuple[MCPToolSpec, ...] = (
    # ========== KnowledgeBase Core Tools ==========
    MCPToolSpec(
        name="kb_search",
        description="Search the knowledgebase for relevant documents using semantic vector search",
        input_schema=_schema(
            {
                "query": {"type": "string", "description": "Search query"},
                "index": {"type": "string", "description": "Optional index to search"},
                "index_name": {"type": "string", "description": ALIAS_FOR_INDEX_DESC},
                "group": {"type": "string", "description": "Optional taxonomy top group"},
                "domain": {"type": "string", "description": "Optional taxonomy domain"},
                "subgroup": {"type": "string", "description": "Optional taxonomy subgroup"},
                "source_repo": {
                    "type": "string",
                    "description": "Optional source repository filter (e.g. 'BaylyAI-GEN3-AIS-InfraKnowledge')",
                },
                "top_k": {"type": "integer", "description": "Maximum results"},
                "limit": {"type": "integer", "description": "Alias for top_k"},
                "min_score": {"type": "number", "description": "Minimum similarity score"},
                "offset": {
                    "type": "integer",
                    "description": "Result offset for pagination (default 0)",
                },
                "full_content": {
                    "type": "boolean",
                    "description": "Return full document content instead of preview (default false)",
                },
                "summarize": {
                    "type": "boolean",
                    "description": "Whether to return a summary of results",
                },
            },
            required=["query"],
        ),
    ),
    MCPToolSpec(
        name="kb_get_document",
        description="Retrieve a complete document from the KnowledgeBase by index and document ID",
        input_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Document ID to retrieve"},
                "doc_id": {
                    "type": "string",
                    "description": "Alias for id",
                },
                "index": {
                    "type": "string",
                    "description": "Index name (required if multiple indices exist)",
                },
                "index_name": {"type": "string", "description": ALIAS_FOR_INDEX_DESC},
            },
            "anyOf": [{"required": ["id"]}, {"required": ["doc_id"]}],
        },
    ),
    MCPToolSpec(
        name="kb_index_list",
        description="List all available indices in the KnowledgeBase",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="kb_index_create",
        description="Create a new index in the KnowledgeBase",
        input_schema=_schema(
            {
                "name": {"type": "string", "description": "Index name to create"},
                "description": {"type": "string", "description": "Optional description"},
            },
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="kb_index_delete",
        description="Delete an index by name",
        input_schema=_schema(
            {
                "name": {"type": "string", "description": "Index name to delete"},
                "force": {"type": "boolean", "description": "Force delete if populated"},
            },
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="kb_add_document",
        description="Add a new document to an index with text content",
        input_schema=_schema(
            {
                "id": {"type": "string", "description": DOCUMENT_ID_DESC},
                "content": {"type": "string", "description": "Document content"},
                "index_name": {"type": "string", "description": "Target index"},
            },
            required=["id", "content"],
        ),
    ),
    MCPToolSpec(
        name="kb_add_file",
        description="Add a local file to a KnowledgeBase index by path",
        input_schema=_schema(
            {
                "path": {"type": "string", "description": "Local filesystem path"},
                "index": {"type": "string", "description": TARGET_INDEX_NAME_DESC},
                "title": {"type": "string", "description": "Optional document title"},
            },
            required=["path", "index"],
        ),
    ),
    MCPToolSpec(
        name="kb_remove_document",
        description="Remove a document from the KnowledgeBase by ID",
        input_schema=_schema(
            {
                "doc_id": {"type": "string", "description": DOCUMENT_ID_DESC},
                "index": {"type": "string", "description": "Optional index restriction"},
                "index_name": {"type": "string", "description": ALIAS_FOR_INDEX_DESC},
            },
            required=["doc_id"],
        ),
    ),
    MCPToolSpec(
        name="kb_sync_all",
        description="Trigger a full sync of all configured indices",
        input_schema=_schema(
            {
                "target": {
                    "type": "string",
                    "description": (
                        "Sync destination: 'local' (default) syncs into this instance's "
                        "own storage; 'dev' pushes to the configured dev AegisCMCP instance"
                    ),
                    "enum": ["local", "dev"],
                },
            }
        ),
    ),
    MCPToolSpec(
        name="kb_health",
        description="Check KnowledgeBase health and system status",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="kb_stats",
        description="Get KnowledgeBase system and usage statistics",
        input_schema=_schema(),
    ),
    # ========== Documentation Management Tools ==========
    MCPToolSpec(
        name="docs_kb_list",
        description="List KnowledgeBase documents with filtering options",
        input_schema=_schema(
            {
                "path": {"type": "string", "description": "Subdirectory path in knowledgebase"},
                "extension": {"type": "string", "description": "File extension filter"},
                "limit": {"type": "integer", "description": "Maximum files to return"},
            }
        ),
    ),
    MCPToolSpec(
        name="docs_kb_search",
        description="Search KnowledgeBase files by filename pattern",
        input_schema=_schema(
            {
                "pattern": {"type": "string", "description": "Filename pattern"},
                "path": {"type": "string", "description": "Subdirectory path"},
            },
            required=["pattern"],
        ),
    ),
    MCPToolSpec(
        name="docs_kb_info",
        description="Get KnowledgeBase structure and statistics",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="docs_read_meta",
        description="Read document metadata (frontmatter, size, dates)",
        input_schema=_schema(
            {"path": {"type": "string", "description": "Path relative to .infraOS/knowledgebase"}},
            required=["path"],
        ),
    ),
    MCPToolSpec(
        name="docs_read_content",
        description="Read full text content of a KnowledgeBase document file",
        input_schema=_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Path relative to .infraOS/knowledgebase",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum bytes to return (default 1MB)",
                },
            },
            required=["path"],
        ),
    ),
    MCPToolSpec(
        name="docs_list_dirs",
        description="List directories in documentation structure",
        input_schema=_schema(
            {
                "path": {"type": "string", "description": "Optional subdirectory path"},
                "limit": {"type": "integer", "description": "Maximum directories to return"},
            }
        ),
    ),
    # ========== System Utility Tools ==========
    MCPToolSpec(
        name="infraos_context",
        description="Get current system context (time, cwd, version, system info)",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="infraos_ping",
        description="Health check - returns pong with server timestamp",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="infraos_echo",
        description="Echo back the provided message for testing connectivity",
        input_schema=_schema(
            {"message": {"type": "string", "description": "Message to echo"}},
            required=["message"],
        ),
    ),
    MCPToolSpec(
        name="infraos_env_get",
        description="Get an environment variable value by name",
        input_schema=_schema(
            {"name": {"type": "string", "description": "Environment variable name"}},
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="infraos_env_list",
        description="List environment variables (optionally filtered by prefix)",
        input_schema=_schema(
            {
                "prefix": {"type": "string", "description": "Optional prefix filter"},
                "values": {"type": "boolean", "description": "Whether to include values"},
            }
        ),
    ),
    # ========== Runbook Management Tools ==========
    MCPToolSpec(
        name="runbook_list",
        description="List all available runbooks in the knowledgebase",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="runbook_get",
        description="Get a specific runbook by name",
        input_schema=_schema(
            {"name": {"type": "string", "description": "Runbook name to retrieve"}},
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="runbook_create",
        description="Create a new runbook from file or text content",
        input_schema=_schema(
            {
                "name": {"type": "string", "description": RUNBOOK_NAME_DESC},
                "file": {
                    "type": "string",
                    "description": "Path to runbook file (optional, use content instead)",
                },
                "content": {
                    "type": "string",
                    "description": "Runbook content text (optional, use file instead)",
                },
            },
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="runbook_delete",
        description="Delete a runbook by name",
        input_schema=_schema(
            {
                "name": {"type": "string", "description": "Runbook name to delete"},
                "force": {"type": "boolean", "description": "Force delete without confirmation"},
            },
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="runbook_reindex",
        description="Reindex runbooks to update search indices",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="runbook_get_prompt",
        description="Get a prompt template from a runbook with variable substitution",
        input_schema=_schema(
            {
                "name": {"type": "string", "description": RUNBOOK_NAME_DESC},
                "vars": {
                    "type": "string",
                    "description": "Comma-separated key=value variable assignments",
                },
            },
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="runbook_log_create",
        description="Create an execution log entry for a runbook run",
        input_schema=_schema(
            {
                "name": {"type": "string", "description": RUNBOOK_NAME_DESC},
                "file": {"type": "string", "description": "Path to log file"},
                "content": {"type": "string", "description": "Log content text"},
            },
            required=["name"],
        ),
    ),
    # ========== Search Configuration Tools ==========
    MCPToolSpec(
        name="kb_search_config_get",
        description="Get current search configuration (mode, weights, parameters)",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="kb_search_config_set",
        description="Set search configuration parameters",
        input_schema=_schema(
            {
                "mode": {"type": "string", "description": "Search mode: vector, bm25, or hybrid"},
                "bm25_weight": {
                    "type": "number",
                    "description": "BM25 weight for hybrid search (0-1)",
                },
                "vector_weight": {
                    "type": "number",
                    "description": "Vector weight for hybrid search (0-1)",
                },
            }
        ),
    ),
    # ========== Discovery & Index Tools ==========
    MCPToolSpec(
        name="kb_taxonomy_list",
        description="List all distinct taxonomy values (groups, domains, subgroups) in the knowledgebase",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="kb_index_info",
        description="Get detailed metadata about a specific index",
        input_schema=_schema(
            {
                "name": {"type": "string", "description": "Index name"},
            },
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="kb_embedding_info",
        description="Get information about the embedding provider and model",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="kb_rag_config_get",
        description="Get current RAG (Retrieval-Augmented Generation) configuration",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="kb_rag_config_set",
        description="Set RAG configuration parameters",
        input_schema=_schema(
            {
                "top_k": {"type": "integer", "description": "Number of documents to retrieve"},
                "min_score": {"type": "number", "description": "Minimum similarity score"},
                "use_reranker": {"type": "boolean", "description": "Enable reranking"},
            }
        ),
    ),
    MCPToolSpec(
        name="runbook_search",
        description="Search runbooks using semantic search",
        input_schema=_schema(
            {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Maximum results (default 10)"},
            },
            required=["query"],
        ),
    ),
    # ========== Lifecycle & Batch Tools ==========
    MCPToolSpec(
        name="kb_index_directory",
        description="Index all files in a directory recursively",
        input_schema=_schema(
            {
                "path": {"type": "string", "description": "Directory path to index"},
                "index": {"type": "string", "description": TARGET_INDEX_NAME_DESC},
                "pattern": {
                    "type": "string",
                    "description": "File pattern to match (default *.md)",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum files to scan before truncating",
                },
                "time_budget_seconds": {
                    "type": "integer",
                    "description": "Maximum scan time budget in seconds",
                },
            },
            required=["path", "index"],
        ),
    ),
    MCPToolSpec(
        name="kb_upsert_document",
        description="Create or update a document (delete if exists, then add). Supports federated repo attribution via source_repo/source_vcs.",
        input_schema=_schema(
            {
                "id": {"type": "string", "description": DOCUMENT_ID_DESC},
                "content": {"type": "string", "description": "Document content"},
                "index": {"type": "string", "description": TARGET_INDEX_NAME_DESC},
                "index_name": {"type": "string", "description": ALIAS_FOR_INDEX_DESC},
                "title": {"type": "string", "description": "Document title (optional)"},
                "source_repo": {
                    "type": "string",
                    "description": "Source repository ID for federated content (e.g. 'BaylyAI-GEN1-IBS-Admin')",
                },
                "source_vcs": {
                    "type": "string",
                    "description": "Version control system (default: 'github')",
                },
                "path": {"type": "string", "description": "Source file path (optional)"},
            },
            required=["id", "content"],
        ),
    ),
    MCPToolSpec(
        name="kb_add_documents_batch",
        description="Add multiple documents in a single batch operation (max 50 documents)",
        input_schema=_schema(
            {
                "documents": {
                    "type": "array",
                    "description": "List of documents to add (each with id, content, optional metadata)",
                },
                "index": {"type": "string", "description": TARGET_INDEX_NAME_DESC},
                "index_name": {"type": "string", "description": ALIAS_FOR_INDEX_DESC},
            },
            required=["documents"],
        ),
    ),
    # ========== Observability & Analytics Tools ==========
    MCPToolSpec(
        name="kb_index_reindex",
        description="Reindex a specific index to update embeddings and search indices",
        input_schema=_schema(
            {
                "name": {"type": "string", "description": "Index name to reindex"},
            },
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="kb_search_analytics",
        description="Get search analytics (recent queries, latency, top searches)",
        input_schema=_schema(
            {
                "limit": {
                    "type": "integer",
                    "description": "Maximum queries to return (default 20)",
                },
                "order_by": {
                    "type": "string",
                    "description": "Order by: recent, frequency, or latency",
                },
            }
        ),
    ),
    MCPToolSpec(
        name="kb_status_full",
        description="Get comprehensive status diagnostics for tools, endpoints, sync state, and system metrics",
        input_schema=_schema(),
    ),
)

# Preserve original client names alongside the infraos rename.
DEFAULT_MCP_TOOL_SPECS += tuple(
    MCPToolSpec(
        spec.name.replace("infraos_", "aegis_", 1), spec.description, deepcopy(spec.input_schema)
    )
    for spec in DEFAULT_MCP_TOOL_SPECS
    if spec.name.startswith("infraos_")
)

_SCHEMA_MAP: dict[str, dict[str, Any]] = {
    tool_spec.name: tool_spec.input_schema for tool_spec in DEFAULT_MCP_TOOL_SPECS
}


def get_default_mcp_tool_specs() -> tuple[MCPToolSpec, ...]:
    """Return all default MCP tool specifications."""
    return DEFAULT_MCP_TOOL_SPECS


def get_default_mcp_tool_schema(tool_name: str) -> dict[str, Any]:
    """Return default JSON schema for a tool name."""
    return deepcopy(_SCHEMA_MAP.get(tool_name, _EMPTY_SCHEMA))
