# Procedure: Local Quality Gates Setup & Evaluation (`CR-LOCAL-QGATES-001`)

> **Procedure ID**: `PROC-LOCAL-QGATES-001`  
> **Owning Bot**: `LocalQualityGateBot` (`local-quality-gate-bot`)

## Steps
1. **Initialize Per-Repo `thresholds.json`**:
   - Run `hath0r quality init` in the repository root (or `hath0r quality ensure-all` across the workspace).
   - Verify `<repo>/thresholds.json` is created with `max_errors: 0`, `min_coverage_pct: 80.0`, `max_complexity: 15`, and `max_duplicated_lines_pct: 3.0`.
2. **Provision Supporting Libraries & Test System**:
   - Run `hath0r quality init --install --scaffold` to ensure technology-specific test/coverage/lint/complexity libraries and test directories exist.
3. **Execute Local Quality Gates**:
   - Run `hath0r quality local` to evaluate Errors, Test Coverage, Complexity, and Repeated Code locally against `thresholds.json`.
4. **Verify in 4-Tier Task Evaluations**:
   - Run `hath0r evals run` and `hath0r evals verify` to confirm `local_quality_gates` passes in `.hath0r/evals/latest.json`.
