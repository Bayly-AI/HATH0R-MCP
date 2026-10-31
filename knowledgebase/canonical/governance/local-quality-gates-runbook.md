# Runbook: Local Quality Gates (`CR-LOCAL-QGATES-001`)

> **Runbook ID**: `RB-LOCAL-QGATES-001`  
> **Owning Bot**: `LocalQualityGateBot` (`local-quality-gate-bot`)

## Commands
```bash
# Provision thresholds.json and scaffold missing test harness
hath0r quality init --scaffold

# Run local quality gates against thresholds.json
hath0r quality local

# Fleet rollout across all workspace repos
hath0r quality ensure-all

# Full 4-tier task evaluation with local quality gates
hath0r evals run --task-id "issue-561"
hath0r evals verify
```

## Diagnostics
- **`thresholds.json` missing**: Run `hath0r quality init` to generate the canonical file for the repo's detected technology stack.
- **Complexity / Duplication failure**: Run `hath0r -o json quality local` and inspect `gates.complexity.offending_functions` and `gates.duplication.duplicated_blocks`.
