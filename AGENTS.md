# AGENTS.md — HATH0R-MCP (Hath0r MCP Server)

> HATHOR OpenSource member · Hath0r OpenSource Suite MCP service
> Initialized: 2026-09-23 · fileset pin `0.2.0` · engine version `1.0.1`

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
| Host / Container Port | `*********:38083` / `8083` |
| Canonical Cloud URL | **`https://mcp.hath0r-cli.com`** |
| Project MCP priority | **1** — tower [`cfg/mcp.servers.json`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/cfg/mcp.servers.json) · local [`cfg/mcp/README.md`](cfg/mcp/README.md) |

---

## CLI-First & Missing Capability Offer (CRITICAL — `cr-cli-first-001`)

Canonical: [HATH0R-CLI `docs/governance/cli-first-rules.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/cli-first-rules.md).

1. **CLI-First**: For connections, MCP, workflows, factories, Docker group ops, KB path, or suite orientation, invoke **`hath0r`** (or the documented operator entrypoint) instead of ad-hoc scripts.
2. **Missing Capability Offer**: If a required connection/MCP/workflow/factory is missing, do not silently invent workarounds. Offer to create the missing capability and use the original request as its acceptance test.
3. **Session start**: Prefer tower checklist `docs/governance/checklists/agent-session-start.md` when present.
4. **Docs before code**: Follow workflow documentation standard (playbook → procedure → runbook) before scaffolding implementation — see suite standards pointers.
5. **Project MCP first**: Prefer **`hath0r-mcp` (priority 1)** from the tower MCP registry for suite knowledge/tools.

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
     VERSION                  # fileset pin (0.2.0)
     NOTICE                   # notice file
     AGENTS.md                # this file
     docs/runbook.md          # technology operations runbook
     src/                     # application source (knowledgebase/)
     knowledgebase/canonical/ # bundled markdown knowledge corpus
     tests/                   # test suite (unit/ and api/)
     dist/                    # build output (.gitkeep)
     lib/                     # assets (.gitkeep)
   ```
4. **Hidden root rule (`cr-hath0r-root-001`)**: Use **only** `.hath0r/`. NEVER create `.ai/`, `.aegis/`, or `.infraOS/`.

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

1. **Issue first**: Every change must correspond to a GitHub issue.
2. **Branch from `development` only**:
   `feature|bugfix|enhancement|research|fix|chore/<issue-number>-short-slug`
3. **Feature PRs target `development` only** (never direct to master/staging/testing).
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
