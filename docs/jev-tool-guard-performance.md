# JEV Tool-Guard — Performance Impact

**Date:** 2026-09-23  
**Host:** macOS developer workstation (local FastAPI `TestClient`, no Docker network hop)  
**Code:** AegisCMCP JEV POC (`src/knowledgebase/core/jev_*.py`, hook in `_execute_mcp_tool`)  
**Method:** Integration suite + dedicated micro-benchmarks and end-to-end MCP `tools/call` timing

## Executive summary

| Mode | Where cost lands | Typical added latency | Impact on agent loops |
|------|------------------|----------------------|------------------------|
| **`off` (default)** | Catalog check skipped when client disabled → early return | **~0 ms** (noise floor) | None |
| **`stub`** | Local heuristics only | **~0.2 ms** guard-only; **~1–2 ms** on full MCP path vs off | Negligible vs tool/IO work |
| **`live` (mock 0 RTT)** | httpx + JSON parse | **~2.5 ms** guard-only; **~2–3 ms** e2e vs off | Small fixed overhead |
| **`live` (real JEV)** | Network + model | **~70–500 ms** (vendor band); measured **~80 ms** and **~250 ms** injected RTT | Dominates mutating tool calls; still cheap vs embeddings/sync |

**Read-only tools are not guarded.** Search/health paths do not call JEV even when the guard is enabled.

---

## Test runs

### Integration + unit (functional)

```bash
KB_TEST_MODE=1 PYTHONPATH=src pytest \
  tests/integration/test_jev_tool_guard_integration.py \
  tests/unit/test_jev_tool_guard.py \
  -v --no-cov
```

**Result (2026-09-23):** **20 passed** in ~6 s.

Coverage:

- MCP `POST /mcp` `tools/call` with stub deny / off allow / live mock allow / live mock deny
- Read-only tool not blocked under stub
- Guard-path latency sanity budgets

### Guard-only micro-benchmark (no FastAPI)

From `test_guard_latency_budget_stub_and_off` (200 iterations after warmup):

| Path | Mean ms / call |
|------|----------------|
| `off` (enabled=false) | **0.0027** |
| `stub` | **0.2310** |
| `live` + MockTransport (0 ms RTT) | **2.4617** |
| `live` + MockTransport (80 ms sleep) | **83.75** |

### End-to-end MCP `tools/call` (FastAPI TestClient)

Handlers stubbed to return immediately (`ok`) or raise if unexpectedly reached. Wall times include ASGI/TestClient overhead (~3–5 ms baseline).

| Scenario | n | mean ms | p50 ms | p95 ms |
|----------|---|---------|--------|--------|
| Read-only `kb_health`, stub **on** (catalog skip) | 40 | **4.278** | 4.142 | 5.469 |
| Mutating `kb_index_delete`, guard **off** | 40 | **4.218** | 4.269 | 5.932 |
| Mutating `kb_index_delete`, **stub** block | 40 | **5.429** | 5.299 | 6.625 |
| Mutating delete, **live mock 0 RTT** deny | 30 | **6.671** | 6.707 | 8.255 |
| Mutating add, **live mock +80 ms** allow | 10 | **90.064** | 89.414 | 93.228 |
| Mutating add, **live mock +250 ms** allow | 8 | **258.139** | 258.384 | 260.286 |

#### Derived overhead (e2e, vs mutating off baseline ~4.2 ms)

| Mode | Δ mean vs off | Notes |
|------|---------------|--------|
| stub block | **+1.2 ms** | Local policy + JSON error payload |
| live mock 0 RTT | **+2.5 ms** | Client + serialize/parse |
| live +80 ms RTT | **+86 ms** | Almost entirely injected/network-like delay |
| live +250 ms RTT | **+254 ms** | Mid of published 70–500 ms JEV band |

Read-only with stub enabled stays within the same ~4 ms TestClient band as mutating-off (no JEV call).

---

## Interpretation for agent control loops

1. **Default `JEV_MODE=off`**  
   Production-safe default: no extra latency, no external dependency.

2. **`stub` for local demos / CI**  
   Validates control-loop wiring with **sub-millisecond to low-millisecond** cost. Suitable for always-on in test environments if desired.

3. **`live` against real JEV**  
   Expect **tens to hundreds of ms per guarded tool call**. That is acceptable for:
   - `kb_index_delete`, `kb_sync_all`, `kb_remove_document`, runbook writes  
   and **not** acceptable if mistakenly applied to high-QPS `kb_search` (the catalog already excludes those).

4. **Timeout**  
   Default `JEV_TIMEOUT_SECONDS=2.5`. Worst case when JEV hangs: up to timeout then `JEV_ON_ERROR` (`allow` fail-open by default). Fail-open avoids turning JEV outages into full agent freezes; use `deny` only where safety > availability.

5. **Compared to existing heavy paths**  
   - Hybrid search + embeddings: often **tens–hundreds of ms to seconds**  
   - `kb_sync_all` / directory index: **seconds to minutes**  
   JEV live overhead is in the same order as a light network hop, far below bulk mutating work.

---

## What was *not* measured here

- Real TypeSafe/jevai.org RTT from this workstation (no API key in CI; live path used `httpx.MockTransport`).
- Concurrent load / connection pooling under multi-agent fan-out.
- Docker bridge or in-cluster service mesh hop to AegisCMCP.

To re-measure with a real key:

```bash
export JEV_MODE=live
export JEV_API_KEY=...   # from .credentials — never commit
# single timed call against a running server on :48080
```

---

## Recommendations

| Environment | Suggested mode | Rationale |
|-------------|----------------|-----------|
| Local unit/integration CI | `off` or `stub` | Fast, deterministic |
| Dev agent demos | `stub` or `live` | Show block payloads without prod risk |
| Staging mutating tools | `live`, `JEV_ON_ERROR=deny` | Prefer safe failure |
| Production (initial) | `off` until approval UX exists | POC blocks `confirm`/`review` without a human channel |

**Do not** lower `JEV_TIMEOUT_SECONDS` below ~1 s for live mode; cold TLS + model can exceed that.

---

## Reproduce

```bash
cd /Users/raybayly/Development/BAI/MCP
. .venv/bin/activate  # if present

# Functional
KB_TEST_MODE=1 PYTHONPATH=src pytest \
  tests/integration/test_jev_tool_guard_integration.py \
  tests/unit/test_jev_tool_guard.py -v --no-cov -s
# Look for: JEV_GUARD_PERF off_ms=... stub_ms=... live_mock_ms=... live_80ms_rtt_ms=...

# Full API suite (includes pre-existing non-JEV failures if any)
KB_TEST_MODE=1 PYTHONPATH=src pytest tests/api -q --no-cov
```

Related docs: [`jev-tool-guard-poc.md`](jev-tool-guard-poc.md), [`cfg/jev.json`](../cfg/jev.json).
