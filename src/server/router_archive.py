from fastapi import APIRouter, Request, HTTPException, Query
from .events.event_log import EventLog
from .campaign_archive import CampaignArchive
from .models import CampaignArchiveQuery

router = APIRouter(prefix="/api/rooms")


# ── Auth helpers ──

def _verify_owner_or_admin(request: Request, room_id: str) -> dict:
    """Verify room owner (X-Owner-Token or account) or admin account."""
    token = request.headers.get("X-Owner-Token", "")
    conn = request.app.state.db
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s", (room_id,),
    ).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    room = dict(room)

    # 1. X-Owner-Token
    if token and room.get("owner_token") == token:
        return room

    # 2. Account-based
    try:
        from .router_auth import get_account_from_token
        account = get_account_from_token(request)
        if account:
            if account.get("role") == "admin":
                return room
            if account.get("account_id") == room.get("owner_account_id"):
                return room
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "_verify_owner_or_admin: account lookup failed room=%s: %s", room_id, exc)

    raise HTTPException(403, "不是房间所有者或管理员")


def _verify_player(request: Request, room_id: str = "") -> dict:
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "缺少 X-Room-Token")
    conn = request.app.state.db
    if room_id:
        char = conn.execute(
            "SELECT * FROM characters WHERE player_token = %s AND room_id = %s",
            (token, room_id),
        ).fetchone()
    else:
        char = conn.execute(
            "SELECT * FROM characters WHERE player_token = %s", (token,)
        ).fetchone()
    if not char:
        raise HTTPException(403, "令牌无效")
    return dict(char)


# ── Event endpoints ──

@router.get("/{room_id}/events")
async def get_events(
    request: Request,
    room_id: str,
    since_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    event_log = EventLog(conn)
    events = event_log.get_events(room_id, since_sequence, limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/{room_id}/events/public")
async def get_public_events(
    request: Request,
    room_id: str,
    since_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    _verify_player(request, room_id)  # any valid player in this room can read public events
    conn = request.app.state.db
    event_log = EventLog(conn)
    events = event_log.get_public_events(room_id, since_sequence, limit)
    return {"events": [e.model_dump() for e in events]}


@router.get("/{room_id}/timeline")
async def get_timeline(
    request: Request,
    room_id: str,
    since_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    event_type: str = Query("", description="Filter by event type"),
    keyword: str = Query("", description="Search payload text"),
):
    """Host timeline with filters."""
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    event_log = EventLog(conn)
    events = event_log.get_events(room_id, since_sequence, limit)
    if event_type:
        events = [e for e in events if e.event_type == event_type]
    if keyword:
        import json
        kw = keyword.lower()
        events = [e for e in events if kw in json.dumps(e.payload, ensure_ascii=False).lower()]
    return {"events": [e.model_dump() for e in events]}


@router.get("/{room_id}/timeline/{sequence}")
async def get_timeline_event(request: Request, room_id: str, sequence: int):
    """Get a single event by sequence for replay."""
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    row = conn.execute(
        "SELECT sequence, room_id, event_type, audience, payload, issued_at "
        "FROM events WHERE room_id = %s AND sequence = %s",
        (room_id, sequence),
    ).fetchone()
    if not row:
        raise HTTPException(404, "事件不存在")
    from .events.event_log import _decode_json, _to_iso
    from .models import EventLogEntry
    entry = EventLogEntry(
        sequence=row["sequence"], room_id=row["room_id"],
        event_type=row["event_type"], audience=row["audience"],
        payload=_decode_json(row["payload"]), issued_at=_to_iso(row["issued_at"]),
    )
    return entry.model_dump()


# ── Checkpoint endpoints ──

@router.post("/{room_id}/checkpoint")
async def create_checkpoint(request: Request, room_id: str):
    _verify_owner_or_admin(request, room_id)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    conn = request.app.state.db
    event_log = EventLog(conn)
    auto = body.get("auto", False)
    reason = body.get("reason", body.get("note", ""))
    checkpoint = event_log.create_checkpoint(room_id, auto=auto, reason=reason)
    return checkpoint.model_dump()


@router.get("/{room_id}/checkpoints")
async def list_checkpoints(request: Request, room_id: str):
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    event_log = EventLog(conn)
    checkpoints = event_log.list_checkpoints(room_id)
    return {"checkpoints": [c.model_dump() for c in checkpoints]}


@router.post("/{room_id}/restore/{checkpoint_id}")
async def restore_checkpoint(request: Request, room_id: str, checkpoint_id: str):
    _verify_owner_or_admin(request, room_id)
    body = await request.json()
    if body.get("confirm") is not True:
        raise HTTPException(400, "需要二次确认（发送 confirm: true）")
    reason = body.get("reason", "").strip()
    if not reason:
        raise HTTPException(400, "恢复 checkpoint 必须提供 reason")
    conn = request.app.state.db
    event_log = EventLog(conn)
    try:
        snapshot = event_log.restore_checkpoint(room_id, checkpoint_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    # Log strengthened audit event (host-only, NOT for player visibility)
    from datetime import datetime, timezone
    actor_id = "host"
    try:
        from .router_auth import get_account_from_token
        acct = get_account_from_token(request)
        if acct:
            actor_id = acct.get("account_id", "host")
    except Exception:
        pass
    event_log.log_event(room_id, "s2c_checkpoint_restored", "host", {
        "checkpointId": checkpoint_id,
        "actorAccountId": actor_id,
        "reason": reason,
        "restoreMode": "full",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "restored", "snapshot": snapshot}


# ── Campaign endpoints ──

@router.get("/{room_id}/campaign")
async def get_campaign_summary(request: Request, room_id: str,
                                scope: str = Query("public")):
    """Get campaign summary. scope=public for players, scope=full for owner/admin."""
    conn = request.app.state.db
    if scope == "full":
        _verify_owner_or_admin(request, room_id)
    else:
        _verify_player(request, room_id)
    archive = CampaignArchive(conn)
    try:
        summary = archive.get_campaign_summary(room_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return summary.model_dump() if hasattr(summary, 'model_dump') else summary


@router.post("/{room_id}/end")
async def end_campaign(request: Request, room_id: str):
    _verify_owner_or_admin(request, room_id)
    conn = request.app.state.db
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    ending_type = body.get("ending_type") or "mixed"
    ending_name = body.get("ending_name") or ""
    text = body.get("text") or body.get("summary") or ""
    payload = {"ending_type": ending_type}
    if ending_name:
        payload["endingName"] = ending_name
        payload["endingPhase"] = ending_name
    if text:
        payload["text"] = text

    event_log = EventLog(conn)
    event_log.log_event(room_id, "s2c_campaign_ended", "party", payload)

    archive = CampaignArchive(conn)
    ending = archive.generate_ending(room_id)
    return ending.model_dump()


# ── Export endpoints ──

@router.get("/{room_id}/export")
async def export_room(request: Request, room_id: str,
                      format: str = Query("markdown"),
                      scope: str = Query("public")):
    """Export room data as Markdown or JSON."""
    if scope == "full":
        _verify_owner_or_admin(request, room_id)
    else:
        _verify_player(request, room_id)
    conn = request.app.state.db
    from .export import export_markdown, export_json
    if format == "json":
        return export_json(conn, room_id, scope)
    return export_markdown(conn, room_id, scope)
