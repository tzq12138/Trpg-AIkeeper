import asyncio
import logging
import uuid
import json
import os
import random
import tempfile
import time
from collections import defaultdict
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from starlette.responses import JSONResponse
from ..models import InventoryTransferCreate, PlayerIntent, SkillCheckRequest
from ..ai.mechanic_compiler import MechanicCompiler
from ..engine.projection import ProjectionDispatcher
from ..engine.resolution_pipeline import ResolutionPipeline
from ..host.ws_manager import manager as ws_manager
from ..engine.action_lifecycle import transition_action
from ..engine.retro_items import RetroactiveClaimError, RetroactiveItemService, extract_retroactive_claim
from ..engine.skill_check import roll_skill_check
from ..scenario.character_presets import character_preview, find_preset, list_presets, preset_dir_from_app
from ..scenario.xlsx_parser import parse_xlsx_character
from ..router_auth import get_account_from_token

router = APIRouter(prefix="/api/player")
logger = logging.getLogger(__name__)

_join_attempts: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str, limit: int = 5, window: float = 60.0):
    now = time.time()
    _join_attempts[ip] = [t for t in _join_attempts[ip] if now - t < window]
    if len(_join_attempts[ip]) >= limit:
        raise HTTPException(429, "Too many join attempts")
    _join_attempts[ip].append(now)


def _join_rate_key(client_ip: str, account: dict | None) -> str:
    account_id = account.get("account_id") if account else None
    return f"account:{account_id}" if account_id else f"ip:{client_ip}"


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
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    account = _require_v2_join_account(request, dict(room))
    _check_rate_limit(_join_rate_key(client_ip, account))
    player_token = str(uuid.uuid4())
    character_id = str(uuid.uuid4())[:8]
    # Set status based on room state: active rooms put joiners in pending_approval
    char_status = "pending_approval" if room["status"] == "active" else "joined"
    conn.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status, account_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            character_id,
            room_id,
            "未命名玩家",
            player_token,
            char_status,
            account["account_id"] if account else None,
        ),
    )
    conn.commit()
    return {"character_id": character_id, "player_token": player_token, "status": char_status}


@router.get("/rooms/{room_id}/preflight")
async def room_preflight(request: Request, room_id: str):
    conn = request.app.state.db
    room = conn.execute(
        "SELECT room_id, status, player_experience_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    account = get_account_from_token(request)
    recovered = None
    if account:
        recovered = conn.execute(
            "SELECT character_id FROM characters WHERE room_id = %s AND account_id = %s "
            "AND status != 'left' ORDER BY character_id LIMIT 1",
            (room_id, account["account_id"]),
        ).fetchone()
    status = room["status"]
    if status in ("lobby", "draft"):
        join_mode = "direct"
    elif status == "active":
        join_mode = "host_approval"
    else:
        join_mode = "closed"
    return {
        "room_id": room_id,
        "rest_ok": True,
        "websocket_path": "/ws",
        "room_status": status,
        "join_mode": join_mode,
        "requires_login": room.get("player_experience_version") == "v2",
        "authenticated": bool(account),
        "recovery_available": bool(recovered),
        "recovery_character_id": recovered["character_id"] if recovered else None,
    }


@router.get("/rooms/{room_id}/join-info")
async def get_join_info(request: Request, room_id: str):
    """Return room info for the join page: status, presets, templates, players."""
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    account = _require_v2_join_account(request, dict(room))

    room_status = room["status"]
    scenario_id = room.get("scenario_id")
    scenario_title = ""
    templates = []
    if scenario_id:
        sc = conn.execute("SELECT title FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone()
        scenario_title = sc["title"] if sc else ""
        tpl_rows = conn.execute(
            "SELECT * FROM character_templates WHERE scenario_id = %s", (scenario_id,)
        ).fetchall()
        templates = [dict(r) for r in tpl_rows]

    # Determine join mode
    if room_status == "lobby" or room_status == "draft":
        join_mode = "direct"
    elif room_status == "active":
        join_mode = "host_approval"
    else:
        join_mode = "closed"

    # Current players summary
    chars = conn.execute(
        "SELECT character_id, player_name, xlsx_data, status, is_ready FROM characters WHERE room_id = %s AND status != 'left'",
        (room_id,)
    ).fetchall()
    players = []
    for c in chars:
        xlsx = _json_val(c.get("xlsx_data")) or {}
        players.append({
            "character_id": c["character_id"],
            "player_name": c["player_name"],
            "investigator_name": xlsx.get("name", ""),
            "occupation": xlsx.get("occupation", ""),
            "status": c.get("status", "joined"),
            "is_ready": bool(c.get("is_ready")),
        })

    # Presets
    occupied = _occupied_preset_ids(conn, room_id)
    presets = list_presets(preset_dir_from_app(request.app), occupied)

    return {
        "room_id": room_id,
        "room_status": room_status,
        "scenario_title": scenario_title,
        "join_mode": join_mode,
        "players": players,
        "presets": presets,
        "templates": templates,
    }


@router.get("/me/characters")
async def get_my_characters(request: Request):
    """Return all characters owned by the logged-in account."""
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "Login required")
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT c.*, r.status as room_status, s.title as scenario_title "
        "FROM characters c "
        "JOIN rooms r ON c.room_id = r.room_id "
        "LEFT JOIN scenarios s ON r.scenario_id = s.scenario_id "
        "WHERE c.account_id = %s ORDER BY c.room_id, c.player_name",
        (account["account_id"],)
    ).fetchall()
    result = []
    for row in rows:
        r = dict(row)
        xlsx = _json_val(r.get("xlsx_data")) or {}
        result.append({
            "character_id": r["character_id"],
            "room_id": r["room_id"],
            "room_status": r.get("room_status", ""),
            "scenario_title": r.get("scenario_title", ""),
            "player_name": r["player_name"],
            "investigator_name": xlsx.get("name", ""),
            "occupation": xlsx.get("occupation", ""),
            "status": r.get("status", "joined"),
            "is_ready": bool(r.get("is_ready")),
            "hp": xlsx.get("hp", 0), "san": xlsx.get("san", 0),
        })
    return result


@router.post("/characters/{character_id}/restore-session")
async def restore_session(request: Request, character_id: str):
    """Restore a player token for a character owned by the account."""
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "Login required")
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(404, "Character not found")
    if char.get("account_id") != account["account_id"]:
        raise HTTPException(403, "Not your character")
    return {
        "character_id": char["character_id"],
        "room_id": char["room_id"],
        "player_token": char["player_token"],
        "player_name": char["player_name"],
    }


@router.get("/character/presets")
async def character_presets(request: Request, room_id: str = ""):
    conn = request.app.state.db
    occupied = _occupied_preset_ids(conn, room_id) if room_id else set()
    presets = list_presets(preset_dir_from_app(request.app), occupied)
    return {"presets": presets}


@router.post("/character/preview-xlsx")
async def preview_character_xlsx(file: UploadFile = File(...)):
    parsed = await _parse_uploaded_xlsx(file)
    return character_preview(parsed)


