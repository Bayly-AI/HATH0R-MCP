# MCP configuration — HATH0R-MCP

> **Project MCP is priority 1** for the Hath0r OpenSource suite.

## Canonical registry (control tower)

Do not maintain a divergent full server list here. The suite-wide MCP server
registry (priorities, transports, endpoints) is owned by:

**[HATH0R-CLI `cfg/mcp.servers.json`](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/cfg/mcp.servers.json)**

| id | scope | priority | role |
|----|-------|----------|------|
| `hath0r-mcp` | project | **1** | Primary — Hath0r knowledge & tools (this repo) |
| `bai-mcp` | org | 2 | Bayly AI enterprise |
| `1-nation-mcp` | group | 3 | 1-Nation reference |

## This product

| Field | Value |
|-------|-------|
| Product / id | HATH0R-MCP / `hath0r-mcp` |
| GitHub | `Bayly-AI/HATH0R-MCP` |
| Transport | streamable-http |
| Base URL (local) | `http://localhost:38083` |
| MCP endpoint | `/mcp` |
| Health / ready | `/health` · `/ready` |

When agents or Warp project MCP settings conflict, **prefer project MCP
(`hath0r-mcp`, priority 1)** over org/group servers unless the task explicitly
requires another scope.

Local path: `/Users/raybayly/Development/OpenSource/hath0r-mcp`  
Setup how-to: [`docs/HOWTO-MCP-SETUP.md`](../../docs/HOWTO-MCP-SETUP.md)
