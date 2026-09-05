"""Durable owner-pause state that is independent of the Host presentation UI."""

from __future__ import annotations

from typing import Any, Literal


PauseMode = Literal["soft_pause", "emergency_pause"]
PAUSE_MODES = {"soft_pause", "emergency_pause"}
SAFE_PAUSE_BOUNDARIES = {
    "between_actions",
    "pre_roll",
    "post_roll_receipt",
    "post_state_mutation",
    "post_projection",
}


class RoomPauseError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def pause_blocks_new_actions(room: dict[str, Any] | None) -> bool:
    """True once an owner pause is requested or the room is system-paused.

    System pauses (paused_system) and active recovery (recovering) must also
    reject new game actions; only owner resume or a verified recovery returns
    the room to running.
    """
    if not room:
        return False
    return (
        bool(room.get("pause_mode"))
        or room.get("runtime_status") in {"paused_by_owner", "paused_system", "recovering"}
    )


def sync_legacy_room_status(conn, room_id: str) -> None:
    """Keep legacy rooms.status readers aligned with the runtime state.

    Args:
        conn: caller-owned connection (caller commits).
        room_id: room whose legacy status column should mirror runtime_status.
    """
    conn.execute(
        "UPDATE rooms SET status = CASE runtime_status "
        "WHEN 'running' THEN 'active' "
        "WHEN 'ended' THEN 'completed' "
        "ELSE status END "
        "WHERE room_id = %s AND status IN ('paused', 'paused_provider', 'active')",
        (room_id,),
    )


def pause_room_for_system_integrity(
    conn,
    *,
    room_id: str,
    reason: str,
    source: str,
    action_id: str | None = None,
    tx=None,
) -> None:
    """Write a system integrity pause in one transaction (R1 alignment).

    The pause records runtime_status='paused_system' plus the legacy status
    column, marks integrity read-only with the current state version, and —
    crucially — never terminates the in-flight action. Preserving the action in
    its current (claimed) state and its committed artifacts is what allows a
    verified recovery proposal to resume the same action later.

    Args:
        conn: caller-owned connection.
        room_id: room to pause.
        reason: machine-readable integrity reason.
        source: which subsystem requested the pause (resolution_pipeline,
            collaboration_batch, ...).
        action_id: optional in-flight action preserved for recovery; a status
            event records the reason without transitioning the action.
        tx: optional caller-owned transaction object; when omitted a new
            transaction is opened and committed.
    """
    if tx is None:
        with conn.transaction() as tx_ctx:
            _write_pause_statements(tx_ctx, room_id, reason, source, action_id)
        return
    _write_pause_statements(tx, room_id, reason, source, action_id)


def _write_pause_statements(tx, room_id: str, reason: str, source: str, action_id: str | None) -> None:
    tx.execute(
        "UPDATE rooms SET status = 'paused', runtime_status = 'paused_system', "
        "integrity_status = 'read_only_recovery', integrity_reason = %s, "
        "integrity_source = %s, integrity_state_version = state_version, "
        "integrity_updated_at = NOW() WHERE room_id = %s",
        (reason, source, room_id),
    )
    if action_id:
        import json as _json

        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) "
            "VALUES (%s, 'resolving', %s)",
            (
                action_id,
                _json.dumps(
                    {
                        "reason_code": "room_integrity_paused",
                        "note": "action preserved for recovery; not terminated",
                    }
                ),
            ),
        )


