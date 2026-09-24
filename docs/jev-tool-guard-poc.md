# JEV Tool-Guard POC (AegisCMCP)

Proof-of-concept: insert **TypeSafe JEV** (System One) into the MCP **agent control loop** so consequential tool calls are judged before execution.

## Control loop

```text
Agent ──tools/call──► AegisCMCP._execute_mcp_tool
                         │
                         ├─ read-only tool? ──► execute handler
                         │
                         └─ mutating tool + JEV enabled?
                               │
                               ▼
                         JEV tool-guard (choice: allow|confirm|review|deny)
                               │
                    ┌──────────┴──────────┐
                    │ blocked             │ allow
                    ▼                     ▼
             MCP isError + JSON     run tool handler
             (no side effects)
```

## Files

| Path | Role |
|------|------|
| `src/knowledgebase/core/jev_client.py` | Settings, HTTP/stub client, response parsing |
| `src/knowledgebase/core/jev_tool_guard.py` | Mutating-tool catalog + evaluate/format helpers |
| `cfg/jev.json` | Operator-facing reference config |
| `tests/unit/test_jev_tool_guard.py` | Unit tests (no live network) |
| `tests/integration/test_jev_tool_guard_integration.py` | MCP `tools/call` path + latency budgets |
| `docs/jev-tool-guard-performance.md` | Measured overhead by mode |

Hook point: `src/knowledgebase/api/main.py` → `_execute_mcp_tool`.

## Enable

Default is **off** (zero behavior change).

### Offline stub (no API key)

```bash
export JEV_MODE=stub
# restart AegisCMCP / make docker-up
```

Stub heuristics:

- `delete` / `remove` / `force` → **deny** (blocked)
- writes / sync / reindex / batch → **confirm** (blocked in POC)
- other guarded tools → **review** (blocked)

### Live JEV

```bash
export JEV_MODE=live
export JEV_API_KEY=ts_...   # or TYPESAFE_API_KEY / AUTOJEV_API_KEY
# optional:
# export JEV_ENDPOINT=https://www.jevai.org/api/v1/decisions/tool-guard
# export JEV_PROTOCOL=preset   # or systemone
# export JEV_ON_ERROR=allow    # fail-open if JEV is down
# export JEV_TIMEOUT_SECONDS=2.5
```

Store keys under `/Users/raybayly/Development/.credentials/` and inject via `.env` — never commit them.

## Try it

With the service up and `JEV_MODE=stub`:

```bash
# Read-only: should succeed (not guarded)
curl -sS http://localhost:48080/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kb_health","arguments":{}}}'

# Mutating: should return isError with jev_tool_guard_blocked
curl -sS http://localhost:48080/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"kb_index_delete","arguments":{"name":"demo-index"}}}'
```

## Policy notes

- JEV confidence is a **signal**; this service enforces `block_decisions`.
- POC blocks `confirm` and `review` so agents cannot self-approve.
- Production follow-ups: human approval channel, allow-list overrides, audit log sink, per-env stricter `on_error=deny`.

## Tests

```bash
cd /Users/raybayly/Development/BAI/MCP
# Unit
PYTHONPATH=src python -m pytest tests/unit/test_jev_tool_guard.py -q --no-cov
# Integration (MCP tools/call path + latency budgets)
PYTHONPATH=src python -m pytest tests/integration/test_jev_tool_guard_integration.py -v --no-cov -s
```

Performance impact (measured overhead by mode): [`jev-tool-guard-performance.md`](jev-tool-guard-performance.md).