@router.post("/rooms/{room_id}/join-with-character")
async def join_room_with_character(
    request: Request, room_id: str,
    player_name: str = Form(...),
    preset_id: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    character_data: str | None = Form(default=None),
    template_id: str | None = Form(default=None),
    copy_character_id: str | None = Form(default=None),
):
    client_ip = request.client.host if request.client else "unknown"
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    account = _require_v2_join_account(request, dict(room))
    _check_rate_limit(_join_rate_key(client_ip, account))
    nickname = player_name.strip()
    if not nickname:
        raise HTTPException(400, "Player name is required")
    source_count = sum(1 for x in [preset_id, file, character_data, template_id, copy_character_id] if x)
    if source_count != 1:
        raise HTTPException(400, "Choose exactly one character source")
    account_id = account["account_id"] if account else _optional_account_id(request)
    room_status = room["status"]
    # Status: lobby→joined, active→pending_approval
    char_status = "pending_approval" if room_status == "active" else "joined"

    source: dict
    initial_inventory: list[dict] = []
    if character_data:
        try:
            parsed = _parse_builder_character_data(character_data)
        except Exception:
            logger.exception("Builder character data parse failed")
            raise HTTPException(400, "Invalid character data from builder")
        source = {"type": "builder"}
    elif preset_id:
        if preset_id in _occupied_preset_ids(conn, room_id):
            raise HTTPException(409, "Character preset already selected")
        preset_path = find_preset(preset_dir_from_app(request.app), preset_id)
        if not preset_path:
            raise HTTPException(404, "Character preset not found")
        try:
            parsed = parse_xlsx_character(str(preset_path))
        except Exception:
            logger.exception("Character preset parse failed: %s", preset_id)
            raise HTTPException(400, "Invalid character preset")
        source = {"type": "preset", "preset_id": preset_id, "file_name": preset_path.name}
    elif template_id:
        tpl_rows = conn.execute(
            "SELECT * FROM character_templates WHERE template_id = %s AND scenario_id = %s",
            (template_id, room.get("scenario_id", "")),
        ).fetchall()
        if not tpl_rows:
            tpl = conn.execute("SELECT * FROM character_templates WHERE template_id = %s", (template_id,)).fetchone()
            if not tpl:
                raise HTTPException(404, "Template not found")
            tpl_rows = [tpl]
        tpl = dict(tpl_rows[0])
        template_attributes = {
            str(key).lower(): value
            for key, value in _json_val(tpl.get("attributes")).items()
        }
        con_score = int(template_attributes.get("con", 50) or 50)
        size_score = template_attributes.get("siz")
        template_hp = (
            (con_score + int(size_score)) // 10
            if size_score is not None
            else con_score // 5 or 10
        )
        parsed = {
            "name": tpl.get("name", ""), "occupation": tpl.get("occupation", ""),
            "age": tpl.get("age", 25), "sex": tpl.get("gender", ""),
            "hp": template_hp,
            "max_hp": template_hp,
            "san": template_attributes.get("pow", 50),
            "max_san": template_attributes.get("pow", 50),
            "mp": template_attributes.get("pow", 50) // 5,
            "max_mp": template_attributes.get("pow", 50) // 5,
            "luck": template_attributes.get("luck", 50),
            "attributes": template_attributes,
            "skills": _json_val(tpl.get("skills")) or {},
            "background": tpl.get("background", ""),
            "backstory": _json_val(tpl.get("backstory")) or {},
            "raw": {"format": "template"},
        }
        initial_inventory = _template_initial_inventory(parsed["backstory"])
        source = {"type": "template", "template_id": template_id}
    elif copy_character_id:
        src = conn.execute("SELECT * FROM characters WHERE character_id = %s", (copy_character_id,)).fetchone()
        if not src:
            raise HTTPException(404, "Source character not found")
        src = dict(src)
        req_token = request.headers.get("X-Room-Token", "")
        if src.get("account_id"):
            if src["account_id"] != account_id:
                raise HTTPException(403, "Cannot copy another account's character")
        elif src.get("player_token") != req_token:
            raise HTTPException(403, "Cannot copy another player's character")
        parsed = _json_val(src.get("xlsx_data")) or {}
        parsed["name"] = parsed.get("name", "") + " (副本)"
        source = {"type": "copy", "copy_character_id": copy_character_id}
    else:
        parsed = await _parse_uploaded_xlsx(file)
        source = {"type": "upload", "file_name": file.filename if file else ""}
    parsed["source"] = source
    player_token = str(uuid.uuid4())
    character_id = str(uuid.uuid4())[:8]
    conn.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data, account_id, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (character_id, room_id, nickname, player_token, json.dumps(parsed, ensure_ascii=False), account_id, char_status),
    )
    for item in initial_inventory:
        conn.execute(
            "INSERT INTO inventory "
            "(id, character_id, room_id, name, description, quantity, is_secret, source) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'scenario_template')",
            (
                str(uuid.uuid4()),
                character_id,
                room_id,
                item["name"],
                item["description"],
                item["quantity"],
                item["is_secret"],
            ),
        )
    conn.commit()
    _index_character_if_available(request, room_id, character_id, parsed)
    # Initialize runtime state via StateService
    state_service = getattr(request.app.state, "state_service", None)
    if state_service:
        try:
            state_service.initialize_character_state(character_id, room_id)
        except Exception as exc:
            logger.warning("StateService init failed for char=%s room=%s: %s", character_id, room_id, exc)
            pass

    # Broadcast updated lobby snapshot so host sees the new player immediately
    try:
        snapshot = _build_lobby_snapshot(conn, room_id)
        from ..engine.projection import ProjectionDispatcher
        dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
        asyncio.create_task(
            dispatcher.emit(room_id, "s2c_room_lobby_snapshot", "party", snapshot)
        )
    except Exception:
        logger.warning("Failed to broadcast lobby snapshot after join", exc_info=True)

    return {
        "character_id": character_id, "player_token": player_token,
        "player_name": nickname, "investigator_name": parsed.get("name", ""),
        "status": char_status, "character": parsed,
    }


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

    from ..scenario.xlsx_parser import parse_xlsx_character

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

    # Initialize runtime state via StateService
    state_service = getattr(request.app.state, "state_service", None)
    if state_service:
        try:
            state_service.initialize_character_state(char["character_id"], char["room_id"])
        except Exception:
            pass

    return parsed


# ── Speech-to-Text ──

@router.post("/speech-to-text")
async def speech_to_text(
    request: Request,
    audio: UploadFile = File(...),
    durationMs: int = Form(default=0),
):
    """Upload audio recording, return transcribed text."""
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()
    if not char:
        raise HTTPException(403, "Invalid token")

    # Validate MIME
    mime = (audio.content_type or "audio/webm").lower()
    from ..stt import ALLOWED_MIME_TYPES, MAX_AUDIO_BYTES, MAX_DURATION_SECONDS, get_stt_provider
    if mime not in ALLOWED_MIME_TYPES and not any(mime.startswith(a.split(";")[0]) for a in ALLOWED_MIME_TYPES):
        raise HTTPException(400, f"Unsupported audio format: {mime}")

    # Read audio
    audio_bytes = await audio.read()
    if not audio_bytes or len(audio_bytes) < 100:
        raise HTTPException(400, "Empty or too short audio")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(413, f"Audio too large: {len(audio_bytes)} bytes (max {MAX_AUDIO_BYTES})")

    # Validate duration
    if durationMs and durationMs / 1000 > MAX_DURATION_SECONDS:
        raise HTTPException(400, f"Audio too long: {durationMs}ms (max {MAX_DURATION_SECONDS}s)")

    # Transcribe
    provider = get_stt_provider(getattr(request.app.state, "settings", None))
    result = await provider.transcribe(audio_bytes, mime)

    if "error" in result:
        if "not configured" in result.get("error", ""):
            raise HTTPException(503, result["error"])
        raise HTTPException(500, result["error"])

    return {
        "transcribedText": result.get("transcribedText", ""),
        "provider": type(provider).__name__.replace("SttProvider", "").lower(),
        "durationMs": durationMs or 0,
        "confidence": result.get("confidence"),
    }


