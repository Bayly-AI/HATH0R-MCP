# Changelog

All notable changes to **HATH0R-MCP** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.1] - 2026-10-29

### Changed
- **Rule Harmonization, `CLAUDE.md` 1:1 Sync & Workflow Upgrade (`CR-CLAUDE-SYNC-001` · `CR-AGENTIC-SEC-001`)**:
  - Added `CR-CLAUDE-SYNC-001`, `CR-AGENTIC-SEC-001`, and `CR-MEMORY-COMPOUND-001` to `AGENTS.md`, synchronized `CLAUDE.md` 1:1 with `AGENTS.md`, initialized `THREATMODEL.md`, and updated `.agents/skills/clean-repos/SKILL.md` and `.agents/skills/orient/SKILL.md`.

## [1.3.0] - 2026-10-29

### Added
- **Purpose-Based Access Control (PBAC), Inline Contextual Curation & L2 Secret/PII Sanitizer (`knowledgebase.search.curation`)** (#84):
  - Added `PBACCurationEngine` (`src/knowledgebase/search/curation.py`) and `cfg/pbac/personas.yaml` supporting agent personas (`operator`, `developer_agent`, `research_subagent`, `external_auditor`, `public_reader`), sensitivity tiers (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`), inline span curation (`[CURATED:restricted_for_persona=<persona>]`), and pre-persist secret/PII redaction (`[REDACTED:<type>]`, `[PII_REDACTED:<type>]`).
  - Wired `PBACCurationEngine` into `kb_search`, `kb_get_document`, `kb_add_document`, and `kb_upsert_document` in `src/knowledgebase/server.py`, and exposed new MCP tools `pbac_curate` and `pbac_redteam_probe`.

## [1.2.6] - 2026-10-28

### Added
- **`CR-CLI-ENTRY-001` (Start with the CLI — CANONICAL)** in `AGENTS.md`: agents check the `hath0r` operator CLI first on every request, offer to register missing capabilities, and require docs before code.

## [1.2.5] - 2026-10-28

### Changed
- Synchronized canonical `CR-TASK-EVAL-001` directive in `WARP.md` (#77).

## [1.2.4] - 2026-10-28

### Added
- **Automatic Task Evaluation Configuration (`CR-TASK-EVAL-001`)**: Added declarative `cfg/evals/task-eval.json` binding `HATH0R-MCP` to `TaskEvaluatorBot` (`hath0r evals run`) and `.hath0r/evals/` gitignore negation rules (#75).

## [1.2.3] - 2026-10-28

### Added
- CR-SEMVER-BUMP-001: every created or merged PR must create or bump the product's Semantic Version (`VERSION` is the source of truth).

## [1.2.2] - 2026-10-28

### Changed
- Added `CR-SONAR-PREANNOUNCE-001` to the agent instructions: confirm SonarCloud Quality Gate thresholds before announcing work Complete.

## [1.2.1] - 2026-10-12

### Added
- Ingested canonical Gameshow CAG/RAG Benchmark knowledge into the semantic index.
