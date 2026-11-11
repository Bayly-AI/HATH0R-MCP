"""Read-only Level 1 views of the HATH0R-CLI industrial QA state (#594).

The numbers are produced by the Hath0r tools in HATH0R-CLI (``hath0r evals msa``, ``hath0r spc``,
``hath0r fmea``, ``hath0r andon``). These readers only load what those tools wrote under ``.hath0r/``
in the workspace, so the MCP never recomputes an eval. The workspace is the repository root, or
``HATH0R_MCP_QA_ROOT`` when the CLI workspace is mounted elsewhere. Client input never names a path.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

MAX_STATE_BYTES = 2 * 1024 * 1024
MAX_ANDON_EVENTS = 5000
_PROCESS_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_DEFAULT_ROOT = Path(__file__).resolve().parents[3]
_STATE_DIR = ".hath0r"
_PRIORITY_ORDER = {"H": 0, "M": 1, "L": 2}


def qa_root() -> Path:
    """Return the workspace whose ``.hath0r/`` state is reported."""
    env = os.environ.get("HATH0R_MCP_QA_ROOT", "").strip()
    return Path(env).resolve() if env else _DEFAULT_ROOT


def _state(root: Path | None) -> Path:
    return (root or qa_root()) / _STATE_DIR


def _read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        raw = handle.read(MAX_STATE_BYTES + 1)
    if len(raw) > MAX_STATE_BYTES:
        raise ValueError(f"{path.name} exceeds the {MAX_STATE_BYTES} byte limit for QA state")
    return raw.decode("utf-8")


def _missing(what: str, command: str) -> dict[str, Any]:
    return {"success": False, "exists": False, "message": f"No {what} yet. Run '{command}' in HATH0R-CLI."}


def msa_report(root: Path | None = None) -> dict[str, Any]:
    """Latest gauge (Gage R&R) study of the eval pipeline, without raw measurements."""
    text = _read_text(_state(root) / "evals" / "msa" / "latest.json")
    if text is None:
        return _missing("MSA study", "hath0r evals msa run")
    study = json.loads(text)
    study.pop("measurements", None)
    return {"success": True, "exists": True, "source": "hath0r evals msa report", **study}


def spc_status(root: Path | None = None, metric: str | None = None) -> dict[str, Any]:
    """Latest SPC status (charts and capability) written by ``hath0r spc status`` or the gate."""
    text = _read_text(_state(root) / "spc" / "latest.json")
    if text is None:
        return _missing("SPC status", "hath0r spc status")
    status = json.loads(text)
    if metric:
        metrics = status.get("metrics") or {}
        if metric not in metrics:
            raise ValueError(f"unknown metric '{metric}'. Known: {', '.join(sorted(metrics))}")
        status["metrics"] = {metric: metrics[metric]}
    return {"success": True, "exists": True, "source": "hath0r spc status", **status}


def _fmea_files(base: Path, process: str | None) -> list[Path]:
    if process:
        return [base / f"{process}.yaml"]
    if not base.is_dir():
        return []
    return sorted(base.glob("*.yaml"))


def _rpn(row: dict[str, Any]) -> int:
    return int(row.get("rpn") or 0)


def _row_matches(row: dict[str, Any], priority: str | None, min_rpn: int | None) -> bool:
    if priority and row.get("action_priority") != priority:
        return False
    return min_rpn is None or _rpn(row) >= min_rpn


def fmea_query(
    root: Path | None = None,
    process: str | None = None,
    priority: str | None = None,
    min_rpn: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Rows of the process FMEAs, highest action priority and RPN first."""
    if process is not None and not _PROCESS_RE.match(process):
        raise ValueError("process must be a lowercase FMEA name such as 'end-of-task'")
    if priority is not None and priority not in _PRIORITY_ORDER:
        raise ValueError("priority must be H, M or L")
    rows: list[dict[str, Any]] = []
    processes: list[str] = []
    for path in _fmea_files(_state(root) / "fmea", process):
        text = _read_text(path)
        if text is None:
            continue
        data = yaml.safe_load(text) or {}
        name = str(data.get("process") or path.stem)
        processes.append(name)
        rows.extend({"process": name, **row} for row in data.get("rows") or [] if _row_matches(row, priority, min_rpn))
    if not processes:
        what = f"FMEA for '{process}'" if process else "FMEA"
        return _missing(what, "hath0r fmea init <process>")
    rows.sort(key=lambda r: (_PRIORITY_ORDER.get(str(r.get("action_priority")), 3), -_rpn(r)))
    limit = max(1, min(int(limit), 500))
    return {
        "success": True,
        "exists": True,
        "source": "hath0r fmea report",
        "processes": processes,
        "total": len(rows),
        "rows": rows[:limit],
        "high_priority": sum(1 for r in rows if r.get("action_priority") == "H"),
    }


def andon_status(root: Path | None = None) -> dict[str, Any]:
    """Active Andon events (open or acknowledged) folded from the hash-chained ledger."""
    text = _read_text(_state(root) / "state" / "andon" / "events.jsonl")
    if text is None:
        return {"success": True, "exists": False, "stopped": False, "active": [], "source": "hath0r andon status"}
    state: dict[str, dict[str, Any]] = {}
    lines = [ln for ln in text.splitlines() if ln.strip()][-MAX_ANDON_EVENTS:]
    for line in lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        eid = str(rec.get("event_id"))
        kind = rec.get("type")
        if kind == "event":
            state[eid] = {k: rec.get(k) for k in ("event_id", "severity", "source", "reason", "workflow_id", "step_id", "timestamp")}
            state[eid]["state"] = "open"
        elif eid in state and kind == "ack":
            state[eid]["state"] = "acknowledged"
        elif eid in state and kind == "clear":
            state[eid]["state"] = "cleared"
    active = [e for e in state.values() if e["state"] != "cleared"]
    stops = [e for e in active if e.get("severity") == "stop"]
    return {
        "success": True,
        "exists": True,
        "source": "hath0r andon status",
        "stopped": bool(stops),
        "active": active,
        "stops": len(stops),
        "warnings": len(active) - len(stops),
        "note": "Read-only. Hash-chain verification and ack/clear stay in 'hath0r andon verify|ack|clear'.",
    }