@router.post("/team-message")
async def team_message(request: Request):
    """Send a team chat message (not an action, not resolved by AI)."""
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()
    if not char:
        raise HTTPException(403, "Invalid token")

    body = await request.json()
    from .team_messages import TeamMessageError, send_team_message
    try:
        payload = await send_team_message(
            conn,
            dispatcher=getattr(request.app.state, "dispatcher", None),
            character=dict(char),
            text=body.get("text") or "",
            source=body.get("source", "text"),
        )
    except TeamMessageError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    return {"status": "sent", "messageId": payload["messageId"]}


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

    room = conn.execute(
        "SELECT status, player_experience_version FROM rooms WHERE room_id = %s",
        (char["room_id"],),
    ).fetchone()
    if (
        room
        and room.get("player_experience_version") == "v2"
        and intent.intent_type != "ready_toggle"
        and os.getenv("AIKEEPER_DEV_MODE", "").strip() != "1"
    ):
        raise HTTPException(409, detail={"code": "v2_action_draft_required"})
    if intent.intent_type == "retroactive_item_claim" or extract_retroactive_claim(intent.declared_intent):
        return await _submit_retroactive_claim(request, dict(char), intent)
    is_active = room and room["status"] == "active"

    if is_active and intent.intent_type not in ("ready_toggle",):
        # Turn-based mode: queue action in current turn
        # Check duplicate BEFORE writing action (prevents orphan actions)
        from ..turn_manager import TurnManager
        tm = TurnManager(conn)
        turn = tm.ensure_current_turn(char["room_id"])
        existing = conn.execute(
            "SELECT action_id FROM actions WHERE turn_id = %s AND character_id = %s "
            "AND status NOT IN ('rejected', 'canceled', 'timeout')",
            (turn["turn_id"], char["character_id"]),
        ).fetchone()
        if existing:
            return JSONResponse(
                content={"status": "duplicate", "turn_id": turn["turn_id"], "turn_index": turn["turn_index"],
                         "message": "Already submitted this turn"},
                status_code=409,
            )

        result = engine.submit_intent(char["room_id"], char["character_id"], intent)
        turn_result = tm.submit_action(char["room_id"], char["character_id"], intent.action_id)
        result["turnId"] = turn_result.get("turn_id")
        result["turnIndex"] = turn_result.get("turn_index")
        # Check if all submitted → auto-settle
        if tm.all_submitted(char["room_id"]):
            asyncio.create_task(_settle_turn_background(request.app, char["room_id"], turn_result["turn_id"]))
        return JSONResponse(content=result, status_code=202)

    # Legacy: immediate resolution for non-active rooms
    result = engine.submit_intent(char["room_id"], char["character_id"], intent)
    if result.get("status") == "conflict":
        raise HTTPException(409, "State version conflict")

    # After ready_toggle, broadcast updated lobby snapshot to the whole room
    if intent.intent_type == "ready_toggle" and result.get("status") == "accepted":
        try:
            snapshot = _build_lobby_snapshot(conn, char["room_id"])
            from ..engine.projection import ProjectionDispatcher
            dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
            asyncio.create_task(
                dispatcher.emit(char["room_id"], "s2c_room_lobby_snapshot", "party", snapshot)
            )
        except Exception:
            logger.warning("Failed to broadcast lobby snapshot after ready_toggle", exc_info=True)

    if getattr(request.app.state, "pipeline", None) or getattr(request.app.state, "pg_db", None):
        asyncio.create_task(_resolve_action_background(request.app, intent.action_id))
    return JSONResponse(content=result, status_code=202)


@router.get("/combat-round")
async def get_combat_round(request: Request):
    """Return the caller's safe view of an active combat declaration round."""
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    conn = request.app.state.db
    character = conn.execute(
        "SELECT character_id, room_id FROM characters WHERE player_token = %s",
        (token,),
    ).fetchone()
    if not character:
        raise HTTPException(403, "Invalid token")

    from ..encounter_persistence import get_active_encounter
    from ..turn_manager import TurnManager

    encounter = get_active_encounter(conn, character["room_id"])
    if not encounter or encounter.get("type") != "combat":
        return {"hasCombat": False}

    snapshot = TurnManager(conn).get_turn_snapshot(character["room_id"])
    if snapshot.get("mode") != "combat" or snapshot.get("encounter_id") != encounter["encounter_id"]:
        return {"hasCombat": False}

    players = snapshot["players"]
    own = next(
        (player for player in players if player["character_id"] == character["character_id"]),
        None,
    )
    if not own:
        return {"hasCombat": False}

    submitted_count = sum(1 for player in players if player["submitted"])
    payload = {
        "hasCombat": True,
        "encounterId": encounter["encounter_id"],
        "roundNumber": snapshot.get("encounter_round") or 1,
        "phase": snapshot["phase"],
        "turnId": snapshot["turn_id"],
        "declaration": {
            "submitted": own["submitted"],
            "locked": snapshot["phase"] != "declaration",
            "submittedCount": submitted_count,
            "totalPlayers": len(players),
        },
    }
    turn_row = conn.execute(
        "SELECT combat_plan FROM room_turns WHERE turn_id = %s",
        (snapshot["turn_id"],),
    ).fetchone()
    plan = _json_val(turn_row.get("combat_plan")) if turn_row else None
    public_clusters = _player_public_combat_clusters(plan)
    if public_clusters:
        payload["publicClusters"] = public_clusters
    observable_preparations = _player_observable_preparations(plan)
    if observable_preparations:
        payload["observablePreparations"] = observable_preparations
    from ..host.public_stage import build_public_combat_units_for_encounter
    public_units = build_public_combat_units_for_encounter(conn, encounter["encounter_id"])
    if public_units:
        payload["publicUnits"] = public_units
    return payload


@router.post("/combat-round/idle")
async def declare_combat_round_idle(request: Request):
    """Let the current player formally declare no proactive combat action."""
    character = _get_character(request)
    conn = request.app.state.db
    from ..encounter_persistence import get_active_encounter
    from ..turn_manager import TurnManager

    encounter = get_active_encounter(conn, character["room_id"])
    if not encounter or encounter.get("type") != "combat":
        raise HTTPException(409, "No active combat declaration round")

    turn_manager = TurnManager(conn)
    snapshot = turn_manager.get_turn_snapshot(character["room_id"])
    if (
        snapshot.get("mode") != "combat"
        or snapshot.get("encounter_id") != encounter["encounter_id"]
        or snapshot.get("phase") != "declaration"
    ):
        raise HTTPException(409, "Combat declarations are locked")

    existing = conn.execute(
        "SELECT action_id, intent_type, declared_intent FROM actions "
        "WHERE turn_id = %s AND character_id = %s "
        "AND status NOT IN ('rejected', 'canceled', 'timeout')",
        (snapshot["turn_id"], character["character_id"]),
    ).fetchone()
    if existing:
        if existing["intent_type"] == "system_skip" and existing["declared_intent"] == "本回合跳过: idle":
            return {
                "status": "declared_idle",
                "turnId": snapshot["turn_id"],
                "actionId": existing["action_id"],
            }
        raise HTTPException(409, "A combat declaration already exists")

    result = turn_manager.skip_character(
        character["room_id"],
        snapshot["turn_id"],
        character["character_id"],
        "idle",
    )
    if result.get("status") != "skipped":
        raise HTTPException(409, "Unable to declare idle")

    if turn_manager.all_submitted(character["room_id"]):
        asyncio.create_task(_settle_turn_background(request.app, character["room_id"], snapshot["turn_id"]))
    return {
        "status": "declared_idle",
        "turnId": snapshot["turn_id"],
        "actionId": result["action_id"],
    }


