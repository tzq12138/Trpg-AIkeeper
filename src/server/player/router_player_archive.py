import json
from fastapi import APIRouter, Request, HTTPException, Query
from typing import Literal

from ..campaign_archive import project_campaign_archive
from ..events.event_log import EventLog
from .auth import find_player_character

router = APIRouter(prefix="/api")

ARCHIVE_EVENT_TYPES = {
    "narrative": ["s2c_public_observation"],
    "clues": [
        "s2c_private_notice",
        "s2c_public_observation",
        "s2c_fact_revealed",
        "s2c_fact_corrected",
        "s2c_fact_safety_event",
    ],
    "actions": ["s2c_action_queued", "s2c_action_batched", "s2c_action_completed"],
    "skill_checks": ["s2c_action_completed"],
    "citations": [],
    "state_changes": ["s2c_state_patch", "s2c_full_snapshot", "s2c_engine_state"],
    "messages": ["s2c_team_message"],
}


def _json_object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _released_bundle_entries(conn, room_id: str, character_id: str, archive_type: str):
    if archive_type not in {"all", "narrative", "actions", "skill_checks", "citations"}:
        return [], set()
    rows = conn.execute(
        """
        SELECT bundle.action_id, bundle.character_id, bundle.canonical_result,
               bundle.rule_explanation, bundle.actor_projection, bundle.stage_projection,
               bundle.host_console,
               bundle.created_at, bundle.released_at, action.intent_type, action.declared_intent
        FROM resolution_bundles AS bundle
        JOIN actions AS action ON action.action_id = bundle.action_id
        WHERE bundle.room_id = %s AND bundle.release_status = 'released'
        ORDER BY COALESCE(bundle.released_at, bundle.created_at), bundle.action_id
        """,
        (room_id,),
    ).fetchall()
    entries = []
    released_action_ids = set()
    for row in rows:
        row = dict(row)
        stage_projection = _json_object(row.get("stage_projection"))
        narration = stage_projection.get("narrativeText")
        if not isinstance(narration, str) or not narration.strip():
            continue
        owns_action = row["character_id"] == character_id
        rule_explanation = _json_object(row.get("rule_explanation"))
        if archive_type == "actions" and not owns_action:
            continue
        if archive_type == "skill_checks" and (
            not owns_action or row.get("intent_type") != "skill_check"
        ):
            continue
        if archive_type == "citations" and (
            not owns_action or not isinstance(rule_explanation.get("citations"), list)
        ):
            continue
        released_action_ids.add(row["action_id"])
        data = {
            "kind": "resolution_bundle",
            "actionId": row["action_id"],
            "text": narration,
            "spoilerStatus": stage_projection.get("spoilerStatus", "none"),
        }
        if owns_action:
            actor_projection = _json_object(row.get("actor_projection"))
            canonical_result = _json_object(row.get("canonical_result"))
            host_console = _json_object(row.get("host_console"))
            data["intent"] = row.get("declared_intent") or ""
            if isinstance(actor_projection.get("result"), dict):
                data["result"] = actor_projection["result"]
            citations = rule_explanation.get("citations")
            if isinstance(citations, list):
                data["citations"] = citations
            state_version = canonical_result.get("stateVersion")
            if isinstance(state_version, int):
                data["stateVersion"] = state_version
            transaction_id = host_console.get("transactionId")
            if isinstance(transaction_id, str) and transaction_id:
                data["transactionId"] = transaction_id
        entries.append({
            "sequence": f"bundle:{row['action_id']}",
            "type": "resolution_bundle",
            "timestamp": row.get("released_at") or row.get("created_at"),
            "data": data,
            "is_public": True,
        })
    return entries, released_action_ids


def _get_character(conn, token: str):
    return find_player_character(conn, token)


@router.get("/player/campaign-archive")
async def player_campaign_archive(request: Request):
    char = _get_character(request.app.state.db, request.headers.get("X-Room-Token", ""))
    if not char:
        raise HTTPException(403, "Invalid token")
    row = request.app.state.db.execute(
        "SELECT archive_id, room_id, ending_type, summary, highlights, "
        "character_arcs, created_at "
        "FROM campaign_archives WHERE room_id = %s ORDER BY created_at DESC LIMIT 1",
        (char["room_id"],),).fetchone()
    if not row:
        raise HTTPException(404, "Archive not found")
    return project_campaign_archive(
        row,
        scope="player",
        character_id=char["character_id"],
    )


@router.get("/player/campaign-archive/arcs/{character_id}")
async def player_campaign_arc(request: Request, character_id: str):
    char = _get_character(request.app.state.db, request.headers.get("X-Room-Token", ""))
    if not char or char["character_id"] != character_id:
        raise HTTPException(403, "Character arc is private")
    archive = await player_campaign_archive(request)
    return {"character_arc": archive["character_arc"]}


@router.get("/player/archive")
async def player_archive(
    request: Request,
    type: Literal["narrative", "clues", "actions", "skill_checks", "citations", "state_changes", "messages", "all"] = "all",
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

    if not allowed_types and type != "citations":
        return {"entries": [], "total": 0}

    rows = []
    if allowed_types:
        placeholders = ",".join("%s" for _ in allowed_types)
        params: list = [room_id, *allowed_types]
        rows = conn.execute(
            f"SELECT sequence, room_id, event_type, audience, payload, action_id, "
            f"state_version, issued_at FROM events "
            f"WHERE room_id = %s AND event_type IN ({placeholders}) "
            f"ORDER BY sequence ASC",
            params,
        ).fetchall()

    bundle_entries, released_action_ids = _released_bundle_entries(
        conn, room_id, character_id, type
    )
    entries = list(bundle_entries)
    event_log = EventLog(conn)
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}

        if (
            r["event_type"] == "s2c_public_observation"
            and payload.get("actionId") in released_action_ids
        ):
            continue

        if not event_log._can_player_see_event(
            r["event_type"],
            r["audience"],
            payload,
            character_id,
            r["sequence"],
            r.get("action_id"),
            r.get("state_version"),
            r.get("room_id"),
        ):
            continue
        is_public = r["audience"] in ("party", "system")

        entries.append({
            "sequence": r["sequence"],
            "type": r["event_type"],
            "timestamp": r["issued_at"],
            "data": payload,
            "is_public": is_public,
        })

    if keyword:
        keyword_lower = keyword.lower()
        entries = [
            entry for entry in entries
            if keyword_lower in json.dumps(entry["data"], ensure_ascii=False).lower()
        ]

    entries.sort(key=lambda entry: (str(entry.get("timestamp") or ""), str(entry["sequence"])))
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
        "SELECT sequence, room_id, event_type, audience, payload, action_id, "
        "state_version, issued_at FROM events "
        "WHERE room_id = %s AND event_type IN ('s2c_private_notice', 's2c_public_observation') "
        "ORDER BY sequence ASC",
        (char["room_id"],),
    ).fetchall()

    clues = []
    event_log = EventLog(conn)
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}

        if not event_log._can_player_see_event(
            r["event_type"],
            r["audience"],
            payload,
            char["character_id"],
            r["sequence"],
            r.get("action_id"),
            r.get("state_version"),
            r.get("room_id"),
        ):
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
