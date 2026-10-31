# Playbook: Local Quality Gates (`CR-LOCAL-QGATES-001`)

> **Playbook ID**: `PB-LOCAL-QGATES-001`  
> **Owning Bot**: `LocalQualityGateBot` (`local-quality-gate-bot`)

## Scenario 1: Onboarding a New or Existing Repository
1. Run `hath0r quality init --install --scaffold`.
2. Inspect the generated `thresholds.json` at the repository root.
3. Run `hath0r quality local` and confirm all 4 gates (`errors`, `coverage`, `complexity`, `duplication`) pass.

## Scenario 2: Remediating a Failing Local Gate During `hath0r evals run`
- **Errors Gate (`actual_errors > max_errors`)**: Run the repo's lint/typecheck command from `thresholds.json` and resolve all reported syntax/lint/type errors.
- **Test Coverage Gate (`actual_coverage_pct < min_coverage_pct`)**: Add unit tests for uncovered modules/functions or generate fresh `coverage.xml` / `coverage/coverage-summary.json`.
- **Complexity Gate (`max_observed_complexity > max_complexity`)**: Refactor functions listed in `offending_functions` into smaller helper functions with cognitive complexity `<= 15`.
- **Repeated Code Gate (`duplicated_lines_pct > max_duplicated_lines_pct`)**: Extract duplicated 6+ line blocks into shared helper functions or constants (`<= 3.0%`).
