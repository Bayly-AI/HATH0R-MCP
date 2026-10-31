# Bot Specification: `LocalQualityGateBot` (`local-quality-gate-bot`)

> **Bot ID**: `local-quality-gate-bot`  
> **Class**: `hath0r_cli.bots.local_quality_gate_bot.LocalQualityGateBot`  
> **Level 2 CLI**: `hath0r quality init|local|ensure-all`  
> **Level 1 MCP**: `mcp_quality_local_gates`, `mcp_quality_init_thresholds`

## Responsibilities
1. Detect repository technology stack (`python`, `node-ts`, `infra-python`, `rust`, `go`).
2. Manage per-repository canonical `thresholds.json` seeded with SonarCloud's canonical thresholds (`max_errors: 0`, `min_coverage_pct: 80.0`, `max_complexity: 15`, `max_duplicated_lines_pct: 3.0`).
3. Verify and install technology-specific supporting libraries (`pytest`, `pytest-cov`, `ruff`, `vitest`, `eslint`, `typescript`, etc.) and scaffold missing test harnesses automatically.
4. Execute local static and coverage gates for Errors, Test Coverage, Cognitive/Cyclomatic Complexity, and Repeated Code without calling SonarCloud's remote API.
5. Supply continuous `qgate_score` and detailed gate telemetry to `TaskEvaluatorBot` (`CR-TASK-EVAL-001`).