async def _enrich_combat_round_plan(app, room_id: str, turn_manager, turn_id: str, plan: dict) -> dict:
    gateway = getattr(app.state, "gateway", None)
    resolve_combat_round = getattr(gateway, "resolve_combat_round", None)
    if not callable(resolve_combat_round):
        return plan
    from ..combat_round_planner import (
        apply_combat_round_suggestions,
        build_combat_round_ai_context,
    )

    try:
        actions = turn_manager.get_pending_actions(turn_id)
        suggestion = await resolve_combat_round(
            build_combat_round_ai_context(plan, actions),
            room_id=room_id,
        )
        if hasattr(suggestion, "model_dump"):
            suggestion = suggestion.model_dump(by_alias=True)
        if not isinstance(suggestion, dict):
            return plan
        enriched = apply_combat_round_suggestions(plan, suggestion)
        turn_manager.save_combat_plan(turn_id, enriched)
        return enriched
    except Exception as exc:
        logger.warning("Combat round AI planning failed for room=%s turn=%s: %s", room_id, turn_id, type(exc).__name__)
        return plan


async def _replan_combat_round_after_public_fact(
    app,
    room_id: str,
    turn_manager,
    turn_id: str,
    plan: dict,
    completed_action_id: str,
) -> dict:
    """Refresh only the public presentation for unresolved rule-dependent actions."""
    dependent_action_ids = _dependent_combat_action_ids(plan, completed_action_id)
    if not dependent_action_ids:
        return plan
    replan_history = plan.get("presentation_replan_after_action_ids")
    completed_history = []
    if isinstance(replan_history, list):
        for action_id in replan_history:
            normalized_action_id = str(action_id) if isinstance(action_id, str) else ""
            if normalized_action_id and normalized_action_id not in completed_history:
                completed_history.append(normalized_action_id)
    if completed_action_id in completed_history:
        return plan

    gateway = getattr(app.state, "gateway", None)
    resolve_combat_round = getattr(gateway, "resolve_combat_round", None)
    if not callable(resolve_combat_round):
        return plan
    from ..combat_round_planner import (
        apply_combat_round_suggestions,
        build_combat_round_ai_context,
    )

    try:
        actions = turn_manager.get_pending_actions(turn_id)
        suggestion = await resolve_combat_round(
            build_combat_round_ai_context(
                plan,
                actions,
                replan_after_resolution=True,
            ),
            room_id=room_id,
        )
        if hasattr(suggestion, "model_dump"):
            suggestion = suggestion.model_dump(by_alias=True)
        if not isinstance(suggestion, dict):
            return plan
        enriched = apply_combat_round_suggestions(
            plan,
            suggestion,
            eligible_action_ids=dependent_action_ids,
        )
        enriched["presentation_replan_after_action_ids"] = [
            *completed_history,
            completed_action_id,
        ]
        turn_manager.save_combat_plan(turn_id, enriched)
        return enriched
    except Exception as exc:
        logger.warning(
            "Combat round presentation replan failed for room=%s turn=%s action=%s: %s",
            room_id,
            turn_id,
            completed_action_id,
            type(exc).__name__,
        )
        return plan


def _dependent_combat_action_ids(plan: dict, completed_action_id: str) -> set[str]:
    if not isinstance(plan, dict):
        return set()
    completed_action_ids = {
        str(fact.get("action_id"))
        for fact in plan.get("resolved_public_facts", [])
        if isinstance(fact, dict) and fact.get("action_id")
    }
    dependent_action_ids: set[str] = set()
    for step in plan.get("steps", []):
        if not isinstance(step, dict) or step.get("visibility") != "public":
            continue
        action_id = str(step.get("action_id") or "")
        depends_on = step.get("depends_on")
        if (
            action_id
            and action_id not in completed_action_ids
            and isinstance(depends_on, list)
            and completed_action_id in {str(value) for value in depends_on}
        ):
            dependent_action_ids.add(action_id)
    return dependent_action_ids


async def _settle_turn_background(app, room_id: str, turn_id: str):
    """Auto-settle a turn when all players have submitted."""
    logger.info("Auto-settling turn %s for room %s", turn_id, room_id)
    pg_db = getattr(app.state, "pg_db", None)
    conn = pg_db.get_connection() if pg_db else app.state.db
    try:
        from ..turn_manager import TurnManager
        tm = TurnManager(conn)

        # Atomically claim resolving — skip if another worker already took this turn
        if not tm.mark_resolving(turn_id):
            logger.info("Turn %s already claimed by another worker, skipping", turn_id)
            return

        combat_plan = tm.plan_combat_round(turn_id)
        if combat_plan:
            combat_plan = await _enrich_combat_round_plan(
                app,
                room_id,
                tm,
                turn_id,
                combat_plan,
            )
        dispatcher = getattr(app.state, "dispatcher", None)
        if combat_plan and dispatcher:
            await dispatcher.emit(
                room_id,
                "s2c_combat_round_locked",
                "party",
                {
                    "turn_id": turn_id,
                    "round_number": combat_plan["round_number"],
                    "phase": "resolution",
                    "public_clusters": [
                        {"public_title": cluster["public_title"]}
                        for cluster in combat_plan["presentation_clusters"]
                    ],
                    "observable_preparations": _player_observable_preparations(combat_plan),
                },
            )

        # Resolve each queued action through the pipeline
        actions = tm.get_pending_actions(turn_id)
        if combat_plan:
            from ..combat_round_planner import dependency_resolution_order

            actions = dependency_resolution_order(actions)
        _mark_collaboration_batches_resolving(
            conn,
            [action["action_id"] for action in actions],
        )
        results = []
        compiler = getattr(app.state, "compiler", None) or MechanicCompiler(api_key="")
        pipeline = getattr(app.state, "pipeline", None)

        blocked_action_ids: set[str] = set()
        for index, action in enumerate(actions):
            if action["action_id"] in blocked_action_ids:
                continue
            try:
                # Fetch real character name from DB — NOT declared_intent
                char_name = "未知调查员"
                char_row = conn.execute(
                    "SELECT player_name, xlsx_data FROM characters WHERE character_id = %s",
                    (action["character_id"],)
                ).fetchone()
                if char_row:
                    xlsx_d = _json_val(char_row.get("xlsx_data")) or {}
                    char_name = (xlsx_d.get("name") if isinstance(xlsx_d, dict) else None) or char_row["player_name"] or "未知调查员"

                if pipeline:
                    res = await pipeline.resolve_action(action["action_id"])
                    results.append({
                        "action_id": action["action_id"],
                        "character_name": char_name,
                        "declared_intent": action.get("declared_intent", ""),
                        "result": res,
                    })
                    if combat_plan and res.get("status") in {"completed", "resolved"}:
                        public_fact = _released_stage_narration(
                            conn,
                            room_id,
                            action["action_id"],
                        )
                        if public_fact:
                            from ..combat_round_planner import record_combat_round_public_fact

                            combat_plan = record_combat_round_public_fact(
                                combat_plan,
                                action_id=action["action_id"],
                                narrative_text=public_fact,
                            )
                            tm.save_combat_plan(turn_id, combat_plan)
                            combat_plan = await _replan_combat_round_after_public_fact(
                                app,
                                room_id,
                                tm,
                                turn_id,
                                combat_plan,
                                action["action_id"],
                            )
                    if res.get("status") in {"rejected", "timeout"}:
                        dependent_action_ids = _dependent_collaboration_action_ids(
                            conn,
                            action["action_id"],
                            [item["action_id"] for item in actions[index + 1 :]],
                        )
                        if dependent_action_ids:
                            blocked_action_ids.update(dependent_action_ids)
                            for contract_id in _collaboration_contract_ids_for_actions(
                                conn,
                                [action["action_id"], *dependent_action_ids],
                            ):
                                _block_collaboration_batch(
                                    conn,
                                    contract_id,
                                    dependent_action_ids,
                                    "collaboration_dependency_not_met",
                                )
            except Exception as e:
                logger.warning("Action %s failed in turn %s: %s", action["action_id"], turn_id, e)
                transitioned = transition_action(
                    conn,
                    action["action_id"],
                    from_statuses=("resolving",),
                    to_status="awaiting_host_exception",
                    metadata={"reason_code": "resolution_pipeline_error", "ai_stage": "recovering"},
                    result={"reason_code": "resolution_pipeline_error"},
                )
                dispatcher = getattr(app.state, "dispatcher", None)
                if transitioned and dispatcher:
                    await dispatcher.emit(
                        room_id,
                        "s2c_action_exception_requested",
                        "host",
                        {
                            "actionId": action["action_id"],
                            "characterId": action["character_id"],
                            "reasonCode": "resolution_pipeline_error",
                        },
                    )
                    await dispatcher.emit(
                        room_id,
                        "s2c_ai_recovery_required",
                        "player",
                        {
                            "actionId": action["action_id"],
                            "characterId": action["character_id"],
                            "reasonCode": "resolution_pipeline_error",
                        },
                        character_id=action["character_id"],
                    )
                results.append({
                    "action_id": action["action_id"],
                    "character_name": char_name,
                    "declared_intent": action.get("declared_intent", ""),
                    "error": str(e),
                })

        narrative_parts = []
        for item in results:
            result_payload = item.get("result") if isinstance(item, dict) else None
            resolved = result_payload.get("result") if isinstance(result_payload, dict) else None
            if isinstance(resolved, dict) and resolved.get("narrative"):
                narrative_parts.append(str(resolved["narrative"]))
        narrative = "\n".join(narrative_parts)

        _complete_collaboration_batches_for_actions(
            conn,
            [action["action_id"] for action in actions],
        )
        tm.mark_resolved(turn_id, narrative[:500])
        combat_summary = _combat_round_summary(combat_plan, room_id, actions, conn)
        if combat_summary:
            tm.save_combat_summary(turn_id, combat_summary)
        may_open_next_turn = tm.advance_combat_round_if_ready(turn_id) if combat_plan else True

        # Create next turn — only if no newer collecting turn already exists
        existing_next = conn.execute(
            "SELECT turn_id FROM room_turns WHERE room_id = %s AND status = 'collecting' AND turn_index > %s",
            (room_id, conn.execute("SELECT turn_index FROM room_turns WHERE turn_id = %s", (turn_id,)).fetchone()["turn_index"]),
        ).fetchone()
        if may_open_next_turn and not existing_next:
            tm._create_turn(room_id)
        elif existing_next:
            logger.info("Next turn already exists for room %s (turn %s), skipping creation", room_id, existing_next["turn_id"])

        # Broadcast turn resolved event
        if dispatcher:
            if combat_summary:
                await dispatcher.emit(
                    room_id,
                    "s2c_turn_resolved",
                    "party",
                    {"turn_id": turn_id, "combat_summary": combat_summary},
                )
            else:
                await dispatcher.emit(room_id, "s2c_turn_resolved", "party",
                                      {"turn_id": turn_id, "narrative": narrative, "actions": results})

    except Exception as e:
        logger.exception("Turn settlement failed for room %s turn %s: %s", room_id, turn_id, e)
    finally:
        if pg_db:
            conn.close()


