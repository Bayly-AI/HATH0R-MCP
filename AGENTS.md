# AGENTS.md — BAI-1-NATION-MCP (1-Nation MCP Server)

> HATHOR OpenSource member · 1-Nation Suite MCP service  
> Initialized: 2026-09-23 · fileset pin `0.2.0` · engine version `1.0.1`

## Identity (CRITICAL)

| Field | Value |
|---|---|
| Product | **BAI-1-NATION-MCP** (1-Nation MCP Server) |
| Product ID | `bai-1-nation-mcp` (service alias: `1n-mcp`) |
| Local Path | `/Users/raybayly/Development/OpenSource/hath0r-mcp` |
| GitHub | **`Bayly-AI/BAI-1-NATION-MCP`** |
| Group Membership | **`hath0r-opensource`** (OpenSource Project member) |
| Suite Role | MCP service provider for **`1-Nation Suite`** (`1n-suite`) |
| Control Tower (Governance) | **`HATH0R-CLI`** (`Bayly-AI/HATH0R-CLI`) |
| Control Tower (Suite Infra) | **`1-Nation ATC`** (`Bayly-AI/1-Nation-ATC`) |
| Operator CLI | **`hath0r`** |
| Hidden Root | **`.hath0r/` only** |
| Project KB | `.hath0r/knowledgebase` (stub pointing to group hub) |
| Group KB Hub | `/Users/raybayly/Development/OpenSource/.hath0r/knowledgebase` |
| Setup Playbook | `/Users/raybayly/Development/OpenSource/hathor-cli/docs/hathor-playbook-001-repo-init-setup-20260919.md` |
| Tech Runbook | [`docs/runbook.md`](docs/runbook.md) |
| Docker Group | **`1-nation`** (CANONICAL — `CR-DOCKER-1N-GROUP-001`) |
| Docker Network | **`1-nation-net`** (CANONICAL) |
| Container / Image | `1NMCP` / `1-nation/mcp:local` |
| Host / Container Port | `127.0.0.1:58083` / `8083` |

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

## CR-DOCKER-1N-GROUP-001: Docker Group Membership (CRITICAL · CANONICAL)

All services for the 1-Nation Suite belong to the `1-nation` Docker group:

| Requirement | Canonical Value |
|---|---|
| Compose project `name:` | **`1-nation`** |
| Network | external **`1-nation-net`** |
| Container name | **`1NMCP`** |
| Service name | **`1n-mcp`** |
| Image tag | **`1-nation/mcp:local`** |
| Host publish port | **`127.0.0.1:58083`** (container: `8083`) |
| Labels | `com.1nation.org=bayly-ai`<br>`com.1nation.project=1n-suite`<br>`com.1nation.component=mcp`<br>`com.1nation.container=1NMCP` |
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
In production, set `N1_MCP_ENVIRONMENT=production` and `N1_MCP_TOKEN` with at least 32 characters.
