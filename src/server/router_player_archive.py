import json
from fastapi import APIRouter, Request, HTTPException, Query
from typing import Literal

router = APIRouter(prefix="/api")

ARCHIVE_EVENT_TYPES = {
    "clues": ["s2c_private_notice", "s2c_public_observation"],
    "actions": ["s2c_action_queued", "s2c_action_batched", "s2c_action_completed"],
    "skill_checks": ["s2c_action_completed"],
    "state_changes": ["s2c_state_patch", "s2c_full_snapshot", "s2c_engine_state"],
}


def _get_character(conn, token: str):
    return conn.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()


@router.get("/player/archive")
async def player_archive(
    request: Request,
    type: Literal["clues", "actions", "skill_checks", "state_changes", "all"] = "all",
    keyword: str = Query(default=""),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")

    conn = request.app.state.db
    char = _get_character(conn, token)
    if not char:
        raise HTTPException(403, "Invalid token")

    room_id = char["room_id"]
    character_id = char["character_id"]

    if type == "all":
        allowed_types = set()
        for types in ARCHIVE_EVENT_TYPES.values():
            allowed_types.update(types)
    else:
        allowed_types = set(ARCHIVE_EVENT_TYPES.get(type, []))

    if not allowed_types:
        return {"entries": [], "total": 0}

    placeholders = ",".join("%s" for _ in allowed_types)
    params: list = [room_id, *allowed_types]

    rows = conn.execute(
        f"SELECT sequence, event_type, audience, payload, issued_at FROM events "
        f"WHERE room_id = %s AND event_type IN ({placeholders}) "
        f"ORDER BY sequence ASC",
        params,
    ).fetchall()

    entries = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}

        is_public = r["audience"] in ("party", "system")

        if not is_public:
            owner_char_id = payload.get("characterId", "")
            if owner_char_id and owner_char_id != character_id:
                continue

        if keyword:
            payload_str = str(payload).lower()
            if keyword.lower() not in payload_str:
                continue

        entries.append({
            "sequence": r["sequence"],
            "type": r["event_type"],
            "timestamp": r["issued_at"],
            "data": payload,
            "is_public": is_public,
        })

    total = len(entries)
    paginated = entries[offset : offset + limit]

    return {"entries": paginated, "total": total}


@router.get("/player/archive/actions")
async def archive_actions(request: Request):
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")

    conn = request.app.state.db
    char = _get_character(conn, token)
    if not char:
        raise HTTPException(403, "Invalid token")

    rows = conn.execute(
        "SELECT action_id, intent_type, declared_intent, status, batch_id, result, created_at, completed_at "
        "FROM actions WHERE room_id = %s AND character_id = %s ORDER BY created_at ASC",
        (char["room_id"], char["character_id"]),
    ).fetchall()

    return {"actions": [dict(r) for r in rows]}


@router.get("/player/archive/clues")
async def archive_clues(request: Request):
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")

    conn = request.app.state.db
    char = _get_character(conn, token)
    if not char:
        raise HTTPException(403, "Invalid token")

    rows = conn.execute(
        "SELECT sequence, event_type, payload, issued_at FROM events "
        "WHERE room_id = %s AND event_type IN ('s2c_private_notice', 's2c_public_observation') "
        "ORDER BY sequence ASC",
        (char["room_id"],),
    ).fetchall()

    clues = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}

        if r["event_type"] == "s2c_private_notice":
            owner = payload.get("characterId", "")
            if owner and owner != char["character_id"]:
                continue

        clues.append({
            "sequence": r["sequence"],
            "type": r["event_type"],
            "timestamp": r["issued_at"],
            "data": payload,
        })

    return {"clues": clues}


@router.get("/player/archive/skill-checks")
async def archive_skill_checks(request: Request):
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")

    conn = request.app.state.db
    char = _get_character(conn, token)
    if not char:
        raise HTTPException(403, "Invalid token")

    rows = conn.execute(
        "SELECT action_id, intent_type, declared_intent, status, result, created_at, completed_at "
        "FROM actions WHERE room_id = %s AND character_id = %s AND intent_type = 'skill_check' "
        "ORDER BY created_at ASC",
        (char["room_id"], char["character_id"]),
    ).fetchall()

    return {"skill_checks": [dict(r) for r in rows]}


@router.get("/rooms/{room_id}/replay")
async def room_replay(
    request: Request,
    room_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    owner_token = request.headers.get("X-Owner-Token", "")
    conn = request.app.state.db

    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s AND owner_token = %s",
        (room_id, owner_token),
    ).fetchone()
    if not room:
        raise HTTPException(403, "Not room owner")

    rows = conn.execute(
        "SELECT sequence, event_type, audience, payload, issued_at FROM events "
        "WHERE room_id = %s AND audience IN ('party', 'system') "
        "ORDER BY sequence ASC LIMIT %s OFFSET %s",
        (room_id, limit, offset),
    ).fetchall()

    count_row = conn.execute(
        "SELECT COUNT(*) as c FROM events WHERE room_id = %s AND audience IN ('party', 'system')",
        (room_id,),
    ).fetchone()

    events = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}

        events.append({
            "sequence": r["sequence"],
            "type": r["event_type"],
            "audience": r["audience"],
            "payload": payload,
            "timestamp": r["issued_at"],
        })

    return {"events": events, "total": count_row["c"]}
