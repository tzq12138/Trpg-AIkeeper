import asyncio
import logging
import uuid
import json
import os
import random
import tempfile
import time
from collections import defaultdict
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from starlette.responses import JSONResponse
from .models import PlayerIntent, SkillCheckRequest
from .mechanic_compiler import MechanicCompiler
from .projection import ProjectionDispatcher
from .resolution_pipeline import ResolutionPipeline
from .retro_items import RetroactiveClaimError, RetroactiveItemService, extract_retroactive_claim
from .skill_check import roll_skill_check

router = APIRouter(prefix="/api/player")
logger = logging.getLogger(__name__)

_join_attempts: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str, limit: int = 5, window: float = 60.0):
    now = time.time()
    _join_attempts[ip] = [t for t in _join_attempts[ip] if now - t < window]
    if len(_join_attempts[ip]) >= limit:
        raise HTTPException(429, "Too many join attempts")
    _join_attempts[ip].append(now)


def _get_character(request: Request) -> dict:
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()
    if not char:
        raise HTTPException(403, "Invalid token")
    return dict(char)


@router.post("/rooms/{room_id}/join")
async def join_room(request: Request, room_id: str):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    player_token = str(uuid.uuid4())
    character_id = str(uuid.uuid4())[:8]
    conn.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) VALUES (%s, %s, %s, %s)",
        (character_id, room_id, "未命名玩家", player_token),
    )
    conn.commit()
    return {"character_id": character_id, "player_token": player_token}


@router.post("/character/import-xlsx")
async def import_character_xlsx(request: Request, file: UploadFile = File(...)):
    token = request.headers.get("X-Room-Token", "")
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()
    if not char:
        raise HTTPException(403, "Invalid token")

    content = await file.read()
    tmp_path = os.path.join(tempfile.gettempdir(), f"{char['character_id']}.xlsx")
    with open(tmp_path, "wb") as f:
        f.write(content)

    from .xlsx_parser import parse_xlsx_character

    parsed = parse_xlsx_character(tmp_path)
    conn.execute(
        "UPDATE characters SET player_name = %s, xlsx_data = %s WHERE character_id = %s",
        (parsed["name"], json.dumps(parsed, ensure_ascii=False), char["character_id"]),
    )
    conn.commit()

    if hasattr(request.app.state, 'rag') and request.app.state.rag:
        try:
            request.app.state.rag.index_character(char["room_id"], char["character_id"], parsed)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning('Character RAG indexing failed: %s', e)

    return parsed


@router.post("/intent")
async def submit_intent(request: Request, intent: PlayerIntent):
    engine = request.app.state.engine
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()
    if not char:
        raise HTTPException(403, "Invalid token")

    if intent.intent_type == "retroactive_item_claim" or extract_retroactive_claim(intent.declared_intent):
        return await _submit_retroactive_claim(request, dict(char), intent)

    result = engine.submit_intent(char["room_id"], char["character_id"], intent)
    if result.get("status") == "conflict":
        raise HTTPException(409, "State version conflict")
    if getattr(request.app.state, "pipeline", None) or getattr(request.app.state, "pg_db", None):
        asyncio.create_task(_resolve_action_background(request.app, intent.action_id))
    return JSONResponse(content=result, status_code=202)


async def _resolve_action_background(app, action_id: str):
    pg_db = getattr(app.state, "pg_db", None)
    if pg_db:
        conn = pg_db.get_connection()
        try:
            compiler = getattr(app.state, "compiler", None) or MechanicCompiler(api_key="")
            pipeline = ResolutionPipeline(
                conn,
                compiler=compiler,
                dispatcher=ProjectionDispatcher(conn),
            )
            await pipeline.resolve_action(action_id)
        except Exception:
            logger.exception("Background resolution failed for action %s", action_id)
        finally:
            conn.close()
        return

    pipeline = getattr(app.state, "pipeline", None)
    if not pipeline:
        return
    try:
        await pipeline.resolve_action(action_id)
    except Exception:
        logger.exception("Background resolution failed for action %s", action_id)


async def _submit_retroactive_claim(request: Request, char: dict, intent: PlayerIntent):
    conn = request.app.state.db
    intent.intent_type = "retroactive_item_claim"
    if _recent_retro_claim_count(conn, char["character_id"]) >= 2:
        raise HTTPException(429, "Retroactive item claim rate limited")

    service = RetroactiveItemService(conn)
    assets = _scenario_assets_for_room(conn, char["room_id"])
    try:
        decision = service.evaluate_claim(intent, char, assets)
    except RetroactiveClaimError as exc:
        _insert_retro_action(conn, char, intent, "rejected", {"error": exc.detail})
        raise HTTPException(exc.status_code, exc.detail)

    roll_payload = None
    if decision.branch == "roll_required":
        luck = _character_luck(char)
        roll = random.randint(1, 100)
        roll_payload = {"skill": decision.roll_skill or "luck", "roll": roll, "target": luck}
        if roll > luck:
            _insert_retro_action(conn, char, intent, "rejected", {"branch": decision.branch, "roll": roll_payload})
            raise HTTPException(409, "Retroactive item claim roll failed")
        _decrement_luck(conn, char, luck)

    inventory_item = _add_claimed_inventory_item(conn, char, decision.item)
    conn.execute(
        "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s",
        (char["room_id"],),
    )
    result = {
        "branch": decision.branch,
        "item": inventory_item,
        "roll": roll_payload,
    }
    _insert_retro_action(conn, char, intent, "resolved", result)
    conn.commit()

    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
    patch_payload = {
        "actionId": intent.action_id,
        "patches": [{"op": "add", "path": "/inventory/-", "value": inventory_item}],
    }
    await dispatcher.emit(
        char["room_id"],
        "s2c_state_patch",
        "player",
        patch_payload,
        character_id=char["character_id"],
    )
    await dispatcher.emit(
        char["room_id"],
        "s2c_action_completed",
        "player",
        {"actionId": intent.action_id, "status": "resolved"},
        character_id=char["character_id"],
    )
    return JSONResponse(
        content={"status": "accepted", "action_id": intent.action_id, "branch": decision.branch},
        status_code=202,
    )


