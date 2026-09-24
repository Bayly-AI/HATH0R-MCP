#!/usr/bin/env bash
# Post-init checks for hath0r-mcp (HATHOR member).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> HATHOR member bootstrap (hath0r-mcp)"
echo "    root: $ROOT"

missing=0
for path in \
  AGENTS.md \
  cfg/suite.yaml \
  cfg/product.yaml \
  cfg/knowledge-tower.yaml \
  .hath0r/knowledgebase/README.md \
  contracts/hath0r-cli-response-v1.schema.json \
  contracts/exit-codes.yaml \
  MANIFEST.json \
  VERSION \
  NOTICE \
  docs/runbook.md \
  docs \
  bin \
  lib \
  dist \
  src \
  tests
do
  if [[ ! -e "$ROOT/$path" ]]; then
    echo "missing: $path"
    missing=1
  fi
done
if [[ "$missing" -ne 0 ]]; then
  echo "layout incomplete"
  exit 1
fi
echo "==> layout ok"

# Forbidden legacy roots
for bad in .ai .aegis .infraOS; do
  if [[ -e "$ROOT/$bad" ]]; then
    echo "FAIL: forbidden hidden root $bad present (cr-hath0r-root-001)"
    exit 1
  fi
done

# Doctor is advisory after layout verification (suite hub may be partial).
if command -v hath0r >/dev/null 2>&1; then
  echo "==> hath0r --version"
  hath0r --version || true
  if [[ -n "${HATH0R_GROUP_ROOT:-}" ]]; then
    echo "==> HATH0R_GROUP_ROOT=${HATH0R_GROUP_ROOT}"
    echo "==> hath0r doctor (advisory)"
    set +e
    hath0r doctor
    code=$?
    set -e
    if [[ "$code" -ne 0 ]]; then
      echo "doctor exited $code (advisory; layout checks already passed)"
    fi
  else
    echo "==> suite doctor skipped (set HATH0R_GROUP_ROOT to enable)"
  fi
else
  echo "hath0r not found on PATH."
  echo "Install: pipx install hath0r-cli   OR use a GitHub Release binary."
  exit 1
fi

echo "bootstrap ok"
