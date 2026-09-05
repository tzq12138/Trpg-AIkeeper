"""Small, redacted, action-level trace for diagnosing AI-KP resolutions."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from .action_state import RESOLUTION_OUTCOMES


_FORBIDDEN_KEY_PARTS = {
    "token",
    "password",
    "api_key",
    "secret",
    "raw_safety_text",
    "safety_text",
    "private_note",
}
_MAX_STRING = 1000
_MAX_LIST = 24
_MAX_KEYS = 64
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)(owner_token|player_token|access_token|password|api_key|secret|"
    r"private_note|raw_safety_text)\s*[:=]\s*[^\s,;]+"
)


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _forbidden_key(value: Any) -> bool:
    key = _normalized_key(value)
    return key in _FORBIDDEN_KEY_PARTS or any(part in key for part in _FORBIDDEN_KEY_PARTS)


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:_MAX_KEYS]:
            if _forbidden_key(key):
                continue
            result[str(key)] = _safe_value(item)
        return result
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:_MAX_LIST]]
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_STRING]


def _safe_text(value: str) -> str:
    text = str(value or "")[:_MAX_STRING]
    return _SENSITIVE_TEXT_PATTERN.sub("[redacted]", text)


def _json_value(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _hash(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ResolutionTraceRecorder:
    """Persist one idempotent trace document per action.

    The recorder deliberately uses its own pooled connection when the caller
    provides one: trace writes are auxiliary logging and must not share the
    single cursor slot of the authoritative connection, otherwise a trace
    write can close a cursor that an in-flight API request still needs.
    """

    def __init__(self, conn):
        from ..db_adapter import PgConnection

        # Keep the original reference so close() can fall back to it; lazy
        # checkout on a fresh PgConnection keeps callers behind a pool safe.
        self._borrowed = conn
        self._own = None
        pool = getattr(conn, "_pool", None)
        if pool is not None:
            self._own = PgConnection(pool)
        self.conn = self._own or conn

    def close(self) -> None:
        """Return the dedicated connection to the pool, if one was checked out."""
        own, self._own = self._own, None
        if own is not None:
            own.close()
        self.conn = self._borrowed

    def start(self, action: dict[str, Any], *, state_version: int = 0) -> str:
        action_id = str(action.get("action_id") or "").strip()
        if not action_id:
            raise ValueError("resolution_trace_action_required")
        existing = self.conn.execute(
            "SELECT resolution_trace_id FROM actions WHERE action_id = %s",
            (action_id,),
        ).fetchone()
        if existing and existing.get("resolution_trace_id"):
            return str(existing["resolution_trace_id"])

        room_id = str(action.get("room_id") or "")
        trace_id = f"trace-{uuid.uuid4().hex}"
        room = self.conn.execute(
            "SELECT version_bundle, version_bundle_hash FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        version_bundle = _json_value(room.get("version_bundle") if room else None)
        input_summary = {
            "intent_type": str(action.get("intent_type") or ""),
            "declared_intent": _safe_text(action.get("declared_intent") or ""),
        }
        trace = {
            "trace_version": "resolution_trace.v1",
            "resolution_trace_id": trace_id,
            "action_id": action_id,
            "room_id": room_id,
            "state_version": int(state_version or 0),
            "version_bundle": _safe_value(version_bundle),
            "version_bundle_hash": str(room.get("version_bundle_hash") or "") if room else "",
            "input": input_summary,
            "input_hash": _hash(input_summary),
            "phases": [],
            "authority_chain": {
                "mechanic_plan_advisory": None,
                "authoritative_mechanic_plan": None,
                "roll_receipt": None,
                "state_mutations": None,
                "spoiler_guard": None,
                "projection_dispatch": None,
            },
            "provider": {"attempts": [], "fallback": None},
            "status": "in_progress",
            "resolution_outcome": None,
            "trace_hash": "",
        }
        try:
            self.conn.execute(
                "INSERT INTO resolution_traces "
                "(resolution_trace_id, action_id, room_id, state_version, status, trace) "
                "VALUES (%s, %s, %s, %s, 'in_progress', %s) "
                "ON CONFLICT (action_id) DO NOTHING",
                (trace_id, action_id, room_id, int(state_version or 0), json.dumps(trace, ensure_ascii=False)),
            )
            row = self.conn.execute(
                "SELECT resolution_trace_id, room_id, trace FROM resolution_traces "
                "WHERE action_id = %s",
                (action_id,),
            ).fetchone()
            trace_id = str(row["resolution_trace_id"] if row else trace_id)
            self.conn.execute(
                "UPDATE actions SET resolution_trace_id = %s "
                "WHERE action_id = %s AND resolution_trace_id IS NULL",
                (trace_id, action_id),
            )
            stored_trace = _json_value(row.get("trace") if row else None) or trace
            self._persist_secure_trace(
                trace_id,
                str(row.get("room_id") or room_id) if row else room_id,
                stored_trace,
            )
            self.conn.commit()
        except Exception:
            self._rollback()
            raise
        return trace_id

    def record_stage(
        self,
        action_id: str,
        name: str,
        data: dict[str, Any] | None = None,
        *,
        status: str = "completed",
    ) -> None:
        trace_row = self._row(action_id)
        if not trace_row:
            action = self.conn.execute(
                "SELECT * FROM actions WHERE action_id = %s", (action_id,)
            ).fetchone()
            if not action:
                return
            self.start(dict(action), state_version=0)
            trace_row = self._row(action_id)
        if not trace_row:
            return
        trace = _json_value(trace_row.get("trace"))
        safe_data = _safe_value(data or {})
        trace.setdefault("phases", []).append({
            "name": str(name),
            "status": str(status),
            "data": safe_data,
        })
        authority = trace.setdefault("authority_chain", {})
        for source, target in (
            ("mechanic_plan", "mechanic_plan_advisory"),
            ("authoritative_mechanic_plan", "authoritative_mechanic_plan"),
            ("roll_receipt", "roll_receipt"),
            ("state_mutations", "state_mutations"),
            ("spoiler_guard", "spoiler_guard"),
            ("projection_dispatch", "projection_dispatch"),
        ):
            if isinstance(safe_data, dict) and source in safe_data:
                authority[target] = safe_data[source]
        if isinstance(safe_data, dict) and "provider_attempts" in safe_data:
            trace.setdefault("provider", {})["attempts"] = safe_data["provider_attempts"]
        self._write(trace_row, trace)

    def finalize(
        self,
        action_id: str,
        *,
        status: str,
        outcome: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        trace_row = self._row(action_id)
        if not trace_row:
            return
        trace = _json_value(trace_row.get("trace"))
        safe_data = _safe_value(data or {})
        trace.setdefault("phases", []).append({
            "name": "finalized",
            "status": str(status),
            "data": safe_data,
        })
        trace["status"] = str(status)
        normalized_outcome = str(outcome) if outcome in RESOLUTION_OUTCOMES else None
        trace["resolution_outcome"] = normalized_outcome
        trace["trace_hash"] = ""
        trace_hash = _hash(trace)
        trace["trace_hash"] = trace_hash
        try:
            self.conn.execute(
                "UPDATE resolution_traces SET status = %s, resolution_outcome = %s, "
                "trace = %s, trace_hash = %s, updated_at = NOW() "
                "WHERE resolution_trace_id = %s",
                (
                    str(status),
                    normalized_outcome,
                    json.dumps(trace, ensure_ascii=False),
                    trace_hash,
                    trace_row["resolution_trace_id"],
                ),
            )
            self._persist_secure_trace(
                str(trace_row["resolution_trace_id"]),
                str(trace_row.get("room_id") or trace.get("room_id") or ""),
                trace,
            )
            self.conn.commit()
        except Exception:
            self._rollback()
            raise

    def get(self, action_id: str) -> dict[str, Any] | None:
        row = self._row(action_id)
        if not row:
            return None
        trace = _json_value(row.get("trace"))
        trace["resolution_trace_id"] = row["resolution_trace_id"]
        trace["status"] = row.get("status") or trace.get("status")
        trace["resolution_outcome"] = row.get("resolution_outcome") or trace.get("resolution_outcome")
        trace["trace_hash"] = row.get("trace_hash") or trace.get("trace_hash")
        return trace

    def _row(self, action_id: str):
        return self.conn.execute(
            "SELECT resolution_trace_id, room_id, status, resolution_outcome, trace, trace_hash "
            "FROM resolution_traces WHERE action_id = %s",
            (action_id,),
        ).fetchone()

    def _write(self, trace_row: dict[str, Any], trace: dict[str, Any]) -> None:
        try:
            self.conn.execute(
                "UPDATE resolution_traces SET trace = %s, updated_at = NOW() "
                "WHERE resolution_trace_id = %s",
                (
                    json.dumps(trace, ensure_ascii=False),
                    trace_row["resolution_trace_id"],
                ),
            )
            self._persist_secure_trace(
                str(trace_row["resolution_trace_id"]),
                str(trace_row.get("room_id") or trace.get("room_id") or ""),
                trace,
            )
            self.conn.commit()
        except Exception:
            self._rollback()
            raise

    def _persist_secure_trace(
        self,
        trace_id: str,
        room_id: str,
        trace: dict[str, Any],
    ) -> None:
        from .resolution_trace_security import (
            TRACE_ENCRYPTION_KEY_VERSION,
            encrypt_resolution_trace,
        )

        ciphertext, payload_hash = encrypt_resolution_trace(trace)
        self.conn.execute(
            "INSERT INTO resolution_trace_secure_payloads "
            "(resolution_trace_id, room_id, ciphertext, payload_hash, "
            "encryption_key_version, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, NOW() + INTERVAL '30 days') "
            "ON CONFLICT (resolution_trace_id) DO UPDATE "
            "SET room_id = EXCLUDED.room_id, ciphertext = EXCLUDED.ciphertext, "
            "payload_hash = EXCLUDED.payload_hash, "
            "encryption_key_version = EXCLUDED.encryption_key_version, "
            "expires_at = resolution_trace_secure_payloads.expires_at, "
            "updated_at = NOW()",
            (
                trace_id,
                room_id,
                ciphertext,
                payload_hash,
                TRACE_ENCRYPTION_KEY_VERSION,
            ),
        )

    def _rollback(self) -> None:
        rollback = getattr(self.conn, "rollback", None)
        if callable(rollback):
            rollback()
            return
        raw_connection = getattr(self.conn, "_conn", None)
        if raw_connection is not None:
            raw_connection.rollback()
