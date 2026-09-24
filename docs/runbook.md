# Runbook: HATH0R-MCP Service

> Canonical operations and developer runbook for **HATH0R-MCP** (`hath0r-mcp` / `hath0r-mcp`).
> Satisfies Hath0r initialization gate requirement **CR-HATH0R-INIT-001**.

---

## 1. Overview & Architecture

`HATH0R-MCP` is the knowledge Model Context Protocol (MCP) server for the Hath0r OpenSource Suite, hosted as an OpenSource Project member under `OpenSource/hath0r-mcp`.

Key capabilities:
- **FastMCP Transport**: Exposes stateless Streamable HTTP at `/mcp` via the official `mcp` Python SDK.
- **Suite Tools**:
  - `suite_info`: Returns canonical Hath0r OpenSource Suite identity and loaded document catalog.
  - `kb_search(query, limit=5)`: Deterministic lexical word match search against canonical reference documents.
  - `kb_get_document(document_id)`: Exact document retrieval by identifier.
- **Knowledge Engine**: Preserves the complete hybrid search (dense embeddings + BM25 keyword matching), chunking, storage adapters, runbooks engine, and legacy REST/SSE API (`/mcp/sse`).
- **Health Probes**: Liveness `/health`, Readiness `/ready` (verifies corpus load and session runner), and Version `/version`.

---

## 2. Prerequisites

- Python 3.11+
- Docker & Docker Compose v2 (for containerized runs)
- Hath0r operator CLI (`hath0r` on PATH, or accessible via `hathor-cli/src`)

---

## 3. Local Development & Testing

### 3.1 Environment Setup
```bash
cp .env.example .env
make install
```

### 3.2 Running the Test Suite
```bash
make test
```
Runs unit and API tests with branch coverage reporting. Minimum coverage requirement is 80%.

### 3.3 Running Locally
```bash
make serve
```
Listens on `http://127.0.0.1:8083`.

### 3.4 Local Smoke Testing
In another terminal, run:
```bash
make smoke-local
```
Performs automated MCP client connection, tool enumeration, and search execution.

---

## 4. Docker Container Operations (`Hath0r Compose configuration`)

The service deploys as part of the `hath0r` Docker project:
- Network: `hath0r-net` (external, managed by HATH0R-ATC)
- Container: `hath0r-mcp`
- Host publish port: `127.0.0.1:38083` -> `8083`

### 4.1 Validate Compose Configuration
```bash
make docker-config
```

### 4.2 Build Container Image
```bash
make docker-build
```

### 4.3 Start Service
```bash
make docker-up
```
Waits for the container to become healthy before returning.

### 4.4 Check Status & Logs
```bash
make docker-status
make docker-logs
```

### 4.5 In-Container Smoke Test
```bash
make smoke
```

### 4.6 Stop Service
```bash
make docker-stop
```
> [!CAUTION]
> Never run `docker compose down` or `--remove-orphans` against the shared `hath0r` Docker project. Scope all operations strictly to `hath0r-mcp`.

---

## 5. Hath0r Fileset & Governance Verification

### 5.1 Fileset Bootstrap
```bash
./bin/hath0r-bootstrap.sh
```
Confirms all pinned schemas, exit-code definitions, and `cfg/` identity files are present and valid.

### 5.2 Operator Doctor
```bash
export HATH0R_GROUP_ROOT=/Users/raybayly/Development/OpenSource
hath0r doctor
```

---

## 6. Sibling Client Integration

### 6.1 HATH0R-ATC (Control Tower)
ATC routes requests to `hath0r-mcp:8083` across the internal `hath0r-net` bridge.

### 6.2 Hath0r UXP (Frontend)
UXP's Vite dev server proxies `/api/mcp/*` to `http://127.0.0.1:38083`.
Browser clients access the Streamable HTTP transport at `/api/mcp/mcp`.

---

## 7. Environment Promotion (`CR-BAI-001`)

Always follow the canonical promotion path:
```text
local → development → testing → staging → master (Production)
```

1. Develop features on `feature/<issue>-slug` branched from `development`.
2. Open PR targeting `development`. Ensure all CI checks and `make test` pass.
3. Promote through `testing` and `staging` sequentially after validating readiness URLs.
4. Merge into `master` only after staging approval.

---

## 8. Rollback & Troubleshooting

- **Container fails `/ready`**: Check that `knowledgebase/canonical/` contains valid markdown files and does not exceed memory or document limits (max 1000 docs, 256 KiB per doc).
- **Port conflicts on 38083**: Check for lingering containers: `docker ps --filter "publish=38083"`.
- **Unauthorized errors**: When `HATH0R_MCP_ENVIRONMENT=production`, clients must pass `Authorization: Bearer <HATH0R_MCP_TOKEN>`.