def request_owner_pause(
    conn,
    room_id: str,
    *,
    mode: PauseMode,
    actor_id: str | None,
    reason: str,
) -> dict[str, Any]:
    """Persist a pause request and stop immediately when no action is resolving."""
    if mode not in PAUSE_MODES:
        raise RoomPauseError("invalid_pause_mode")
    room = conn.execute(
        "SELECT room_id, status, runtime_status, pause_mode FROM rooms "
        "WHERE room_id = %s FOR UPDATE",
        (room_id,),
    ).fetchone()
    if not room:
        raise RoomPauseError("room_not_found")
    if room.get("runtime_status") == "ended" or room.get("status") in {"completed", "archived"}:
        raise RoomPauseError("room_not_running")
    if room.get("pause_mode"):
        raise RoomPauseError("room_pause_already_requested")
    resolving = conn.execute(
        "SELECT 1 FROM actions WHERE room_id = %s AND status = 'resolving' LIMIT 1",
        (room_id,),
    ).fetchone()
    boundary = None if resolving else "between_actions"
    if boundary:
        conn.execute(
            "UPDATE rooms SET runtime_status = 'paused_by_owner', pause_mode = %s, "
            "pause_requested_at = NOW(), pause_requested_by = %s, pause_reason = %s, "
            "pause_cursor = %s, paused_at = NOW() WHERE room_id = %s",
            (mode, actor_id, reason, boundary, room_id),
        )
    else:
        conn.execute(
            "UPDATE rooms SET pause_mode = %s, pause_requested_at = NOW(), "
            "pause_requested_by = %s, pause_reason = %s, pause_cursor = NULL "
            "WHERE room_id = %s",
            (mode, actor_id, reason, room_id),
        )
    from ..events.event_log import EventLog

    EventLog(conn).log_event(
        room_id,
        "s2c_room_pause_requested",
        "system",
        {
            "mode": mode,
            "reason": reason,
            "settled": bool(boundary),
            "safe_boundary": boundary,
        },
        commit=False,
    )
    return {
        "status": "paused_by_owner" if boundary else "pause_requested",
        "mode": mode,
        "cursor": boundary,
    }


def settle_owner_pause_at_boundary(
    conn,
    room_id: str,
    *,
    boundary: str,
    action_id: str | None = None,
) -> bool:
    """Stop at a durable side-effect boundary without mutating committed effects."""
    if boundary not in SAFE_PAUSE_BOUNDARIES:
        raise ValueError("invalid_pause_boundary")
    room = conn.execute(
        "SELECT room_id, runtime_status, pause_mode FROM rooms "
        "WHERE room_id = %s FOR UPDATE",
        (room_id,),
    ).fetchone()
    if not pause_blocks_new_actions(room):
        return False
    if room.get("runtime_status") == "paused_by_owner":
        return True
    conn.execute(
        "UPDATE rooms SET runtime_status = 'paused_by_owner', pause_cursor = %s, "
        "paused_at = NOW() WHERE room_id = %s",
        (boundary, room_id),
    )
    from ..events.event_log import EventLog

    EventLog(conn).log_event(
        room_id,
        "s2c_room_paused",
        "system",
        {
            "mode": room.get("pause_mode"),
            "safe_boundary": boundary,
        },
        commit=False,
        action_id=action_id,
    )
    return True


def resume_owner_pause(
    conn,
    room_id: str,
    *,
    actor_id: str | None,
    reason: str,
) -> dict[str, Any]:
    """Resume future work from the saved boundary; never rewrites prior effects."""
    room = conn.execute(
        "SELECT room_id, runtime_status, pause_mode, pause_cursor FROM rooms "
        "WHERE room_id = %s FOR UPDATE",
        (room_id,),
    ).fetchone()
    if not room:
        raise RoomPauseError("room_not_found")
    if not pause_blocks_new_actions(room):
        raise RoomPauseError("room_not_paused_by_owner")
    cursor = room.get("pause_cursor")
    conn.execute(
        "UPDATE rooms SET runtime_status = 'running', pause_mode = NULL, "
        "pause_resumed_at = NOW(), pause_resumed_by = %s, "
        "pause_resume_reason = %s WHERE room_id = %s",
        (actor_id, reason, room_id),
    )
    sync_legacy_room_status(conn, room_id)
    from ..events.event_log import EventLog

    EventLog(conn).log_event(
        room_id,
        "s2c_room_resumed",
        "system",
        {"resume_reason": reason, "resume_from_cursor": cursor},
        commit=False,
    )
    return {"status": "running", "resume_from_cursor": cursor}
