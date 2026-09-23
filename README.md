# BAI-1-NATION-MCP

Runnable, read-only Model Context Protocol (MCP) server and knowledge engine for the 1-Nation Suite, hosted as an OpenSource Project member under `OpenSource/hath0r-mcp`.

| Contract | Value |
|---|---|
| Product ID | `bai-1-nation-mcp` (service alias: `1n-mcp`) |
| Repository | `Bayly-AI/BAI-1-NATION-MCP` |
| Local Path | `/Users/raybayly/Development/OpenSource/hath0r-mcp` |
| Compose project / network | `1-nation` / `1-nation-net` (`CR-DOCKER-1N-GROUP-001`) |
| Container / service / image | `1NMCP` / `1n-mcp` / `1-nation/mcp:local` |
| Host base URL | `http://127.0.0.1:58083` |
| Suite internal URL | `http://1NMCP:8083` |
| MCP transport | Streamable HTTP at `/mcp` via official MCP Python SDK |
| Probes | `/health` (liveness), `/ready` (readiness), `/version` |
| Hath0r Fileset Pin | `0.2.0` (`CR-HATH0R-INIT-001`) |

---

## Capabilities & MCP Tools

`BAI-1-NATION-MCP` starts without an external database, Redis, or cloud credentials. Deterministic lexical search operates against the bundled canonical reference corpus.

### Available Tools
1. **`suite_info()`**: Returns 1-Nation Suite identity, ATC control tower reference, and the available reference document catalog.
2. **`kb_search(query, limit=5)`**: Case-insensitive word search across reference markdown documents, returning scores, excerpts, and document IDs.
3. **`kb_get_document(document_id)`**: Safe retrieval by exact document ID (never executes client-supplied filesystem paths).

Additionally, the preserved BAI knowledge engine remains available under `src/knowledgebase/` for hybrid dense-vector and BM25 search and legacy REST/SSE API endpoints (`/mcp/sse`).

---

## Quick Start

### 1. Local Development
```bash
cp .env.example .env
make install
make test
make serve           # Runs on 127.0.0.1:8083
```

In another terminal, test tool execution with the smoke client:
```bash
make smoke-local
```

### 2. Docker Deployment (`1-nation` Docker Group)
```bash
# Ensure ATC external network exists (or create locally)
docker network create 1-nation-net 2>/dev/null || true

make docker-config   # Validate compose
make docker-up       # Builds and runs 1n-mcp with readiness wait
make smoke           # In-container smoke check
make docker-status   # View container status
```

### 3. Hath0r Governance Bootstrap
```bash
./bin/hath0r-bootstrap.sh
```

---

## Directory Structure

```text
.
├── .hath0r/                # Hath0r framework metadata and KB stub
├── bin/
│   └── hath0r-bootstrap.sh # Hath0r post-unpack smoke check
├── cfg/
│   ├── product.yaml        # Hath0r product identity
│   ├── suite.yaml          # Suite membership (OpenSource + 1-Nation)
│   ├── knowledge-tower.yaml# KB tower pointer
│   ├── knowledgebase.json  # Search index definitions
│   └── rag.json            # RAG defaults
├── contracts/              # Pinned Hath0r CLI schemas and exit codes
├── dist/                   # Build artifacts (.gitkeep)
├── docs/
│   ├── runbook.md          # Operations and developer runbook (CR-HATH0R-INIT-001)
│   ├── provenance.md       # Source origin documentation
│   └── INDEX.md            # Docs index
├── knowledgebase/
│   └── canonical/          # Bundled Markdown knowledge corpus (10 taxonomies)
├── src/
│   └── knowledgebase/
│       ├── server.py       # Primary FastMCP Streamable HTTP server
│       ├── api/            # Full REST and legacy SSE API
│       ├── core/           # Data models, config, MCP tool schemas
│       ├── search/         # Hybrid BM25 + vector search engine
│       ├── storage/        # In-memory and disk storage adapters
│       ├── indexing/       # Chunkers and BM25 indexers
│       ├── runbooks/       # Runbook services
│       └── cli/            # CLI and smoke runner (smoke.py)
├── tests/                  # Unit and API pytest test suite
├── Dockerfile, docker-compose.yml, Makefile, pyproject.toml, requirements.txt
└── AGENTS.md               # Agent rules and governance
```

---

## Sibling Integration

- **1-Nation ATC** (`../1-Nation/ATC`): Canonical control tower and infrastructure owner. Routes to `1NMCP:8083` over `1-nation-net`.
- **1-Nation UXP** (`../1-Nation/UXP`): Frontend web application. Vite dev/preview server proxies `/api/mcp/*` to `http://127.0.0.1:58083`.
- **HATH0R-CLI** (`../OpenSource/HATH0R-CLI`): Operator control tower and CLI for Hath0r suite operations (`hath0r doctor`, `hath0r kb *`).

See [`docs/runbook.md`](docs/runbook.md) for full operational instructions.
