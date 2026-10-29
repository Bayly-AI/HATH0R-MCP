# AGENTS.md — HATH0R-MCP (Hath0r MCP Server)

> HATHOR OpenSource member · Hath0r OpenSource Suite MCP service
> Updated: 2026-10-29 · fileset pin `1.3.1` · engine version `1.11.1`

## CR-CLI-ENTRY-001: Start with the CLI (CRITICAL — Org-Wide · CANONICAL)

1. **Start with the CLI (CRITICAL ENTRY GATE)**: When receiving ANY request or starting any task, agents **MUST ALWAYS START WITH THE OPERATOR CLI (`hath0r`)** rather than inventing ad-hoc scripts. Check `hath0r --help` and the matching `hath0r <group> --help` first.
2. **Missing Capability Offer**: If the required connection, MCP, workflow, bot, or factory does not exist in `hath0r`, offer to register the missing capability, using the original request as the acceptance test.
3. **Docs before code**: Require procedure/playbook/runbook before scaffolding implementation.

Canonical: [HATH0R-CLI `docs/governance/cli-first-rules.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/cli-first-rules.md).

## Identity (CRITICAL)

| Field | Value |
|---|---|
| Product | **HATH0R-MCP** (Hath0r MCP Server) |
| Product ID | `hath0r-mcp` (service alias: `hath0r-mcp`) |
| Local Path | `/Users/raybayly/Development/OpenSource/hath0r-mcp` |
| GitHub | **`Bayly-AI/HATH0R-MCP`** |
| Group Membership | **`hath0r-opensource`** (OpenSource Project member) |
| Suite Role | MCP service provider for **`Hath0r OpenSource Suite`** (`hath0r-opensource`) |
| Control Tower (Governance) | **`HATH0R-CLI`** (`Bayly-AI/HATH0R-CLI`) |
| Control Tower (Suite Infra) | **`HATH0R-ATC`** (`Bayly-AI/HATH0R-ATC`) |
| Operator CLI | **`hath0r`** |
| Hidden Root | **`.hath0r/` only** |
| Project KB | `.hath0r/knowledgebase` (stub pointing to group hub) |
| Group KB Hub | `/Users/raybayly/Development/OpenSource/.hath0r/knowledgebase` |
| Setup Playbook | `/Users/raybayly/Development/OpenSource/hathor-cli/docs/hathor-playbook-001-repo-init-setup-20260919.md` |
| Tech Runbook | [`docs/runbook.md`](docs/runbook.md) |
| Suite standards | [`docs/governance/SUITE_STANDARDS.md`](docs/governance/SUITE_STANDARDS.md) |
| Docker Group | **`hath0r`** (CANONICAL — `Hath0r Compose configuration`) |
| Docker Network | **`hath0r-net`** (CANONICAL) |
| Container / Image | `hath0r-mcp` / `hath0r/mcp:local` |
| Host / Container Port | `127.0.0.1:38083` / `8083` |
| Canonical Cloud URL | **`https://mcp.hath0r-cli.com`** |
| Project MCP priority | **1** — tower [`cfg/mcp.servers.json`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/cfg/mcp.servers.json) · local [`cfg/mcp/README.md`](cfg/mcp/README.md) |

---

## CR-CLAUDE-SYNC-001 (Mandatory `CLAUDE.md` ↔ `AGENTS.md` 1:1 Synchronization — CRITICAL · CANONICAL)
- **Exact 1:1 Mirror**: `CLAUDE.md` at the repository root MUST remain an exact byte-for-byte mirror of `AGENTS.md` so all agentic runtimes enforce identical non-conflicting rules.
- **Automated Synchronization**: `hath0r agentgraph sync`, `hath0r memory hash --sync`, and `hath0r clean-repos` automatically synchronize `CLAUDE.md` from `AGENTS.md` and track both files in `.hath0r/memory/hashes.json`.

---

## CR-AGENTIC-SEC-001 (Agentic Security, Supply-Chain & Governance Controls — CRITICAL · CANONICAL)
- **BITE Supply-Chain & Skill Integrity (`hath0r skills audit` / `hath0r mcp audit`)**: Audit all `.agents/skills/**/SKILL.md`, `CLAUDE.md`, `AGENTS.md`, `WARP.md`, and MCP tool schemas for prompt injection, hidden Unicode tag characters, reverse shells, and credential exfiltration, and pin SHA-256 digests in `.hath0r/security/mcp-schema-pins.json`.
- **PBAC & L2 Output Sanitizer (`src/knowledgebase/mcp_server.py`)**: Enforce `PBACPolicyEngine` (`clearance`, `purpose`, `sensitivity`) and `L2OutputSanitizer` canary honeytoken verification on `kb_search`, `kb_get`, and `kb_status`.
- **Cryptographic Hash-Chained Token & Tool Ledger (`hath0r finops tokens verify-ledger`)**: Every tool/completion event is recorded in `.hath0r/state/finops/token_ledger.jsonl` with a tamper-evident SHA-256 hash chain (`prev_hash` → `entry_hash`).
- **Fail-Closed `THREATMODEL.md` Gate (`hath0r threatmodel validate`) & Slopsquatting Guard**: Maintain a valid `THREATMODEL.md` in every repository and verify dependency/rule drift (`DependencyGuardBot`) during preflight.

---

## CR-MEMORY-COMPOUND-001 (Mandatory `.hath0r/memory` Repository Presence, Micro Memory Sessions, SHA-256 File Hashing, Un-Ignored Graph Folders & Pre-Announcement MemoryGraph Compounding — CANONICAL)
- **Universal `.hath0r/memory`, `.hath0r/memory/sessions` & `.hath0r/memory/hashes.json` Folder**: Maintain `.hath0r/memory/graph.json`, `.hath0r/memory/sessions/current.json`, `.hath0r/memory/sessions/latest.json`, `.hath0r/memory/hashes.json`, `core_rules.md`, and `architecture.md` (`hath0r memory init` / `hath0r memory ensure-all`).
- **True Micro Memory Session Read & Write**: Every session MUST read and write a compact (<2KB) micro memory session (`hath0r memory session start|read`, `hath0r memory session write`, `hath0r memory session end`).
- **Pre-Announcement Memory Compounding & Hashing**: Compound structured knowledge (`hath0r memory compound`), sync SHA-256 hashes (`hath0r memory hash --sync`), and verify (`hath0r memory verify`) before announcing complete.

---

## CLI-First & Missing Capability Offer (CRITICAL — `cr-cli-first-001`)

Canonical: [HATH0R-CLI `docs/governance/cli-first-rules.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/cli-first-rules.md).

1. **CLI-First**: For connections, MCP, workflows, factories, Docker group ops, KB path, or suite orientation, invoke **`hath0r`** (or the documented operator entrypoint) instead of ad-hoc scripts.
2. **Missing Capability Offer**: If a required connection/MCP/workflow/factory is missing, do not silently invent workarounds. Offer to create the missing capability and use the original request as its acceptance test.
3. **Session start**: Prefer tower checklist `docs/governance/checklists/agent-session-start.md` when present.
4. **CR-CLI-FEATURE-STANDARD-001 (Shared Code in CLI & Artifact Hexad — CRITICAL · CANONICAL)**:
   - Anything usable across multiple repos MUST live in `HATH0R-CLI`.
   - Feature packages must include CLI commands, managing bots, workflows, and the documentation hexad (Strategy, Procedure, Playbook, Runbook, Workflow, Bot Spec).
   - This repo contains declarative configuration files (`cfg/`, `otel.json`, factory YAMLs) that bind to CLI tools.
5. **Docs before code**: Follow workflow documentation standard (playbook → procedure → runbook) before scaffolding implementation — see suite standards pointers.
6. **Project MCP first**: Prefer **`hath0r-mcp` (priority 1)** from the tower MCP registry for suite knowledge/tools.

---

## Orientation & Quick Start

1. Run the Hath0r fileset bootstrap verification:
   ```bash
   ./bin/hath0r-bootstrap.sh
   ```
2. Run local tests:
   ```bash
   make test
   ```
3. Run the FastMCP service locally:
   ```bash
   make serve
   ```
4. Verify health and MCP tools:
   ```bash
   curl http://127.0.0.1:8083/health
   curl http://127.0.0.1:8083/ready
   make smoke-local
   ```

---

## CR-HATH0R-INIT-001: Hath0r Repo Initialization Gate (CRITICAL)

**Before initializing (or re-initializing) any repository with Hath0r, agents MUST:**

1. **Setup playbook**: Follow canonical playbook:
   `/Users/raybayly/Development/OpenSource/hathor-cli/docs/hathor-playbook-001-repo-init-setup-20260919.md`
2. **Same-technology runbook**: Maintain [`docs/runbook.md`](docs/runbook.md) covering install, dev, quality, test, build, deploy, rollback, and operator bootstrap.
3. **Universal Project Layout**:
   ```text
   hath0r-mcp/
     .hath0r/knowledgebase/   # stub/pointer only
     bin/hath0r-bootstrap.sh  # bootstrap verification check
     cfg/                     # product.yaml, suite.yaml, knowledge-tower.yaml
     contracts/               # pinned CLI schemas + exit codes
     MANIFEST.json            # version matrix
     VERSION                  # fileset pin
     NOTICE                   # notice file
     AGENTS.md                # this file
     CLAUDE.md                # 1:1 mirror of AGENTS.md (CR-CLAUDE-SYNC-001)
     THREATMODEL.md           # fail-closed threat model (CR-AGENTIC-SEC-001)
     docs/runbook.md          # technology operations runbook
     src/                     # application source (knowledgebase/)
     knowledgebase/canonical/ # bundled markdown knowledge corpus
     tests/                   # test suite (unit/ and api/)
     dist/                    # build output (.gitkeep)
     lib/                     # assets (.gitkeep)
   ```
4. **Hidden root rule (`cr-hath0r-root-001`)**: Use **only** `.hath0r/`. NEVER create `.ai/`, `.aegis/`, or `.infraOS/`.

## CR-SEMVER-BUMP-001 (Semantic Version Bump on Every PR — CANONICAL)
- Every pull request that is created and merged must create or bump this product's Semantic Version (`MAJOR.MINOR.PATCH`, https://semver.org). The root `VERSION` file is the source of truth; keep `VERSION`, `pyproject.toml` and `CHANGELOG.md` in step with it.
- Pick the bump by impact: MAJOR for breaking changes, MINOR for backward-compatible features, PATCH for fixes, docs, chores and everything else. `Version Impact: none` is not allowed.
- New products start at `0.1.0`.
- Declare the bump in the PR body as `Version Impact: patch|minor|major` and add a matching `CHANGELOG.md` entry. Verify with `hath0r release validate` before announcing complete.
- A PR merged without a version bump is not Complete.

---

## Hath0r Compose configuration: Docker Group Membership (CRITICAL · CANONICAL)

All services for the Hath0r OpenSource Suite belong to the `hath0r` Docker group:

| Requirement | Canonical Value |
|---|---|
| Compose project `name:` | **`hath0r`** |
| Network | external **`hath0r-net`** |
| Container name | **`hath0r-mcp`** |
| Service name | **`hath0r-mcp`** |
| Image tag | **`hath0r/mcp:local`** |
| Host publish port | **`127.0.0.1:38083`** (container: `8083`) |
| Labels | `com.hath0r.org=bayly-ai`<br>`com.hath0r.project=hath0r-opensource`<br>`com.hath0r.component=mcp`<br>`com.hath0r.container=hath0r-mcp` |
| Security | Non-root `mcp:mcp`, read-only rootfs, dropped capabilities, no-new-privileges |

---

## Branch & Promotion Governance (`cr-branch-gov-001` · `CR-BAI-001`)

1. **Issue first**: Every change must correspond to a GitHub issue (`hath0r branch start <type> <issue> <slug>`).
2. **Branch from `development` only**:
   `feature|bugfix|enhancement|research|fix|chore/<issue-number>-short-slug`
3. **Feature PRs target `development` only** (`hath0r pr create --semver <patch|minor|major>` — never direct to master/staging/testing).
4. **Canonical branches (locked)**:
   `development` (default), `testing`, `staging`, `master`
5. **Promotion path**:
   ```text
   local → development → testing → staging → master (Production)
   ```

---

## Secrets Management

Never commit secrets to git. Always use gitignored `.env` or external credentials in `/Users/raybayly/Development/.credentials/`.
In production, set `HATH0R_MCP_ENVIRONMENT=production` and `HATH0R_MCP_TOKEN` with at least 32 characters.

---

## Suite standards & observability stubs

See [`docs/governance/SUITE_STANDARDS.md`](docs/governance/SUITE_STANDARDS.md) for control-tower URLs (OTel, OpenFeature, OpenObservation, workflow docs, docker groups, SemVer).

Local stubs (identity only; policy stays in tower):

- `cfg/observability/otel.json` — `service_name: hath0r-mcp`
- `cfg/observability/openobservation.json`
- `cfg/feature-flags/openfeature.json`
- `cfg/docker/groups/README.md` — pointer to tower `hath0r` group template
- `.hath0r/audits/hathor-adopt-2026-09-24.md` — adopt audit for issue #3

## AgentGraph Substrate

This repository is governed by the Hath0r AgentGraph substrate. Dynamic rule retrieval, role RBAC, and policy graphs are stored under `.hath0r/agentgraph/`.
- Query status: `hath0r agentgraph status`
- Query rules: `hath0r agentgraph query "<topic>"`
- Route role: `hath0r agentgraph route --role <role>`
- Sync rules & `CLAUDE.md`: `hath0r agentgraph sync`
- Validate rules: `hath0r agentgraph validate`

---

## CR-SONAR-PREANNOUNCE-001 (SonarCloud Thresholds Before Announcing Complete — CANONICAL)
- **Pre-Announcement SonarCloud Gate**: Before announcing any work as Complete, the agent MUST analyze the code and confirm it meets this repository's SonarCloud Quality Gate thresholds (coverage on new code, duplication, reliability, security, maintainability, and security hotspots reviewed).
- **How to Verify**: Use `hath0r quality sonar` (project key from `sonar-project.properties`) together with local test and coverage runs. If the gate cannot be checked, state that plainly instead of announcing Complete.
- **Not Complete Until Green**: A failing or unverified Quality Gate means the work is not Complete.

---

## CR-TASK-EVAL-001 (Automatic Task Evaluation Before Announcing Complete — CRITICAL · CANONICAL)
- **Mandatory Pre-Announcement Task Evaluation Gate**: Every task MUST be evaluated across the 4-tier hybrid evaluation pipeline (Tier 1 Deterministic Rubrics, Tier 2 Trajectory & FinOps Efficiency, Tier 3 Adversarial & Diff Critics, Tier 4 Goal Alignment & Consensus) prior to announcing work as Complete.
- **Composite Reward Threshold**: Task completion requires `passed_gate: true` and composite reward score `R_task >= 0.80` persisted in `.hath0r/evals/latest.json` and compounded as an `eval:<task_id>` node in `.hath0r/memory/graph.json`.
- **How to Verify**: Run `hath0r evals run` and `hath0r evals verify` before announcing Complete (`EndOfTaskBot`, `TaskAnnouncerBot.announce_complete`, and `CleanReposWorkflowBot` enforce this gate automatically).
- **Mandatory Eval Scorecard Summary After Every Task (CRITICAL · CANONICAL)**: Immediately after running task evaluations (`hath0r evals run`), the agent MUST always return a structured summary of the **Eval Scorecard** (`eval_id`, `task_id`, `passed_gate`, composite `R_task`, Tier 1–4 scores, and `.hath0r/evals/latest.json` path) in its completion response to the user.
- **Not Complete Until Evaluated & Scorecard Returned**: A missing, failing, unverified, or unreported task evaluation scorecard means the work is not Complete.
