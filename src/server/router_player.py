import uuid
import json
import os
import tempfile
import time
from collections import defaultdict
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from starlette.responses import JSONResponse
from .models import PlayerIntent, SkillCheckRequest
from .skill_check import roll_skill_check

router = APIRouter(prefix="/api/player")

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
        "SELECT character_id, room_id FROM characters WHERE player_token = %s", (token,)
    ).fetchone()
    if not char:
        raise HTTPException(403, "Invalid token")
    result = engine.submit_intent(char["room_id"], char["character_id"], intent)
    if result.get("status") == "conflict":
        raise HTTPException(409, "State version conflict")
    return JSONResponse(content=result, status_code=202)


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
