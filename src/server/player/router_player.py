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
from ..models import PlayerIntent, SkillCheckRequest
from ..ai.mechanic_compiler import MechanicCompiler
from ..engine.projection import ProjectionDispatcher
from ..engine.resolution_pipeline import ResolutionPipeline
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
    # Set status based on room state: active rooms put joiners in pending_approval
    char_status = "pending_approval" if room["status"] == "active" else "joined"
    conn.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) VALUES (%s, %s, %s, %s, %s)",
        (character_id, room_id, "未命名玩家", player_token, char_status),
    )
    conn.commit()
    return {"character_id": character_id, "player_token": player_token, "status": char_status}


@router.get("/rooms/{room_id}/join-info")
async def get_join_info(request: Request, room_id: str):
    """Return room info for the join page: status, presets, templates, players."""
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")

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
    _check_rate_limit(client_ip)
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "Room not found")
    nickname = player_name.strip()
    if not nickname:
        raise HTTPException(400, "Player name is required")
    source_count = sum(1 for x in [preset_id, file, character_data, template_id, copy_character_id] if x)
    if source_count != 1:
        raise HTTPException(400, "Choose exactly one character source")
    account_id = _optional_account_id(request)
    room_status = room["status"]
    # Status: lobby→joined, active→pending_approval
    char_status = "pending_approval" if room_status == "active" else "joined"

    source: dict
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
        parsed = {
            "name": tpl.get("name", ""), "occupation": tpl.get("occupation", ""),
            "age": tpl.get("age", 25), "sex": tpl.get("gender", ""),
            "hp": _json_val(tpl.get("attributes")).get("con", 50) // 5 or 10,
            "max_hp": _json_val(tpl.get("attributes")).get("con", 50) // 5 or 10,
            "san": _json_val(tpl.get("attributes")).get("pow", 50),
            "max_san": _json_val(tpl.get("attributes")).get("pow", 50),
            "mp": _json_val(tpl.get("attributes")).get("pow", 50) // 5,
            "max_mp": _json_val(tpl.get("attributes")).get("pow", 50) // 5,
            "luck": _json_val(tpl.get("attributes")).get("luck", 50),
            "skills": _json_val(tpl.get("skills")) or {},
            "background": tpl.get("background", ""),
            "backstory": _json_val(tpl.get("backstory")) or {},
            "raw": {"format": "template"},
        }
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
    from ...stt import ALLOWED_MIME_TYPES, MAX_AUDIO_BYTES, MAX_DURATION_SECONDS, get_stt_provider
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


# ── Simple rate limiter for team messages ──
_team_msg_rates: dict[str, list[float]] = {}  # character_id -> [timestamps]

def _check_team_msg_rate(character_id: str, max_per_sec: int = 3) -> bool:
    import time as _time
    now = _time.monotonic()
    stamps = _team_msg_rates.get(character_id, [])
    stamps = [s for s in stamps if now - s < 1.0]
    if len(stamps) >= max_per_sec:
        _team_msg_rates[character_id] = stamps
        return False
    stamps.append(now)
    _team_msg_rates[character_id] = stamps
    return True


