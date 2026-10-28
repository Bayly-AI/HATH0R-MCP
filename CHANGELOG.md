# Changelog

All notable changes to **HATH0R-MCP** (Hath0r MCP Server) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.2] - 2026-10-28

### Added
- CR-SEMVER-BUMP-001: every created or merged PR must create or bump the product's Semantic Version (`VERSION` is the source of truth).

## [1.2.1] - 2026-10-12

### Fixed
- **Container Hardening & FastMCP Runtime Entrypoint**:
  - Aligned MCP `Dockerfile` multi-stage build with `FastMCP` ASGI runtime entrypoint.
  - Hardened runtime execution with non-root security context (`UID 10001:GID 10001`) adhering strictly to CR-IAC-001.

## [1.2.0] - 2026-10-11

### Added
- **Apache Airflow Integration Toolset** (#58): Added FastMCP tools `airflow_list_dags`, `airflow_trigger_dag`, and `airflow_get_dag_run` via `AirflowService` REST client.
- **Infrastructure as Code (IaC) & AWS EKS Fargate Standards** (#56): Multi-stage Dockerfile hardening, non-root user execution, container salting, and EKS Fargate serverless manifests.

## [1.1.0] - 2026-10-11

### Added
- Semantic versioning compliance and release automation workflow (`.github/workflows/release.yml`, `version-policy-guard.yml`) (#49).
- Integration and registration with HATH0R CLI Sibling Bot for automated suite sibling installation and lifecycle management (#49).

### Changed
- Updated canonical container name to `Hath0r-MCP` (#51).
- Maintained legacy `hath0r-mcp` network alias for backwards compatibility across suite compose stacks (#51).

## [1.0.1] - 2026-10-10

First tagged release. Aligns the repository VERSION with the deployed container
(`APP_VERSION=1.0.1`) and records the history to date.

### Added
- FastMCP server exposing generic knowledgebase, docs, runbook and system tools.
- Voice tools and session state (`voice_listen`, `voice_speak`, `voice_dispatch_action`) (#9).
- MCP container git tools with automatic task promotion (#13).
- JEV tool-guard integration on the agent control loop (#7).
- AWS App Runner deployment and canonical cloud endpoint `mcp.hath0r-cli.com` (#18, #19).
- AgentGraph substrate adoption for agent files (#21, #22).
- Client setup HOWTO for Claude, Warp, Gemini and VS Code (#4).
- Suite clean-repos skill standard and CR-CLI-FEATURE-STANDARD-001 governance (#27).
- SonarCloud Quality Gate workflow and project configuration (#29).

### Changed
- Repository made public with the open-source PR workflow (#24).
- Version bumped from 0.2.3 to 1.0.1 to match the running service.

### Fixed
- SonarCloud project key and security hardening (#33).
- Input sanitization in the promotion workflow (#35).
