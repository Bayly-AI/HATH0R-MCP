# Synced from HATH0R-CLI/cfg/group (control tower) at 2026-09-22T19:07:59Z
# Canonical git path: Bayly-AI/HATH0R-CLI → cfg/group/
# Re-run: ./scripts/sync-group-hub.sh

# WARP.md — OpenSource Project policy

> Group: `hath0r-opensource`  
> Control tower: `HATH0R-CLI` (`Bayly-AI/HATH0R-CLI`)  
> Updated: 2026-09-19

## Purpose

Agent and operator policy for the **OpenSource Project**: every canonical repo under `/Users/raybayly/Development/OpenSource`.

## Control tower

| Field | Value |
|-------|-------|
| Tower product | HATH0R-CLI |
| Path | `/Users/raybayly/Development/OpenSource/HATH0R-CLI` |
| Remote | `Bayly-AI/HATH0R-CLI` |
| CLI | `hath0r` |
| Config | `HATH0R-CLI/cfg/control-tower.yaml` |

Members point `control_tower_path` at the tower repo, not at the bare group folder.

## Membership

- **In scope**: all sibling git repositories under the OpenSource folder.
- **Registry**: tower `cfg/products.yaml` and hub `/.hath0r/knowledgebase/catalogs/suite-products.yaml`.
- New sibling repos join the OpenSource Project by default and should add member `AGENTS.md` + stub KB pointer.

## Knowledge & docs

| Surface | Path | Role |
|---------|------|------|
| Group KB hub | `OpenSource/.hath0r/knowledgebase` | Canonical local knowledge |
| Member KB | `<repo>/.hath0r/knowledgebase` | Stub/pointer only |
| Docs corpus | `OpenSource/hath0r/docs` | Canonical documentation |
| Group rules | `OpenSource/AGENTS.md` | Agent rules |
| Tower configs | `OpenSource/HATH0R-CLI/cfg/*` | Suite governance |

## Hidden root

Only `.hath0r/`. Forbidden: `.ai/`, `.aegis/`, `.infraOS/`.

## Branch protection & promotion (CR-BAI-001 / cr-branch-gov-001)

```text
local → development → testing → staging → master (Production)
```

- Issue before branch
- Feature work merges to `development` only
- Stage PRs: `development→testing`, `testing→staging`, `staging→master`
- No force-push/deletes on canonical branches; code owner review required

## Secrets

Never commit secrets. Use `/Users/raybayly/Development/.credentials/<service>/.env`.

## CR-HATH0R-INIT-001: Hath0r repo initialization entry gate (CRITICAL — org-wide)

**Main entry statement:** Before initializing (or re-initializing) any repository with Hath0r, agents MUST:

1. **Setup playbook** — Locate and follow the canonical Hath0r setup playbook:
   - `/Users/raybayly/Development/OpenSource/hath0r/docs/developers/hathor-playbook-001-repo-init-setup-20260919.md`
   - If the playbook is missing or incomplete, **create or update it first**, then proceed.
2. **Same-technology runbook** — Locate a runbook for an **individual repo with the same technology stack** (e.g. React+Vite UXP, Python CLI):
   - Prefer a sibling/product `docs/runbook.md` (or `docs/*runbook*`) in that tech family.
   - If none exists, **create a tech-appropriate runbook in the target repo** before finishing init.
3. Only after (1) and (2) are satisfied: apply fileset/layout, `.hath0r/`, `cfg/`, contracts pin, `AGENTS.md` identity, and `./bin/hath0r-bootstrap.sh`.

Do not skip the playbook/runbook gate. Layout scaffolding without a documented ops path is incomplete initialization.
