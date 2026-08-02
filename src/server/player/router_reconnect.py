import json
import logging
from fastapi import APIRouter, Request, HTTPException
from ..events.event_log import EventLog
from ..host.ws_manager import NONTERMINAL_ACTION_STATUSES, manager
from .private_data import PrivateDataDecryptionError, private_data_cipher_from_env

logger = logging.getLogger(__name__)

# Client-side State Version Barrier (PRD-19 §11):
# When receiving s2c_state_patch:
# - If baseStateVersion === currentVersion: apply normally
# - If baseStateVersion > currentVersion: buffer the patch, fetch /api/player/sync
# - After snapshot arrives: discard buffered patches with baseStateVersion <= snapshot.version
#   Apply remaining buffered patches in order

router = APIRouter(prefix="/api/player")


def _scene_snapshot(conn, room_id: str) -> dict:
    row = conn.execute(
        "SELECT current_scene, visited_scenes, version FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if not row:
        return {"currentScene": "", "visitedScenes": [], "version": 0}
    visited = row.get("visited_scenes") or []
    if isinstance(visited, str):
        try:
            visited = json.loads(visited)
        except json.JSONDecodeError:
            visited = []
    return {
        "currentScene": row.get("current_scene") or "",
        "visitedScenes": visited if isinstance(visited, list) else [],
        "version": int(row.get("version") or 0),
    }


def _get_character(conn, token: str):
    return conn.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()


def _pending_submissions(conn, room_id: str, character_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT action_id, input_mode, raw_text_ciphertext, requested_visibility, "
        "client_sequence, base_state_version, status "
        "FROM player_action_submissions "
        "WHERE room_id = %s AND character_id = %s "
        "AND status = ANY(%s) ORDER BY created_at ASC",
        (room_id, character_id, ["received", "analyzing", "awaiting_confirmation"]),
    ).fetchall()
    cipher = private_data_cipher_from_env()
    pending: list[dict] = []
    for row in rows:
        submission = dict(row)
        try:
            raw_text = cipher.decrypt(submission["raw_text_ciphertext"])
        except PrivateDataDecryptionError:
            logger.warning("Skipping unreadable action submission during reconnect: %s", submission["action_id"])
            continue
        pending.append({
            "action_id": submission["action_id"],
            "input_mode": submission["input_mode"],
            "raw_text": raw_text,
            "requested_visibility": submission["requested_visibility"],
            "client_sequence": submission["client_sequence"],
            "base_state_version": submission["base_state_version"],
            "status": submission["status"],
        })
    return pending


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
        "SELECT state_version, risk_contract FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    current_state_version = room_row["state_version"] if room_row else 0
    pending_submissions = _pending_submissions(conn, room_id, character_id)

    result = manager.reconnect(conn, room_id, character_id, last_sequence)
    from ..engine.risk_contract import public_risk_contract

    risk_contract = public_risk_contract(
        room_row.get("risk_contract") if room_row else None
    )

    if result.get("needs_snapshot"):
        char_data = dict(char)
        char_data.pop("player_token", None)

        pending = conn.execute(
            "SELECT action_id, intent_type, declared_intent, status, result, created_at "
            "FROM actions WHERE room_id = %s AND character_id = %s AND status = ANY(%s)",
            (room_id, character_id, list(NONTERMINAL_ACTION_STATUSES)),
        ).fetchall()

        max_seq_row = conn.execute(
            "SELECT MAX(sequence) as max_seq FROM events WHERE room_id = %s", (room_id,)
        ).fetchone()
        max_seq = max_seq_row["max_seq"] or 0
        all_events = [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "audience": event.audience,
                "payload": event.payload,
                "issued_at": event.issued_at,
            }
            for event in EventLog(conn).get_events_for_player(
                room_id,
                character_id,
                limit=max_seq,
            )
        ]

        return {
            "character": char_data,
            "recent_events": all_events,
            "pending_actions": [dict(r) for r in pending],
            "pending_submissions": pending_submissions,
            "last_sequence": max_seq,
            "stateVersion": current_state_version,
            "sceneState": _scene_snapshot(conn, room_id),
            "riskContract": risk_contract,
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
        "pending_submissions": pending_submissions,
        "last_sequence": new_last,
        "stateVersion": current_state_version,
        "sceneState": _scene_snapshot(conn, room_id),
        "riskContract": risk_contract,
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

    from .action_service import ActionDraftError, build_action_receipt

    try:
        return build_action_receipt(conn, char["character_id"], action_id)
    except ActionDraftError as exc:
        if exc.status_code == 404:
            raise HTTPException(404, "Action not found") from exc
        raise HTTPException(exc.status_code, exc.detail) from exc
