<!-- Choose the correct template path if your client supports it:
  Feature/work → .github/PULL_REQUEST_TEMPLATE/feature.md
  Release/promote → .github/PULL_REQUEST_TEMPLATE/release.md
  Default below assumes work → development.
-->
## Summary

## Issue
Fixes #

## PR class
- [ ] **Feature/work** → base `development`
- [ ] **Release/promotion** → base `testing`|`staging`|`master` (use release template)

## Version Impact (SemVer)
- [ ] `major` — Breaking change
- [ ] `minor` — New feature / capability
- [ ] `patch` — Bug fix / minor update
- [ ] `none` — Maintenance / doc chore

## Checks
- [ ] `validate-promotion-path`
- [ ] CI
- [ ] CODEOWNERS when required
- [ ] Human gate if staging/master
## Quality gates
- [ ] CI / tests
- [ ] **SonarCloud Quality Gate** green (hard stop if failed; do not weaken thresholds)
