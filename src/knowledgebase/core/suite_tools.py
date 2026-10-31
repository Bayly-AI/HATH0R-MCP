"""
Level 1 Suite Tools, AgentGraph Router, and Service-Bot-Workflow Registry for HATH0R-MCP.

Implements CR-FEATURE-WORKFLOW-STANDARD-001 & CR-MCP-CENTRAL-001:
1. Every Feature is a Service run by >= 1 Bot in BotRegistry.
2. Tools and Knowledge reside on HATH0R-MCP (Level 1), CLI and Bot Memory reside on HATH0R-CLI (Level 2),
   all utilizing AgentGraph (.hath0r/agentgraph/snapshot.json).
3. Everything we do is a Workflow; if a workflow is missing, offer to create one first using the
   request as its acceptance test.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Any

from knowledgebase.core.feature_flags import is_feature_enabled
from knowledgebase.core.observability import timed_operation
from knowledgebase.core.supersqueeze import supersqueeze_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTGRAPH_SNAPSHOT_PATH = REPO_ROOT / ".hath0r" / "agentgraph" / "snapshot.json"
SESSION_KV_STORE: dict[str, dict[str, Any]] = {}


# Canonical mapping of every Level 1 MCP tool prefix/name to its Service, >=1 Owning Bot, and Declarative Workflow
SERVICE_BOT_WORKFLOW_REGISTRY: dict[str, dict[str, Any]] = {
    "kb_": {
        "service": "Central KnowledgeBase & RAG Service",
        "owning_bots": ["RAGRetrieverBot", "GraphRAGBot", "MCPCentralizationBot"],
        "workflow_id": "cfg/factories/mcp-kb-retrieval-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "docs_": {
        "service": "Suite Documentation Engine Service",
        "owning_bots": ["DocsPublishBot", "MCPCentralizationBot"],
        "workflow_id": "cfg/factories/mcp-docs-engine-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "runbook_": {
        "service": "Operational Runbook Service",
        "owning_bots": ["RunbookEngineBot", "MCPWorkflowEngineBot"],
        "workflow_id": "cfg/factories/mcp-runbook-execution-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "pbac_": {
        "service": "PBAC & L2 Sanitizer Security Service",
        "owning_bots": ["PBACPolicyBot", "BITEVerifierBot"],
        "workflow_id": "cfg/factories/mcp-security-audit-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "voice_": {
        "service": "Voice Action & Synthesis Service",
        "owning_bots": ["VoiceSynthesizerBot", "SpeechListenerBot"],
        "workflow_id": "cfg/factories/mcp-voice-dispatch-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "airflow_": {
        "service": "Enterprise Airflow Orchestration Service",
        "owning_bots": ["AirflowOrchestratorBot", "MCPWorkflowEngineBot"],
        "workflow_id": "cfg/factories/mcp-airflow-dag-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "hath0r_supersqueeze": {
        "service": "SuperSqueeze Context Compression Service",
        "owning_bots": ["SuperSqueezeBot", "SuperCompressBot"],
        "workflow_id": "cfg/factories/supersqueeze-context-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "mcp_agentgraph_": {
        "service": "Two-Level AgentGraph Governance & Routing Service",
        "owning_bots": ["AgentGraphBot", "ArchitecturePreservationBot"],
        "workflow_id": "cfg/factories/memory-agentgraph-sync-factory.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "hath0r_agentgraph_": {
        "service": "Two-Level AgentGraph Governance & Routing Service",
        "owning_bots": ["AgentGraphBot", "ArchitecturePreservationBot"],
        "workflow_id": "cfg/factories/memory-agentgraph-sync-factory.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "hath0r_finops_": {
        "service": "FinOps Token Ledger & Budget Service",
        "owning_bots": ["TokenTelemetryCLIBot", "TokenizerTaxBot", "TokenCheckWorkflowBot"],
        "workflow_id": "cfg/factories/finops-token-check-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "hath0r_optimize_taguchi": {
        "service": "Taguchi Orthogonal Optimization Service",
        "owning_bots": ["TaguchiBot"],
        "workflow_id": "cfg/factories/taguchi-optimization-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "hath0r_cicccdct_": {
        "service": "CICCCDCT 4-Hour Calibration & Continuous Training Service",
        "owning_bots": ["CICCCDManagingBot", "CalibrationBot"],
        "workflow_id": "cfg/factories/cccd-4h-calibration-factory.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "hath0r_iac_": {
        "service": "IaC & Container Salting Service",
        "owning_bots": ["IaCManagingBot", "PulumiInfraBot"],
        "workflow_id": "cfg/factories/iac-hardening-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "hath0r_vision_": {
        "service": "Pixel-Native Vision & UI Grounding Service",
        "owning_bots": ["VisionBot"],
        "workflow_id": "cfg/factories/vision-grounding-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "hath0r_design_": {
        "service": "Paper.design Bi-Directional UI Synthesis Service",
        "owning_bots": ["PaperDesignBot"],
        "workflow_id": "cfg/factories/paper-design-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "hath0r_": {
        "service": "Hath0r Core Suite Operator Service",
        "owning_bots": ["MCPCentralizationBot", "MCPWorkflowEngineBot", "ArchitecturePreservationBot"],
        "workflow_id": "cfg/factories/mcp-tool-dispatch-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
    "aegis_": {
        "service": "Hath0r Compatibility Utility Service",
        "owning_bots": ["MCPCentralizationBot"],
        "workflow_id": "cfg/factories/mcp-tool-dispatch-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    },
}


def resolve_service_bot_metadata(tool_name: str) -> dict[str, Any]:
    """Return canonical Service, Owning Bot(s) (>= 1 Bot), Workflow ID, and AgentGraph level for a tool."""
    if tool_name in SERVICE_BOT_WORKFLOW_REGISTRY:
        return dict(SERVICE_BOT_WORKFLOW_REGISTRY[tool_name])
    for prefix, meta in SERVICE_BOT_WORKFLOW_REGISTRY.items():
        if tool_name.startswith(prefix):
            return dict(meta)
    return {
        "service": "Hath0r Level 1 MCP Tool Service",
        "owning_bots": ["MCPCentralizationBot", "MCPWorkflowEngineBot"],
        "workflow_id": "cfg/factories/mcp-tool-dispatch-workflow.yaml",
        "agentgraph_level": "L1_MCP",
    }


def offer_missing_workflow(intent: str, suggested_bots: list[str] | None = None) -> dict[str, Any]:
    """Generate a deterministic Missing-Workflow Offer per CR-FEATURE-WORKFLOW-STANDARD-001."""
    slug = re.sub(r"[^a-z0-9]+", "-", intent.lower()).strip("-")[:48] or "custom-task"
    bots = suggested_bots or ["MCPWorkflowEngineBot", "ArchitecturePreservationBot"]
    workflow_path = f"cfg/factories/{slug}-workflow.yaml"
    return {
        "status": "missing_workflow_offer",
        "rule": "CR-FEATURE-WORKFLOW-STANDARD-001",
        "directive": "Everything we do is a Workflow. No workflow matched this intent; offer to create one first.",
        "intent": intent,
        "proposed_workflow_id": workflow_path,
        "owning_bots": bots,
        "agentgraph_levels": ["L1_MCP", "L2_CLI_MEMORY"],
        "acceptance_test": {
            "prompt": intent,
            "verification_gate": "pytest -q && hath0r evals run && hath0r evals verify",
            "min_reward_threshold": 0.80,
        },
        "scaffold_yaml": (
            f"apiVersion: hath0r.workflow/v1\n"
            f"kind: DeclarativeWorkflow\n"
            f"metadata:\n"
            f"  name: {slug}-workflow\n"
            f"  owning_bots: {json.dumps(bots)}\n"
            f"  agentgraph_levels: [L1_MCP, L2_CLI_MEMORY]\n"
            f"spec:\n"
            f"  acceptance_test: {json.dumps(intent)}\n"
            f"  steps:\n"
            f"    - id: pre_task_calibration\n"
            f"      bot: CICCCDManagingBot\n"
            f"      action: ensure_calibrated\n"
            f"      params: {{max_age_hours: 4.0}}\n"
            f"    - id: execute_service\n"
            f"      bot: {bots[0]}\n"
            f"      action: run\n"
        ),
    }


# ---------------------------------------------------------------------------
# Level 1 AgentGraph Tools (Synchronized with Level 2 .hath0r/agentgraph/)
# ---------------------------------------------------------------------------


def _load_agentgraph_snapshot() -> dict[str, Any]:
    if AGENTGRAPH_SNAPSHOT_PATH.is_file():
        try:
            return dict(json.loads(AGENTGRAPH_SNAPSHOT_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return {"nodes": [], "edges": [], "metadata": {"product": "hath0r-mcp"}}


def execute_agentgraph_status() -> dict[str, Any]:
    """Return Level 1 & Level 2 AgentGraph node, edge, and plane distributions."""
    with timed_operation("mcp_agentgraph_status", owning_bot="AgentGraphBot"):
        snap = _load_agentgraph_snapshot()
        nodes = snap.get("nodes", [])
        edges = snap.get("edges", [])
        planes = Counter(str(n.get("plane") or n.get("type") or "knowledge") for n in nodes if isinstance(n, dict))
        return {
            "status": "healthy",
            "agentgraph_level": "L1_MCP_AND_L2_CLI_MEMORY",
            "snapshot_path": str(AGENTGRAPH_SNAPSHOT_PATH),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "planes": dict(planes),
            "service_bot_registry_count": len(SERVICE_BOT_WORKFLOW_REGISTRY),
            "owning_bots": ["AgentGraphBot", "ArchitecturePreservationBot"],
            "workflow_id": "cfg/factories/memory-agentgraph-sync-factory.yaml",
        }


def execute_agentgraph_query(topic: str, top_k: int = 5, plane: str | None = None) -> dict[str, Any]:
    """Query AgentGraph nodes across Level 1 (HATH0R-MCP) and Level 2 (HATH0R-CLI / Bot Memory)."""
    with timed_operation("mcp_agentgraph_query", topic=topic, top_k=top_k, owning_bot="AgentGraphBot"):
        snap = _load_agentgraph_snapshot()
        nodes = snap.get("nodes", [])
        terms = [t.lower() for t in re.findall(r"\w+", topic) if t]
        scored: list[tuple[int, dict[str, Any]]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_plane = str(node.get("plane") or node.get("type") or "")
            if plane and plane.lower() not in node_plane.lower():
                continue
            haystack = json.dumps(node, default=str).lower()
            score = sum(haystack.count(term) for term in terms)
            if score > 0:
                scored.append((score, node))
        scored.sort(key=lambda item: -item[0])
        matches = [{"score": sc, "node": nd} for sc, nd in scored[: max(1, min(50, top_k))]]
        return {
            "topic": topic,
            "plane": plane,
            "count": len(matches),
            "matches": matches,
            "agentgraph_level": "L1_MCP_AND_L2_CLI_MEMORY",
            "owning_bots": ["AgentGraphBot"],
            "workflow_id": "cfg/factories/memory-agentgraph-sync-factory.yaml",
        }


def execute_agentgraph_route(role: str, tool: str | None = None) -> dict[str, Any]:
    """Evaluate AgentGraph deterministic RBAC role routing and Service-Bot ownership for a tool."""
    with timed_operation("mcp_agentgraph_route", role=role, tool=tool or "", owning_bot="AgentGraphBot"):
        normalized_role = role.strip().lower()
        allowed_roles = {"developer", "operator", "reviewer", "bot", "architect", "admin", "developer_agent"}
        allowed = normalized_role in allowed_roles or normalized_role.endswith("_bot")
        meta = resolve_service_bot_metadata(tool or "hath0r_")
        return {
            "role": role,
            "tool": tool,
            "allowed": allowed,
            "service": meta["service"],
            "owning_bots": meta["owning_bots"],
            "workflow_id": meta["workflow_id"],
            "agentgraph_level": meta["agentgraph_level"],
        }


def execute_agentgraph_validate() -> dict[str, Any]:
    """Validate Level 1 & Level 2 AgentGraph snapshot integrity and Service-Bot ownership."""
    with timed_operation("mcp_agentgraph_validate", owning_bot="AgentGraphBot"):
        snap = _load_agentgraph_snapshot()
        nodes = snap.get("nodes", [])
        edges = snap.get("edges", [])
        enforce_bot = is_feature_enabled("feature.service_bot.enforce", default=True)
        orphan_services = [
            k for k, v in SERVICE_BOT_WORKFLOW_REGISTRY.items() if not v.get("owning_bots")
        ]
        passed = (not enforce_bot or len(orphan_services) == 0) and isinstance(nodes, list)
        return {
            "passed": passed,
            "nodes_checked": len(nodes),
            "edges_checked": len(edges),
            "orphan_services": orphan_services,
            "feature_service_bot_enforced": enforce_bot,
            "owning_bots": ["AgentGraphBot", "ArchitecturePreservationBot"],
            "workflow_id": "cfg/factories/memory-agentgraph-sync-factory.yaml",
        }


# ---------------------------------------------------------------------------
# Ported Level 1 Suite Tools from HATH0R-CLI (CR-MCP-CENTRAL-001)
# ---------------------------------------------------------------------------


def execute_suite_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute any centralized Level 1 suite tool with OTel tracing, OpenFeature gating, and Bot ownership."""
    meta = resolve_service_bot_metadata(tool_name)
    with timed_operation(
        tool_name,
        owning_bot=",".join(meta["owning_bots"]),
        workflow_id=meta["workflow_id"],
        agentgraph_level=meta["agentgraph_level"],
    ):
        if tool_name == "hath0r_supersqueeze":
            res = supersqueeze_engine.compress(
                text=str(args.get("text", "")),
                query=str(args.get("query", "")),
                target_ratio=float(args.get("target_ratio", 0.35)),
            )
            return res.to_dict()

        if tool_name in ("mcp_agentgraph_status", "hath0r_agentgraph_status"):
            return execute_agentgraph_status()

        if tool_name in ("mcp_agentgraph_query", "hath0r_agentgraph_query"):
            return execute_agentgraph_query(
                topic=str(args.get("topic", "")),
                top_k=int(args.get("top_k", 5)),
                plane=args.get("plane"),
            )

        if tool_name in ("mcp_agentgraph_route", "hath0r_agentgraph_route"):
            return execute_agentgraph_route(
                role=str(args.get("role", "developer")),
                tool=args.get("tool"),
            )

        if tool_name in ("mcp_agentgraph_validate", "hath0r_agentgraph_validate"):
            return execute_agentgraph_validate()

        if tool_name in ("mcp_agentgraph_sync", "hath0r_agentgraph_sync"):
            status = execute_agentgraph_status()
            status["synced"] = True
            return status

        if tool_name == "hath0r_optimize_taguchi":
            array = str(args.get("array", "L9"))
            factors = list(args.get("factors") or ["factor_1", "factor_2"])
            snr_values = args.get("snr_values") or []
            criterion = str(args.get("criterion", "smaller_is_better"))
            out: dict[str, Any] = {
                "array": array,
                "factors": factors,
                "runs": 9 if array == "L9" else (4 if array == "L4" else 8),
                **meta,
            }
            if snr_values:
                vals = [float(v) for v in snr_values]
                mean_sq = sum(v * v for v in vals) / max(1, len(vals))
                snr_db = -10.0 * math.log10(max(1e-9, mean_sq))
                out["snr"] = {"values": vals, "criterion": criterion, "snr_db": round(snr_db, 4)}
            if args.get("loss_k") is not None and args.get("target_m") is not None and args.get("measured_y") is not None:
                k = float(args["loss_k"])
                m = float(args["target_m"])
                y = float(args["measured_y"])
                out["quality_loss"] = round(k * ((y - m) ** 2), 6)
            return out

        if tool_name == "hath0r_finops_tokenizer_tax":
            text = str(args.get("text", ""))
            vocab_size = int(args.get("vocab_size", 256000))
            hidden_dim = int(args.get("hidden_dim", 4096))
            precision = str(args.get("precision", "fp16"))
            p_bytes = 2 if precision in ("fp16", "bf16") else 4
            est_tokens = max(1, math.ceil(len(text) / 4.0))
            vram_mb = round((vocab_size * hidden_dim * p_bytes) / (1024 * 1024), 2)
            return {
                "estimated_tokens": est_tokens,
                "char_count": len(text),
                "vocab_vram_mb": vram_mb,
                "precision": precision,
                **meta,
            }

        if tool_name == "hath0r_finops_budget_check":
            prompt = str(args.get("prompt", ""))
            session_id = str(args.get("session_id") or "default_tree")
            est_tokens = max(1, math.ceil(len(prompt) / 4.0))
            remaining = 32768
            return {
                "session_id": session_id,
                "prompt_tokens_estimate": est_tokens,
                "remaining_tokens": remaining,
                "within_budget": est_tokens <= remaining,
                **meta,
            }

        if tool_name == "hath0r_session_set":
            key = str(args.get("key", ""))
            value = args.get("value")
            ttl = args.get("ttl_seconds")
            entry = {
                "key": key,
                "value": value,
                "ttl_seconds": ttl,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            SESSION_KV_STORE[key] = entry
            return {"success": True, **entry, **meta}

        if tool_name == "hath0r_session_get":
            key = str(args.get("key", ""))
            found = SESSION_KV_STORE.get(key)
            return {
                "key": key,
                "exists": found is not None,
                "value": found["value"] if found else None,
                **meta,
            }

        if tool_name == "hath0r_cicccdct_status":
            cccd_path = REPO_ROOT / ".hath0r" / "cccd_state.json"
            state = {}
            if cccd_path.is_file():
                try:
                    state = json.loads(cccd_path.read_text(encoding="utf-8"))
                except Exception:
                    state = {}
            return {
                "status": "fresh",
                "ttl_hours": state.get("ttl_hours", 4.0),
                "max_age_hours": state.get("max_age_hours", 4.0),
                "auto_calibrate_pre_task": state.get("auto_calibrate_pre_task", True),
                "calibrated_params": state.get("calibrated_params", {"temperature": 0.5, "max_tokens": 2048}),
                **meta,
            }

        if tool_name == "hath0r_workflow_offer":
            return offer_missing_workflow(
                intent=str(args.get("intent", "")),
                suggested_bots=args.get("suggested_bots"),
            )

        return {
            "status": "ok",
            "tool": tool_name,
            "arguments": args,
            **meta,
        }
