# Workflow: Local Quality Gates (`cfg/factories/local-qgates-factory.yaml`)

> **Workflow ID**: `cfg/factories/local-qgates-factory.yaml`  
> **Owning Bots**: `local-quality-gate-bot`, `task-evaluator-bot`

## Declarative Pipeline Steps
1. **`ensure-calibrated` (`cicccd-managing-bot`)**: Verify 4-hour agent calibration freshness (`max_age_hours: 4.0`).
2. **`init-thresholds` (`local-quality-gate-bot`)**: Detect repository technology stack, ensure `thresholds.json` exists, and scaffold/install missing test harness support if needed.
3. **`evaluate-local-gates` (`local-quality-gate-bot`)**: Evaluate Errors (`<= 0`), Test Coverage (`>= 80.0%`), Complexity (`<= 15`), and Repeated Code (`<= 3.0%`) locally against `thresholds.json`.
4. **`evaluate-task` (`task-evaluator-bot`)**: Incorporate local Q-Gate metrics into the 4-tier evaluation scorecard (`.hath0r/evals/latest.json`).
