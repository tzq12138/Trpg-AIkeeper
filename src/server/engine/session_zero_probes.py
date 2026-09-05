"""Server-issued Session Zero probes: emission, confirmation, gate status.

A probe is the server-side record proving that a private or party projection
was actually emitted (AIO-SZ-004) or that a device-recovery watermark was
produced by a real reconnect (AIO-SZ-007). Each player's current controlling
device must confirm the private probe; party probes prove the party channel
without requiring a Stage to be online. The start gate and the Session Zero
`complete` flag share this single engine computation (AIO-SZ-001/008), so an
invalidated probe blocks start even when every confirmation button is checked.
"""

from __future__ import annotations

import uuid
from typing import Any

PROBE_TYPES = ("private_projection", "party_projection", "device_recovery")
PROBE_TTL_MINUTES = 30
_EVENT_TYPE = "s2c_session_zero_probe"


class SessionZeroProbeError(ValueError):
    """Raised with a machine-readable code for HTTP mapping."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _controller_device_row(conn, character_id: str) -> dict | None:
    """Return the character's current active controller device session."""
    return conn.execute(
        "SELECT * FROM player_device_sessions "
        "WHERE character_id = %s AND status = 'active' AND is_controller = TRUE "
        "ORDER BY expires_at DESC LIMIT 1",
        (character_id,),
    ).fetchone()


def issue_probes_for_character(conn, room_id: str, character_id: str) -> list[dict]:
    """Emit private, party and device-recovery probes for one character.

    Private/party probes are also written as events on their respective
    audience so the owning client can observe the projection channel. Earlier
    unconfirmed probes of the same type are invalidated (superseded).

    Args:
        conn: caller-owned connection (caller commits).
        room_id: room that is preparing to start.
        character_id: the preparing player's character.
    Returns:
        The newly issued probe rows.
    """
    controller = _controller_device_row(conn, character_id)
    controller_id = controller["device_session_id"] if controller else None
    watermark_row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) AS seq FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    watermark = int(watermark_row["seq"] or 0) if watermark_row else 0

    issued: list[dict] = []
    for probe_type, audience in (
        ("private_projection", "player"),
        ("party_projection", "party"),
        ("device_recovery", "player"),
    ):
        conn.execute(
            "UPDATE session_zero_probes SET status = 'expired', invalidated_at = NOW(), "
            "invalidate_reason = 'superseded_by_new_issue' "
            "WHERE room_id = %s AND character_id = %s AND probe_type = %s "
            "AND status IN ('issued', 'confirmed')",
            (room_id, character_id, probe_type),
        )
        probe_id = str(uuid.uuid4())
        payload = {"probeId": probe_id, "probeType": probe_type}
        conn.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) "
            "VALUES (%s, %s, %s, %s)",
            (
                room_id,
                _EVENT_TYPE,
                "player" if audience == "player" else "party",
                __import__("json").dumps(payload, ensure_ascii=False),
            ),
        )
        conn.execute(
            "INSERT INTO session_zero_probes "
            "(probe_id, room_id, character_id, probe_type, audience, event_type, "
            "event_payload, issued_watermark, device_session_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                probe_id,
                room_id,
                character_id,
                probe_type,
                audience,
                _EVENT_TYPE,
                __import__("json").dumps(payload, ensure_ascii=False),
                watermark,
                controller_id,
            ),
        )
        row = conn.execute(
            "SELECT * FROM session_zero_probes WHERE probe_id = %s",
            (probe_id,),
        ).fetchone()
        issued.append(dict(row))
    return issued


def confirm_projection_probe(
    conn,
    *,
    room_id: str,
    character_id: str,
    probe_id: str,
    probe_type: str,
) -> dict:
    """Confirm a private or party projection probe.

    The confirmation must come from the character's current active controller
    device, and the probe must have been issued for that character/room with
    the matching type and must still be unexpired.

    Args:
        conn: caller-owned connection.
        room_id / character_id / probe_id / probe_type: probe identity inputs.
    Returns:
        The updated probe row.
    Raises:
        SessionZeroProbeError with code probe_not_found (no cross-character
        information leak), probe_wrong_device, probe_expired, probe_type_mismatch.
    """
    row = conn.execute(
        "SELECT * FROM session_zero_probes WHERE probe_id = %s",
        (probe_id,),
    ).fetchone()
    if not row or row["room_id"] != room_id or row["character_id"] != character_id:
        raise SessionZeroProbeError("probe_not_found")
    if row["probe_type"] != probe_type:
        raise SessionZeroProbeError("probe_type_mismatch")
    controller = _controller_device_row(conn, character_id)
    if not controller:
        raise SessionZeroProbeError("probe_wrong_device")
    if (
        row["probe_type"] in {"private_projection", "party_projection"}
        and row["device_session_id"]
        and row["device_session_id"] != controller["device_session_id"]
    ):
        raise SessionZeroProbeError("probe_wrong_device")
    _expire_stale(conn, room_id, character_id)
    fresh = conn.execute(
        "SELECT * FROM session_zero_probes WHERE probe_id = %s",
        (probe_id,),
    ).fetchone()
    if fresh["status"] != "issued":
        raise SessionZeroProbeError("probe_expired")
    conn.execute(
        "UPDATE session_zero_probes SET status = 'confirmed', confirmed_at = NOW(), "
        "device_session_id = %s WHERE probe_id = %s",
        (controller["device_session_id"], probe_id),
    )
    return dict(
        conn.execute(
            "SELECT * FROM session_zero_probes WHERE probe_id = %s",
            (probe_id,),
        ).fetchone()
    )


