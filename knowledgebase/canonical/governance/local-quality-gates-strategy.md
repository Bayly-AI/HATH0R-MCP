# Strategy: Local Quality Gates (`CR-LOCAL-QGATES-001`)

> **Strategy ID**: `STRAT-LOCAL-QGATES-001`  
> **Owning Bot**: `LocalQualityGateBot` (`local-quality-gate-bot`)  
> **Canonical Doc**: [`docs/governance/local-quality-gates.md`](../local-quality-gates.md)

## Objective
Enforce SonarCloud's canonical quality thresholds (`max_errors: 0`, `min_coverage_pct: 80.0`, `max_complexity: 15`, `max_duplicated_lines_pct: 3.0`) locally inside every repository via a canonical `thresholds.json` file and technology-aware static/coverage analyzers, integrated directly into `TaskEvaluatorBot` (`hath0r evals run`) with zero direct dependency on remote SonarCloud API calls.

## Key Pillars
1. **Per-Repository Canonical `thresholds.json`**: Every repo maintains its own `thresholds.json` at the repo root, seeded with SonarCloud thresholds and customizable per repo.
2. **Technology-Aware Provisioning & Auto-Scaffolding**: `hath0r quality init` detects Python, Node/TypeScript, Infra/Control-Tower, Rust, or Go stacks, installs missing supporting libraries, and scaffolds a test harness if none exists.
3. **Continuous Evaluation Integration**: `TaskEvaluatorBot` incorporates all 4 local gates into Tier 1, Tier 3, and the `.hath0r/evals/latest.json` scorecard.
