"""V3 — per-session driver registry for run_session_benchmark.py.

Each driver receives (session_id, plan_entry, base_url, output_dir) and
returns {"ok": bool, "reason_code"?, "session_row"?, "action_rows"?,
"session_id": ...}. Drivers drive the REAL HTTP/WS chain (register
independent identities, join a new room, complete real Session Zero probes,
submit actions, wait for server receipts) — they never touch the database
and never call engine internals.

The live simulation/fault drivers are V4-scope (they need the running frozen
service with a probed real Provider); until then this registry returns an
honest "driver_not_implemented" so the runner exit-code contract (1 = plan
incomplete) stays truthful instead of fabricating sessions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def run_session(
    *,
    session_id: str,
    plan: dict,
    base_url: str,
    output_dir: str,
) -> dict:
    run_kind = plan.get("run_kind")
    if run_kind not in ("simulation", "browser", "fault"):
        return {
            "session_id": session_id,
            "ok": False,
            "reason_code": "session_kind_invalid",
        }
    return {
        "session_id": session_id,
        "ok": False,
        "reason_code": "driver_not_implemented_v4",
        "note": (
            f"{run_kind} driver not yet implemented: live collection is the "
            "V4 wave against the frozen service (real HTTP/WS, real Provider)."
        ),
    }


def write_session_row(output_dir: str, session: dict) -> None:
    with open(f"{output_dir}/benchmark/sessions.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(session, ensure_ascii=False) + "\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
