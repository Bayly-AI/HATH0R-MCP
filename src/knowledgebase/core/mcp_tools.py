"""Shared MCP tool catalog for service registration and API schema lookup."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from knowledgebase.core.suite_tools import resolve_service_bot_metadata


@dataclass(frozen=True)
class MCPToolSpec:
    """Definition for a default Level 1 MCP tool governed by CR-FEATURE-WORKFLOW-STANDARD-001."""

    name: str
    description: str
    input_schema: dict[str, Any]
    owning_bots: tuple[str, ...] = field(default_factory=tuple)
    workflow_id: str = ""
    agentgraph_level: str = "L1_MCP"

    def __post_init__(self) -> None:
        meta = resolve_service_bot_metadata(self.name)
        bots = tuple(self.owning_bots) if self.owning_bots else tuple(meta["owning_bots"])
        wf = self.workflow_id or str(meta["workflow_id"])
        lvl = self.agentgraph_level or str(meta["agentgraph_level"])
        object.__setattr__(self, "owning_bots", bots)
        object.__setattr__(self, "workflow_id", wf)
        object.__setattr__(self, "agentgraph_level", lvl)
        self.input_schema["x-hath0r-owning-bot"] = list(bots)
        self.input_schema["x-hath0r-workflow-id"] = wf
        self.input_schema["x-hath0r-agentgraph-level"] = lvl


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
            {"path": {"type": "string", "description": "Path relative to .hath0r/knowledgebase"}},
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
                    "description": "Path relative to .hath0r/knowledgebase",
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
        name="hath0r_context",
        description="Get current system context (time, cwd, version, system info)",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="hath0r_ping",
        description="Health check - returns pong with server timestamp",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="hath0r_echo",
        description="Echo back the provided message for testing connectivity",
        input_schema=_schema(
            {"message": {"type": "string", "description": "Message to echo"}},
            required=["message"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_env_get",
        description="Get an environment variable value by name",
        input_schema=_schema(
            {"name": {"type": "string", "description": "Environment variable name"}},
            required=["name"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_env_list",
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
                    "description": "List of documents to add (each with id, content, optional title)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": DOCUMENT_ID_DESC},
                            "content": {"type": "string", "description": "Document content"},
                            "title": {
                                "type": "string",
                                "description": "Document title (optional, defaults to id)",
                            },
                        },
                        "required": ["id", "content"],
                    },
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
    # ========== Voice Interaction & Session Mediation Tools ==========
    MCPToolSpec(
        name="voice_speak",
        description="Synthesize and speak feedback text to the user via host audio",
        input_schema=_schema(
            {
                "text": {"type": "string", "description": "Text to synthesize and speak"},
                "voice": {"type": "string", "description": "Optional voice identifier or persona name"},
            },
            required=["text"],
        ),
    ),
    MCPToolSpec(
        name="voice_listen",
        description="Request spoken input from the user with optional spoken prompt",
        input_schema=_schema(
            {
                "prompt": {"type": "string", "description": "Optional question or prompt spoken to user before listening"},
                "timeout_seconds": {"type": "number", "description": "Maximum seconds to wait for speech input (default 10.0)"},
                "simulated_input": {"type": "string", "description": "Optional simulated spoken input for headless/testing environments"},
            }
        ),
    ),
    MCPToolSpec(
        name="voice_dispatch_action",
        description="Dispatch a standardized hath0r.voice.action/1 intent to system or agent",
        input_schema=_schema(
            {
                "transcript": {"type": "string", "description": "Transcribed spoken utterance"},
                "intent": {
                    "type": "string",
                    "description": "Categorized intent classification",
                    "enum": [
                        "cli_command",
                        "computer_use",
                        "agent_delegate",
                        "system_control",
                        "unresolved",
                    ],
                },
                "routing_tier": {
                    "type": "string",
                    "description": "Routing tier: system_one or system_two",
                    "enum": ["system_one", "system_two"],
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score from 0.0 to 1.0 (default 1.0)",
                },
                "command": {"type": "string", "description": "Optional command string or CLI subcommand"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional arguments for the command",
                },
                "target": {"type": "string", "description": "Optional target application, element, or agent identifier"},
                "feedback_text": {"type": "string", "description": "Optional spoken response acknowledging action"},
                "metadata": {"type": "object", "description": "Optional metadata dictionary"},
            },
            required=["transcript", "intent"],
        ),
    ),
    # ========== Apache Airflow Enterprise Integration Tools ==========
    MCPToolSpec(
        name="airflow_list_dags",
        description="List active DAGs in the enterprise Apache Airflow environment",
        input_schema=_schema(
            {
                "limit": {"type": "integer", "description": "Maximum DAGs to return (default 20)"},
                "offset": {"type": "integer", "description": "Offset for pagination (default 0)"},
            }
        ),
    ),
    MCPToolSpec(
        name="airflow_trigger_dag",
        description="Trigger execution of an Apache Airflow DAG with optional configuration parameters",
        input_schema=_schema(
            {
                "dag_id": {"type": "string", "description": "Target Airflow DAG identifier"},
                "conf": {"type": "object", "description": "Optional configuration payload for the DAG run"},
            },
            required=["dag_id"],
        ),
    ),
    MCPToolSpec(
        name="airflow_get_dag_run",
        description="Inspect execution status and state of a specific Apache Airflow DAG run",
        input_schema=_schema(
            {
                "dag_id": {"type": "string", "description": "Airflow DAG identifier"},
                "dag_run_id": {"type": "string", "description": "Airflow DAG run identifier"},
            },
            required=["dag_id", "dag_run_id"],
        ),
    ),
    # ========== Level 1 Centralized Suite Tools (CR-FEATURE-WORKFLOW-STANDARD-001 & CR-MCP-CENTRAL-001) ==========
    MCPToolSpec(
        name="hath0r_supersqueeze",
        description="Compress verbose context, RAG excerpts, or tool payloads using SuperSqueeze (SuperCompressBot)",
        input_schema=_schema(
            {
                "text": {"type": "string", "description": "Input text to compress"},
                "query": {"type": "string", "description": "Optional query for salience-aware compression"},
                "target_ratio": {"type": "number", "description": "Target compression ratio (default 0.35)"},
            },
            required=["text"],
        ),
    ),
    MCPToolSpec(
        name="mcp_agentgraph_status",
        description="Inspect Level 1 (HATH0R-MCP) & Level 2 (HATH0R-CLI/Memory) AgentGraph node and edge distributions",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="mcp_agentgraph_query",
        description="Query AgentGraph rules, contracts, roles, and knowledge nodes across Level 1 and Level 2",
        input_schema=_schema(
            {
                "topic": {"type": "string", "description": "Topic or keyword to search"},
                "top_k": {"type": "integer", "description": "Maximum results to return (default 5)"},
                "plane": {"type": "string", "description": "Optional plane filter"},
            },
            required=["topic"],
        ),
    ),
    MCPToolSpec(
        name="mcp_agentgraph_route",
        description="Evaluate AgentGraph role RBAC and Service-Bot ownership for a tool",
        input_schema=_schema(
            {
                "role": {"type": "string", "description": "Caller role (e.g. developer, operator, bot)"},
                "tool": {"type": "string", "description": "Optional tool name"},
            },
            required=["role"],
        ),
    ),
    MCPToolSpec(
        name="mcp_agentgraph_sync",
        description="Synchronize Level 1 and Level 2 AgentGraph state",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="mcp_agentgraph_validate",
        description="Validate AgentGraph integrity and CR-FEATURE-WORKFLOW-STANDARD-001 Service-Bot ownership",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="hath0r_agentgraph_status",
        description="Inspect unified AgentGraph node, edge, plane distributions, and graph health status",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="hath0r_agentgraph_query",
        description="Query AgentGraph rules, contracts, roles, and knowledge nodes matching a topic string",
        input_schema=_schema(
            {
                "topic": {"type": "string", "description": "Topic or keyword to search"},
                "top_k": {"type": "integer", "description": "Maximum results (default 5)"},
                "plane": {"type": "string", "description": "Optional plane filter"},
            },
            required=["topic"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_agentgraph_route",
        description="Evaluate AgentGraph deterministic role RBAC policies and tool permissions",
        input_schema=_schema(
            {
                "role": {"type": "string", "description": "Agent role name"},
                "tool": {"type": "string", "description": "Optional tool name"},
            },
            required=["role"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_workflow_offer",
        description="Generate a Missing-Workflow Offer (CR-FEATURE-WORKFLOW-STANDARD-001) using the request as acceptance test",
        input_schema=_schema(
            {
                "intent": {"type": "string", "description": "Task or capability request lacking a workflow"},
                "suggested_bots": {"type": "array", "items": {"type": "string"}, "description": "Owning Bot IDs"},
            },
            required=["intent"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_cli",
        description="Execute a Hath0r operator CLI command via Level 1 MCP dispatch",
        input_schema=_schema({"command": {"type": "string", "description": "CLI arguments"}}, required=["command"]),
    ),
    MCPToolSpec(
        name="hath0r_doctor",
        description="Run suite-wide Hath0r health diagnostics",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="hath0r_optimize_taguchi",
        description="Generate Taguchi orthogonal design array, SNR, and Quadratic Quality Loss L(y)",
        input_schema=_schema(
            {
                "array": {"type": "string", "description": "Orthogonal array (L4, L8, L9, L12, L18)"},
                "factors": {"type": "array", "items": {"type": "string"}, "description": "Factor names"},
                "snr_values": {"type": "array", "items": {"type": "number"}, "description": "Observed values"},
                "criterion": {"type": "string", "description": "SNR criterion"},
                "loss_k": {"type": "number", "description": "Loss coefficient k"},
                "target_m": {"type": "number", "description": "Target nominal m"},
                "measured_y": {"type": "number", "description": "Measured characteristic y"},
            }
        ),
    ),
    MCPToolSpec(
        name="hath0r_finops_tokenizer_tax",
        description="Audit token inflation, serving VRAM overhead, and precision budget",
        input_schema=_schema(
            {
                "text": {"type": "string", "description": "Text to audit"},
                "vocab_size": {"type": "integer", "description": "Vocabulary size"},
                "hidden_dim": {"type": "integer", "description": "Hidden dimension"},
                "precision": {"type": "string", "description": "Weight precision"},
            },
            required=["text"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_finops_tokens_list",
        description="Query prompt and completion token usage ledger records",
        input_schema=_schema(
            {
                "user": {"type": "string", "description": "User filter"},
                "agent": {"type": "string", "description": "Agent filter"},
                "session_id": {"type": "string", "description": "Session filter"},
                "tier": {"type": "string", "description": "Model tier filter"},
                "model": {"type": "string", "description": "Model name filter"},
                "limit": {"type": "integer", "description": "Max records"},
            }
        ),
    ),
    MCPToolSpec(
        name="hath0r_finops_tokens_histogram",
        description="Generate statistical quantiles and histogram for token telemetry",
        input_schema=_schema(
            {
                "bin_field": {"type": "string", "description": "Metric field"},
                "bins": {"type": "integer", "description": "Histogram bins"},
            }
        ),
    ),
    MCPToolSpec(
        name="hath0r_finops_token_check",
        description="Execute 90-day FinOps token usage check workflow",
        input_schema=_schema(
            {
                "user_id": {"type": "string", "description": "Target user ID"},
                "days": {"type": "integer", "description": "Trailing days"},
            }
        ),
    ),
    MCPToolSpec(
        name="hath0r_finops_budget_check",
        description="Evaluate prompt against Token Tree Budget Guard before LLM execution",
        input_schema=_schema(
            {
                "prompt": {"type": "string", "description": "Prompt text"},
                "session_id": {"type": "string", "description": "Session ID"},
            },
            required=["prompt"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_ray_search",
        description="Search indexed personal knowledge store",
        input_schema=_schema(
            {
                "query": {"type": "string", "description": "Search query"},
                "source": {"type": "string", "description": "Optional source filter"},
                "limit": {"type": "integer", "description": "Max results"},
            },
            required=["query"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_ray_get_document",
        description="Retrieve document by ID from indexed knowledge store",
        input_schema=_schema({"doc_id": {"type": "string", "description": "Document ID"}}, required=["doc_id"]),
    ),
    MCPToolSpec(
        name="hath0r_session_get",
        description="Retrieve a session working memory key from KV store",
        input_schema=_schema({"key": {"type": "string", "description": "Session key"}}, required=["key"]),
    ),
    MCPToolSpec(
        name="hath0r_session_set",
        description="Store a session working memory key/value in KV store",
        input_schema=_schema(
            {
                "key": {"type": "string", "description": "Session key"},
                "value": {"description": "Session value"},
                "ttl_seconds": {"type": "integer", "description": "Optional TTL in seconds"},
            },
            required=["key", "value"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_vision_parse_doc",
        description="Parse documents and spreadsheets into 2D tabular matrices",
        input_schema=_schema(
            {
                "file_path": {"type": "string", "description": "Document file path"},
                "pixel_native": {"type": "boolean", "description": "Use pixel-native extraction"},
            },
            required=["file_path"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_vision_ground",
        description="Visually ground UI element description on screenshot",
        input_schema=_schema(
            {
                "image_path": {"type": "string", "description": "Image path"},
                "target": {"type": "string", "description": "Target element description"},
                "action": {"type": "string", "description": "UI action"},
            },
            required=["image_path", "target"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_design_status",
        description="Check Paper.design MCP integration status",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="hath0r_design_to_code",
        description="Synthesize React + Tailwind code from Paper canvas layout",
        input_schema=_schema(
            {
                "design_content": {"type": "string", "description": "Design markup"},
                "component_name": {"type": "string", "description": "Component name"},
                "framework": {"type": "string", "description": "Target framework"},
            },
            required=["design_content"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_upgrade",
        description="Check, run, or verify Hath0r CLI installation",
        input_schema=_schema({"action": {"type": "string", "description": "Upgrade action"}}),
    ),
    MCPToolSpec(
        name="hath0r_clean_repos",
        description="Execute 13-step Clean Repos SOP hygiene workflow",
        input_schema=_schema(
            {
                "repo_path": {"type": "string", "description": "Target repo path"},
                "dry_run": {"type": "boolean", "description": "Dry-run flag"},
            }
        ),
    ),
    MCPToolSpec(
        name="hath0r_contracts_validate",
        description="Validate JSON schema contracts and backward compatibility",
        input_schema=_schema({"contracts_dir": {"type": "string", "description": "Contracts directory"}}),
    ),
    MCPToolSpec(
        name="hath0r_pr_review_antagonistic",
        description="Run Antagonistic Review Bot on a pull request",
        input_schema=_schema(
            {
                "pr_number": {"type": "integer", "description": "Pull request number"},
                "repo": {"type": "string", "description": "Target repository"},
            },
            required=["pr_number"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_kb_smart_query",
        description="Execute hybrid CAG + RAG smart query routing",
        input_schema=_schema(
            {
                "query": {"type": "string", "description": "Query string"},
                "top_k": {"type": "integer", "description": "Max results"},
            },
            required=["query"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_evals_redteam",
        description="Conduct dual-agent Red-Team vs Blue-Team adversarial stress testing",
        input_schema=_schema(
            {
                "scenario": {"type": "string", "description": "Attack scenario"},
                "rounds": {"type": "integer", "description": "Simulation rounds"},
            },
            required=["scenario"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_issue_list",
        description="List and validate repository issues against CR-BRANCH-GOV-001",
        input_schema=_schema(
            {
                "repo": {"type": "string", "description": "Repository"},
                "state": {"type": "string", "description": "Issue state"},
            }
        ),
    ),
    MCPToolSpec(
        name="hath0r_cicccdct_status",
        description="Inspect 4-pillar CICCCDCT metrics and 4-hour calibration freshness",
        input_schema=_schema(),
    ),
    MCPToolSpec(
        name="hath0r_cicccdct_validate",
        description="Validate 4-pillar CICCCDCT state across CI, 4h CC freshness, CD, and CT",
        input_schema=_schema({"repo": {"type": "string", "description": "Repository"}}),
    ),
    MCPToolSpec(
        name="hath0r_cicccdct_train",
        description="Request Continuous Training (CT) job",
        input_schema=_schema(
            {
                "target": {"type": "string", "description": "Target model"},
                "method": {"type": "string", "description": "Training method"},
            }
        ),
    ),
    MCPToolSpec(
        name="hath0r_cicccdct_curate_dataset",
        description="Curate high-reward exemplar pairs from execution traces",
        input_schema=_schema({"min_reward": {"type": "number", "description": "Minimum reward threshold"}}),
    ),
    MCPToolSpec(
        name="hath0r_model_registry_promote",
        description="Promote model version in MLflow Model Registry",
        input_schema=_schema(
            {
                "model_name": {"type": "string", "description": "Model name"},
                "version": {"type": "integer", "description": "Version number"},
                "target_stage": {"type": "string", "description": "Target stage"},
            },
            required=["model_name", "version", "target_stage"],
        ),
    ),
    MCPToolSpec(
        name="hath0r_iac_audit",
        description="Audit workspace for Container Hardening and Salting compliance",
        input_schema=_schema({"path": {"type": "string", "description": "Workspace path"}}),
    ),
    MCPToolSpec(
        name="hath0r_iac_init",
        description="Scaffold hardened multi-stage Dockerfile and EKS Fargate manifests",
        input_schema=_schema({"path": {"type": "string", "description": "Workspace path"}}),
    ),
    MCPToolSpec(
        name="hath0r_iac_validate",
        description="Validate repository against CR-IAC-001",
        input_schema=_schema({"path": {"type": "string", "description": "Workspace path"}}),
    ),
    MCPToolSpec(
        name="hath0r_iac_salt",
        description="Cryptographically salt container image and emit SLSA receipt",
        input_schema=_schema({"image": {"type": "string", "description": "Image reference"}}, required=["image"]),
    ),
    MCPToolSpec(
        name="hath0r_iac_render",
        description="Render parameterized Kubernetes manifests targeting canonical environment",
        input_schema=_schema(
            {
                "path": {"type": "string", "description": "Workspace path"},
                "environment": {"type": "string", "description": "Target environment"},
            }
        ),
    ),
)

# Preserve compatibility client aliases for core utility tools.
_UTILITY_BASE_NAMES = {"hath0r_context", "hath0r_ping", "hath0r_echo", "hath0r_env_get", "hath0r_env_list"}
DEFAULT_MCP_TOOL_SPECS += tuple(
    MCPToolSpec(
        spec.name.replace("hath0r_", "aegis_", 1), spec.description, deepcopy(spec.input_schema)
    )
    for spec in DEFAULT_MCP_TOOL_SPECS
    if spec.name in _UTILITY_BASE_NAMES
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
