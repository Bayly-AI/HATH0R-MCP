# Local Quality Gates & Per-Repository `thresholds.json` (`CR-LOCAL-QGATES-001`)

> **Rule ID**: `CR-LOCAL-QGATES-001`  
> **Control Tower**: `Bayly-AI/HATH0R-CLI`  
> **Owning Bot**: `LocalQualityGateBot` (`local-quality-gate-bot` in `BotRegistry`)  
> **Canonical Workflow**: [`cfg/factories/local-qgates-factory.yaml`](../../cfg/factories/local-qgates-factory.yaml)  
> **Evaluation Integration**: `TaskEvaluatorBot` (`hath0r evals run` · `CR-TASK-EVAL-001`)

---

## 1. Overview & Purpose

Every repository in the Hath0r ecosystem enforces **Local Quality Gates (`CR-LOCAL-QGATES-001`)** during local development and task evaluations (`hath0r evals run` and `hath0r quality local`).

Instead of calling the remote SonarCloud HTTP API during local evaluations, Hath0r provisions a canonical **`thresholds.json`** file at the root of each repository (`<repo>/thresholds.json`) seeded with **SonarCloud's canonical Quality Gate thresholds**:

| Gate Dimension | Metric Key in `thresholds.json` | Canonical Default (SonarCloud Standard) | Comparator |
|---|---|---|---|
| **1. Errors** | `max_errors` | **`0`** (`new_reliability_rating = 1`, `new_security_rating = 1`) | `<=` |
| **2. Test Coverage** | `min_coverage_pct` | **`80.0`** (`new_coverage >= 80.0%`) | `>=` |
| **3. Complexity** | `max_complexity` | **`15`** (`S3776` max cognitive/cyclomatic complexity per function) | `<=` |
| **4. Repeated Code** | `max_duplicated_lines_pct` | **`3.0`** (`new_duplicated_lines_density <= 3.0%`) | `<=` |

Because `thresholds.json` is stored canonically in each repository root, individual repositories can customize their thresholds and technology-specific commands while sharing a unified, deterministic evaluation contract.

---

## 2. Technology-Aware Provisioning & Auto-Scaffolding

Each repository uses a different technology stack (`python`, `node-ts`, `infra-python`, `rust`, `go`). When `hath0r quality init`, `hath0r quality bootstrap`, or `hath0r quality ensure-all` runs on a repository, `LocalQualityGateBot`:

1. **Detects the Repository Technology Stack**:
   - **`python`** (`pyproject.toml`, `setup.py`, `requirements.txt` — e.g., `hathor-cli`, `hath0r-mcp`, `hath0r-framework`):
     - Supporting libraries: `pytest`, `pytest-cov`, `coverage`, `ruff`, `mypy`
   - **`node-ts`** (`package.json`, `tsconfig.json` — e.g., `hath0r-poc`):
     - Supporting libraries: `vitest`, `@vitest/coverage-v8`, `eslint`, `typescript`, `prettier`
   - **`infra-python`** (`deploy/docker`, `Makefile`, `tests/` — e.g., `hath0r-atc`):
     - Supporting libraries: `pytest`, `pytest-cov`, `coverage`, `ruff`, `pyyaml`
   - **`rust`** (`Cargo.toml`) / **`go`** (`go.mod`):
     - Supporting tools: `cargo test` / `cargo clippy` or `go test -cover` / `go vet`
2. **Creates the Testing & Quality System If Missing**:
   - If `thresholds.json` does not exist, `LocalQualityGateBot` creates `<repo>/thresholds.json` with the detected technology profile and SonarCloud thresholds.
   - If the repository lacks a test directory (`tests/` or `test/`) or baseline test harness, `LocalQualityGateBot` automatically scaffolds the directory, config, and a baseline smoke test so local Q-Gates can execute immediately.
   - If supporting libraries are missing and `--install` is enabled, `LocalQualityGateBot` installs them using the repository's package manager (`python3 -m pip install` or `npm install --save-dev`).

---

## 3. Canonical `thresholds.json` Schema

```json
{
  "schema_version": "hath0r.quality.thresholds/v1",
  "rule_id": "CR-LOCAL-QGATES-001",
  "repo_name": "hathor-cli",
  "technology": "python",
  "source": "sonarcloud-canonical-thresholds",
  "thresholds": {
    "max_errors": 0,
    "min_coverage_pct": 80.0,
    "max_complexity": 15,
    "max_duplicated_lines_pct": 3.0,
    "new_reliability_rating": 1,
    "new_security_rating": 1,
    "new_maintainability_rating": 1,
    "min_security_hotspots_reviewed_pct": 100.0
  },
  "stack": {
    "language": "python",
    "supporting_libraries": [
      "pytest",
      "pytest-cov",
      "coverage",
      "ruff",
      "mypy"
    ],
    "source_dirs": ["src"],
    "test_dirs": ["tests"],
    "commands": {
      "errors": ["python3", "-m", "ruff", "check", "src"],
      "typecheck": ["python3", "-m", "mypy", "src", "--ignore-missing-imports"],
      "tests": ["python3", "-m", "pytest", "-q"],
      "coverage": ["python3", "-m", "pytest", "--cov=src", "--cov-report=xml"]
    }
  }
}
```

---

## 4. Integration with `TaskEvaluatorBot` (`hath0r evals run`)

`TaskEvaluatorBot` (`src/hath0r_cli/bots/task_evaluator_bot.py`) automatically runs `LocalQualityGateBot.evaluate_local_gates()` during every evaluation:

- **Tier 1 (`Deterministic Engineering Rubrics`)**:
  - Verifies `thresholds.json` is present and valid, and evaluates all 4 local Q-Gates (**Errors**, **Test Coverage**, **Complexity**, **Repeated Code**).
  - Contributes continuous `qgate_score` (`[0.0, 1.0]`) to Tier 1 based on error count, coverage margin above `min_coverage_pct`, complexity headroom below `max_complexity`, and duplication margin below `max_duplicated_lines_pct`.
- **Tier 3 (`Adversarial & Diff Critics`)**:
  - Penalizes functions exceeding `max_complexity` (`15`) or files exceeding `max_duplicated_lines_pct` (`3.0%`).
- **Scorecard Persistence (`.hath0r/evals/latest.json`)**:
  - Persists the full `local_quality_gates` report (`thresholds_file`, `technology`, `passed`, `qgate_score`, and per-gate metrics for `errors`, `coverage`, `complexity`, and `duplication`).

---

## 5. Operator CLI Commands

```bash
# 1. Initialize or refresh canonical thresholds.json and scaffold missing test harness/libraries
hath0r quality init [--install] [--scaffold]

# 2. Run the 4 Local Quality Gates (Errors, Coverage, Complexity, Duplication) against thresholds.json
hath0r quality local [--all-files] [--run-commands]

# 3. Roll out thresholds.json and verify Local Q-Gates across all workspace repositories
hath0r quality ensure-all [--workspace /Users/raybayly/Development/OpenSource]

# 4. Run full 4-tier task evaluation (automatically includes Local Quality Gates)
hath0r evals run --task-id "issue-561"
```
