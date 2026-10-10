---
name: clean-repos
description: Comprehensive standard operating procedure for cleaning repositories across the suite. Activates whenever the user says "clean repo", "clean repos", "clean repository", "clean repositories", or requests repository cleanup and branch hygiene.
---

# Clean Repositories Standard Operating Procedure

This workflow enforces complete repository hygiene, quality gates, documentation sync, PR lifecycle management, and branch cleanup across all repositories in the workspace or suite.

Whenever the user requests **"clean repo"** or **"clean repos"**, execute the following 13 steps in exact sequence:

---

## 13-Step Clean Repo Lifecycle

### Step 1: Capture All Repositories in the Project
- Discover all repositories in the current suite or project root (e.g. inspecting `cfg/suite.yaml` or listing git repositories in `/Users/raybayly/Development/Ray`).
- Ensure all downstream steps are systematically executed across **every** member repository.

### Step 2: Ensure All Changes Are Committed
- Run `git status -s` in each repository.
- If uncommitted modifications or untracked source files exist:
  - Verify that changes belong to source control.
  - Stage and commit with descriptive conventional commit messages (`feat:`, `fix:`, `chore:`).

### Step 3: Cleanup Development Artifacts
- Remove temporary OS artifacts (`.DS_Store`, `Thumbs.db`, `._*`).
- Remove testing, profiling, and coverage caches (`.pytest_cache`, `.coverage`, `coverage.xml`).
- Remove Python bytecode and build caches (`__pycache__`, `*.pyc`, `build/`, `dist/`, `*.egg-info`).
- Remove unneeded scratch scripts and temporary logs.
- Verify `.gitignore` is up to date to prevent re-committing artifacts.

### Step 4: Clean Up and Remove Stale Worktrees
- Check active git worktrees using `git worktree list`.
- Prune stale worktree references:
  ```bash
  git worktree prune
  ```
- Remove any unneeded detached or stale worktree directories.

### Step 5: Ensure All PRs in the Repo Are Merged
- Query open Pull Requests using `gh pr list`.
- Verify if any open PRs are pending review, approval, or merge.
- Address blockers or merge ready PRs.

### Step 6: Share Knowledge
- Update shared knowledge bases, indexing systems, and memory stores:
  - Ray-MCP knowledge roots (OneDrive knowledge roots: Author, Career, Documents, Books, Businesses, Cars, Projects).
  - Sync indexed data to `.hath0r/knowledgebase` single source of truth when applicable.

### Step 7: Update Documentation
- Ensure all recent features, API modifications, database schemas, and architectural changes are documented in:
  - `README.md`
  - `AGENTS.md`
  - `docs/` (playbooks, runbooks, architecture specs)

### Step 8: Commit Documentation & Knowledge Changes
- Stage any updated documentation, governance files, or knowledge sync artifacts.
- Commit them cleanly:
  ```bash
  git add -A && git commit -m "docs: update documentation, runbooks, and knowledge sync"
  ```

### Step 9: Ensure All Changes Are PR'd
- If working on a feature branch (`feature/*`):
  - Push branch to remote: `git push -u origin <branch>`
  - Create Pull Request if one does not exist:
    ```bash
    gh pr create --title "..." --body "..."
    ```

### Step 10: Monitor PRs and Merge When Pass (Or Fix So It Does)
- Run status checks: `gh pr checks`
- If CI/CD checks fail:
  - Diagnose failure, apply fixes, run local tests (`pytest`, `npm test`), and push commits until green.
- Merge the PR once checks pass:
  ```bash
  gh pr merge --squash --delete-branch
  ```

### Step 11: Delete Feature Branch (Local & Remote)
- Once the PR is merged, delete the feature branch locally and ensure remote is purged:
  ```bash
  git branch -d <feature-branch>
  git push origin --delete <feature-branch> 2>/dev/null || true
  git fetch --prune
  ```

### Step 12: Return to Development and Pull Origin
- Switch to the main development branch (`development` or `main` according to repository promotion policy):
  ```bash
  git checkout development
  git pull origin development
  ```
- Verify `git status` reports working tree is clean and up to date.

### Step 13: Announce Complete
- Provide a structured status report confirming the clean status of all repositories, merged PRs, updated docs, and branch state.
