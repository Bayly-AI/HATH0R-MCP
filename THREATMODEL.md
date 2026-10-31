# THREATMODEL.md — Repository Security & Attack Surface Specification

> Governed by `CR-AGENTIC-SEC-001` (OpenAnt Constrained Attacker Persona & BITE Verification).

## Deployment & Runtime Mode
- **Mode**: `hybrid_cli_and_mcp`
- **Privilege Boundary**: Non-root operator execution; secrets isolated in external credential store.

## External Attack Surface
- **CLI Entrypoints**: `@click.command` and `@click.group` handlers accepting operator arguments.
- **MCP Tool Entrypoints**: `@mcp.tool` JSON-RPC handlers exposed over Streamable HTTP / stdio.
- **HTTP Routes**: FastAPI health, readiness, and API endpoints.

## Trusted vs. Untrusted Inputs
- **Trusted**: Local repository configuration (`cfg/*.yaml`) verified by SHA-256 hash manifest.
- **Untrusted**: External web payloads, third-party `SKILL.md` / plugin manifests, unverified RAG documents, and remote JSON-RPC tool arguments.

## Out-of-Scope Threat Assumptions
- `local_cli_only`: Attacks requiring pre-existing local root/shell compromise on the developer workstation.
- `assumes_admin_or_local_shell`: Findings that assume an attacker already controls local environment variables or OS process table.