def _scenario_assets_for_room(conn, room_id: str) -> dict:
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room or not room.get("scenario_id"):
        return {}
    scenario = conn.execute(
        "SELECT * FROM scenarios WHERE scenario_id = %s", (room["scenario_id"],)
    ).fetchone()
    if not scenario:
        return {}
    return _json_value(scenario.get("scenario_assets")) or {}


def _recent_retro_claim_count(conn, character_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) as c FROM actions "
        "WHERE character_id = %s AND intent_type = %s AND created_at > NOW() - INTERVAL '60 seconds'",
        (character_id, "retroactive_item_claim"),
    ).fetchone()
    return int(row["c"] if row else 0)


def _insert_retro_action(conn, char: dict, intent: PlayerIntent, status: str, result: dict):
    conn.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, params, status, result, completed_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW()) "
        "ON CONFLICT (action_id) DO UPDATE SET status = EXCLUDED.status, result = EXCLUDED.result, completed_at = EXCLUDED.completed_at",
        (
            intent.action_id,
            char["room_id"],
            char["character_id"],
            "retroactive_item_claim",
            intent.declared_intent,
            json.dumps(intent.params, ensure_ascii=False),
            status,
            json.dumps(result, ensure_ascii=False),
        ),
    )


def _add_claimed_inventory_item(conn, char: dict, item: dict) -> dict:
    item_id = str(uuid.uuid4())
    narrative = item.get("narrative", {})
    inventory_item = {
        "id": item_id,
        "name": item.get("name", ""),
        "description": narrative.get("description", item.get("description", "")),
        "quantity": 1,
        "is_secret": False,
        "source": "backstory",
    }
    conn.execute(
        "INSERT INTO inventory (id, character_id, room_id, name, description, quantity, is_secret, source) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            item_id,
            char["character_id"],
            char["room_id"],
            inventory_item["name"],
            inventory_item["description"],
            1,
            False,
            "backstory",
        ),
    )
    return inventory_item


def _character_luck(char: dict) -> int:
    data = _json_value(char.get("xlsx_data")) or {}
    try:
        return int(data.get("luck", 0))
    except (TypeError, ValueError):
        return 0


def _decrement_luck(conn, char: dict, luck: int):
    data = _json_value(char.get("xlsx_data")) or {}
    data["luck"] = max(0, luck - 1)
    conn.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = %s",
        (json.dumps(data, ensure_ascii=False), char["character_id"]),
    )
    char["xlsx_data"] = data


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


@router.get("/sync")
async def player_sync(request: Request):
    char = _get_character(request)
    conn = request.app.state.db
    character_id = char["character_id"]

    items = conn.execute(
        "SELECT * FROM inventory WHERE character_id = %s", (character_id,)
    ).fetchall()
    clues = conn.execute(
        "SELECT * FROM clues WHERE character_id = %s", (character_id,)
    ).fetchall()

    room_row = conn.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s", (char["room_id"],)
    ).fetchone()
    state_version = room_row["state_version"] if room_row else 0

    return {
        **char,
        "inventory": [dict(i) for i in items],
        "clues": [dict(c) for c in clues],
        "stateVersion": state_version,
    }


@router.get("/character")
async def get_character(request: Request):
    char = _get_character(request)
    xlsx_data = {}
    if char.get("xlsx_data"):
        try:
            xlsx_data = json.loads(char["xlsx_data"])
        except json.JSONDecodeError:
            pass
    return {
        "character_id": char["character_id"],
        "name": char.get("player_name", ""),
        "hp": xlsx_data.get("hp", 0),
        "max_hp": xlsx_data.get("max_hp", 0),
        "san": xlsx_data.get("san", 0),
        "max_san": xlsx_data.get("max_san", 0),
        "mp": xlsx_data.get("mp", 0),
        "max_mp": xlsx_data.get("max_mp", 0),
        "luck": xlsx_data.get("luck", 0),
        "skills": xlsx_data.get("skills", {}),
        "background": xlsx_data.get("background", ""),
    }


@router.get("/inventory")
async def get_inventory(request: Request):
    char = _get_character(request)
    conn = request.app.state.db
    items = conn.execute(
        "SELECT * FROM inventory WHERE character_id = %s", (char["character_id"],)
    ).fetchall()
    return [dict(i) for i in items]


@router.post("/skill-check")
async def skill_check(request: Request, req: SkillCheckRequest):
    _get_character(request)
    result = roll_skill_check(req.skill_value, req.difficulty, req.bonus_dice)
    result["skill_name"] = req.skill_name
    return result