def _player_public_combat_clusters(plan: dict | None) -> list[dict]:
    if not isinstance(plan, dict):
        return []
    clusters = []
    for cluster in plan.get("presentation_clusters", []):
        if not isinstance(cluster, dict) or cluster.get("visibility") == "private":
            continue
        title = cluster.get("public_title")
        if not isinstance(title, str) or not title.strip():
            continue
        facts = cluster.get("completed_public_facts")
        clusters.append(
            {
                "publicTitle": title.strip()[:80],
                "completedPublicFacts": [
                    fact.strip()
                    for fact in facts
                    if isinstance(fact, str) and fact.strip()
                ][:5] if isinstance(facts, list) else [],
            }
        )
    return clusters


def _player_observable_preparations(plan: dict | None) -> list[str]:
    if not isinstance(plan, dict):
        return []
    values = plan.get("observable_preparations")
    if not isinstance(values, list):
        return []
    return [
        value.strip()[:200]
        for value in values
        if isinstance(value, str) and value.strip()
    ][:8]


def _combat_round_summary(combat_plan, room_id: str, actions: list[dict], conn) -> dict | None:
    if not combat_plan:
        return None
    recorded_facts = combat_plan.get("resolved_public_facts")
    public_facts = [
        str(fact["text"])
        for fact in recorded_facts
        if isinstance(fact, dict) and isinstance(fact.get("text"), str) and fact["text"].strip()
    ] if isinstance(recorded_facts, list) else []
    if not public_facts:
        for action in actions:
            text = _released_stage_narration(conn, room_id, action["action_id"])
            if text:
                public_facts.append(text)
    return {
        "round_number": combat_plan["round_number"],
        "title": f"第 {combat_plan['round_number']} 轮结束",
        "public_facts": public_facts,
        "current_situation": public_facts[-1] if public_facts else "本轮结算完成，局势等待下一轮行动。",
    }


def _released_stage_narration(conn, room_id: str, action_id: str) -> str | None:
    row = conn.execute(
        "SELECT stage_projection FROM resolution_bundles "
        "WHERE action_id = %s AND room_id = %s AND release_status = 'released'",
        (action_id, room_id),
    ).fetchone()
    projection = _json_val(row.get("stage_projection")) if row else None
    text = projection.get("narrativeText") if isinstance(projection, dict) else None
    return str(text).strip() if isinstance(text, str) and text.strip() else None


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
                host_connection_checker=lambda room_id: ws_manager.is_connected(room_id, "host"),
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


async def _resolve_collaboration_batch_background(app, contract_id: str):
    pg_db = getattr(app.state, "pg_db", None)
    conn = pg_db.get_connection() if pg_db else app.state.db
    try:
        batch = conn.execute(
            "UPDATE collaboration_contract_batches SET status = 'resolving', started_at = NOW(), updated_at = NOW() "
            "WHERE contract_id = %s AND status = 'queued' RETURNING *",
            (contract_id,),
        ).fetchone()
        if not batch:
            return
        raw_action_ids = batch.get("action_ids") or []
        if isinstance(raw_action_ids, str):
            try:
                raw_action_ids = json.loads(raw_action_ids)
            except json.JSONDecodeError:
                raw_action_ids = []
        action_ids = [str(action_id) for action_id in raw_action_ids if str(action_id)]
        if not action_ids:
            conn.execute(
                "UPDATE collaboration_contract_batches SET status = 'blocked', updated_at = NOW() "
                "WHERE contract_id = %s",
                (contract_id,),
            )
            return
        if pg_db:
            compiler = getattr(app.state, "compiler", None) or MechanicCompiler(api_key="")
            pipeline = ResolutionPipeline(
                conn,
                compiler=compiler,
                dispatcher=ProjectionDispatcher(conn),
                host_connection_checker=lambda room_id: ws_manager.is_connected(room_id, "host"),
            )
        else:
            pipeline = getattr(app.state, "pipeline", None)
        if not pipeline:
            _block_collaboration_batch(conn, contract_id, action_ids, "resolution_pipeline_unavailable")
            return
        blocked_action_ids: set[str] = set()
        for index, action_id in enumerate(action_ids):
            if action_id in blocked_action_ids:
                continue
            result = await pipeline.resolve_action(action_id)
            if result.get("status") in {"rejected", "timeout"}:
                dependent_action_ids = _dependent_collaboration_action_ids(
                    conn,
                    action_id,
                    action_ids[index + 1 :],
                )
                if dependent_action_ids:
                    blocked_action_ids.update(dependent_action_ids)
                    _block_collaboration_batch(
                        conn,
                        contract_id,
                        dependent_action_ids,
                        "collaboration_dependency_not_met",
                    )
            if result.get("status") not in {"completed", "resolved", "rejected"}:
                _block_collaboration_batch(
                    conn,
                    contract_id,
                    action_ids[index + 1 :],
                    "collaboration_batch_requires_review",
                )
                return
        _complete_collaboration_batch_if_terminal(conn, contract_id)
    except Exception:
        logger.exception("Collaboration batch resolution failed for contract %s", contract_id)
        _block_collaboration_batch(conn, contract_id, [], "collaboration_batch_resolution_failed")
    finally:
        if pg_db:
            conn.close()


