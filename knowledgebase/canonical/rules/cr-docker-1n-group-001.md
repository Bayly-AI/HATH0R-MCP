---
id: cr-docker-1n-group-001
title: Canonical 1-nation Docker group for all 1-Nation workspace repos
version: 1.0.0
severity: CRITICAL
status: canonical
applies_to: "/Users/raybayly/Development/1-Nation/**"
effective_date: 2026-09-22
suite: 1n-suite
---

# CR-DOCKER-1N-GROUP-001 — 1-nation Docker group (CANONICAL)

## Rule statement

**Every repository, service, and container defined under the `1-Nation` workspace folder is a member of the Docker Compose project / Docker Desktop group `1-nation`.**

This is **canonical** and not optional for local suite runtime.

## Workspace root

```text
/Users/raybayly/Development/1-Nation
```

Includes (now and future):

- Product repos (e.g. `UXP/`)
- Site/service trees (e.g. `site/1N-Data`, `site/1N-Experience`)
- Shared deploy assets (`deploy/docker`)
- Any additional clone or package placed under this directory

## Canonical artifacts

| Artifact | Value |
|----------|--------|
| Compose project name (`name:`) | `1-nation` |
| Docker Desktop group | `1-nation` |
| Network | `1-nation-net` (external, shared) |
| Shared communication | container `1NGINX` |
| Shared state | container `1NRedis` |
| Image naming | `1-nation/{component}:tag` |
| Project label | `com.1nation.project=1n-suite` |
| Org label | `com.1nation.org=bayly-ai` |

## Required compose skeleton

```yaml
name: 1-nation

services:
  example:
    image: 1-nation/example:local
    container_name: 1NExample
    networks:
      1-nation-net:
        aliases: [1NExample, 1n-example]
    labels:
      com.1nation.org: bayly-ai
      com.1nation.project: 1n-suite
      com.1nation.component: example
      com.1nation.container: 1NExample

networks:
  1-nation-net:
    name: 1-nation-net
    external: true
```

## Shared stack ownership

Workspace-owned shared services live in:

`deploy/docker/docker-compose.yml`

| Container | Role |
|-----------|------|
| `1NGINX` | Suite edge / reverse proxy |
| `1NRedis` | Shared state / cache / coordination |
| `1NPOSTGRES` | Canonical DB (profile `db` / `apps`) |

Member repos **consume** these; they must not redefine a second Redis/NGINX under a different compose project name for suite use.

## Non-compliance

Using a different compose project name, a private-only network for suite peers, or omitting group labels for 1N containers is a **CRITICAL** violation of this rule.

## Verification

```sh
docker ps -a --filter label=com.docker.compose.project=1-nation \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Label "com.docker.compose.project"}}'
docker network inspect 1-nation-net
```

Every 1N container MUST appear with project `1-nation`.

## Related

- `AGENTS.md` (workspace root)
- `docs/deployment-local-docker.md`
- `deploy/docker/README.md`
- Historical naming registry: Control Tower `docker-container-naming.md` / `cr-docker-1n-001`
