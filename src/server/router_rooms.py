import uuid
import json
import logging
from fastapi import APIRouter, Request, HTTPException
from .models import RoomCreate
from .turn_manager import TurnManager

router = APIRouter(prefix="/api/rooms")
logger = logging.getLogger(__name__)


@router.post("")
async def create_room(request: Request):
    """Host or admin: create a room with scenario. Host creates for self; admin may specify owner."""
    conn = request.app.state.db
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    role = account.get("role", "")
    if role not in ("admin", "host"):
        raise HTTPException(403, "仅房主或管理员可创建房间")

    body = await request.json()
    scenario_id = body.get("scenario_id", "")
    if not scenario_id:
        raise HTTPException(400, "请选择剧本")
    sc = conn.execute("SELECT scenario_id, title FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone()
    if not sc:
        raise HTTPException(404, "剧本不存在")

    # Admin may specify owner; host always creates for self
    if role == "host":
        owner_account_id = account["account_id"]
    else:
        owner_account_id = body.get("owner_account_id") or account["account_id"]

    room_id = str(uuid.uuid4())[:8]
    owner_token = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO rooms (room_id, scenario_id, owner_token, owner_account_id, spoiler_level) VALUES (%s, %s, %s, %s, %s)",
        (room_id, scenario_id, owner_token, owner_account_id, body.get("spoiler_level", "standard")),
    )
    conn.commit()
    return {
        "room_id": room_id, "owner_token": owner_token,
        "status": "lobby", "scenario_title": sc["title"],
        "scenario_id": scenario_id, "owner_account_id": owner_account_id,
    }


@router.get("/mine")
async def list_my_rooms(request: Request):
    """List rooms owned by the authenticated host or admin account."""
    from .router_auth import get_account_from_token
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    role = account.get("role", "")
    if role not in ("admin", "host"):
        raise HTTPException(403, "仅房主或管理员可查看")
    conn = request.app.state.db
    if role == "admin":
        rows = conn.execute("SELECT * FROM rooms ORDER BY created_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM rooms WHERE owner_account_id = %s ORDER BY created_at DESC",
            (account["account_id"],),
        ).fetchall()
    return [{
        "room_id": r["room_id"], "scenario_id": r.get("scenario_id", ""),
        "status": r["status"], "spoiler_level": r.get("spoiler_level", "standard"),
        "owner_account_id": r.get("owner_account_id", ""),
        "created_at": str(r.get("created_at", "")),
        "started_at": str(r.get("started_at", "")) if r.get("started_at") else None,
    } for r in rows]


@router.get("/{room_id}")
async def get_room(request: Request, room_id: str):
    """Public room info — never leaks owner_token or owner_account_id."""
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    scenario_title = ""
    player_count = 0
    if room.get("scenario_id"):
        sc = conn.execute(
            "SELECT title FROM scenarios WHERE scenario_id = %s", (room["scenario_id"],)
        ).fetchone()
        if sc:
            scenario_title = sc["title"]
    char_count = conn.execute(
        "SELECT COUNT(*) as c FROM characters WHERE room_id = %s AND status IN ('active', 'joined')",
        (room_id,),
    ).fetchone()
    player_count = char_count["c"] if char_count else 0
    return {
        "room_id": room["room_id"],
        "status": room["status"],
        "scenario_id": room.get("scenario_id", ""),
        "scenario_title": scenario_title,
        "spoiler_level": room.get("spoiler_level", "standard"),
        "created_at": str(room.get("created_at", "")),
        "started_at": str(room.get("started_at", "")) if room.get("started_at") else None,
        "player_count": player_count,
    }


