# HATH0R CLI response JSON Schemas

Canonical machine-readable contracts for the `hath0r` CLI structured JSON
interface defined by **HATHOR-TS-005** (*HATH0R CLI Machine Interface for the
POC*).

This directory is owned by the **HATH0R Agentic Framework** repository
(`Bayly-AI/HATH0R-Agentic-Framework`). Downstream CLI and POC repos consume
these schemas; they do not redefine them.

## Schemas

| File | Identity | Spec section | Purpose |
|------|----------|--------------|---------|
| `hath0r-cli-response-v1.schema.json` | `hath0r.cli.response/1` | §4 | Top-level response envelope |
| `hath0r-cli-diagnostic-v1.schema.json` | `hath0r.cli.diagnostic/1` | §5 | Diagnostic entry shape |
| `hath0r-cli-version-v1.schema.json` | version `data` | §9 | `command: version` payload |
| `hath0r-cli-doctor-v1.schema.json` | doctor `data` | §10 | `command: doctor` payload |
| `hath0r-cli-kb-path-v1.schema.json` | kb.path `data` | §11 | `command: kb.path` payload |
| `hath0r-cli-kb-products-v1.schema.json` | kb.products `data` | §12 | `command: kb.products` payload |

All schemas use **JSON Schema draft-07**.

The envelope schema `$ref`s the diagnostic schema for `diagnostics` items.
Per-command schemas describe only the `data` object; consumers validate the
envelope first, then validate `data` against the command-specific schema when
`data` is non-null.

## Versioning policy

Aligned with HATHOR-TS-005 §16:

1. **Response major** is encoded in the envelope `schema` field
   (`hath0r.cli.response/1`) and in filenames (`*-v1.schema.json`).
2. **Additive optional fields** keep major `1`. Consumers must ignore unknown
   properties (`additionalProperties: true` on envelope and payload roots).
3. **Breaking changes** (remove/retype a required field, change enum
   semantics, rename a stable code) require a **new major** (`/2`, `*-v2`).
4. **Diagnostic codes** are stable within a response major.
5. Consumers **pin supported response majors** and must refuse unsupported
   majors without falling back to scraping human text.

## How consumers reference these schemas

### CLI (`HATH0R-CLI` / `hath0r-cli`)

- Implement `--output json` envelopes that satisfy
  `hath0r-cli-response-v1.schema.json`.
- Emit command `data` shapes matching the per-command schemas.
- Validate golden fixtures in pytest against these files (e.g. `jsonschema` or
  `check-jsonschema`).
- Prefer vendoring or path-referencing the Framework release that pins the
  contract rather than copying prose-only definitions.

### POC (`hath0r-poc`)

- Validate live or fixture CLI stdout against the envelope schema before
  mapping to `hathor-poc.response/1`.
- Strip operator-only fields (notably `kb.path` → `data.path`) from browser
  payloads.
- Pin the supported envelope major; treat mismatch as unavailable /
  contract-mismatch.

### Example validation

```bash
# Syntax
python3 -m json.tool lib/schemas/hath0r-cli-response-v1.schema.json > /dev/null

# Draft-07 compile (if ajv-cli is installed)
npx --yes ajv-cli compile -s lib/schemas/hath0r-cli-diagnostic-v1.schema.json
npx --yes ajv-cli compile \
  -s lib/schemas/hath0r-cli-response-v1.schema.json \
  -r lib/schemas/hath0r-cli-diagnostic-v1.schema.json

# Instance check (if check-jsonschema is installed)
check-jsonschema --schemafile lib/schemas/hath0r-cli-version-v1.schema.json path/to/data.json
```

## Design notes

- One result model for human and machine renderers (HATHOR-CANON-011).
- `data` may be `object` or `null` on the envelope; command schemas apply when
  `data` is an object.
- `meta.cli_version` is SemVer; `meta.duration_ms` is a non-negative integer.
- `diagnostics[].code` is uppercase snake_case; check IDs are kebab-case.
- Forward compatibility: unknown additive fields are allowed and must be
  ignored by consumers.

## Source specification

Prose authority (until superseded by a released Framework contract tag):

- `HATH0R-CLI/docs/hathor-ts-005-poc-machine-interface-20260916.md`
- Requirements: HATHOR-REQ-002 (HT-CLI-003, HT-CLI-005)

## Issue tracking

Introduced in Framework issue
[#21](https://github.com/Bayly-AI/HATH0R-Agentic-Framework/issues/21).
