# HATH0R MCP-Central Architecture, SuperSqueeze & Bot Execution Plan

> **Control Tower**: `HATH0R-ATC` (`Bayly-AI/HATH0R-ATC` · Issue [#80](https://github.com/Bayly-AI/HATH0R-ATC/issues/80))  
> **Paired Governance & MCP Hub**: `HATH0R-CLI` (`Bayly-AI/HATH0R-CLI`) ⇄ `HATH0R-MCP` (`Bayly-AI/HATH0R-MCP`)  
> **Cognitive Substrate**: `HATH0R-Agentic-Framework` (`Bayly-AI/HATH0R-Agentic-Framework`)  
> **Date**: 2026-10-31 · **Rules**: `CR-CLI-ENTRY-001` · `CR-CLI-MCP-ECOSYSTEM-001` · `CR-SUBSTRATE-001` · `CR-MEMORY-COMPOUND-001` · `CR-TASK-EVAL-001` · `CR-SEMVER-BUMP-001`

---

## 1. Executive Summary & Architectural Directive

To maximize technology utilization across the Hath0r OpenSource Suite and guarantee that every task is **finished, completed, and accurate**, the suite architecture is unified around seven core invariants:

0. **Canonical Feature Definition & Workflow-First Standard (`CR-FEATURE-WORKFLOW-STANDARD-001`)**:
   - **Every Feature Is a Service Run by `>= 1` Bot**: Every feature in the Hath0r ecosystem is a service owned and executed by **at least one Bot** (`src/hath0r_cli/bots/`, registered in `BotRegistry`). Zero orphan commands or scripts.
   - **2-Level Tool, Knowledge & Memory Hierarchy (All Utilizing `AgentGraph`)**:
     - **Level 1 (`HATH0R-MCP` — `hath0r-mcp`)**: All shared tools, declarative workflows, factories, and canonical knowledge reside on the **MCP (Level 1)** (`http://127.0.0.1:38083` / `http://localhost:38000/mcp/`), governed, routed, and validated through **`AgentGraph`** (`.hath0r/agentgraph/`).
     - **Level 2 (`HATH0R-CLI` or Bot Memory — `.hath0r/memory/`)**: The Operator/Agent CLI (`hath0r`) and Bot Micro-Memory / `MemoryGraph` (`.hath0r/memory/graph.json`, `.hath0r/memory/sessions/`) reside at **Level 2**, synchronized and routed through **`AgentGraph`** (`hath0r agentgraph query|route|sync|validate`).
   - **Workflow-First Standard (`Everything We Do Is a Workflow`)**: Every agent or operator action MUST execute as a declarative workflow (`HATH0R-MCP` workflow tool / `cfg/factories/*.yaml` / `.hath0r/workflows/*.yaml`). **If a workflow does not exist for what we are doing, the agent MUST STOP and offer to create the workflow first** (using the original request as the acceptance test of that workflow), governed by OpenFeature flags `workflow.first.strict_offer` and `feature.service_bot.enforce`.
1. **HATH0R-MCP as the Single Central Hub (`Level 1 · Priority 1`)**:
   - All shared tools, declarative workflows (`cfg/factories/*.yaml`), `BotRegistry` dispatches, Quad-Graph queries (`KnowledgeGraph`, `ContextGraph`, `MemoryGraph`, `RulesGraph`), and **SuperSqueeze** (`SuperCompressBot`) compression pipelines reside centrally in **`HATH0R-MCP`** (`http://127.0.0.1:38083` / `https://mcp.hath0r-cli.com`).
   - **`HATH0R-CLI` (`hath0r`)** remains the mandatory operator and agent entry gate (`CR-CLI-ENTRY-001`), dispatching commands and workflows through `HATH0R-MCP` (`Priority 1`) with deterministic local fallback when offline.
2. **Strict 4-Stage Iteration Cascade (`Task → Hath0r-CLI ⇄ Hath0r-MCP → Computer → Web`)**:
   - **Stage 1 (`Task`)**: Check active micro-memory session (`< 2KB`), active `TaskExecutionDAG`, settled facts (`FactSettlementEngine`), and pre-warmed CAG context first.
   - **Stage 2 (`Hath0r-CLI ⇄ Hath0r-MCP`)**: Invoke `hath0r` CLI subcommands, which route tool, workflow, bot, and knowledge operations to `HATH0R-MCP` (`Priority 1`). Every MCP response passes through `PBACPolicyEngine` → `L2OutputSanitizer` → **SuperSqueeze (`SuperCompressBot`)** → `KVCachePrewarmer` 16-token block alignment.
   - **Stage 3 (`Computer`)**: Execute bounded local file line-slices, AST outlines, sandboxed commands (`LocalSandboxProvider` / `WasmSandbox`), `hath0r` Docker group containers, or offline `DeepSeek-R1` (`LocalModelBot`).
   - **Stage 4 (`Web`)**: Query external web/APIs/Playwright only as the final escalation tier, and immediately **SuperSqueeze + L2-sanitize + compound** discovered facts back into `HATH0R-MCP` (`kb_upsert_document`) and `.hath0r/memory/graph.json` so subsequent iterations resolve at Stage 1 or Stage 2.
3. **Mandatory OpenFeature, OpenObserve (`OpenObservation`) & OpenTelemetry (`OTel`) Core Adherence**:
   - **OpenFeature (`cfg/feature-flags/openfeature.json` & `catalog.example.json`)**: Every runtime toggle, MCP workflow route, SuperSqueeze compression stage, and bot gate MUST evaluate through an OpenFeature-compatible client (`mcp.supersqueeze.enabled`, `mcp.workflows.central_dispatch`, `iteration.cascade.strict_mode`, `bots.architecture_preservation.enforce`) with `evaluation_context` (`targetingKey`, `environment`, `product`, `service.name`) and safe-for-production defaults. No ad-hoc `if os.getenv(...)` sprawl.
   - **OpenTelemetry (`cfg/observability/otel.json`)**: Every MCP tool call, CLI command, workflow step, and bot dispatch MUST emit OTLP/OpenInference spans (`AGENT | LLM | TOOL | RETRIEVER | GUARDRAIL`) with required resource attributes (`service.name`, `service.namespace="hath0r-opensource"`, `deployment.environment`, `service.version`) and OpenFeature correlation attributes (`feature_flag.key`, `feature_flag.variant`). Legacy `ddtrace` in `hath0r-mcp/src/knowledgebase/core/observability.py` is replaced by canonical OTel.
   - **OpenObserve / OpenObservation (`cfg/observability/openobservation.json`)**: Every service tracks the 4 Golden Signals (`latency`, `traffic`, `errors`, `saturation`), suite SLIs (`mcp.health.success_rate >= 0.99`, `mcp.tool.error_rate < 0.05`, `factory.step.abort_rate < 0.10`, `supersqueeze.token_savings_ratio >= 0.35`, `iteration.cascade.adherence_rate >= 0.95`), and event classes (`security`, `governance`, `ops`, `product`), spooling non-blockingly (`never_block: true`, `never_secrets: true`) to `.hath0r/spool/telemetry-*.jsonl` when collectors (`http://localhost:38000/phoenix` / `http://Hath0r-phoenix:6006`) are offline.
4. **Full `hath0r-net` Network Utilization (`Hath0r-phoenix`, `Hathor-MLFLOW`, `Hath0r-Cruise-Control`, `Hath0r-MCP`, `Hath0r-Edge`)**:
   - All suite containers communicate over **`hath0r-net`** (`172.23.0.0/16`) behind **`Hath0r-Edge`** (`http://localhost:38000`):
     - **Arize Phoenix (`Hath0r-phoenix`, `172.23.0.8`, host `:36006`/`:34317`/`:34318`, edge `http://localhost:38000/phoenix`)**: Ingests OTLP/OpenInference spans (`/v1/traces`, `/v1/metrics`) from `HATH0R-CLI`, `HATH0R-MCP`, `Hath0r-Cruise-Control`, and `TaskEvaluatorBot` (`hath0r.eval.task`). Fixes legacy 1-Nation `localhost:58000/phoenix` port drift across all 5 repos' `cfg/observability/otel.json`.
     - **MLflow (`Hathor-MLFLOW`, `172.23.0.4`, host `:35000`, edge `http://localhost:38000/mlflow/`)**: Tracks every 4-Tier Task Evaluation run (`hath0r-task-evals`), CCCD calibration (`cccd-calibration`), and prompt calibration (`hath0r-prompt-calibration`) with `SuperSqueeze` compression metrics, `IterationCascade` telemetry, OpenFeature flag variants, and cross-linked `phoenix.trace_id` tags.
     - **Cruise Control (`Hath0r-Cruise-Control`, `172.23.0.3`, host `:38090`, edge `http://localhost:38000/cruise/radar` & `/api/decisions`)**: Serves as the live Agent Decision Control Layer & Unblocking Engine (`DecisionRadarBot`), enforcing bidirectional Input/Output work boundary gates (`approve-in`, `approve-out`), transitive unblocking impact (`U(d)`), and event-driven `FactSettlementEngine` probes (`eval.gate.passed:<task_id>`, `mlflow.run.logged:<task_id>`, `phoenix.trace.verified:<trace_id>`).
5. **Automated 4-Hour Agent Calibration TTL & Pre-Task Auto-Calibration (`CR-CCCD-CALIBRATE-4H-001`)**:
   - **4-Hour Calibration Expiry (`max_age_hours = 4.0`)**: Replaces the legacy 24-hour passive warning in `CCCDCalibrationLoop` (`src/hath0r_cli/cccd/calibration_loop.py`), `CICCCDManagingBot` (`src/hath0r_cli/bots/cicccd_bot.py`), and `cli.py` (`_check_cccd_freshness_gate`) with a strict **4.0-hour (`14,400s`) TTL** stored in `.hath0r/cccd_state.json` (`ttl_hours: 4.0`, `auto_calibrate_pre_task: true`), governed by OpenFeature flags `cccd.auto_calibrate.pre_task_enabled` (`true`) and `cccd.auto_calibrate.ttl_hours` (`4.0`).
   - **Automatic Pre-Task Execution (`CCCDCalibrationLoop.ensure_calibrated(max_age_hours=4.0)`)**: Whenever the 4-hour calibration window expires (`age_hours > 4.0` or never run), starting any task or session (`hath0r task start`, `start-of-task-factory.yaml`, `hath0r memory session start`, `hath0r orient`, `IterationCascadeBot` Stage 1 `Task`, or `HATH0R-MCP` `mcp_cccd_ensure_calibrated`) **automatically runs `CCCDCalibrationLoop.run_calibration()` prior to executing the task**:
     1. Compiles DSPy signatures (`DSPyCompilerBridge`) and applies Princeton `L2WS` warm-start parameters (`.hath0r/l2ws_warmstarts.json`).
     2. Executes Taguchi L9 Orthogonal Array parameter optimization (`TaguchiLossOptimizer` for `temperature`, `top_p`, `guardrail_threshold`).
     3. Logs the calibration run (`mean_snr_db`, `quality_loss`, `accuracy_drift`, `latency_drift_ms`) to **`Hathor-MLFLOW`** (`cccd-calibration` experiment, ID `4`) and emits an OTel calibration span to **`Hath0r-phoenix`**.
     4. Asserts the declarative fact `cccd.calibration.fresh:4h` in **`Hath0r-Cruise-Control`** (`FactSettlementEngine`) so input work boundary gates (`approve-in`) auto-settle.
6. **Mandatory Per-Issue Test + 4-Tier Eval + SemVer + PR Gate**:
   - Every issue in the roadmap MUST execute the full verification lifecycle (4h Auto-Calibration Gate + Unit/Integration Tests + MemoryGraph Compounding + 4-Tier Task Evaluation with `R_task >= 0.80` synced to `Hath0r-phoenix` & `Hathor-MLFLOW` + Cruise Control Settlement + SemVer Bump + PR to `development` + SonarCloud Quality Gate) before advancing to the next issue.

---

## 2. Cross-Repository GitHub Issue Matrix

| Order | Repository | Issue | Title & Scope (with `CR-FEATURE-WORKFLOW-STANDARD-001` + Level 1/2 `AgentGraph` + Workflow-First + OpenFeature/OpenObserve/OTel + Phoenix/MLflow/Cruise Control + 4h Auto-Calibration + Continuous Evals) |
|---|---|---|---|
| **1** | `Bayly-AI/HATH0R-MCP` | [#85](https://github.com/Bayly-AI/HATH0R-MCP/issues/85) | **`feat(mcp): centralize Level 1 suite tools & knowledge on AgentGraph, SuperSqueeze middleware, and OTel/OpenObserve/OpenFeature in HATH0R-MCP`**: Port 28+ CLI-trapped MCP tools to Level 1 `HATH0R-MCP` on `AgentGraph` with `x-hath0r-owning-bot` (`>= 1` Bot in `BotRegistry`) and `x-hath0r-workflow-id`, expose `hath0r_supersqueeze` gated by OpenFeature (`mcp.supersqueeze.enabled`), replace `ddtrace` with OpenTelemetry exporting to `Hath0r-phoenix` (`http://localhost:38000/phoenix`) + OpenObservation `.hath0r/spool`, and purge `infraos_*`. |
| **2** | `Bayly-AI/HATH0R-MCP` | [#86](https://github.com/Bayly-AI/HATH0R-MCP/issues/86) | **`feat(mcp): expose Workflow-First engine, missing-workflow offer, BotRegistry dispatch, Level 1/2 AgentGraph & MemoryGraph sync, 4h calibration, and Phoenix/MLflow/Cruise Control tools in HATH0R-MCP`**: Expose `mcp_workflow_match|run|scaffold` (Missing-Workflow Offer using the request as acceptance test), `mcp_bot_list|invoke|health` (Feature = Service `>= 1` Bot), `mcp_memory_*` & `mcp_agentgraph_*` (Level 1 ↔ Level 2 bridge), `mcp_cccd_ensure_calibrated(max_age_hours=4.0)`, `mcp_cruise_*`, `mcp_mlflow_*`, and `mcp_phoenix_*`. |
| **3** | `Bayly-AI/HATH0R-CLI` | [#551](https://github.com/Bayly-AI/HATH0R-CLI/issues/551) | **`feat(bots): register all 69 bots as feature service owners in BotRegistry, enforce 4-hour pre-task auto-calibration, and wire SuperSqueeze across Level 1/2 AgentGraph`**: Register all 69 bots in `step_runner.py` with `SERVICE_BOT_MAP` (`bot:*` → `service:*` edges in `AgentGraph`), upgrade `CCCDCalibrationLoop` (`max_age_hours=4.0` + `ensure_calibrated(max_age_hours=4.0)`) in `cli.py` / `task.py` / `start-of-task-factory.yaml`, fix `otel.json` (`38000/phoenix`), and wire `SuperSqueezeBot`. |
| **4** | `Bayly-AI/HATH0R-CLI` | [#552](https://github.com/Bayly-AI/HATH0R-CLI/issues/552) | **`feat(mcp): implement MCPCentralizationBot & MCPWorkflowEngineBot, enforce Workflow-First missing-workflow offer, and bridge Level 1 (HATH0R-MCP) & Level 2 (HATH0R-CLI/Memory) on AgentGraph`**: Route CLI commands through Level 1 `HATH0R-MCP` (`Priority 1`), implement `hath0r workflow offer` (`mcp_workflow_scaffold`) for unmapped requests, propagate W3C `traceparent` + `feature_flag.*` into `Hath0r-phoenix`, and sync boundaries with `Hath0r-Cruise-Control`. |
| **5** | `Bayly-AI/HATH0R-CLI` | [#553](https://github.com/Bayly-AI/HATH0R-CLI/issues/553) | **`feat(bots): implement IterationCascadeBot to enforce Workflow-First Stage 1 (Task + 4h Calibration) -> Stage 2 (Level 1 MCP + Level 2 CLI/Memory on AgentGraph) -> Stage 3 (Computer) -> Stage 4 (Web)`**: Enforce 4-stage cascade where Stage 1 verifies Workflow-First binding (`CR-FEATURE-WORKFLOW-STANDARD-001`), 4-hour calibration freshness (`ensure_calibrated(max_age_hours=4.0)`), and Cruise Control settled facts before Stage 2 (`Level 1 MCP` ⇄ `Level 2 CLI/Memory` on `AgentGraph`). |
| **6** | `Bayly-AI/HATH0R-CLI` | [#554](https://github.com/Bayly-AI/HATH0R-CLI/issues/554) | **`feat(bots): implement ArchitecturePreservationBot, SubstrateUtilizationBot & TaskCompletionVerifierBot to enforce CR-FEATURE-WORKFLOW-STANDARD-001 across all 5 repos`**: Audit Feature=Service (`>= 1` Bot), Level 1/2 `AgentGraph` parity, Workflow-First coverage, `otel.json` (`http://localhost:38000/phoenix`), `openobservation.json`, `openfeature.json`, and `.hath0r/cccd_state.json` (`ttl_hours: 4.0`) across all 5 repos, plus `FactSettlementEngine` probes (`cccd.calibration.fresh:4h`, `workflow.first.verified`, `eval.gate.passed`). |
| **7** | `Bayly-AI/HATH0R-CLI` | [#555](https://github.com/Bayly-AI/HATH0R-CLI/issues/555) | **`feat(evals): replace binary 1.00 score inflation in TaskEvaluatorBot with continuous Taguchi, FinOps, AST diff, Workflow-First, Level 1/2 AgentGraph, and semantic goal-alignment grading`**: Upgrade all 4 evaluation tiers (`_evaluate_tier1_deterministic`, `_evaluate_tier2_trajectory`, `_evaluate_tier3_adversarial`, `_evaluate_tier4_goal_alignment`) so `hath0r evals run` produces real continuous scores (`0.80 <= R_task < 1.00`) logged to `Hathor-MLFLOW` and `Hath0r-phoenix`. |
| **8** | `Bayly-AI/HATH0R-Agentic-Framework` | [#313](https://github.com/Bayly-AI/HATH0R-Agentic-Framework/issues/313) | **`feat(engine): add Workflow-First & Service-Bot contracts (CR-FEATURE-WORKFLOW-STANDARD-001), Level 1/2 AgentGraph routing, 4h CalibrationGateStage, SuperSqueezeStage, and IterationCascade to hath0r-framework`**: Add `WorkflowFirstGateStage`, `CalibrationGateStage` (`max_age_hours=4.0`), `SuperSqueezeStage`, and `IterationCascadeContract` to `src/hathor/engine/pipeline.py`, and align `otel.json` (`http://localhost:38000/phoenix`). |
| **9** | `Bayly-AI/HATH0R-ATC` | [#80](https://github.com/Bayly-AI/HATH0R-ATC/issues/80) | **`docs(architecture): codify CR-FEATURE-WORKFLOW-STANDARD-001, Level 1/2 AgentGraph topology, 4h auto-calibration, continuous evals, and hath0r-net Phoenix/MLflow/Cruise Control in HATH0R-ATC`**: Update `AGENTS.md`, `CLAUDE.md`, `otel.json`, `openobservation.json`, `catalog.example.json`, `docker-compose.yml`, and `.hath0r/cccd_state.json`, validate `make smoke` (24/24 PASS), `pytest` (12/12 PASS), and continuous 4-tier evals, and update PR [#81](https://github.com/Bayly-AI/HATH0R-ATC/pull/81). |

---

## 3. Architecture-Preserving Bots Specification

1. **`MCPCentralizationBot` (`mcp-centralization-bot`)**: Audits tool, workflow, and schema parity between `HATH0R-CLI` (Level 2) and `HATH0R-MCP` (Level 1), ensures Level 1 tools/knowledge and Level 2 CLI/Bot Memory both utilize **`AgentGraph`**, prunes verbose JSON schemas via `SchemaPruner`, and pins SHA-256 digests via `BITEVerifierBot` (`hath0r mcp audit`).
2. **`MCPWorkflowEngineBot` (`mcp-workflow-engine-bot`)**: Enforces the **Workflow-First Standard (`CR-FEATURE-WORKFLOW-STANDARD-001` — "Everything We Do Is a Workflow")**: resolves every task to a registered workflow in `HATH0R-MCP` (Level 1) or `HATH0R-CLI` `cfg/factories/*.yaml` (Level 2); if no workflow matches, halts ad-hoc execution and offers to scaffold and register a new workflow (`mcp_workflow_scaffold` / `hath0r factory init`) using the request as its acceptance test. Propagates W3C OpenTelemetry trace context (`traceparent`) across CLI → MCP calls and gates central dispatch via OpenFeature (`mcp.workflows.central_dispatch`, `workflow.first.strict_offer`).
3. **`SuperSqueezeBot` (`supersqueeze-bot` / `supercompress-bot`)**: Applies query-aware semantic context compression across `HATH0R-MCP` tool outputs, `CAGEngine.pack_context()`, `HybridCAGRAGRouter.rag_search()`, and `HAHPEnvelope` handoffs (gated by OpenFeature `mcp.supersqueeze.enabled`) and records OpenObservation SLI `supersqueeze.token_savings_ratio`.
4. **`IterationCascadeBot` (`iteration-cascade-bot`)**: Enforces the `Task → Hath0r-CLI (⇄ Hath0r-MCP) → Computer → Web` execution order, verifies at Stage 1 (`Task`) that a canonical workflow exists (`CR-FEATURE-WORKFLOW-STANDARD-001`) and 4-hour agent calibration is fresh, queries Level 1 (`HATH0R-MCP`) and Level 2 (`HATH0R-CLI` / Bot Memory) via `AgentGraph` at Stage 2, tags OTel spans with `hath0r.cascade.stage`, and records OpenObservation SLIs `iteration.cascade.adherence_rate` and `workflow.first.coverage_rate`.
5. **`ArchitecturePreservationBot` (`architecture-preservation-bot`)**: Enforces **`CR-FEATURE-WORKFLOW-STANDARD-001` (every Feature is a Service run by `>= 1` registered Bot in `BotRegistry`, with Level 1 Tools/Knowledge on `HATH0R-MCP` and Level 2 CLI/Bot Memory on `HATH0R-CLI` / `.hath0r/memory/` all utilizing `AgentGraph`)**, `CR-CLI-FEATURE-STANDARD-001` (zero code duplication in member repos), 100% `BotRegistry` registration coverage, control-tower role separation, `.hath0r/` hidden root (`cr-hath0r-root-001`), `.hath0r/mcp.json` Priority 1 config, and **mandatory presence and schema validity of `cfg/observability/otel.json`, `cfg/observability/openobservation.json`, and `cfg/feature-flags/openfeature.json` across every repository**.
6. **`SubstrateUtilizationBot` (`substrate-utilization-bot`)**: Enforces `CR-SUBSTRATE-001`, `CR-CLI-AGENT-SUBSTRATE-002`, and **OpenFeature / OpenObserve / OpenTelemetry runtime compliance**: AST audit verifying `GuardrailsManager`, `AIGatewayClient`/`TieredRouter`, `PBACPolicyEngine`, `L2OutputSanitizer`, `KVCachePrewarmer`, `OTELTracerBot` (`feature_flag.*` span attributes), OpenFeature client usage (flagging raw `os.getenv` feature toggles or legacy `ddtrace`), and non-blocking `.hath0r/spool/` telemetry.
7. **`TaskCompletionVerifierBot` (`task-completion-verifier-bot`)**: Hard pre-merge gate verifying all `TaskExecutionDAG` nodes are `COMPLETED`, zero `CruiseControlBot` blockers remain open, knowledge is synced to `HATH0R-MCP`, OpenObservation SLIs are within target bounds, `CLAUDE.md == AGENTS.md`, `THREATMODEL.md` is valid, SemVer is bumped, SonarCloud is green, and `R_task >= 0.80`.

---

## 4. `hath0r-net` Network Topology: Arize Phoenix, MLflow & Cruise Control

All infrastructure and observability services in the Hath0r OpenSource Suite run on the canonical **`hath0r-net`** Docker network (`172.23.0.0/16`, compose project `hath0r`, `CR-DOCKER-HATH0R-GROUP-001`) behind **`Hath0r-Edge`** (`http://localhost:38000`):

| Container | DNS Aliases on `hath0r-net` | Host Port → Container Port | Edge Gateway Route (`Hath0r-Edge` `:38000`) | Architectural Role in the Execution Plan |
|---|---|---|---|---|
| **`Hath0r-Edge`** | `Hath0r-Edge`, `hath0r-nginx`, `nginx`, `h0-nginx` (`172.23.0.2`) | `0.0.0.0:38000 -> 80/tcp` | `/healthz`, `/mcp/`, `/phoenix/`, `/v1/traces`, `/v1/metrics`, `/otlp/`, `/mlflow/`, `/cruise/`, `/api/decisions` | Unified reverse proxy & OTLP/API gateway for host CLI and external tools |
| **`Hath0r-phoenix`** | `Hath0r-phoenix`, `hath0r-phoenix`, `phoenix`, `h0-phoenix` (`172.23.0.8`) | `36006 -> 6006/tcp`<br>`34317 -> 4317/tcp` (gRPC)<br>`34318 -> 4318/tcp` (HTTP) | `http://localhost:38000/phoenix/`<br>`http://localhost:38000/v1/traces` | **Arize Phoenix OTel & OpenInference Collector**: Receives distributed traces (`AGENT`, `LLM`, `TOOL`, `RETRIEVER`, `GUARDRAIL`, `EVALUATOR`), `feature_flag.*` attributes, and `SuperSqueeze` token-saving spans |
| **`Hathor-MLFLOW`** | `Hathor-MLFLOW`, `hath0r-mlflow`, `mlflow`, `h0-mlflow` (`172.23.0.4`) | `35000 -> 5000/tcp` | `http://localhost:38000/mlflow/` | **MLOps Experiment Tracking & Model Registry**: Persists 4-Tier Task Evaluations (`hath0r-task-evals`), CCCD calibration (`cccd-calibration`), and prompt calibration (`hath0r-prompt-calibration`) with cross-linked `phoenix.trace_id` tags |
| **`Hath0r-Cruise-Control`** | `Hath0r-Cruise-Control`, `hath0r-cruise-control`, `cruise-control`, `h0-cruise` (`172.23.0.3`) | `38090 -> 8090/tcp` | `http://localhost:38000/cruise/radar`<br>`http://localhost:38000/api/decisions` | **Agent Decision Control Layer & Unblocking Engine (`DecisionRadarBot`)**: Manages the 7 canonical decision wedges, transitive unblocking impact (`U(d)`), bidirectional Input/Output work boundary gates (`approve-in`, `approve-out`), and event-driven `FactSettlementEngine` |
| **`Hath0r-MCP`** | `Hath0r-MCP`, `hath0r-mcp`, `mcp` (`172.23.0.7`) | `127.0.0.1:38083 -> 8083/tcp` | `http://localhost:38000/mcp/` | **Central Suite MCP Hub (`Priority 1`)**: Centralizes all suite tools, workflows, factories, `BotRegistry` dispatch, `SuperSqueeze` middleware, and bridges to `Hath0r-phoenix`, `Hathor-MLFLOW`, and `Hath0r-Cruise-Control` over `hath0r-net` |
| **`Hath0r-Sessions`** | `Hath0r-Sessions`, `hath0r-redis`, `redis`, `h0-redis` (`172.23.0.5`) | internal `6379/tcp` | internal `hath0r-net` | Shared Redis session & cache state |
| **`Hath0r-Data`** | `Hath0r-Data`, `hath0r-postgres`, `postgres`, `h0-postgres` (`172.23.0.6`) | `35432 -> 5432/tcp` | internal `hath0r-net` | Canonical PostgreSQL persistence |

---

## 5. Mandatory Per-Issue Execution Protocol (Tests + Evals + Phoenix + MLflow + Cruise Control + PR)

Every issue above MUST be executed using the canonical CLI lifecycle:

```bash
# 1. Start work branch, auto-run 4-hour CCCD calibration if expired, & sync Cruise Control decisions
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:38000/phoenix"
hath0r cccd status # Auto-triggers `hath0r cccd calibrate` via `ensure_calibrated(max_age_hours=4.0)` when >4h expired
hath0r task start --issue <ISSUE_NUMBER> --slug <SHORT_SLUG> --prefix feature
hath0r cruise sync

# 2. Verify hath0r-net Phoenix, MLflow & Cruise Control health
hath0r observe status
hath0r mlflow status
hath0r cruise status

# 3. Author Governance Documentation Hexad + Implementation + Unit/Integration Tests
pytest -q

# 4. Compound MemoryGraph & synchronize SHA-256 file hashes (CR-MEMORY-COMPOUND-001)
hath0r memory session read
hath0r memory session write --summary "<SUMMARY>" --kind finding
hath0r memory compound --id "episode:issue-<ISSUE_NUMBER>" --type episode --label "<LABEL>" --content "<CONTENT>"
hath0r memory session end --summary "Completed Issue #<ISSUE_NUMBER>"
hath0r memory hash --sync
hath0r memory verify

# 5. Run & verify 4-Tier Hybrid Task Evaluation Gate (CR-TASK-EVAL-001: R_task >= 0.80)
#    Automatically emits OTel EVALUATOR span to Hath0r-phoenix and logs run to Hathor-MLFLOW (hath0r-task-evals)
hath0r evals run --task-id "issue-<ISSUE_NUMBER>"
hath0r memory hash --sync
hath0r evals verify

# 6. Settle Cruise Control facts & boundary gates
hath0r cruise settle

# 7. Bump SemVer (VERSION, pyproject.toml, CHANGELOG.md) & validate (CR-SEMVER-BUMP-001)
hath0r release validate

# 8. Check SonarCloud & preflight gates (CR-SONAR-PREANNOUNCE-001)
hath0r quality sonar

# 9. Open Pull Request targeting development & monitor checks (CR-BRANCH-GOV-001)
hath0r pr create --semver minor
```
