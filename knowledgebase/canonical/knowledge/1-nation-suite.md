# 1-Nation Suite

1 Nation is a nonprofit, nonpartisan organization tracking political votes and producing politician report cards.

ATC is the canonical infrastructure, observation, and group controller.
MCP provides document indexing, hybrid search, runbooks, and MCP tools.
All services join Docker project `1-nation` and external network `1-nation-net`.
MCP is `1NMCP:8083`. Shared edge and state belong to ATC: `1NGINX` and `1NRedis`.

Source: 1-Nation ATC cfg/suite.yaml and AGENTS.md, copied 2026-09-23.