def _block_collaboration_batch(conn, contract_id: str, action_ids: list[str], reason_code: str) -> None:
    conn.execute(
        "UPDATE collaboration_contract_batches SET status = 'blocked', updated_at = NOW() "
        "WHERE contract_id = %s AND status = 'resolving'",
        (contract_id,),
    )
    for action_id in action_ids:
        cursor = conn.execute(
            "UPDATE actions SET status = 'awaiting_host_exception' "
            "WHERE action_id = %s AND status = 'batched'",
            (action_id,),
        )
        if cursor.rowcount:
            conn.execute(
                "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, 'awaiting_host_exception', %s)",
                (action_id, json.dumps({"reason_code": reason_code}, ensure_ascii=False)),
            )


def _dependent_collaboration_action_ids(
    conn,
    prerequisite_action_id: str,
    candidate_action_ids: list[str],
) -> list[str]:
    if not candidate_action_ids:
        return []
    placeholders = ", ".join("%s" for _ in candidate_action_ids)
    rows = conn.execute(
        "SELECT action_id, params FROM actions "
        f"WHERE action_id IN ({placeholders})",
        tuple(candidate_action_ids),
    ).fetchall()
    dependent_ids = {
        str(row["action_id"])
        for row in rows
        if prerequisite_action_id in ((_json_val(row.get("params")) or {}).get("depends_on_action_ids") or [])
    }
    return [action_id for action_id in candidate_action_ids if action_id in dependent_ids]


def _mark_collaboration_batches_resolving(conn, action_ids: list[str]) -> None:
    contract_ids = _collaboration_contract_ids_for_actions(conn, action_ids)
    for contract_id in contract_ids:
        conn.execute(
            "UPDATE collaboration_contract_batches SET status = 'resolving', started_at = NOW(), updated_at = NOW() "
            "WHERE contract_id = %s AND status = 'queued'",
            (contract_id,),
        )


def _complete_collaboration_batches_for_actions(conn, action_ids: list[str]) -> None:
    for contract_id in _collaboration_contract_ids_for_actions(conn, action_ids):
        _complete_collaboration_batch_if_terminal(conn, contract_id)


def _collaboration_contract_ids_for_actions(conn, action_ids: list[str]) -> list[str]:
    if not action_ids:
        return []
    placeholders = ", ".join("%s" for _ in action_ids)
    rows = conn.execute(
        "SELECT DISTINCT batches.contract_id "
        "FROM collaboration_contract_batches AS batches "
        "JOIN collaboration_contract_drafts AS links ON links.contract_id = batches.contract_id "
        "JOIN actions ON actions.draft_id = links.draft_id "
        f"WHERE actions.action_id IN ({placeholders}) "
        "AND batches.status IN ('queued', 'resolving')",
        tuple(action_ids),
    ).fetchall()
    return [str(row["contract_id"]) for row in rows]


def _complete_collaboration_batch_if_terminal(conn, contract_id: str) -> bool:
    rows = conn.execute(
        "SELECT actions.status FROM collaboration_contract_drafts AS links "
        "JOIN actions ON actions.draft_id = links.draft_id "
        "WHERE links.contract_id = %s",
        (contract_id,),
    ).fetchall()
    if not rows or any(row["status"] not in {"completed", "resolved", "rejected"} for row in rows):
        return False
    completed = conn.execute(
        "UPDATE collaboration_contract_batches SET status = 'completed', completed_at = NOW(), updated_at = NOW() "
        "WHERE contract_id = %s AND status IN ('queued', 'resolving')",
        (contract_id,),
    )
    if not completed.rowcount:
        return False
    conn.execute(
        "UPDATE collaboration_contracts SET status = 'completed', updated_at = NOW() "
        "WHERE contract_id = %s AND status = 'accepted'",
        (contract_id,),
    )
    return True


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
    # Read from character_runtime_state first (authoritative), fallback to xlsx_data
    conn2 = None
    try:
        # Check if we have a connection available
        data = _json_value(char.get("xlsx_data")) or {}
        luck_xlsx = data.get("luck", 0)
    except (TypeError, ValueError):
        luck_xlsx = 0
    try:
        return int(luck_xlsx)
    except (TypeError, ValueError):
        return 0


def _decrement_luck(conn, char: dict, luck: int):
    new_luck = max(0, luck - 1)
    # Write to character_runtime_state as authoritative source
    existing = conn.execute(
        "SELECT * FROM character_runtime_state WHERE character_id = %s",
        (char["character_id"],),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE character_runtime_state SET luck = %s, updated_at = NOW() WHERE character_id = %s",
            (new_luck, char["character_id"]),
        )
    else:
        conn.execute(
            "INSERT INTO character_runtime_state (character_id, luck) VALUES (%s, %s)",
            (char["character_id"], new_luck),
        )
    # Also sync xlsx_data for backward compatibility (derived, not authoritative)
    data = _json_value(char.get("xlsx_data")) or {}
    data["luck"] = new_luck
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
    owned_clues = conn.execute(
        "SELECT * FROM clues WHERE character_id = %s", (character_id,)
    ).fetchall()
    # Include shared clues from teammates (public_version only)
    shared_clues = conn.execute(
        "SELECT cs.clue_id, cs.public_version AS text, cs.shared_by, cs.shared_at, c.source, c.discovered_at "
        "FROM clue_shares cs JOIN clues c ON cs.clue_id = c.clue_id "
        "WHERE c.room_id = %s AND c.character_id != %s",
        (char["room_id"], character_id),
    ).fetchall()

    all_clues = []
    for c in owned_clues:
        all_clues.append(dict(c))
    for c in shared_clues:
        all_clues.append({
            "clue_id": c["clue_id"],
            "text": c["text"],
            "source": c["source"],
            "discovered_at": c["discovered_at"],
            "shared_by": c["shared_by"],
            "is_owner": False,
        })

    room_row = conn.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s", (char["room_id"],)
    ).fetchone()
    state_version = room_row["state_version"] if room_row else 0

    return {
        **char,
        "inventory": [dict(i) for i in items],
        "clues": all_clues,
        "stateVersion": state_version,
    }


