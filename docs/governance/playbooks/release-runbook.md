# Release Runbook — HATH0R MCP

> Role: Operational guide for versioning, package build, and release publishing.  
> Status: Canonical · Member of `hath0r-opensource`  
> Policy: [Semantic Versioning](../semantic-versioning.md) · [HATH0R-CLI SemVer](https://github.com/Bayly-AI/HATH0R-CLI/blob/development/docs/governance/semantic-versioning.md)

---

## 1. Prerequisites

Before cutting a release:
1. All PRs merged into `development`.
2. Promotion gates satisfied: `development` -> `testing` -> `staging` -> `master`.
3. Working tree is clean: `git status`.
4. Tests and SonarCloud quality gates pass.

---

## 2. Release Steps

### Step 1: Validate Version and Changelog
Verify alignment between `VERSION`, `pyproject.toml`, and `CHANGELOG.md`:
```bash
hath0r release validate
```

### Step 2: Bump Version
Update the root `VERSION` file and `pyproject.toml`:
```bash
echo "1.0.2" > VERSION
```
Update `pyproject.toml` version string to match.
Update `CHANGELOG.md` with the new version section under `## [X.Y.Z] - YYYY-MM-DD`.

### Step 3: Promote along Canonical Path
Promote branch following CR-BAI-001:
```bash
git checkout testing && git merge development
git checkout staging && git merge testing
git checkout master && git merge staging
```

### Step 4: Tag Release on Master
Create an annotated Git tag on `master`:
```bash
git tag -a v1.0.2 -m "Release v1.0.2"
git push origin v1.0.2
```

### Step 5: Verify Automated Release Workflow
The `.github/workflows/release.yml` workflow triggers on push of `v*` tags, builds Python sdist and wheel artifacts, extracts release notes from `CHANGELOG.md`, and creates the GitHub Release with distributions attached.
