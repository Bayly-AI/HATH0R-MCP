#!/usr/bin/env bash
# Canonical CR-TASK-EVAL-001 post-task evaluation & pre-push verification hook
set -euo pipefail
export OTEL_SDK_DISABLED=true
if command -v hath0r >/dev/null 2>&1; then
  hath0r evals verify --auto-run
fi
