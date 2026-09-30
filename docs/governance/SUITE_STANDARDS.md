# Suite standards — HATH0R-MCP

> Member pointer document. **Canonical standards live in the control tower**  
> (`Bayly-AI/HATH0R-CLI` on branch `development`). Do not fork policy here.

Product: **HATH0R-MCP** (`hath0r-mcp`)  
Group: **hath0r-opensource**  
Control tower: **HATH0R-CLI** (`Bayly-AI/HATH0R-CLI`)  
Updated: 2026-09-24 · Issue: [#3](https://github.com/Bayly-AI/HATH0R-MCP/issues/3)

---

## Purpose

This file orients agents and operators to suite-wide governance owned by the
OpenSource control tower. Local `cfg/` stubs mirror defaults with
**product-specific `service.name` / identity only**.

---

## Canonical references (GitHub `development`)

Base URL:

`https://github.com/Bayly-AI/HATH0R-CLI/blob/development/`

| Topic | Control tower doc | Local stub / note |
|-------|-------------------|-------------------|
| OpenTelemetry | [`docs/governance/opentelemetry-standards.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/opentelemetry-standards.md) | [`cfg/observability/otel.json`](../../cfg/observability/otel.json) |
| OpenFeature | [`docs/governance/openfeature-standards.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/openfeature-standards.md) | [`cfg/feature-flags/openfeature.json`](../../cfg/feature-flags/openfeature.json) |
| OpenObservation | [`docs/governance/openobservation-standards.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/openobservation-standards.md) | [`cfg/observability/openobservation.json`](../../cfg/observability/openobservation.json) |
| CLI-first | [`docs/governance/cli-first-rules.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/cli-first-rules.md) | `AGENTS.md` → CLI-first section (`cr-cli-first-001`) |
| Workflow docs | [`docs/governance/workflow-documentation-standard.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/workflow-documentation-standard.md) | Prefer playbook → procedure → runbook before code |
| Docker groups | [`docs/governance/docker-group-standard.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/docker-group-standard.md) | [`cfg/docker/groups/README.md`](../../cfg/docker/groups/README.md) + root `docker-compose.yml` |
| SemVer | [`docs/governance/semantic-versioning.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/semantic-versioning.md) | [`semantic-versioning.md`](semantic-versioning.md) + root `VERSION` |
| MCP priority | [`cfg/mcp.servers.json`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/cfg/mcp.servers.json) | [`cfg/mcp/README.md`](../../cfg/mcp/README.md) — **project MCP priority 1** |
| Branch / promotion | [`docs/governance/branch-rules.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/branch-rules.md) | `AGENTS.md` · `CR-BAI-001` |

Tower cfg defaults:

- OTel: [`cfg/observability/otel.json`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/cfg/observability/otel.json)
- OpenFeature: [`cfg/feature-flags/openfeature.json`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/cfg/feature-flags/openfeature.json)
- OpenObservation: [`cfg/observability/openobservation.json`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/cfg/observability/openobservation.json)
- Docker group template: [`cfg/docker/groups/hath0r/`](https://github.com/Bayly-AI/HATH0R-CLI/tree/development/cfg/docker/groups/hath0r)

---

## Local layout expectations

```text
.hath0r/                 # only allowed hidden framework root
cfg/suite.yaml           # member orientation
cfg/product.yaml         # product identity
cfg/observability/       # OTel + OpenObservation stubs
cfg/feature-flags/       # OpenFeature stub
cfg/docker/groups/       # pointer to tower hath0r group
cfg/mcp/                 # project-MCP-first notes
contracts/               # pinned CLI schemas
VERSION                  # SemVer source of truth
docs/runbook.md          # tech ops runbook
docs/governance/         # this folder (pointers, not forks)
```

---

## Operator entrypoints

1. `./bin/hath0r-bootstrap.sh` — fileset / contracts presence
2. `hath0r doctor` with `HATH0R_GROUP_ROOT` set to the OpenSource root
3. `make test` / `make serve` / `make smoke-local` — see [`docs/runbook.md`](../runbook.md)

---

## Related

- Adopt audit: [`.hath0r/audits/hathor-adopt-2026-09-24.md`](../../.hath0r/audits/hathor-adopt-2026-09-24.md)
- Control tower epic: [HATH0R-CLI#58–#63 / PR #111](https://github.com/Bayly-AI/HATH0R-CLI/pull/111)
