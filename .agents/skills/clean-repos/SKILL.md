---
name: clean-repos
description: Comprehensive standard operating procedure for cleaning repositories across the suite. Activates whenever the user says "clean repo", "clean repos", "clean repository", "clean repositories", or requests repository cleanup and branch hygiene.
---

# Clean Repositories Standard Operating Procedure (`hath0r clean-repos`)

This workflow enforces complete repository hygiene, quality gates, documentation & `CLAUDE.md` synchronization (`CR-CLAUDE-SYNC-001`), agentic security & supply-chain audits (`CR-AGENTIC-SEC-001`), PR lifecycle management, and branch cleanup across all repositories in the OpenSource Project (`/Users/raybayly/Development/OpenSource`).

Whenever the user requests **"clean repo"** or **"clean repos"**, start with the operator CLI (`hath0r clean-repos --all`) and execute the following 13 steps in exact sequence:

---

## 13-Step Clean Repo Lifecycle

### Step 1: Capture All Repositories in the Project
- Discover all repositories in the current suite or project root (`cfg/suite.yaml` / `cfg/products.yaml` under `/Users/raybayly/Development/OpenSource`: `hathor-cli`, `hath0r-atc`, `hath0r-framework`, `hath0r-mcp`, `hath0r-poc`).
- Ensure a micro memory session is active (`hath0r memory session start --task "clean-repos"`).

### Step 2: Ensure All Changes Are Committed & Version Bumped (`CR-SEMVER-BUMP-001`)
- Run `git status -s` in each repository.
- If uncommitted source changes exist:
  - Ensure `VERSION`, `pyproject.toml` / `package.json`, and `CHANGELOG.md` are bumped in step (`hath0r release validate`).
  - Stage and commit with descriptive conventional commit messages (`feat:`, `fix:`, `chore:`).

### Step 3: Cleanup Development Artifacts (`hath0r repo clean`)
- Execute `hath0r repo clean` (or `CleanReposWorkflowBot` Step 3) to remove:
  - Temporary OS artifacts (`.DS_Store`, `Thumbs.db`, `._*`).
  - Testing, profiling, and coverage caches (`.pytest_cache`, `.coverage`, `coverage.xml`, `.ruff_cache`, `.mypy_cache`).
  - Python bytecode and build caches (`__pycache__`, `*.pyc`, `build/`, `dist/`, `*.egg-info`).
- Verify `.gitignore` never ignores `.hath0r/memory/`, `.hath0r/agentgraph/`, `.hath0r/graphs/`, `.hath0r/state/cache/`, or `.hath0r/state/context/`.

### Step 4: Clean Up and Remove Stale Worktrees
- Check active git worktrees using `git worktree list` and prune stale references:
  ```bash
  git worktree prune
  ```

### Step 5: Review Branches, Merge Changes, Resolve Conflicts & Ensure PRs Are Merged
- Query and merge ready Pull Requests via the CLI workflow (`hath0r pr merge <n>` or `gh pr list` / `gh pr merge --squash --delete-branch`).
- Fetch all remote branches (`git fetch --all --prune`), checkout `development`, and pull latest (`hath0r branch sync` or `git pull --rebase origin development`).
- Review every local and remote non-canonical branch (`feature/*`, `chore/*`, `fix/*`, `bugfix/*`, `enhancement/*`, `docs/*`, `release/*`) and merge unmerged commits cleanly into `development`.

### Step 6: Share Knowledge & Compound MemoryGraph (`CR-MEMORY-COMPOUND-001`)
- Synchronize knowledge to `HATH0R-MCP` (`hath0r-mcp`) and the canonical group hub `/Users/raybayly/Development/OpenSource/.hath0r/knowledgebase` (`hath0r docs share` / `hath0r kb smart-query`).
- Write session progress (`hath0r memory session write`) and compound the clean-repo episode into `.hath0r/memory/graph.json` (`hath0r memory compound --type episode`).

### Step 7: Update Documentation, `CLAUDE.md` Sync (`CR-CLAUDE-SYNC-001`), AgentGraph & Security Gates (`CR-AGENTIC-SEC-001`)
- Ensure `README.md`, `AGENTS.md`, `THREATMODEL.md`, and `docs/` reflect all recent changes.
- Synchronize `CLAUDE.md` 1:1 from `AGENTS.md`, export W3C OWL `.ttl` snapshot, and validate AgentGraph + security gates:
  ```bash
  hath0r agentgraph sync
  hath0r agentgraph validate
  hath0r skills audit
  hath0r mcp audit --pin
  hath0r threatmodel validate
  hath0r finops tokens verify-ledger
  ```
  Verify 0 rule conflicts, `CLAUDE.md == AGENTS.md`, and 0 BITE supply-chain findings before proceeding.

### Step 8: Run Task Evaluation (`CR-TASK-EVAL-001`) & Commit Documentation / State Changes
- Sync SHA-256 file hashes (`hath0r memory hash --sync`), run the 4-tier Task Evaluation (`hath0r evals run`), and re-sync file hashes (`hath0r memory hash --sync`):
  ```bash
  hath0r memory hash --sync
  hath0r evals run
  hath0r memory hash --sync
  git add -A && git commit -m "chore: sync documentation, CLAUDE.md, AgentGraph, and evals"
  ```

### Step 9: Ensure All Changes Are PR'd (`hath0r pr create`)
- If working on an active feature branch (`feature/*`, `chore/*`, `fix/*`):
  - Push branch and open a PR targeting `development`:
    ```bash
    hath0r pr create --semver patch
    ```

### Step 10: Monitor PRs and Merge When Checks Pass (`hath0r pr merge`)
- Run antagonistic diff review and status checks (`hath0r pr review --antagonistic`, `gh pr checks`).
- Merge once green (`hath0r pr merge <n>`).

### Step 11: Remove All Stale Feature Branches (Local & Remote)
- Delete all merged and stale non-canonical feature branches locally and on `origin`:
  ```bash
  git branch -D <feature-branch>
  git push origin --delete <feature-branch> 2>/dev/null || true
  git fetch --prune
  ```

### Step 12: Switch Back to Development and Pull/Push Origin
- Switch back to `development`, pull with rebase, and push to `origin`:
  ```bash
  git checkout development
  git pull --rebase origin development
  git push origin development
  ```

### Step 13: Verify Pre-Announce Gates & Announce Complete
- Verify all canonical pre-announce gates:
  ```bash
  hath0r memory verify
  hath0r evals verify
  hath0r quality sonar
  hath0r release validate
  ```
- Present a concise repository status report and the mandatory **Eval Scorecard Summary** (`eval_id`, `task_id`, `passed_gate`, composite `R_task`, Tier 1–4 scores, and `.hath0r/evals/latest.json` path).
