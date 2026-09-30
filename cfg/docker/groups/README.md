# Docker groups — HATH0R-MCP pointer

> Canonical **hath0r** Docker group template and standard live in the control tower.

| Resource | Location |
|----------|----------|
| Standard | [HATH0R-CLI `docs/governance/docker-group-standard.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/docker-group-standard.md) |
| Group template | [HATH0R-CLI `cfg/docker/groups/hath0r/`](https://github.com/Bayly-AI/HATH0R-CLI/tree/development/cfg/docker/groups/hath0r) |
| Suite compose (this product) | Repo root [`docker-compose.yml`](../../../docker-compose.yml) |

## Membership (canonical)

| Field | Value |
|-------|-------|
| Compose project `name:` | `hath0r` (product service file) / tower group may use `hath0r-opensource` |
| Network | external `hath0r-net` |
| Service / container | `hath0r-mcp` |
| Image | `hath0r/mcp:local` |
| Host port | `38083` → container `8083` |

Do **not** run `docker compose down --remove-orphans` against the shared group.
Scope operations to the `hath0r-mcp` service (see [`docs/runbook.md`](../../../docs/runbook.md)).

Secrets: `/Users/raybayly/Development/.credentials/` only — never commit `.env` secrets.
