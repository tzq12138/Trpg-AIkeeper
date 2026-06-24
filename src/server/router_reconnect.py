import json
from fastapi import APIRouter, Request, HTTPException
from .ws_manager import manager

# Client-side State Version Barrier (PRD-19 §11):
# When receiving s2c_state_patch:
# - If baseStateVersion === currentVersion: apply normally
# - If baseStateVersion > currentVersion: buffer the patch, fetch /api/player/sync
# - After snapshot arrives: discard buffered patches with baseStateVersion <= snapshot.version
#   Apply remaining buffered patches in order

router = APIRouter(prefix="/api/player")


def _get_character(conn, token: str):
    return conn.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()


@router.get("/reconnect")
async def reconnect(request: Request):
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")

    conn = request.app.state.db
    char = _get_character(conn, token)
    if not char:
        raise HTTPException(403, "Invalid token")

    room_id = char["room_id"]
    character_id = char["character_id"]

    last_seq_row = conn.execute(
        "SELECT last_delivered_sequence FROM player_sequences WHERE character_id = %s AND room_id = %s",
        (character_id, room_id),
    ).fetchone()
    last_sequence = last_seq_row["last_delivered_sequence"] if last_seq_row else 0

    room_row = conn.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    current_state_version = room_row["state_version"] if room_row else 0

    result = manager.reconnect(conn, room_id, character_id, last_sequence)

    if result.get("needs_snapshot"):
        char_data = dict(char)
        char_data.pop("player_token", None)

        all_events = conn.execute(
            "SELECT sequence, event_type, audience, payload, issued_at FROM events "
            "WHERE room_id = %s ORDER BY sequence ASC",
            (room_id,),
        ).fetchall()

        pending = conn.execute(
            "SELECT action_id, intent_type, declared_intent, status, result, created_at "
            "FROM actions WHERE room_id = %s AND character_id = %s AND status IN ('queued', 'batched', 'resolving')",
            (room_id, character_id),
        ).fetchall()

        max_seq_row = conn.execute(
            "SELECT MAX(sequence) as max_seq FROM events WHERE room_id = %s", (room_id,)
        ).fetchone()
        max_seq = max_seq_row["max_seq"] or 0

        return {
            "character": char_data,
            "recent_events": [dict(r) for r in all_events],
            "pending_actions": [dict(r) for r in pending],
            "last_sequence": max_seq,
            "stateVersion": current_state_version,
        }

    char_data = dict(char)
    char_data.pop("player_token", None)

    new_last = result.get("last_sequence", last_sequence)
    conn.execute(
        "INSERT INTO player_sequences (character_id, room_id, last_delivered_sequence) "
        "VALUES (%s, %s, %s) "
        "ON CONFLICT (character_id, room_id) DO UPDATE SET last_delivered_sequence = EXCLUDED.last_delivered_sequence, updated_at = NOW()",
        (character_id, room_id, new_last),
    )
    conn.commit()

    return {
        "character": char_data,
        "recent_events": result["events"],
        "pending_actions": result["pending_actions"],
        "last_sequence": new_last,
        "stateVersion": current_state_version,
    }


@router.get("/actions/{action_id}")
async def get_action_status(request: Request, action_id: str):
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")

    conn = request.app.state.db
    char = _get_character(conn, token)
    if not char:
        raise HTTPException(403, "Invalid token")

    action = conn.execute(
        "SELECT action_id, intent_type, declared_intent, status, batch_id, result, created_at, completed_at "
        "FROM actions WHERE action_id = %s AND character_id = %s",
        (action_id, char["character_id"]),
    ).fetchone()

    if not action:
        raise HTTPException(404, "Action not found")

    return dict(action)