@router.get("/character")
async def get_character(request: Request):
    char = _get_character(request)
    xlsx_data = _json_val(char.get("xlsx_data")) or {}
    player_name = char.get("player_name", "")
    investigator_name = char.get("investigator_name") or xlsx_data.get("name") or player_name

    # Room status — needed so the client can redirect to lobby if game hasn't started
    conn = request.app.state.db
    room = conn.execute(
        "SELECT status FROM rooms WHERE room_id = %s", (char["room_id"],)
    ).fetchone()

    # Merge character_runtime_state for live HP/SAN/MP/Luck values
    crs = conn.execute(
        "SELECT * FROM character_runtime_state WHERE character_id = %s",
        (char["character_id"],),
    ).fetchone()
    runtime = dict(crs) if crs else {}

    return {
        "character_id": char["character_id"],
        "player_name": player_name,
        "playerName": player_name,
        "investigator_name": investigator_name,
        "investigatorName": investigator_name,
        "name": investigator_name,
        "hp": runtime.get("hp") if runtime.get("hp") is not None else xlsx_data.get("hp", 0),
        "max_hp": xlsx_data.get("max_hp", 0),
        "san": runtime.get("san") if runtime.get("san") is not None else xlsx_data.get("san", 0),
        "max_san": xlsx_data.get("max_san", 0),
        "mp": runtime.get("mp") if runtime.get("mp") is not None else xlsx_data.get("mp", 0),
        "max_mp": xlsx_data.get("max_mp", 0),
        "luck": runtime.get("luck") if runtime.get("luck") is not None else xlsx_data.get("luck", 0),
        "skills": xlsx_data.get("skills", {}),
        "background": xlsx_data.get("background", ""),
        # Lobby-ready fields — single source of truth from DB
        "is_ready": bool(char.get("is_ready", False)),
        "status": char.get("status", "joined"),
        "room_status": room["status"] if room else "unknown",
    }


@router.get("/inventory")
async def get_inventory(request: Request):
    char = _get_character(request)
    conn = request.app.state.db
    items = conn.execute(
        "SELECT * FROM inventory WHERE character_id = %s", (char["character_id"],)
    ).fetchall()
    return [dict(i) for i in items]


def _inventory_transfer_payload(row: dict) -> dict:
    return {
        "transferId": row["transfer_id"],
        "itemId": row["item_id"],
        "itemName": row["item_name"],
        "isSecret": bool(row.get("item_is_secret", False)),
        "fromCharacterId": row["from_character_id"],
        "toCharacterId": row["to_character_id"],
        "fromPlayerName": row.get("from_player_name") or "调查员",
        "toPlayerName": row.get("to_player_name") or "调查员",
        "quantity": row["quantity"],
        "status": row["status"],
        "createdAt": str(row["created_at"]),
        "resolvedAt": str(row["resolved_at"]) if row.get("resolved_at") else None,
    }


@router.get("/inventory-transfer-candidates")
async def get_inventory_transfer_candidates(request: Request):
    char = _get_character(request)
    rows = request.app.state.db.execute(
        """
        SELECT character_id, player_name
        FROM characters
        WHERE room_id = %s AND character_id != %s AND status != 'left'
        ORDER BY player_name, character_id
        """,
        (char["room_id"], char["character_id"]),
    ).fetchall()
    return {"candidates": [
        {"characterId": row["character_id"], "playerName": row.get("player_name") or "调查员"}
        for row in rows
    ]}


@router.post("/inventory/{item_id}/transfers", status_code=201)
async def create_inventory_transfer(
    request: Request,
    item_id: str,
    payload: InventoryTransferCreate,
):
    char = _get_character(request)
    conn = request.app.state.db
    if payload.to_character_id == char["character_id"]:
        raise HTTPException(400, "不能转移给自己")
    recipient = conn.execute(
        "SELECT character_id FROM characters WHERE character_id = %s AND room_id = %s AND status != 'left'",
        (payload.to_character_id, char["room_id"]),
    ).fetchone()
    if not recipient:
        raise HTTPException(404, "目标调查员不在当前房间")
    item = conn.execute(
        "SELECT * FROM inventory WHERE id = %s AND character_id = %s AND room_id = %s",
        (item_id, char["character_id"], char["room_id"]),
    ).fetchone()
    if not item:
        raise HTTPException(404, "物品不存在或不属于当前角色")
    pending = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS quantity FROM inventory_transfer_requests "
        "WHERE item_id = %s AND status = 'pending'",
        (item_id,),
    ).fetchone()
    available_quantity = int(item.get("quantity") or 0) - int(pending.get("quantity") or 0)
    if payload.quantity > available_quantity:
        raise HTTPException(409, "可转移数量不足，已有待接收请求")

    transfer_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO inventory_transfer_requests
            (transfer_id, room_id, item_id, from_character_id, to_character_id,
             item_name, item_is_secret, quantity)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            transfer_id, char["room_id"], item_id, char["character_id"], payload.to_character_id,
            item["name"], bool(item.get("is_secret", False)), payload.quantity,
        ),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT transfer.*, sender.player_name AS from_player_name, recipient.player_name AS to_player_name
        FROM inventory_transfer_requests AS transfer
        LEFT JOIN characters AS sender ON sender.character_id = transfer.from_character_id
        LEFT JOIN characters AS recipient ON recipient.character_id = transfer.to_character_id
        WHERE transfer.transfer_id = %s
        """,
        (transfer_id,),
    ).fetchone()
    return _inventory_transfer_payload(dict(row))


@router.get("/inventory-transfers")
async def get_inventory_transfers(request: Request):
    char = _get_character(request)
    rows = request.app.state.db.execute(
        """
        SELECT transfer.*, sender.player_name AS from_player_name, recipient.player_name AS to_player_name
        FROM inventory_transfer_requests AS transfer
        LEFT JOIN characters AS sender ON sender.character_id = transfer.from_character_id
        LEFT JOIN characters AS recipient ON recipient.character_id = transfer.to_character_id
        WHERE transfer.from_character_id = %s OR transfer.to_character_id = %s
        ORDER BY transfer.created_at DESC
        """,
        (char["character_id"], char["character_id"]),
    ).fetchall()
    outgoing = []
    incoming = []
    for row in rows:
        transfer = _inventory_transfer_payload(dict(row))
        if row["from_character_id"] == char["character_id"]:
            outgoing.append(transfer)
        else:
            incoming.append(transfer)
    return {"incoming": incoming, "outgoing": outgoing}


def _resolve_inventory_transfer(request: Request, transfer_id: str, resolution: str) -> dict:
    char = _get_character(request)
    conn = request.app.state.db
    transfer = conn.execute(
        "SELECT * FROM inventory_transfer_requests WHERE transfer_id = %s FOR UPDATE",
        (transfer_id,),
    ).fetchone()
    if not transfer:
        raise HTTPException(404, "转移请求不存在")
    transfer = dict(transfer)
    if transfer["to_character_id"] != char["character_id"]:
        raise HTTPException(403, "只有接收方可以处理该请求")
    if transfer["status"] != "pending":
        raise HTTPException(409, "转移请求已经处理")
    if resolution == "rejected":
        conn.execute(
            "UPDATE inventory_transfer_requests SET status = 'rejected', resolved_at = NOW() WHERE transfer_id = %s",
            (transfer_id,),
        )
        conn.commit()
        transfer["status"] = "rejected"
        return _inventory_transfer_payload(transfer)

    source_item = conn.execute(
        "SELECT * FROM inventory WHERE id = %s AND character_id = %s AND room_id = %s FOR UPDATE",
        (transfer["item_id"], transfer["from_character_id"], transfer["room_id"]),
    ).fetchone()
    if not source_item or int(source_item.get("quantity") or 0) < int(transfer["quantity"]):
        conn.execute(
            "UPDATE inventory_transfer_requests SET status = 'unavailable', resolved_at = NOW() WHERE transfer_id = %s",
            (transfer_id,),
        )
        conn.commit()
        raise HTTPException(409, "物品已不可用，转移请求已关闭")

    source_item = dict(source_item)
    if int(source_item["quantity"]) == int(transfer["quantity"]):
        result_item_id = source_item["id"]
        conn.execute(
            "UPDATE inventory SET character_id = %s WHERE id = %s",
            (char["character_id"], result_item_id),
        )
    else:
        result_item_id = str(uuid.uuid4())
        conn.execute(
            "UPDATE inventory SET quantity = quantity - %s WHERE id = %s",
            (transfer["quantity"], source_item["id"]),
        )
        conn.execute(
            """
            INSERT INTO inventory (id, character_id, room_id, name, description, quantity, is_secret, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result_item_id, char["character_id"], transfer["room_id"], source_item["name"],
                source_item.get("description") or "", transfer["quantity"],
                bool(source_item.get("is_secret", False)), source_item.get("source") or "",
            ),
        )
    state = conn.execute(
        "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s RETURNING state_version",
        (transfer["room_id"],),
    ).fetchone()
    conn.execute(
        """
        UPDATE inventory_transfer_requests
        SET status = 'completed', result_item_id = %s, resolved_at = NOW()
        WHERE transfer_id = %s
        """,
        (result_item_id, transfer_id),
    )
    from ..events.event_log import EventLog
    EventLog(conn).log_event(transfer["room_id"], "inventory_transfer_completed", "system", {
        "operation": "inventory_transfer_completed",
        "transferId": transfer_id,
        "fromCharacterId": transfer["from_character_id"],
        "toCharacterId": char["character_id"],
        "quantity": transfer["quantity"],
        "stateVersion": state["state_version"],
    })
    transfer["status"] = "completed"
    transfer["resolved_at"] = "now"
    return _inventory_transfer_payload(transfer)