def confirm_device_recovery_probe(
    conn,
    *,
    room_id: str,
    character_id: str,
    probe_id: str,
    watermark: int,
) -> dict:
    """Confirm a device-recovery probe with a reconnect watermark.

    The watermark must come from a real `/api/player/reconnect` response
    (client passes the returned last_sequence). Claiming success without a
    server-issued record, or with a watermark below the issued watermark, is
    rejected.

    Args:
        conn / room_id / character_id / probe_id: probe identity inputs.
        watermark: last_sequence observed by a real reconnect call.
    Returns:
        The updated probe row.
    Raises:
        SessionZeroProbeError: probe_not_found / probe_wrong_device /
        probe_watermark_insufficient / probe_expired.
    """
    row = conn.execute(
        "SELECT * FROM session_zero_probes WHERE probe_id = %s",
        (probe_id,),
    ).fetchone()
    if not row or row["room_id"] != room_id or row["character_id"] != character_id:
        raise SessionZeroProbeError("probe_not_found")
    if row["probe_type"] != "device_recovery":
        raise SessionZeroProbeError("probe_type_mismatch")
    controller = _controller_device_row(conn, character_id)
    if not controller:
        raise SessionZeroProbeError("probe_wrong_device")
    _expire_stale(conn, room_id, character_id)
    fresh = conn.execute(
        "SELECT * FROM session_zero_probes WHERE probe_id = %s",
        (probe_id,),
    ).fetchone()
    if fresh["status"] != "issued":
        raise SessionZeroProbeError("probe_expired")
    try:
        issued_watermark = int(fresh["issued_watermark"] or 0)
    except (TypeError, ValueError):
        issued_watermark = 0
    if int(watermark) < issued_watermark:
        raise SessionZeroProbeError("probe_watermark_insufficient")
    conn.execute(
        "UPDATE session_zero_probes SET status = 'confirmed', confirmed_at = NOW(), "
        "confirmed_watermark = %s, device_session_id = %s WHERE probe_id = %s",
        (int(watermark), controller["device_session_id"], probe_id),
    )
    return dict(
        conn.execute(
            "SELECT * FROM session_zero_probes WHERE probe_id = %s",
            (probe_id,),
        ).fetchone()
    )


def _expire_stale(conn, room_id: str, character_id: str) -> None:
    """Expire probes whose confirming device is no longer the controller."""
    conn.execute(
        "UPDATE session_zero_probes SET status = 'revoked', invalidated_at = NOW(), "
        "invalidate_reason = 'controller_device_changed' "
        "WHERE room_id = %s AND character_id = %s AND status = 'confirmed' "
        "AND device_session_id IS NOT NULL AND device_session_id NOT IN ("
        "  SELECT device_session_id FROM player_device_sessions "
        "  WHERE character_id = %s AND status = 'active' AND is_controller = TRUE"
        ")",
        (room_id, character_id, character_id),
    )


def probe_gate_status(conn, room_id: str) -> dict[str, dict[str, dict[str, Any]]]:
    """Compute per-character probe validity used by the shared start gate.

    A probe type is valid only when the latest issued probe for it is
    confirmed, unexpired, and its confirming device is still the character's
    active controller. Superseded/revoked/expired probes invalidate the gate
    so the Engine recomputes readiness on every call (AIO-SZ-008).

    Args:
        conn: caller-owned connection.
        room_id: preparing room.
    Returns:
        Mapping character_id -> probe_type -> {valid, status, reason}.
    """
    rows = conn.execute(
        "SELECT character_id, probe_type, status, issued_at, confirmed_at, "
        "invalidated_at, invalidate_reason, device_session_id, "
        "ROW_NUMBER() OVER (PARTITION BY character_id, probe_type "
        "  ORDER BY issued_at DESC) AS rank "
        "FROM session_zero_probes WHERE room_id = %s",
        (room_id,),
    ).fetchall()
    status: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if int(row["rank"]) != 1:
            continue
        character_id = row["character_id"]
        probe_type = row["probe_type"]
        controller = _controller_device_row(conn, character_id)
        same_device = bool(
            controller
            and row["device_session_id"]
            and row["device_session_id"] == controller["device_session_id"]
        )
        valid = bool(
            row["status"] == "confirmed"
            and (controller is not None)
            and same_device
        )
        reason = (
            None
            if valid
            else (
                "device_not_claimed"
                if controller is None
                else "controller_device_changed"
                if not same_device
                else "probe_unconfirmed"
            )
        )
        status.setdefault(character_id, {})[probe_type] = {
            "valid": valid,
            "status": row["status"],
            "reason": reason,
        }
    return status


def required_probes_valid(conn, room_id: str, character_id: str) -> tuple[bool, list[str]]:
    """Return (all_valid, missing_probe_types) for one character.

    Args:
        conn: caller-owned connection.
        room_id / character_id: identity inputs.
    Returns:
        True plus empty list when all three probe types are valid; otherwise
        False plus the invalid/missing probe type names.
    """
    status = probe_gate_status(conn, room_id).get(character_id, {})
    missing: list[str] = []
    for probe_type in PROBE_TYPES:
        entry = status.get(probe_type)
        if not entry or not entry.get("valid"):
            missing.append(probe_type)
    return not missing, missing


def latest_probes_for_character(conn, room_id: str, character_id: str) -> list[dict]:
    """Return the latest probe of each type for one character (for GET UI)."""
    rows = conn.execute(
        "SELECT * FROM session_zero_probes WHERE room_id = %s AND character_id = %s "
        "AND (probe_type, issued_at) IN ("
        "  SELECT probe_type, MAX(issued_at) FROM session_zero_probes "
        "  WHERE room_id = %s AND character_id = %s GROUP BY probe_type"
        ") ORDER BY probe_type",
        (room_id, character_id, room_id, character_id),
    ).fetchall()
    return [dict(row) for row in rows]
