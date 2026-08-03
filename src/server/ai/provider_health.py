"""Consecutive health tracking for a room's immutable AI binding."""

import hashlib
import json
import uuid
from typing import Any

from ..events.event_log import EventLog


FAILURE_THRESHOLD = 3


def _json_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def current_runtime_binding(executor, room_id: str) -> dict[str, Any]:
    row = executor.execute(
        "SELECT state FROM host_states WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    state = _json_value(row.get("state") if row else {})
    ai_config = _json_value(state.get("ai_config"))
    return _json_value(ai_config.get("runtime_binding"))


def binding_id(binding: dict[str, Any]) -> str:
    explicit = str(binding.get("binding_id") or "").strip()
    if explicit:
        return explicit
    canonical = json.dumps(
        binding,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "binding:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def error_category(error: BaseException | str) -> str:
    if isinstance(error, TimeoutError):
        return "timeout"
    name = (
        type(error).__name__.lower()
        if isinstance(error, BaseException)
        else str(error).strip().lower()
    )
    if "timeout" in name:
        return "timeout"
    if "schema" in name or "invalid" in name or "incomplete" in name:
        return "invalid_response"
    if "null" in name or "empty" in name:
        return "empty_response"
    return "provider_error"


class RoomProviderHealth:
    def __init__(self, conn):
        self.conn = conn

    def record_failure(
        self,
        room_id: str,
        expected_binding_id: str,
        category: str,
    ) -> int | None:
        with self.conn.transaction() as tx:
            room = tx.execute(
                "SELECT integrity_status FROM rooms WHERE room_id = %s FOR UPDATE",
                (room_id,),
            ).fetchone()
            if not room:
                return None
            current = current_runtime_binding(tx, room_id)
            if binding_id(current) != expected_binding_id:
                return None
            previous = tx.execute(
                "SELECT binding_id, consecutive_failures, status "
                "FROM room_provider_health WHERE room_id = %s FOR UPDATE",
                (room_id,),
            ).fetchone()
            previous_count = (
                int(previous.get("consecutive_failures") or 0)
                if previous and previous.get("binding_id") == expected_binding_id
                else 0
            )
            count = previous_count + 1
            was_paused = bool(previous and previous.get("status") == "paused")
            should_pause = count >= FAILURE_THRESHOLD
            status = "paused" if should_pause or was_paused else "healthy"
            tx.execute(
                "INSERT INTO room_provider_health "
                "(room_id, binding_id, consecutive_failures, status, "
                "last_error_category, last_failure_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, NOW(), NOW()) "
                "ON CONFLICT (room_id) DO UPDATE SET "
                "binding_id = EXCLUDED.binding_id, "
                "consecutive_failures = EXCLUDED.consecutive_failures, "
                "status = EXCLUDED.status, "
                "last_error_category = EXCLUDED.last_error_category, "
                "last_failure_at = NOW(), updated_at = NOW()",
                (room_id, expected_binding_id, count, status, category),
            )
            if not should_pause or was_paused:
                return None
            paused = tx.execute(
                "UPDATE rooms SET integrity_status = 'paused_provider', "
                "integrity_reason = 'provider_unavailable', "
                "integrity_source = 'provider_health', "
                "integrity_state_version = state_version, "
                "integrity_updated_at = NOW() "
                "WHERE room_id = %s AND integrity_status = 'healthy' "
                "RETURNING room_id",
                (room_id,),
            ).fetchone()
            if not paused:
                return None
            tx.execute(
                "INSERT INTO room_provider_health_audits "
                "(provider_health_audit_id, room_id, binding_id, action, "
                "error_category) VALUES (%s, %s, %s, 'paused', %s)",
                (
                    f"provider-health-{uuid.uuid4().hex}",
                    room_id,
                    expected_binding_id,
                    category,
                ),
            )
            return EventLog(tx).log_event(
                room_id,
                "s2c_runtime_integrity_changed",
                "party",
                {
                    "status": "paused_provider",
                    "reasonCode": "provider_unavailable",
                    "allowedActions": ["read", "export", "wait_for_recovery"],
                },
                commit=False,
            )

    def record_success(self, room_id: str, expected_binding_id: str) -> None:
        with self.conn.transaction() as tx:
            if binding_id(current_runtime_binding(tx, room_id)) != expected_binding_id:
                return
            previous = tx.execute(
                "SELECT status FROM room_provider_health "
                "WHERE room_id = %s FOR UPDATE",
                (room_id,),
            ).fetchone()
            status = (
                "paused"
                if previous and previous.get("status") == "paused"
                else "healthy"
            )
            tx.execute(
                "INSERT INTO room_provider_health "
                "(room_id, binding_id, consecutive_failures, status, "
                "last_error_category, last_success_at, updated_at) "
                "VALUES (%s, %s, 0, %s, '', NOW(), NOW()) "
                "ON CONFLICT (room_id) DO UPDATE SET "
                "binding_id = EXCLUDED.binding_id, consecutive_failures = 0, "
                "status = %s, last_error_category = '', "
                "last_success_at = NOW(), updated_at = NOW()",
                (room_id, expected_binding_id, status, status),
            )

    def recover(
        self,
        room_id: str,
        expected_binding_id: str,
        *,
        actor_id: str,
    ) -> int:
        with self.conn.transaction() as tx:
            room = tx.execute(
                "SELECT integrity_status FROM rooms WHERE room_id = %s FOR UPDATE",
                (room_id,),
            ).fetchone()
            if not room or binding_id(
                current_runtime_binding(tx, room_id)
            ) != expected_binding_id:
                raise ValueError("provider_binding_changed")
            if room.get("integrity_status") != "paused_provider":
                raise ValueError("room_not_paused_provider")
            tx.execute(
                "INSERT INTO room_provider_health "
                "(room_id, binding_id, consecutive_failures, status, "
                "last_error_category, last_success_at, updated_at) "
                "VALUES (%s, %s, 0, 'healthy', '', NOW(), NOW()) "
                "ON CONFLICT (room_id) DO UPDATE SET "
                "binding_id = EXCLUDED.binding_id, consecutive_failures = 0, "
                "status = 'healthy', last_error_category = '', "
                "last_success_at = NOW(), updated_at = NOW()",
                (room_id, expected_binding_id),
            )
            tx.execute(
                "UPDATE rooms SET integrity_status = 'healthy', "
                "integrity_reason = NULL, integrity_source = NULL, "
                "integrity_state_version = state_version, "
                "integrity_updated_at = NOW() WHERE room_id = %s",
                (room_id,),
            )
            tx.execute(
                "INSERT INTO room_provider_health_audits "
                "(provider_health_audit_id, room_id, binding_id, action, "
                "error_category, actor_id) "
                "VALUES (%s, %s, %s, 'recovered', '', %s)",
                (
                    f"provider-health-{uuid.uuid4().hex}",
                    room_id,
                    expected_binding_id,
                    actor_id,
                ),
            )
            return EventLog(tx).log_event(
                room_id,
                "s2c_runtime_integrity_changed",
                "party",
                {
                    "status": "healthy",
                    "reasonCode": "provider_recovered",
                },
                commit=False,
            )
