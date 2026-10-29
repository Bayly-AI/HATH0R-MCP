---
name: orient
description: Standard operating procedure for repository orientation. Activates whenever the operator runs "orient", "run orient", "orient repo", "orient repository", or requests full repository orientation.
---

# Repository Orientation Standard Operating Procedure (`hath0r orient`)

This workflow executes full cognitive, security, and operational orientation when an operator triggers **"orient"**. It establishes complete context across governance rules (`AGENTS.md` / `CLAUDE.md`), agentic security posture (`CR-AGENTIC-SEC-001`), application architecture, AST symbol trees, agent performance telemetry, and runtime parameter calibration / continuous training (`CIC³DCT`).

Whenever an operator or prompt triggers **"orient"**, start with `hath0r orient` and execute the following 6 steps in exact sequence:

---

## 6-Step Orientation Procedure

### Step 1: Read the Agents, Rules, `CLAUDE.md` Sync, and MemoryGraph from AgentGraph
- Ensure `.hath0r/memory/graph.json` is initialized (`hath0r memory init`), start/read the Micro Memory Session (`hath0r memory session start --task "orient"` / `hath0r memory session read`), and synchronize `CLAUDE.md` with `AGENTS.md` (`hath0r agentgraph sync` / `hath0r agentgraph validate`).
- Extract via `hath0r agentgraph status` and `hath0r agentgraph query "rules"`:
  - **Agent Roles & PBAC**: Identify declared roles (`role:developer`, `role:reader`), permitted/forbidden tools, and PBAC clearance policies.
  - **Rules & Governance Policies**: Verify `CR-CLI-ENTRY-001`, `CR-CLAUDE-SYNC-001`, `CR-AGENTIC-SEC-001`, `CR-AGENTGRAPH-001`, `CR-MEMORY-COMPOUND-001`, `CR-CICCCDCT-001`, `CR-SEMVER-BUMP-001`, `CR-SONAR-PREANNOUNCE-001`, and `CR-TASK-EVAL-001` have zero contradictions.
  - **MemoryGraph Topology**: Tally node distributions across Knowledge, Memory, Rules, and Context planes.

### Step 2: Verify Agentic Security, Threat Model & Supply-Chain Integrity (`CR-AGENTIC-SEC-001`)
- Run the preflight security and supply-chain verification suite:
  ```bash
  hath0r skills audit
  hath0r mcp audit
  hath0r threatmodel validate
  hath0r finops tokens verify-ledger
  hath0r observe shadow-ai
  ```
- Confirm `THREATMODEL.md` is valid, 0 BITE skill/rule injection findings exist, the hash-chained token ledger is intact, and shadow AI inventory is clean.

### Step 3: Read the Project Readme & Scan Code Architecture
- Read `README.md` (and `VERSION` / `MANIFEST.json`).
- Scan the codebase (`src/`, `lib/`, `contracts/`, `tests/`) using structural code intelligence (`hath0r code outline`) to summarize primary languages, entry points, bots, and subsystem boundaries.

### Step 4: Run Agent Metrics & FinOps Telemetry
- Execute Agent Metrics inspection (`hath0r observe charts`, `hath0r pmat stats`, `hath0r finops budget check`):
  - **Observability Tracing**: Latency quantiles (P50, P90, P95, P99), request volume, token consumption, and spend (USD).
  - **PMAT Code Churn & Hotspots**: Provability score, cyclomatic complexity, and highest-risk files ranked by Composite Hotspot Risk Index ($R$).

### Step 5: Run Continuous Calibration & SFT/LoRA/PEFT Readiness (`CIC³DCT`)
- Execute Continuous Calibration (`hath0r cccd calibrate` / `hath0r cicccdct validate`):
  - Verify calibration freshness SLA ($\le 24.0\text{ hours}$) and record calibrated parameters (`temperature`, `max_tokens`, `top_p`, `retry_count`, `guardrail_threshold`).
  - Check Continuous Training (`hath0r cccd train`) SFT/LoRA/PEFT status and benchmark reward gate ($R_{\text{candidate}} \ge R_{\text{production}} + 0.02$).

### Step 6: Compound Orientation Memory & Present the Orientation Report
- Compound orientation observations (`hath0r memory session write`, `hath0r memory compound`, `hath0r memory hash --sync`) and run task evaluation (`hath0r evals run` + `hath0r memory hash --sync`).
- Present a structured orientation report covering:
  1. **AgentGraph & Rule Sync (`CLAUDE.md == AGENTS.md`)**
  2. **Security & Supply-Chain Posture (`CR-AGENTIC-SEC-001`)**
  3. **Project & Code Architecture**
  4. **Agent Metrics & PMAT Hotspots**
  5. **CIC³DCT Calibration & SFT/LoRA Status**
  6. **Eval Scorecard Summary (`CR-TASK-EVAL-001`)**
