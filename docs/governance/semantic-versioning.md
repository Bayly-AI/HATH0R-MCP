# Semantic versioning — HATH0R-MCP

> **Pointer only.** Canonical policy:
> [HATH0R-CLI `docs/governance/semantic-versioning.md`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/semantic-versioning.md)
> on branch `development`.

## Local rules

1. Root **`VERSION`** is the exclusive SemVer source of truth for this repo.
2. `MANIFEST.json` `fileset_version` / `cli_version` / `contracts_version` and
   `cfg/product.yaml` `fileset_version` must stay aligned with `VERSION` when
   the fileset pin changes.
3. Every PR targeting `development` declares version impact:
   `semver:major` | `semver:minor` | `semver:patch` | `semver:none`.
4. Release trains: `development` → `release/x.x.x` → `testing` → `staging` → `master`.

Current pin: see [`VERSION`](../../VERSION).