ALLOWED_SOURCES = {"text", "voice"}  # system_import is server/internal only, not player-facing
MAX_TEAM_MSG_LENGTH = 2000


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
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    if len(text) > MAX_TEAM_MSG_LENGTH:
        raise HTTPException(400, f"text exceeds {MAX_TEAM_MSG_LENGTH} characters")
    source = body.get("source", "text")
    if source not in ALLOWED_SOURCES:
        raise HTTPException(400, f"source must be one of: {', '.join(sorted(ALLOWED_SOURCES))}")

    # Rate limit: max 3 messages per second per character
    if not _check_team_msg_rate(char["character_id"]):
        raise HTTPException(429, "Too many messages — slow down")

    # Build payload
    xlsx = char.get("xlsx_data") or {}
    if isinstance(xlsx, str):
        import json as _json
        try:
            xlsx = _json.loads(xlsx)
        except Exception:
            xlsx = {}

    from ..models import EngineEvent
    import uuid as _uuid
    from datetime import datetime, timezone

    payload = {
        "messageId": str(_uuid.uuid4()),
        "characterId": char["character_id"],
        "playerName": char.get("player_name", ""),
        "investigatorName": xlsx.get("name", ""),
        "text": text,
        "source": source,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    # Write + broadcast via ProjectionDispatcher (handles both DB insert and WS push)
    from ..engine.projection import ProjectionDispatcher
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(conn)
    import asyncio
    try:
        asyncio.get_running_loop().create_task(
            dispatcher.emit(char["room_id"], "s2c_team_message", "party", payload)
        )
    except RuntimeError:
        # No running event loop — fall back to direct event log write
        from ..events.event_log import EventLog
        EventLog(conn).log_event(char["room_id"], "s2c_team_message", "party", payload)

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

    if intent.intent_type == "retroactive_item_claim" or extract_retroactive_claim(intent.declared_intent):
        return await _submit_retroactive_claim(request, dict(char), intent)

    room = conn.execute("SELECT status FROM rooms WHERE room_id = %s", (char["room_id"],)).fetchone()
    is_active = room and room["status"] == "active"

    if is_active and intent.intent_type not in ("ready_toggle",):
        # Turn-based mode: queue action in current turn
        # Check duplicate BEFORE writing action (prevents orphan actions)
        from ..turn_manager import TurnManager
        tm = TurnManager(conn)
        turn = tm.ensure_current_turn(char["room_id"])
        existing = conn.execute(
            "SELECT action_id FROM actions WHERE turn_id = %s AND character_id = %s AND status != 'rejected'",
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


async def _settle_turn_background(app, room_id: str, turn_id: str):
    """Auto-settle a turn when all players have submitted."""
    logger.info("Auto-settling turn %s for room %s", turn_id, room_id)
    try:
        pg_db = getattr(app.state, "pg_db", None)
        conn = pg_db.get_connection() if pg_db else app.state.db
        from ..turn_manager import TurnManager
        tm = TurnManager(conn)

        # Atomically claim resolving — skip if another worker already took this turn
        if not tm.mark_resolving(turn_id):
            logger.info("Turn %s already claimed by another worker, skipping", turn_id)
            return

        # Resolve each queued action through the pipeline
        actions = tm.get_pending_actions(turn_id)
        results = []
        compiler = getattr(app.state, "compiler", None) or MechanicCompiler(api_key="")
        pipeline = getattr(app.state, "pipeline", None)

        for action in actions:
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
            except Exception as e:
                logger.warning("Action %s failed in turn %s: %s", action["action_id"], turn_id, e)
                results.append({
                    "action_id": action["action_id"],
                    "character_name": char_name,
                    "declared_intent": action.get("declared_intent", ""),
                    "error": str(e),
                })

        # Generate narrative
        provider = getattr(app.state, "narrative_provider", None)
        if not provider:
            from ..narrative_provider import TemplateNarrativeProvider, DeepSeekNarrativeProvider
            settings = getattr(app.state, "settings", None)
            api_key = getattr(settings, "deepseek_api_key", "") if settings else ""
            if api_key:
                provider = DeepSeekNarrativeProvider(api_key=api_key)
            else:
                provider = TemplateNarrativeProvider()

        try:
            room = conn.execute("SELECT r.*, s.title FROM rooms r LEFT JOIN scenarios s ON r.scenario_id = s.scenario_id WHERE r.room_id = %s", (room_id,)).fetchone()
            narrative = await provider.generate({
                "turn_index": conn.execute("SELECT turn_index FROM room_turns WHERE turn_id = %s", (turn_id,)).fetchone()["turn_index"],
                "scenario_title": dict(room).get("title", ""),
                "actions": results,
            })
        except Exception as e:
            logger.exception("Narrative generation failed: %s", e)
            from ..narrative_provider import TemplateNarrativeProvider
            narrative = await TemplateNarrativeProvider().generate({
                "turn_index": 1,
                "scenario_title": "",
                "actions": results,
            })

        tm.mark_resolved(turn_id, narrative[:500])

        # Create next turn — only if no newer collecting turn already exists
        existing_next = conn.execute(
            "SELECT turn_id FROM room_turns WHERE room_id = %s AND status = 'collecting' AND turn_index > %s",
            (room_id, conn.execute("SELECT turn_index FROM room_turns WHERE turn_id = %s", (turn_id,)).fetchone()["turn_index"]),
        ).fetchone()
        if not existing_next:
            tm._create_turn(room_id)
        else:
            logger.info("Next turn already exists for room %s (turn %s), skipping creation", room_id, existing_next["turn_id"])

        # Broadcast turn resolved event
        dispatcher = getattr(app.state, "dispatcher", None)
        if dispatcher:
            await dispatcher.emit(room_id, "s2c_turn_resolved", "party",
                                  {"turn_id": turn_id, "narrative": narrative, "actions": results})
            await dispatcher.emit(room_id, "s2c_public_observation", "party",
                                  {"text": narrative})

        if pg_db:
            conn.close()
    except Exception as e:
        logger.exception("Turn settlement failed for room %s turn %s: %s", room_id, turn_id, e)


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


@router.post("/skill-check")
async def skill_check(request: Request, req: SkillCheckRequest):
    _get_character(request)
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


def _json_val(value):
    if value is None: return None
    if isinstance(value, (dict, list)): return value
    if isinstance(value, str):
        try: return json.loads(value)
        except json.JSONDecodeError: return None
    return value


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