@router.get("/{room_id}/scenario-options")
async def get_scenario_options(request: Request, room_id: str):
    """List imported scenarios that can be assigned to this room. Requires owner or admin."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT scenario_id, title, import_status FROM scenarios "
        "WHERE import_status IN ('structured', 'pending') OR title IS NOT NULL "
        "ORDER BY created_at DESC"
    ).fetchall()
    return {"scenarios": [{"scenario_id": r["scenario_id"], "title": r["title"] or "未命名剧本", "import_status": r["import_status"]} for r in rows]}


@router.patch("/{room_id}/scenario")
async def set_room_scenario(request: Request, room_id: str):
    """Assign a scenario to the room. Only allowed in draft/lobby/paused status."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    body = await request.json()
    scenario_id = body.get("scenario_id", "")
    if not scenario_id:
        raise HTTPException(400, "scenario_id is required")
    conn = request.app.state.db
    # Verify scenario exists
    sc = conn.execute("SELECT scenario_id FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone()
    if not sc:
        raise HTTPException(404, "Scenario not found")
    # Check room status
    room = conn.execute("SELECT status FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    if room["status"] in ("active", "completed", "archived"):
        raise HTTPException(409, "Cannot change scenario in active/completed/archived room")
    conn.execute("UPDATE rooms SET scenario_id = %s WHERE room_id = %s", (scenario_id, room_id))
    conn.commit()
    # Return updated room with title
    return await get_room(request, room_id)


@router.patch("/{room_id}")
async def update_room(request: Request, room_id: str):
    """Admin: update room scenario, owner, status, or archive."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    body = await request.json()
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")

    # Update scenario
    if "scenario_id" in body:
        if room["status"] in ("active",):
            raise HTTPException(409, "进行中的房间不能切换剧本，请先暂停")
        sc = conn.execute("SELECT scenario_id FROM scenarios WHERE scenario_id = %s", (body["scenario_id"],)).fetchone()
        if not sc:
            raise HTTPException(404, "剧本不存在")
        conn.execute("UPDATE rooms SET scenario_id = %s WHERE room_id = %s", (body["scenario_id"], room_id))

    # Update owner
    if "owner_account_id" in body:
        conn.execute("UPDATE rooms SET owner_account_id = %s WHERE room_id = %s", (body["owner_account_id"], room_id))

    # Update status
    if "status" in body:
        valid = {"draft", "lobby", "active", "paused", "completed", "archived"}
        if body["status"] not in valid:
            raise HTTPException(400, f"无效状态: {body['status']}")
        conn.execute("UPDATE rooms SET status = %s WHERE room_id = %s", (body["status"], room_id))

    conn.commit()
    return await get_room(request, room_id)


@router.post("/{room_id}/start")
async def start_room(request: Request, room_id: str):
    conn = request.app.state.db
    owner_token = request.headers.get("X-Owner-Token", "")

    # Allow owner_token, owner account, or admin account
    is_owner = False
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    room = dict(room)

    if owner_token and room.get("owner_token") == owner_token:
        is_owner = True

    if not is_owner:
        try:
            from .router_auth import get_account_from_token
            account = get_account_from_token(request)
            if account:
                if account.get("role") == "admin":
                    is_owner = True
                elif account.get("account_id") == room.get("owner_account_id"):
                    is_owner = True
        except Exception:
            pass

    if not is_owner:
        raise HTTPException(403, "不是房间所有者或管理员")

    # Require scenario
    if not room.get("scenario_id"):
        raise HTTPException(400, "请先选择剧本再开始游戏")

    # Readiness check
    chars = conn.execute(
        "SELECT * FROM characters WHERE room_id = %s AND status IN ('active', 'joined')",
        (room_id,),
    ).fetchall()
    not_ready = [c for c in chars if not c["is_ready"]]

    # Check for force_start param
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    force_start = body.get("force_start", False)

    if chars and not_ready and not force_start:
        return {
            "status": "not_ready",
            "not_ready_players": [
                {"character_id": c["character_id"], "player_name": c["player_name"],
                 "is_ready": c["is_ready"]}
                for c in not_ready
            ],
            "hint": "发送 force_start: true 确认强制开始",
        }

    conn.execute(
        "UPDATE rooms SET status = 'active', started_at = NOW() WHERE room_id = %s",
        (room_id,),
    )
    conn.commit()

    # Initialize room map state from confirmed scenario map
    scenario_id = room.get("scenario_id")
    if scenario_id:
        try:
            from .map_persistence import get_scenario_map_by_scenario, init_room_map_state
            scenario_map = get_scenario_map_by_scenario(conn, scenario_id)
            if scenario_map and scenario_map.get("status") == "confirmed":
                init_room_map_state(conn, room_id, scenario_map["map_id"])
                logger.info("Map initialized for room %s from scenario %s", room_id, scenario_id)
        except Exception as e:
            logger.warning("Failed to init map for room %s: %s", room_id, e)

    # Auto-checkpoint on room start
    try:
        from .events.event_log import EventLog
        EventLog(conn).create_checkpoint(room_id, auto=True, reason="Room started")
    except Exception as e:
        logger.warning("Auto-checkpoint failed: %s", e)

    # Create first turn
    tm = TurnManager(conn)
    turn = tm._create_turn(room_id)

    return {"status": "active", "turn_id": turn["turn_id"], "turn_index": turn["turn_index"]}


# ── Turn endpoints ──

@router.get("/{room_id}/turns/current")
async def get_current_turn(request: Request, room_id: str):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    tm = TurnManager(conn)
    return tm.get_turn_snapshot(room_id)


@router.post("/{room_id}/turns/{turn_id}/skip-character")
async def skip_character(request: Request, room_id: str, turn_id: str):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    body = await request.json()
    character_id = body.get("character_id", "")
    if not character_id:
        raise HTTPException(400, "character_id required")
    tm = TurnManager(conn)
    result = tm.skip_character(room_id, turn_id, character_id)
    if result.get("status") == "not_found":
        raise HTTPException(404, "Turn not found")
    if tm.all_submitted(room_id):
        import asyncio
        from .player.router_player import _settle_turn_background
        asyncio.create_task(_settle_turn_background(request.app, room_id, turn_id))
    return result


@router.post("/{room_id}/turns/{turn_id}/retry")
async def retry_turn(request: Request, room_id: str, turn_id: str):
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    turn = conn.execute(
        "SELECT * FROM room_turns WHERE turn_id = %s AND room_id = %s",
        (turn_id, room_id),
    ).fetchone()
    if not turn:
        raise HTTPException(404, "Turn not found")
    import asyncio
    from .player.router_player import _settle_turn_background
    asyncio.create_task(_settle_turn_background(request.app, room_id, turn_id))
    return {"status": "retrying", "turn_id": turn_id}


def _verify_owner_or_admin(request: Request, room_id: str, conn):
    """Verify the request is from room owner (token or account) or admin account."""
    owner_token = request.headers.get("X-Owner-Token", "")
    if owner_token:
        room = conn.execute(
            "SELECT * FROM rooms WHERE room_id = %s AND owner_token = %s", (room_id, owner_token)
        ).fetchone()
        if room:
            return
    try:
        from .router_auth import get_account_from_token
        account = get_account_from_token(request)
        if account:
            if account.get("role") == "admin":
                return
            room = conn.execute(
                "SELECT owner_account_id FROM rooms WHERE room_id = %s", (room_id,)
            ).fetchone()
            if room and room.get("owner_account_id") == account.get("account_id"):
                return
    except Exception as exc:
        logger.warning("_verify_owner_or_admin: account lookup failed room=%s: %s", room_id, exc)
    raise HTTPException(403, "不是房间所有者或管理员")


@router.get("/{room_id}/ai-status")
async def ai_status(request: Request, room_id: str):
    """Return AI provider status for the room."""
    conn = request.app.state.db
    _verify_owner_or_admin(request, room_id, conn)
    turn = conn.execute(
        "SELECT * FROM room_turns WHERE room_id = %s ORDER BY turn_index DESC LIMIT 1", (room_id,)
    ).fetchone()
    provider = getattr(request.app.state, "narrative_provider", None)
    provider_name = type(provider).__name__ if provider else "TemplateNarrativeProvider"
    return {
        "room_id": room_id,
        "provider": provider_name if provider else "none",
        "turn_status": dict(turn)["status"] if turn else "no_turns",
        "turn_index": dict(turn)["turn_index"] if turn else 0,
    }


# ── Room AI Config ──

@router.get("/{room_id}/ai-config")
async def get_room_ai_config(request: Request, room_id: str):
    """Get room-level AI config override."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    from .ai.ai_config import get_room_ai_config, get_global_ai_config
    room_cfg = get_room_ai_config(request.app.state.db, room_id)
    global_cfg = get_global_ai_config(request.app.state.db)
    return {
        "room_id": room_id,
        "room_config": room_cfg,
        "global_config": global_cfg,
    }


@router.patch("/{room_id}/ai-config")
async def update_room_ai_config(request: Request, room_id: str):
    """Set room-level AI config override."""
    _verify_owner_or_admin(request, room_id, request.app.state.db)
    body = await request.json()
    from .ai.ai_config import update_room_ai_config
    update_room_ai_config(request.app.state.db, room_id, body)
    return {"status": "updated", "room_id": room_id}
