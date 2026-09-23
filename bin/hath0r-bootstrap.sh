#!/usr/bin/env bash
# Minimal post-unpack checks for the HATHOR OpenSource fileset.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> HATHOR fileset bootstrap: BAI-1-NATION-MCP (hath0r-mcp)"
echo "    root: $ROOT"

# Resolve hath0r CLI
HATH0R_BIN=""
if command -v hath0r >/dev/null 2>&1 && hath0r --version >/dev/null 2>&1; then
  HATH0R_BIN="hath0r"
elif [[ -d "/Users/raybayly/Development/OpenSource/hathor-cli/src" ]]; then
  HATH0R_BIN="python3 -m hath0r_cli.cli"
  export PYTHONPATH="/Users/raybayly/Development/OpenSource/hathor-cli/src:${PYTHONPATH:-}"
else
  echo "hath0r not found on PATH and Hath0r-CLI source unavailable."
  echo "Install: pipx install hath0r-cli   OR use a GitHub Release binary."
  exit 1
fi

echo "==> hath0r --version"
$HATH0R_BIN --version || true

# Group root orientation
export HATH0R_GROUP_ROOT="${HATH0R_GROUP_ROOT:-/Users/raybayly/Development/OpenSource}"
echo "==> HATH0R_GROUP_ROOT=${HATH0R_GROUP_ROOT}"

# Check contract files
echo "==> Verifying pinned Hath0r contracts"
test -f contracts/exit-codes.yaml
test -f contracts/hath0r-cli-response-v1.schema.json
test -f cfg/product.yaml
test -f cfg/suite.yaml
test -f cfg/knowledge-tower.yaml

echo "bootstrap ok"