@router.post("/inventory-transfers/{transfer_id}/accept")
async def accept_inventory_transfer(request: Request, transfer_id: str):
    return _resolve_inventory_transfer(request, transfer_id, "completed")


@router.post("/inventory-transfers/{transfer_id}/reject")
async def reject_inventory_transfer(request: Request, transfer_id: str):
    return _resolve_inventory_transfer(request, transfer_id, "rejected")


@router.post("/skill-check")
async def skill_check(request: Request, req: SkillCheckRequest):
    char = _get_character(request)
    room = request.app.state.db.execute(
        "SELECT player_experience_version FROM rooms WHERE room_id = %s",
        (char["room_id"],),
    ).fetchone()
    if (
        room
        and room.get("player_experience_version") == "v2"
        and os.getenv("AIKEEPER_DEV_MODE", "").strip() != "1"
    ):
        raise HTTPException(409, detail={"code": "v2_action_draft_required"})
    result = roll_skill_check(req.skill_value, req.difficulty, req.bonus_dice)
    result["skill_name"] = req.skill_name
    return result


# ── helpers ──

async def _parse_uploaded_xlsx(file: UploadFile | None) -> dict:
    if file is None:
        raise HTTPException(400, "Missing character file")
    try:
        content = await file.read()
        # Save to temp file for parse_xlsx_character
        import tempfile, os as _os
        tmp_path = _os.path.join(tempfile.gettempdir(), f"upload_{uuid.uuid4().hex[:8]}.xlsx")
        with open(tmp_path, "wb") as f:
            f.write(content)
        result = parse_xlsx_character(tmp_path)
        _os.remove(tmp_path)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Character xlsx parse failed: %s", getattr(file, "filename", ""))
        raise HTTPException(400, "Invalid character xlsx")


def _occupied_preset_ids(conn, room_id: str) -> set[str]:
    if not room_id:
        return set()
    rows = conn.execute(
        "SELECT xlsx_data FROM characters WHERE room_id = %s", (room_id,)
    ).fetchall()
    occupied = set()
    for row in rows:
        data = _json_val(row.get("xlsx_data")) or {}
        source = data.get("source") or {}
        pid = source.get("preset_id")
        if pid:
            occupied.add(str(pid))
    return occupied


def _index_character_if_available(request: Request, room_id: str, character_id: str, parsed: dict):
    if hasattr(request.app.state, "rag") and request.app.state.rag:
        try:
            request.app.state.rag.index_character(room_id, character_id, parsed)
        except Exception as e:
            logger.warning("Character RAG indexing failed: %s", e)


def _parse_builder_character_data(raw: str) -> dict:
    data = json.loads(raw)
    attributes = data.get("attributes", {})
    derived = data.get("derived_stats", {})
    return {
        "name": data.get("name", ""), "occupation": data.get("occupation", ""),
        "age": data.get("age", 25), "sex": data.get("gender", ""),
        "hp": derived.get("hp", 0), "max_hp": derived.get("hp", 0),
        "san": derived.get("san", 0), "max_san": derived.get("san", 0),
        "mp": derived.get("mp", 0), "max_mp": derived.get("mp", 0),
        "luck": attributes.get("luck", 0),
        "skills": data.get("skills", {}), "background": data.get("background", ""),
        "backstory": data.get("backstory", {}),
        "attributes": attributes, "derived_stats": derived,
        "raw": {"format": "builder"},
    }


def _optional_account_id(request: Request) -> str | None:
    try:
        from ..router_auth import get_account_from_token
        account = get_account_from_token(request)
        return account["account_id"] if account else None
    except Exception:
        return None


def _require_v2_join_account(request: Request, room: dict) -> dict | None:
    account = get_account_from_token(request)
    if room.get("player_experience_version") != "v2" or account:
        return account
    if os.getenv("AIKEEPER_DEV_MODE", "").strip() == "1":
        return None
    raise HTTPException(401, detail={"code": "login_required"})


def _json_val(value):
    if value is None: return None
    if isinstance(value, (dict, list)): return value
    if isinstance(value, str):
        try: return json.loads(value)
        except json.JSONDecodeError: return None
    return value


def _template_initial_inventory(backstory: dict | None) -> list[dict]:
    raw_items = (backstory or {}).get("inventory") if isinstance(backstory, dict) else []
    if not isinstance(raw_items, list):
        return []
    items = []
    for raw in raw_items:
        value = {"name": raw} if isinstance(raw, str) else raw
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or "").strip()
        if not name:
            continue
        try:
            quantity = max(1, min(99, int(value.get("quantity") or 1)))
        except (TypeError, ValueError):
            quantity = 1
        items.append({
            "name": name[:120],
            "description": str(value.get("description") or "")[:1000],
            "quantity": quantity,
            "is_secret": bool(value.get("is_secret", False)),
        })
    return items[:50]


def _build_lobby_snapshot(conn, room_id: str) -> dict:
    """Build a lobby snapshot for broadcast after player state changes."""
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    if not room:
        return {"room_id": room_id, "room_status": "unknown", "players": []}

    scenario_title = ""
    if room.get("scenario_id"):
        sc = conn.execute(
            "SELECT title FROM scenarios WHERE scenario_id = %s",
            (room["scenario_id"],)
        ).fetchone()
        scenario_title = sc["title"] if sc else ""

    chars = conn.execute(
        """SELECT character_id, player_name, xlsx_data, status, is_ready
           FROM characters WHERE room_id = %s AND status != 'left'""",
        (room_id,)
    ).fetchall()

    players = []
    for c in chars:
        xlsx = _json_val(c.get("xlsx_data")) or {}
        players.append({
            "character_id": c["character_id"],
            "player_name": c["player_name"],
            "investigator_name": xlsx.get("name", "") if isinstance(xlsx, dict) else "",
            "status": c.get("status", "joined"),
            "is_ready": bool(c.get("is_ready")),
        })

    return {
        "room_id": room_id,
        "room_status": room["status"],
        "scenario_title": scenario_title,
        "players": players,
    }
