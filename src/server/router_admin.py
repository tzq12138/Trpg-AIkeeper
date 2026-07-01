"""Admin API router — requires admin-role account authentication."""
import json
import uuid
import os
import logging
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form

from .router_auth import verify_token, get_account_from_token, _hash_password

router = APIRouter(prefix="/api/admin")
logger = logging.getLogger(__name__)

ASSETS_ROOT = Path(os.path.dirname(__file__)).parent.parent / "data" / "scenario_assets"


def _require_admin(request: Request) -> dict:
    """Return authenticated admin account dict, or raise."""
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") != "admin":
        raise HTTPException(403, "仅管理员可访问")
    # Touch last_seen_at
    try:
        request.app.state.db.execute(
            "UPDATE accounts SET last_seen_at = NOW() WHERE account_id = %s",
            (account["account_id"],),
        )
        request.app.state.db.commit()
    except Exception:
        pass
    return dict(account)


# ── Overview ──

@router.get("/overview")
async def admin_overview(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    total_rooms = conn.execute("SELECT COUNT(*) as c FROM rooms").fetchone()["c"]
    active_rooms = conn.execute(
        "SELECT COUNT(*) as c FROM rooms WHERE status = 'active'"
    ).fetchone()["c"]
    total_accounts = conn.execute("SELECT COUNT(*) as c FROM accounts").fetchone()["c"]
    online_players = conn.execute(
        "SELECT COUNT(DISTINCT character_id) as c FROM characters WHERE status = 'active'"
    ).fetchone()["c"]
    pending_actions = conn.execute(
        "SELECT COUNT(*) as c FROM actions WHERE status IN ('queued', 'resolving')"
    ).fetchone()["c"]
    return {
        "total_rooms": total_rooms,
        "active_rooms": active_rooms,
        "total_accounts": total_accounts,
        "online_players": online_players,
        "pending_actions": pending_actions,
    }


# ── Rooms ──

@router.get("/rooms")
async def list_rooms(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT r.*, s.title as scenario_title FROM rooms r "
        "LEFT JOIN scenarios s ON r.scenario_id = s.scenario_id "
        "ORDER BY r.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/rooms/{room_id}")
async def get_room_detail(request: Request, room_id: str):
    _require_admin(request)
    conn = request.app.state.db
    room = conn.execute(
        "SELECT r.*, s.title as scenario_title FROM rooms r "
        "LEFT JOIN scenarios s ON r.scenario_id = s.scenario_id "
        "WHERE r.room_id = %s", (room_id,)
    ).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    chars = conn.execute(
        "SELECT * FROM characters WHERE room_id = %s", (room_id,)
    ).fetchall()
    result = dict(room)
    result["characters"] = [_char_summary(c) for c in chars]
    return result


@router.patch("/rooms/{room_id}")
async def update_room(request: Request, room_id: str):
    _require_admin(request)
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    body = await request.json()
    allowed = ["status", "scenario_id", "spoiler_level"]
    sets, vals = [], []
    for k in allowed:
        if k in body:
            sets.append(f"{k} = %s")
            vals.append(body[k])
    if not sets:
        raise HTTPException(400, "没有有效字段")
    vals.append(room_id)
    conn.execute(f"UPDATE rooms SET {', '.join(sets)} WHERE room_id = %s", tuple(vals))
    conn.commit()
    return {"status": "updated", "room_id": room_id}


# ── Accounts ──

@router.get("/accounts")
async def list_accounts(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT account_id, username, display_name, role, last_seen_at, created_at "
        "FROM accounts ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.patch("/accounts/{account_id}")
async def update_account(request: Request, account_id: str):
    _require_admin(request)
    conn = request.app.state.db
    acc = conn.execute("SELECT * FROM accounts WHERE account_id = %s", (account_id,)).fetchone()
    if not acc:
        raise HTTPException(404, "账户不存在")
    body = await request.json()
    allowed = ["role", "display_name"]
    sets, vals = [], []
    for k in allowed:
        if k in body:
            if k == "role" and body[k] not in ("admin", "host", "player"):
                raise HTTPException(400, "角色必须是 admin, host 或 player")
            sets.append(f"{k} = %s")
            vals.append(body[k])
    if not sets:
        raise HTTPException(400, "没有有效字段")
    vals.append(account_id)
    conn.execute(f"UPDATE accounts SET {', '.join(sets)} WHERE account_id = %s", tuple(vals))
    conn.commit()
    return {"status": "updated", "account_id": account_id}


# ── Characters ──

@router.get("/characters")
async def list_characters(request: Request, room_id: str = ""):
    _require_admin(request)
    conn = request.app.state.db
    if room_id:
        rows = conn.execute(
            "SELECT * FROM characters WHERE room_id = %s ORDER BY player_name", (room_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM characters ORDER BY room_id, player_name"
        ).fetchall()
    return [_char_detail(c) for c in rows]


@router.patch("/characters/{character_id}")
async def update_character(request: Request, character_id: str):
    _require_admin(request)
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(404, "角色不存在")
    body = await request.json()

    # Fields that update xlsx_data
    stat_fields = {"hp", "max_hp", "san", "max_san", "mp", "max_mp", "luck", "status_tags"}
    xlsx = json.loads(char.get("xlsx_data") or "{}")
    for k in stat_fields & set(body.keys()):
        xlsx[k] = body[k]
    conn.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = %s",
        (json.dumps(xlsx, ensure_ascii=False), character_id),
    )

    # Fields that are top-level columns
    if "is_ready" in body:
        conn.execute("UPDATE characters SET is_ready = %s WHERE character_id = %s",
                     (body["is_ready"], character_id))
    if "status" in body:
        allowed_statuses = {"active", "removed"}
        if body["status"] not in allowed_statuses:
            raise HTTPException(400, f"Invalid status: {body['status']}")
        conn.execute("UPDATE characters SET status = %s WHERE character_id = %s",
                     (body["status"], character_id))

    conn.commit()

    # Push via ProjectionDispatcher for real-time Host/Player refresh
    try:
        updated_char = _char_summary(
            conn.execute("SELECT * FROM characters WHERE character_id = %s", (character_id,)).fetchone()
        )
        dispatcher = getattr(request.app.state, "dispatcher", None)
        if dispatcher is None:
            from .engine.projection import ProjectionDispatcher
            dispatcher = ProjectionDispatcher(conn)
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(dispatcher.emit(
                char["room_id"], "s2c_state_patch", "party",
                {"patches": [{"op": "replace", "path": f"/characters/{character_id}", "value": updated_char}]},
                character_id=character_id,
            ))
        except RuntimeError:
            pass  # no running event loop (sync context)
    except Exception as e:
        logger.warning("Admin character update WS push failed: %s", e)

    updated = conn.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    return _char_detail(updated)


# ── Scenarios & Assets ──

@router.get("/scenarios")
async def admin_list_scenarios(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT * FROM scenarios ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/scenarios/{scenario_id}/assets")
async def list_assets(request: Request, scenario_id: str):
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT * FROM scenario_assets WHERE scenario_id = %s ORDER BY created_at DESC",
        (scenario_id,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/scenarios/{scenario_id}/assets")
async def upload_asset(request: Request, scenario_id: str, file: UploadFile = File(...)):
    _require_admin(request)
    # Validate scenario exists
    conn = request.app.state.db
    sc = conn.execute("SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone()
    if not sc:
        raise HTTPException(404, "剧本不存在")

    # Secure the filename — no path traversal
    safe_name = Path(file.filename or "unnamed").name
    asset_id = str(uuid.uuid4())[:8]
    ext = Path(safe_name).suffix or ".bin"
    stored_name = f"{asset_id}{ext}"
    asset_dir = ASSETS_ROOT / scenario_id
    asset_dir.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    asset_path = asset_dir / stored_name
    with open(asset_path, "wb") as f:
        f.write(content)

    relative_path = f"data/scenario_assets/{scenario_id}/{stored_name}"
    conn.execute(
        "INSERT INTO scenario_assets (asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (asset_id, scenario_id, stored_name, safe_name,
         file.content_type or "application/octet-stream", len(content), relative_path),
    )
    conn.commit()
    return {"asset_id": asset_id, "filename": safe_name, "relative_path": relative_path}


@router.delete("/scenarios/{scenario_id}/assets/{asset_id}")
async def delete_asset(request: Request, scenario_id: str, asset_id: str):
    _require_admin(request)
    conn = request.app.state.db
    row = conn.execute(
        "SELECT * FROM scenario_assets WHERE asset_id = %s AND scenario_id = %s",
        (asset_id, scenario_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "素材不存在")
    # Delete file
    asset_path = Path(os.path.dirname(__file__)).parent.parent / dict(row)["relative_path"]
    try:
        os.remove(asset_path)
    except FileNotFoundError:
        pass
    conn.execute("DELETE FROM scenario_assets WHERE asset_id = %s", (asset_id,))
    conn.commit()
    return {"status": "deleted", "asset_id": asset_id}


# ── Scenario Import ──

@router.post("/scenarios/import-pdf")
async def admin_import_pdf(request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    from .scenario.router_scenarios import import_pdf
    return await import_pdf(request, file)


@router.post("/scenarios/{scenario_id}/classify")
async def admin_classify_scenario(request: Request, scenario_id: str):
    """Generate scenario type/classification from structured data."""
    _require_admin(request)
    conn = request.app.state.db
    sc = conn.execute("SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone()
    if not sc:
        raise HTTPException(404, "剧本不存在")
    kg = _json_val(sc.get("knowledge_graph")) or {}
    synopsis = kg.get("synopsis", "")
    scene_count = len(kg.get("scenes", []))
    npc_count = len(kg.get("npcs", []))
    clue_count = len(kg.get("clues", []))
    truth = kg.get("truth", {})
    endings = kg.get("endings", [])

    classification = {
        "scenario_id": scenario_id,
        "title": sc["title"],
        "synopsis_preview": synopsis[:200] if synopsis else "",
        "scene_count": scene_count,
        "npc_count": npc_count,
        "clue_count": clue_count,
        "has_truth": bool(truth),
        "ending_count": len(endings),
        "type": _classify_type(synopsis, scene_count, npc_count, clue_count),
        "status": "classified",
    }
    return classification


def _classify_type(synopsis: str, scenes: int, npcs: int, clues: int) -> str:
    """Heuristic scenario type classification."""
    keywords = synopsis.lower() if synopsis else ""
    if any(w in keywords for w in ["凶杀", "谋杀", "杀人", "命案", "尸体"]):
        return "mystery"
    if any(w in keywords for w in ["失踪", "消失", "寻找", "搜索"]):
        return "investigation"
    if any(w in keywords for w in ["恐怖", "怪物", "诅咒", "疯狂"]):
        return "horror"
    if any(w in keywords for w in ["探险", "遗迹", "考古", "地下"]):
        return "expedition"
    if any(w in keywords for w in ["阴谋", "组织", "势力", "政治"]):
        return "conspiracy"
    if scenes >= 5 and npcs >= 5:
        return "epic"
    return "oneshot"


# ── Map Generation ──

@router.post("/scenarios/{scenario_id}/map/generate")
async def admin_generate_map(request: Request, scenario_id: str):
    """Generate a map draft from scenario_assets.scenes[]."""
    _require_admin(request)
    conn = request.app.state.db

    scenario = conn.execute(
        "SELECT scenario_assets FROM scenarios WHERE scenario_id = %s", (scenario_id,)
    ).fetchone()
    if not scenario:
        raise HTTPException(404, "剧本不存在")

    assets = _json_val(scenario.get("scenario_assets")) or {}
    scenes = assets.get("scenes", [])
    if not scenes:
        raise HTTPException(400, "剧本没有场景数据")

    from .config import Settings
    settings = Settings.from_env()

    from .ai.map_generator import MapGenerator
    gen = MapGenerator(api_key=settings.deepseek_api_key, model=settings.deepseek_model)
    nodes, edges = await gen.generate(scenes)

    map_id = f"map_{scenario_id}_{str(uuid.uuid4())[:4]}"
    from .map_persistence import create_scenario_map
    result = create_scenario_map(conn, map_id, scenario_id, gen.last_generated_by, nodes, edges)

    return {
        "mapId": result["map_id"],
        "scenarioId": result["scenario_id"],
        "generatedBy": result["generated_by"],
        "status": result["status"],
        "nodes": result["nodes"],
        "edges": result["edges"],
    }


@router.get("/scenarios/{scenario_id}/map")
async def admin_get_map(request: Request, scenario_id: str):
    """Get the current map draft for a scenario."""
    _require_admin(request)
    conn = request.app.state.db
    from .map_persistence import get_scenario_map_by_scenario
    mp = get_scenario_map_by_scenario(conn, scenario_id)
    if not mp:
        raise HTTPException(404, "该剧本暂无地图")
    return {
        "mapId": mp["map_id"],
        "scenarioId": mp["scenario_id"],
        "generatedBy": mp["generated_by"],
        "status": mp["status"],
        "nodes": mp["nodes"],
        "edges": mp["edges"],
        "createdAt": mp.get("created_at"),
        "confirmedAt": mp.get("confirmed_at"),
    }


@router.patch("/scenarios/{scenario_id}/map")
async def admin_edit_map(request: Request, scenario_id: str):
    """Host edits map nodes/edges before confirming."""
    _require_admin(request)
    body = await request.json()
    conn = request.app.state.db
    from .map_persistence import get_scenario_map_by_scenario, update_scenario_map
    mp = get_scenario_map_by_scenario(conn, scenario_id)
    if not mp:
        raise HTTPException(404, "该剧本暂无地图")
    if mp["status"] == "confirmed":
        raise HTTPException(400, "已确认的地图不可编辑")
    nodes = body.get("nodes", [])
    edges = body.get("edges", [])
    update_scenario_map(conn, mp["map_id"], nodes, edges)
    return {"status": "updated", "mapId": mp["map_id"]}


@router.post("/scenarios/{scenario_id}/map/confirm")
async def admin_confirm_map(request: Request, scenario_id: str):
    """Host confirms map — locks it for use in rooms."""
    _require_admin(request)
    conn = request.app.state.db
    from .map_persistence import get_scenario_map_by_scenario, confirm_scenario_map
    mp = get_scenario_map_by_scenario(conn, scenario_id)
    if not mp:
        raise HTTPException(404, "该剧本暂无地图")
    result = confirm_scenario_map(conn, mp["map_id"])
    return {
        "mapId": result["map_id"],
        "status": result["status"],
        "confirmedAt": result.get("confirmed_at"),
    }


# ── AI Config ──

@router.get("/ai/config")
async def get_ai_config(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    from .ai.ai_config import get_global_ai_config
    return get_global_ai_config(conn)


@router.patch("/ai/config")
async def update_ai_config(request: Request):
    _require_admin(request)
    body = await request.json()
    conn = request.app.state.db
    from .ai.ai_config import update_global_ai_config
    update_global_ai_config(conn, body)
    return {"status": "updated"}


@router.post("/ai/health-check")
async def trigger_ai_health_check(request: Request):
    _require_admin(request)
    gateway = getattr(request.app.state, "gateway", None)
    if not gateway:
        raise HTTPException(503, "AiGateway not initialized")
    result = await gateway.health_check()
    return result


@router.get("/ai/logs")
async def get_ai_logs(request: Request, room_id: str = "", task_type: str = "",
                       provider: str = "", status: str = "", limit: int = 50):
    _require_admin(request)
    conn = request.app.state.db
    where = []
    params: list = []
    if room_id:
        where.append("room_id = %s"); params.append(room_id)
    if task_type:
        where.append("task_type = %s"); params.append(task_type)
    if provider:
        where.append("provider = %s"); params.append(provider)
    if status:
        where.append("status = %s"); params.append(status)
    where_clause = " AND ".join(where) if where else "TRUE"
    rows = conn.execute(
        f"SELECT * FROM ai_call_logs WHERE {where_clause} ORDER BY created_at DESC LIMIT %s",
        tuple(params + [min(limit, 200)]),
    ).fetchall()
    return {"logs": [dict(r) for r in rows]}


@router.post("/ai/query")
async def test_knowledge_query(request: Request):
    _require_admin(request)
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    room_id = body.get("room_id", "")
    sources = body.get("sources", "both")
    gateway = getattr(request.app.state, "gateway", None)
    if not gateway:
        raise HTTPException(503, "AiGateway not initialized")
    result = await gateway.query_knowledge(query, room_id or "test", sources)
    return result.model_dump(by_alias=True) if hasattr(result, 'model_dump') else result


# ── RAG Admin ──

@router.post("/rag/context-preview")
async def rag_context_preview(request: Request):
    _require_admin(request)
    body = await request.json()
    room_id = body.get("room_id", "")
    action_text = body.get("action_text", "")
    character_id = body.get("character_id", "")
    scenario_id = body.get("scenario_id", "")
    rag = getattr(request.app.state, "rag", None)
    conn = request.app.state.db
    from .ai.rag_context import RAGContextBuilder
    builder = RAGContextBuilder(conn, rag)
    if not room_id:
        raise HTTPException(400, "room_id required")
    return builder.preview(room_id, action_text, character_id, scenario_id)


@router.post("/rag/reindex")
async def rag_reindex(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    rag = getattr(request.app.state, "rag", None)
    if not rag:
        raise HTTPException(503, "RAG not available")
    body = await request.json()
    kinds = body.get("kinds", ["scenarios", "characters", "events", "rules"])

    counts = {}
    # Re-index scenarios
    if "scenarios" in kinds:
        rows = conn.execute("SELECT scenario_id, raw_text, knowledge_graph FROM scenarios WHERE raw_text IS NOT NULL").fetchall()
        for r in rows:
            rag.index_scenario(r["scenario_id"], r["raw_text"])
            kg = r.get("knowledge_graph") or {}
            if isinstance(kg, str):
                try:
                    from json import loads; kg = loads(kg)
                except Exception:
                    kg = {}
            if kg:
                rag.index_npc_graph(r["scenario_id"], kg)
        counts["scenarios"] = len(rows)

    # Re-index characters
    if "characters" in kinds:
        rows = conn.execute("SELECT * FROM characters WHERE xlsx_data IS NOT NULL").fetchall()
        for r in rows:
            xlsx = r.get("xlsx_data") or {}
            if isinstance(xlsx, str):
                try:
                    from json import loads; xlsx = loads(xlsx)
                except Exception:
                    xlsx = {}
            rag.index_character(r["room_id"], r["character_id"], xlsx)
        counts["characters"] = len(rows)

    # Re-index events
    if "events" in kinds:
        rows = conn.execute("SELECT room_id, sequence, event_type, payload FROM events ORDER BY sequence DESC LIMIT 500").fetchall()
        for r in rows:
            payload = r["payload"] or {}
            if isinstance(payload, str):
                try:
                    from json import loads; payload = loads(payload)
                except Exception:
                    payload = {}
            rag.index_event(r["room_id"], r["event_type"], payload, r["sequence"])
        counts["events"] = len(rows)

    return {"status": "reindexed", "counts": counts}


# ── SpoilerGuard Audit ──

@router.get("/rooms/{room_id}/spoiler-audits")
async def get_spoiler_audits(request: Request, room_id: str, limit: int = 50):
    """View spoiler interception logs for a room. Admin-only."""
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT * FROM spoiler_audits WHERE room_id = %s ORDER BY created_at DESC LIMIT %s",
        (room_id, min(limit, 200)),
    ).fetchall()
    audits = []
    for r in rows:
        violations_raw = r.get("violations")
        if isinstance(violations_raw, str):
            try:
                violations_raw = json.loads(violations_raw)
            except Exception:
                violations_raw = []
        unlock_raw = r.get("unlock_snapshot")
        if isinstance(unlock_raw, str):
            try:
                unlock_raw = json.loads(unlock_raw)
            except Exception:
                unlock_raw = {}
        audits.append({
            "auditId": r["audit_id"],
            "roomId": r["room_id"],
            "actionId": r.get("action_id", ""),
            "originalText": r["original_text"],
            "violations": violations_raw or [],
            "retryCount": r.get("retry_count", 0),
            "finalStatus": r.get("final_status", ""),
            "finalText": r.get("final_text", ""),
            "unlockSnapshot": unlock_raw or {},
            "createdAt": str(r.get("created_at", "")),
        })
    return {"room_id": room_id, "audits": audits}


@router.post("/scenarios/{scenario_id}/spoiler-index/rebuild")
async def rebuild_spoiler_index(request: Request, scenario_id: str):
    """Rebuild sensitive item index for a scenario. Admin-only."""
    _require_admin(request)
    conn = request.app.state.db
    from .engine.spoiler_guard import SpoilerGuard
    sg = SpoilerGuard(conn)
    count = sg.rebuild_index(scenario_id)
    return {"scenario_id": scenario_id, "items_indexed": count}


# ── Helpers ──

def _char_summary(row) -> dict:
    r = dict(row) if not isinstance(row, dict) else row
    xlsx = _json_val(r.get("xlsx_data")) or {}
    return {
        "character_id": r.get("character_id", ""),
        "player_name": r.get("player_name", ""),
        "investigator_name": xlsx.get("name", ""),
        "occupation": xlsx.get("occupation", ""),
        "hp": xlsx.get("hp", 0),
        "max_hp": xlsx.get("max_hp", 0),
        "san": xlsx.get("san", 0),
        "max_san": xlsx.get("max_san", 0),
        "is_ready": bool(r.get("is_ready")),
        "status": r.get("status", "active"),
        "account_id": r.get("account_id", ""),
    }


def _char_detail(row) -> dict:
    r = dict(row) if not isinstance(row, dict) else row
    xlsx = _json_val(r.get("xlsx_data")) or {}
    return {
        **r,
        "xlsx_data": xlsx,
        "summary": _char_summary(r),
    }


def _json_val(value):
    if value is None: return None
    if isinstance(value, (dict, list)): return value
    if isinstance(value, str):
        try: return json.loads(value)
        except json.JSONDecodeError: return None
    return value
