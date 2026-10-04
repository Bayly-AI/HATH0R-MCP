# Contributing to HATH0R-MCP

Thank you for your interest in contributing to **HATH0R-MCP**, the Model Context Protocol knowledge engine for the Hath0r OpenSource Suite.

## Governance & Rules

All contributions to this repository follow standard Hath0r suite policies:

- **Issue First**: Create a GitHub issue before opening a work branch or PR.
- **Base Branch**: Feature and chore pull requests **MUST target `development`**. Feature PRs targeting `master`, `staging`, or `testing` will fail validation.
- **Branch Naming**: Branch from `development` using the format:
  ```text
  feature|bugfix|enhancement|research|fix|chore/<issue-number>-short-slug
  ```
  Example: `feature/24-add-fastmcp-tool`
- **Promotion Path (CR-BAI-001)**:
  ```text
  development → testing → staging → master (Production)
  ```
- **Semantic Versioning**: Declare version impact (`major`, `minor`, `patch`, `none`) in the PR description or labels.

---

## Local Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Bayly-AI/HATH0R-MCP.git
   cd HATH0R-MCP
   git checkout development
   ```

2. **Set up the virtual environment & dependencies**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt -e .
   ```

3. **Run the test suite**:
   ```bash
   KB_TEST_MODE=1 pytest
   ```

4. **Verify formatting & linting**:
   ```bash
   ruff check src/ tests/
   ```

5. **Run the local MCP server**:
   ```bash
   make serve
   # In another terminal:
   make smoke-local
   ```

---

## Submitting a Pull Request

1. Create a GitHub issue describing your proposed change or fix.
2. Create your branch from `development`:
   ```bash
   git checkout development
   git pull origin development
   git checkout -b feature/<issue-number>-your-feature
   ```
3. Make your changes and add tests for any new functionality.
4. Ensure all tests pass: `KB_TEST_MODE=1 pytest`.
5. Push your branch and open a PR against `development` on GitHub.
6. Complete the PR checklist and declare your SemVer impact.

Thank you for contributing!
