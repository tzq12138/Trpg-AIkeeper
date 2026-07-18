"""Admin API router — requires admin-role account authentication."""
import asyncio
import json
import uuid
import os
import logging
import hashlib
import re
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from .router_auth import verify_token, get_account_from_token, _hash_password

router = APIRouter(prefix="/api/admin")
logger = logging.getLogger(__name__)

ASSETS_ROOT = Path(os.path.dirname(__file__)).parent.parent / "data" / "scenario_assets"

# Allowed MIME types and extensions for asset upload
ALLOWED_MIME_TYPES = {
    "image/png", "image/jpeg", "image/webp", "image/gif",
    "audio/mpeg", "audio/wav", "audio/ogg", "audio/webm",
    "application/pdf",
}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp3", ".wav", ".ogg", ".webm", ".pdf"}
BLOCKED_EXTENSIONS = {".svg", ".html", ".htm", ".js", ".exe", ".sh", ".bat", ".ps1", ".php"}
MAX_ASSET_SIZE = 50 * 1024 * 1024  # 50 MB

# Magic bytes for file header validation
MAGIC_BYTES: dict[str, bytes] = {
    ".png": b'\x89PNG\r\n\x1a\n',
    ".jpg": b'\xff\xd8\xff',
    ".jpeg": b'\xff\xd8\xff',
    ".webp": b'RIFF',
    ".gif": b'GIF8',
    ".pdf": b'%PDF',
    ".mp3": b'\xff\xfb',  # MPEG audio frame sync
}


async def _safe_json(request: Request) -> dict:
    try:
        value = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _get_account_id(request: Request) -> str:
    """Extract account_id from request token without raising. Returns 'unknown' if not authenticated."""
    try:
        account = get_account_from_token(request)
        return account.get("account_id", "unknown") if account else "unknown"
    except Exception:
        return "unknown"


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

@router.get("/acceptance")
async def admin_acceptance(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    rooms = conn.execute("SELECT COUNT(*) AS c FROM rooms").fetchone()["c"]
    scenarios = conn.execute("SELECT COUNT(*) AS c FROM scenarios").fetchone()["c"]
    return {
        "fixtures": [
            {
                "label": "玩家邀请与准备",
                "description": "登录、选预设角色、进入准备台。",
                "href": "/player/join",
            },
            {
                "label": "玩家叙事行动",
                "description": "自然语言、风险确认、判定卡与地图投影。",
                "href": "/player/join",
            },
            {
                "label": "房主开局检查",
                "description": "可开团剧本、玩家状态与开始门禁。",
                "href": "/host/create",
            },
            {
                "label": "剧本编译向导",
                "description": "导入、质量审核、素材绑定与发布。",
                "href": "/admin",
            },
        ],
        "counts": {"rooms": rooms, "scenarios": scenarios},
        "retention_days": 90,
    }

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
            if k == "scenario_id":
                scenario = conn.execute(
                    "SELECT publish_status, published_version_id FROM scenarios "
                    "WHERE scenario_id = %s",
                    (body[k],),
                ).fetchone()
                if not scenario:
                    raise HTTPException(404, "剧本不存在")
                scenario_version_id = scenario.get("published_version_id")
                if scenario.get("publish_status") != "published" or not scenario_version_id:
                    raise HTTPException(409, "剧本尚未确认发布，不能绑定房间")
                sets.append("scenario_version_id = %s")
                vals.append(scenario_version_id)
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
    if acc["username"] == "admin" and "role" in body and body["role"] != "admin":
        raise HTTPException(409, "保留管理员账号不能降权")
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
    from .scenario.import_service import is_import_job_retryable

    conn = request.app.state.db
    rows = conn.execute(
        """
        SELECT s.*, latest_job.job_id AS latest_import_job_id,
               latest_job.status AS latest_import_job_status,
               latest_job.updated_at AS latest_import_job_updated_at
        FROM scenarios s
        LEFT JOIN LATERAL (
            SELECT job_id, status, updated_at
            FROM import_jobs
            WHERE scenario_id = s.scenario_id
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
        ) latest_job ON TRUE
        ORDER BY s.created_at DESC
        """
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["latest_import_job_retryable"] = is_import_job_retryable(
            item.get("latest_import_job_status"),
            item.get("latest_import_job_updated_at"),
        )
        result.append(item)
    return result


@router.get("/scenarios/{scenario_id}/assets")
async def list_assets(request: Request, scenario_id: str):
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT * FROM scenario_assets WHERE scenario_id = %s ORDER BY created_at DESC",
        (scenario_id,)
    ).fetchall()
    # Admin-only: return full details including relative_path
    return [dict(r) for r in rows]


@router.post("/scenarios/{scenario_id}/assets")
async def upload_asset(request: Request, scenario_id: str,
                       file: UploadFile = File(...),
                       visibility: str = Form("host_only")):
    _require_admin(request)
    conn = request.app.state.db
    sc = conn.execute("SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone()
    if not sc:
        raise HTTPException(404, "剧本不存在")

    # ── Filename validation ──
    raw_name = file.filename or "unnamed"
    safe_name = Path(raw_name).name  # strip path traversal
    if safe_name != raw_name:
        raise HTTPException(400, "文件名不能包含路径分隔符")
    ext = Path(safe_name).suffix.lower() or ".bin"

    # Block dangerous extensions
    if ext in BLOCKED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: {ext}（安全策略禁止）")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: {ext}")

    # ── Size validation ──
    content = await file.read()
    if len(content) > MAX_ASSET_SIZE:
        raise HTTPException(400, f"文件过大（最大 50MB，当前 {len(content) // (1024*1024)}MB）")

    # ── MIME validation ──
    declared_mime = (file.content_type or "application/octet-stream").lower()
    if declared_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"不支持的 MIME 类型: {declared_mime}")

    # ── File header validation (magic bytes) ──
    if ext in MAGIC_BYTES:
        expected = MAGIC_BYTES[ext]
        if not content[:len(expected)] == expected:
            raise HTTPException(400, f"文件头与扩展名 {ext} 不匹配，可能是伪装文件")

    # ── Validate visibility ──
    if visibility not in ("host_only", "party", "private", "admin_only"):
        visibility = "host_only"

    # ── Persist ──
    asset_id = str(uuid.uuid4())[:8]
    stored_name = f"{asset_id}{ext}"
    asset_dir = ASSETS_ROOT / scenario_id
    asset_dir.mkdir(parents=True, exist_ok=True)

    asset_path = asset_dir / stored_name
    with open(asset_path, "wb") as f:
        f.write(content)

    relative_path = f"data/scenario_assets/{scenario_id}/{stored_name}"
    conn.execute(
        "INSERT INTO scenario_assets (asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (asset_id, scenario_id, stored_name, safe_name,
         declared_mime, len(content), relative_path, visibility),
    )
    conn.commit()
    return {
        "asset_id": asset_id,
        "filename": safe_name,
        "mime_type": declared_mime,
        "file_size": len(content),
        "visibility": visibility,
    }


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

    body = await _safe_json(request)
    force = (body or {}).get("force", False)
    force_confirm = (body or {}).get("confirm", False)
    force_reason = (body or {}).get("reason", "")

    # Check references before deletion
    refs = _find_asset_references(conn, asset_id, scenario_id)
    if refs:
        if not (force and force_confirm and force_reason):
            raise HTTPException(
                409,
                f"素材被 {len(refs)} 处引用，无法直接删除。使用 force=true + confirm=true + reason 强制删除",
            )
        logger.warning("Force-deleting asset %s with %d references by admin: %s",
                       asset_id, len(refs), force_reason)

    # Delete file (resolve symlinks, confirm within ASSETS_ROOT)
    row_dict = dict(row)
    rel_path = row_dict.get("relative_path", "")
    asset_path = (ASSETS_ROOT.parent / rel_path).resolve()
    if not str(asset_path).startswith(str(ASSETS_ROOT.resolve())):
        raise HTTPException(400, "素材路径异常，拒绝删除")
    try:
        os.remove(asset_path)
    except FileNotFoundError:
        pass

    conn.execute("DELETE FROM scenario_assets WHERE asset_id = %s", (asset_id,))
    conn.commit()
    return {"status": "deleted", "asset_id": asset_id, "reference_count": len(refs), "forced": force}


def _find_asset_references(conn, asset_id: str, scenario_id: str) -> list[dict]:
    """Find references to an asset across the database."""
    refs = []
    # Check room_scene_state
    rows = conn.execute(
        "SELECT room_id FROM room_scene_state WHERE current_asset_url LIKE %s",
        (f"%{asset_id}%",)
    ).fetchall()
    for r in rows:
        refs.append({"table": "room_scene_state", "room_id": r["room_id"]})
    # Check scenario_maps, including image/hybrid base assets.
    rows = conn.execute(
        "SELECT map_id FROM scenario_maps WHERE scenario_id = %s "
        "AND (nodes::text LIKE %s OR base_asset::text LIKE %s)",
        (scenario_id, f"%{asset_id}%", f"%{asset_id}%")
    ).fetchall()
    for r in rows:
        refs.append({"table": "scenario_maps", "map_id": r["map_id"]})
    rows = conn.execute(
        "SELECT binding_id FROM scenario_asset_bindings WHERE asset_id = %s",
        (asset_id,),
    ).fetchall()
    for r in rows:
        refs.append({"table": "scenario_asset_bindings", "binding_id": r["binding_id"]})
    return refs


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

def _map_base_asset(assets: dict) -> dict:
    if not isinstance(assets, dict):
        return {}
    candidates = [assets.get("baseMap"), assets.get("map"), assets.get("mapAsset")]
    maps = assets.get("maps")
    if isinstance(maps, list) and maps:
        candidates.append(maps[0])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return {"assetId": candidate}
        if isinstance(candidate, dict):
            asset_id = candidate.get("assetId", candidate.get("asset_id", ""))
            if isinstance(asset_id, str) and asset_id:
                return {"assetId": asset_id}
    return {}


def _select_map_base_asset(conn, scenario_id: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT asset_id, original_name, filename FROM scenario_assets "
        "WHERE scenario_id = %s AND mime_type LIKE 'image/%%' ORDER BY created_at",
        (scenario_id,),
    ).fetchall()
    exact = []
    partial = []
    for row in rows:
        name = Path(str(row.get("original_name") or row.get("filename") or "")).stem.lower()
        if name in {"地图", "map"}:
            exact.append(row)
        elif "地图" in name or "map" in name:
            partial.append(row)
    selected = (exact or partial)
    return {"assetId": selected[0]["asset_id"]} if selected else {}


def _map_draft_payload(map_data: dict) -> dict:
    return {
        "mapId": map_data["map_id"],
        "scenarioId": map_data["scenario_id"],
        "generatedBy": map_data["generated_by"],
        "status": map_data["status"],
        "mapType": map_data.get("map_type", "graph"),
        "baseAsset": map_data.get("base_asset", {}),
        "regions": map_data.get("regions", []),
        "paths": map_data.get("paths", []),
        "nodes": map_data["nodes"],
        "edges": map_data["edges"],
        "createdAt": map_data.get("created_at"),
        "confirmedAt": map_data.get("confirmed_at"),
    }


@router.post("/player-experience-v2/cutover")
async def cutover_player_experience_v2(request: Request):
    account = _require_admin(request)
    body = await _safe_json(request)
    from .v2_cutover import V2CutoverError, V2CutoverService

    backup_root = getattr(request.app.state, "v2_cutover_backup_root", None)
    if backup_root is None:
        backup_root = Path(__file__).resolve().parents[2] / "data" / "backups" / "v2-cutover"
    try:
        return V2CutoverService(
            request.app.state.db,
            Path(backup_root),
        ).backup_and_clear(
            str(body.get("confirmation") or ""),
            requested_by=str(account.get("account_id") or "unknown"),
        )
    except V2CutoverError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/scenarios/{scenario_id}/assets/{asset_id}/content")
async def preview_asset(request: Request, scenario_id: str, asset_id: str):
    _require_admin(request)
    row = request.app.state.db.execute(
        "SELECT filename, mime_type FROM scenario_assets "
        "WHERE asset_id = %s AND scenario_id = %s",
        (asset_id, scenario_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "素材不存在")
    asset_path = (ASSETS_ROOT / scenario_id / row["filename"]).resolve()
    if not asset_path.is_relative_to(ASSETS_ROOT.resolve()) or not asset_path.is_file():
        raise HTTPException(404, "素材文件不存在")
    return FileResponse(asset_path, media_type=row["mime_type"])


def _asset_binding_service(request: Request):
    from .scenario.asset_binding import ScenarioAssetBindingService

    asset_root = getattr(request.app.state, "scenario_asset_root", None)
    return ScenarioAssetBindingService(
        request.app.state.db,
        asset_root=Path(asset_root) if asset_root else None,
        gateway=getattr(request.app.state, "gateway", None),
    )


def _verify_asset_binding_version(conn, scenario_id: str, scenario_version_id: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM scenario_versions WHERE scenario_version_id = %s AND scenario_id = %s",
        (scenario_version_id, scenario_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "剧本版本不存在")


@router.post("/scenarios/{scenario_id}/versions/{scenario_version_id}/asset-bindings/generate")
async def generate_asset_bindings(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
):
    _require_admin(request)
    _verify_asset_binding_version(request.app.state.db, scenario_id, scenario_version_id)
    service = _asset_binding_service(request)
    try:
        bindings = await service.generate_bindings(scenario_version_id)
        targets = service.list_targets(scenario_version_id)
    except Exception as exc:
        logger.exception("Asset binding generation failed version=%s", scenario_version_id)
        raise HTTPException(500, "素材自动匹配失败") from exc
    return {"bindings": bindings, "targets": targets}


@router.get("/scenarios/{scenario_id}/versions/{scenario_version_id}/asset-bindings")
async def list_asset_bindings(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
):
    _require_admin(request)
    _verify_asset_binding_version(request.app.state.db, scenario_id, scenario_version_id)
    service = _asset_binding_service(request)
    return {
        "bindings": service.list_bindings(scenario_version_id),
        "targets": service.list_targets(scenario_version_id),
    }


@router.patch(
    "/scenarios/{scenario_id}/versions/{scenario_version_id}/asset-bindings/{binding_id}"
)
async def review_asset_binding(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
    binding_id: str,
):
    _require_admin(request)
    _verify_asset_binding_version(request.app.state.db, scenario_id, scenario_version_id)
    binding = request.app.state.db.execute(
        "SELECT 1 FROM scenario_asset_bindings "
        "WHERE binding_id = %s AND scenario_version_id = %s",
        (binding_id, scenario_version_id),
    ).fetchone()
    if not binding:
        raise HTTPException(404, "素材绑定不存在")
    body = await request.json()
    from .scenario.asset_binding import AssetBindingError

    try:
        result = _asset_binding_service(request).review_binding(
            binding_id,
            target_type=str(body.get("target_type") or ""),
            target_key=str(body.get("target_key") or ""),
            status=str(body.get("status") or "draft"),
            reviewed_by=_get_account_id(request),
        )
    except AssetBindingError as exc:
        code = str(exc)
        status_code = 404 if code == "binding_not_found" else 409
        raise HTTPException(status_code, code) from exc
    return result


def _load_golden_module(module_id: str) -> tuple[dict, Path]:
    if not re.fullmatch(r"[a-z0-9-]{1,120}", module_id):
        raise HTTPException(404, "黄金模组不存在")
    root = Path(__file__).resolve().parents[2] / "data" / "golden_modules"
    for path in root.glob("*/module.json"):
        try:
            module = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        manifest = module.get("manifest", {})
        if isinstance(manifest, dict) and manifest.get("module_id") == module_id:
            return module, path
    raise HTTPException(404, "黄金模组不存在")


def _golden_map_nodes(raw_nodes: list[dict]) -> list[dict]:
    total = max(1, len(raw_nodes))
    nodes = []
    for index, raw_node in enumerate(raw_nodes):
        node_id = raw_node.get("node_id", raw_node.get("nodeId", ""))
        if not isinstance(node_id, str) or not node_id:
            raise HTTPException(422, "黄金模组包含无效文字地图节点")
        x = 50 if total == 1 else round(15 + index * 70 / (total - 1), 1)
        nodes.append({
            "node_id": node_id,
            "name": raw_node.get("name", node_id),
            "description": raw_node.get("description", ""),
            "npcs_present": raw_node.get("npcs_present", raw_node.get("npcsPresent", [])),
            "clues_available": raw_node.get("clues_available", raw_node.get("cluesAvailable", [])),
            "position": raw_node.get("position", {"x": x, "y": 50}),
            "is_start": bool(raw_node.get("is_start", raw_node.get("isStart", index == 0))),
        })
    return nodes


def _golden_map_edges(raw_edges: list[dict]) -> list[dict]:
    edges = []
    for raw_edge in raw_edges:
        from_node = raw_edge.get("from_node", raw_edge.get("fromNode", raw_edge.get("from", "")))
        to_node = raw_edge.get("to_node", raw_edge.get("toNode", raw_edge.get("to", "")))
        if not isinstance(from_node, str) or not isinstance(to_node, str) or not from_node or not to_node:
            raise HTTPException(422, "黄金模组包含无效文字地图路径")
        edges.append({
            "from_node": from_node,
            "to_node": to_node,
            "is_one_way": bool(raw_edge.get("is_one_way", raw_edge.get("isOneWay", False))),
            "label": raw_edge.get("label", ""),
        })
    return edges


def _normalize_golden_knowledge_graph(
    raw_graph: dict,
    raw_citations: list,
    *,
    source_part_id: str,
) -> dict:
    """Adapt authored golden-module references into runtime-verifiable evidence."""
    graph = json.loads(json.dumps(raw_graph, ensure_ascii=False))
    citations = {
        str(entry.get("citation_id") or ""): entry
        for entry in raw_citations
        if isinstance(entry, dict) and str(entry.get("citation_id") or "")
    }

    def source_citation(value: dict, fallback_ref: str) -> dict:
        existing = value.get("citation")
        if isinstance(existing, dict) and (
            existing.get("source_part_id") or existing.get("source_ref")
        ):
            citation = dict(existing)
            citation.setdefault("source_part_id", source_part_id)
            citation.setdefault("source_ref", fallback_ref)
            return citation
        citation_ids = value.get("citation_ids")
        if not isinstance(citation_ids, list):
            citation_ids = []
        entry = next(
            (
                citations.get(str(citation_id))
                for citation_id in citation_ids
                if citations.get(str(citation_id))
            ),
            {},
        )
        citation = {
            "source_part_id": source_part_id,
            "source_ref": str(entry.get("source_ref") or fallback_ref),
        }
        if entry.get("citation_id"):
            citation["citation_id"] = str(entry["citation_id"])
        if entry.get("label"):
            citation["label"] = str(entry["label"])
        return citation

    for collection_name in ("scenes", "npcs", "clues", "endings"):
        values = graph.get(collection_name)
        if not isinstance(values, list):
            continue
        for ordinal, value in enumerate(values):
            if not isinstance(value, dict):
                continue
            value["citation"] = source_citation(
                value,
                f"module.json#/knowledge_graph/{collection_name}/{ordinal}",
            )
    truth = graph.get("truth")
    if isinstance(truth, dict):
        truth["citation"] = source_citation(
            truth,
            "module.json#/knowledge_graph/truth",
        )

    raw_rule_triggers = graph.get("rule_triggers") or graph.get("rule_citations")
    if isinstance(raw_rule_triggers, dict):
        raw_rule_triggers = [raw_rule_triggers]
    if isinstance(raw_rule_triggers, list):
        rule_triggers = []
        for ordinal, trigger in enumerate(raw_rule_triggers):
            if not isinstance(trigger, dict):
                continue
            normalized_trigger = dict(trigger)
            source_ref = str(normalized_trigger.get("source_ref") or "")
            if source_ref:
                normalized_trigger["citation"] = {
                    "source_ref": source_ref,
                    "citation_id": str(normalized_trigger.get("citation_id") or ""),
                }
            else:
                normalized_trigger["citation"] = source_citation(
                    normalized_trigger,
                    f"module.json#/knowledge_graph/rule_citations/{ordinal}",
                )
            rule_triggers.append(normalized_trigger)
        graph["rule_triggers"] = rule_triggers

    branches = graph.get("branches")
    if not isinstance(branches, list) or not branches:
        scene_ids = {
            str(scene.get("scene_id") or scene.get("id") or "")
            for scene in graph.get("scenes") or []
            if isinstance(scene, dict)
        }
        generated_branches = []
        emitted_pairs = set()
        for scene_index, scene in enumerate(graph.get("scenes") or []):
            if not isinstance(scene, dict):
                continue
            from_scene_id = str(scene.get("scene_id") or scene.get("id") or "")
            if not from_scene_id:
                continue
            for target in scene.get("exits") or []:
                to_scene_id = str(target or "")
                pair = (from_scene_id, to_scene_id)
                if to_scene_id not in scene_ids or pair in emitted_pairs:
                    continue
                emitted_pairs.add(pair)
                generated_branches.append({
                    "branch_id": f"{from_scene_id}-to-{to_scene_id}",
                    "from_scene_id": from_scene_id,
                    "to_scene_id": to_scene_id,
                    "conditions": [],
                    "citation": source_citation(
                        scene,
                        f"module.json#/knowledge_graph/scenes/{scene_index}",
                    ),
                })
        graph["branches"] = generated_branches
    else:
        for ordinal, branch in enumerate(branches):
            if isinstance(branch, dict):
                branch["citation"] = source_citation(
                    branch,
                    f"module.json#/knowledge_graph/branches/{ordinal}",
                )
    return graph


@router.post("/golden-modules/{module_id}/install", status_code=201)
async def install_golden_module(request: Request, module_id: str):
    account = _require_admin(request)
    module, module_path = _load_golden_module(module_id)
    manifest = module.get("manifest", {})
    raw_knowledge_graph = module.get("knowledge_graph", {})
    scenario_assets = module.get("scenario_assets", {})
    templates = module.get("character_templates", [])
    quality_report = module.get("quality_report", {})
    if (
        manifest.get("format") != "aikeeper-golden-module"
        or not isinstance(raw_knowledge_graph, dict)
        or not all(isinstance(raw_knowledge_graph.get(key), list) and raw_knowledge_graph[key] for key in ("scenes", "npcs", "clues"))
        or not isinstance(scenario_assets, dict)
        or not isinstance(templates, list)
        or not templates
    ):
        raise HTTPException(422, "黄金模组结构不完整")
    text_map = scenario_assets.get("text_map", {})
    if not isinstance(text_map, dict):
        raise HTTPException(422, "黄金模组缺少文字地图")
    nodes = _golden_map_nodes(text_map.get("nodes", []))
    edges = _golden_map_edges(text_map.get("edges", []))
    if not nodes:
        raise HTTPException(422, "黄金模组缺少文字地图节点")

    conn = request.app.state.db
    scenario_id = f"golden-{module_id}"
    if conn.execute("SELECT 1 FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone():
        raise HTTPException(409, "黄金模组已安装")
    rule_version = conn.execute(
        "SELECT rsv.rule_set_version_id FROM rule_set_versions rsv "
        "JOIN rule_sets rs ON rs.rule_set_id = rsv.rule_set_id "
        "WHERE rs.slug = 'coc7' AND rs.status = 'published' AND rsv.status = 'published' "
        "ORDER BY rsv.version_number DESC LIMIT 1"
    ).fetchone()
    if not rule_version:
        raise HTTPException(409, "需要先发布授权的 CoC7 规则版本")

    raw_module = module_path.read_bytes()
    source_sha256 = hashlib.sha256(raw_module).hexdigest()
    scenario_version_id = f"{scenario_id}-v1"
    source_document_id = f"{scenario_id}-source"
    source_part_id = f"{source_document_id}-part-1"
    map_id = f"{scenario_id}-map"
    created_by = account.get("account_id", "unknown")
    knowledge_graph = _normalize_golden_knowledge_graph(
        raw_knowledge_graph,
        module.get("citations", []),
        source_part_id=source_part_id,
    )
    prep_package = {
        "golden_module": manifest,
        "citations": module.get("citations", []),
        "rag_expectations": module.get("rag_expectations", []),
    }
    with conn.transaction() as transaction:
        transaction.execute(
            "INSERT INTO scenarios "
            "(scenario_id, title, raw_text, knowledge_graph, scenario_assets, quality_report, import_status, publish_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'structured', 'published')",
            (
                scenario_id, manifest.get("title", module_id), module.get("raw_text", ""),
                json.dumps(knowledge_graph, ensure_ascii=False), json.dumps(scenario_assets, ensure_ascii=False),
                json.dumps(quality_report, ensure_ascii=False),
            ),
        )
        transaction.execute(
            "INSERT INTO source_documents "
            "(source_document_id, scenario_id, source_kind, title, source_filename, mime_type, source_sha256, "
            "storage_path, license_type, license_ref, status, metadata, created_by) "
            "VALUES (%s, %s, 'golden_module', %s, 'module.json', 'application/json', %s, %s, 'authorized', %s, 'parsed', %s, %s)",
            (
                source_document_id, scenario_id, manifest.get("title", module_id), source_sha256,
                str(module_path.relative_to(Path(__file__).resolve().parents[2])).replace("\\", "/"),
                manifest.get("license", {}).get("license_id", ""),
                json.dumps({"module_id": module_id, "schema_version": manifest.get("schema_version", "")}, ensure_ascii=False),
                created_by,
            ),
        )
        transaction.execute(
            "INSERT INTO source_parts "
            "(source_part_id, source_document_id, ordinal, part_kind, text_content, mime_type, anchor, checksum) "
            "VALUES (%s, %s, 1, 'text', %s, 'application/json', %s, %s)",
            (
                source_part_id, source_document_id, module.get("raw_text", ""),
                json.dumps({"source_ref": "module.json#/raw_text"}), source_sha256,
            ),
        )
        transaction.execute(
            "INSERT INTO scenario_versions "
            "(scenario_version_id, scenario_id, version_number, status, knowledge_graph, quality_report, prep_package, created_by, published_at) "
            "VALUES (%s, %s, 1, 'published', %s, %s, %s, %s, NOW())",
            (
                scenario_version_id, scenario_id, json.dumps(knowledge_graph, ensure_ascii=False),
                json.dumps(quality_report, ensure_ascii=False), json.dumps(prep_package, ensure_ascii=False), created_by,
            ),
        )
        transaction.execute(
            "INSERT INTO scenario_version_sources (scenario_version_id, source_document_id, ordinal) VALUES (%s, %s, 1)",
            (scenario_version_id, source_document_id),
        )
        transaction.execute(
            "UPDATE scenarios SET published_version_id = %s WHERE scenario_id = %s",
            (scenario_version_id, scenario_id),
        )
        transaction.execute(
            "INSERT INTO scenario_rule_bindings (scenario_version_id, rule_set_version_id) VALUES (%s, %s)",
            (scenario_version_id, rule_version["rule_set_version_id"]),
        )
        for index, template in enumerate(templates):
            transaction.execute(
                "INSERT INTO character_templates "
                "(template_id, scenario_id, name, occupation, background, age, gender, attributes, skills, backstory) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    f"{scenario_id}-template-{index + 1}", scenario_id, template.get("name", f"预设角色 {index + 1}"),
                    template.get("occupation", ""), template.get("background", ""), template.get("age", 25),
                    template.get("gender", ""), json.dumps(template.get("attributes", {}), ensure_ascii=False),
                    json.dumps(template.get("skills", {}), ensure_ascii=False), json.dumps(template.get("backstory", {}), ensure_ascii=False),
                ),
            )
        transaction.execute(
            "INSERT INTO scenario_maps "
            "(map_id, scenario_id, generated_by, status, map_type, nodes, edges, paths, confirmed_at) "
            "VALUES (%s, %s, 'golden_module', 'confirmed', 'graph', %s, %s, %s, NOW())",
            (
                map_id, scenario_id, json.dumps(nodes, ensure_ascii=False), json.dumps(edges, ensure_ascii=False),
                json.dumps([
                    {"pathId": f"path-{index}", "fromNodeId": edge["from_node"], "toNodeId": edge["to_node"],
                     "isOneWay": edge["is_one_way"], "label": edge["label"]}
                    for index, edge in enumerate(edges)
                ], ensure_ascii=False),
            ),
        )
    from .scenario.content_projection import ContentProjectionService
    from .scenario.module_compiler import ModuleCompiler

    ContentProjectionService(conn).rebuild(
        scenario_version_id,
        knowledge_graph,
        requested_by=created_by,
    )
    runtime_package = ModuleCompiler(conn).compile(
        scenario_version_id,
        requested_by=created_by,
    )
    if runtime_package["gate_status"] != "ready":
        conn.execute(
            "UPDATE scenario_versions SET status = 'draft' WHERE scenario_version_id = %s",
            (scenario_version_id,),
        )
        conn.execute(
            "UPDATE scenarios SET publish_status = 'draft' WHERE scenario_id = %s",
            (scenario_id,),
        )
        conn.commit()
        raise HTTPException(422, {
            "message": "黄金模组运行包未达到可开团门槛",
            "quality_exceptions": runtime_package["quality_exceptions"],
        })
    return {
        "scenarioId": scenario_id,
        "scenarioVersionId": scenario_version_id,
        "title": manifest.get("title", module_id),
        "status": "published",
        "runtimePackage": runtime_package,
    }


@router.post("/scenarios/{scenario_id}/map/generate")
async def admin_generate_map(
    request: Request,
    scenario_id: str,
    scenario_version_id: str | None = None,
):
    """Generate a map draft from knowledge_graph.scenes (primary) or scenario_assets.scenes (fallback)."""
    _require_admin(request)
    conn = request.app.state.db

    scenario = conn.execute(
        "SELECT knowledge_graph, scenario_assets FROM scenarios WHERE scenario_id = %s", (scenario_id,)
    ).fetchone()
    if not scenario:
        raise HTTPException(404, "剧本不存在")

    if scenario_version_id:
        version = conn.execute(
            "SELECT knowledge_graph FROM scenario_versions "
            "WHERE scenario_version_id = %s AND scenario_id = %s",
            (scenario_version_id, scenario_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "剧本版本不存在")
        kg = _json_val(version.get("knowledge_graph")) or {}
    else:
        kg = _json_val(scenario.get("knowledge_graph")) or {}

    # Primary source: versioned knowledge_graph.scenes (WorldBook structured output)
    scenes = kg.get("scenes", [])

    # Fallback: scenario_assets.scenes (legacy)
    if not scenes:
        assets = _json_val(scenario.get("scenario_assets")) or {}
        scenes = assets.get("scenes", [])
        if scenes:
            logger.info("Map generation using legacy scenario_assets.scenes for %s", scenario_id)

    if not scenes:
        raise HTTPException(400, "剧本没有场景数据（knowledge_graph.scenes 和 scenario_assets.scenes 均为空）")

    from .config import Settings
    settings = Settings.from_env()

    from .ai.gateway import AiGateway
    from .ai.map_generator import MapGenerator
    gen = MapGenerator(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        gateway=AiGateway(settings=settings, db_conn=conn),
    )
    base_asset = (
        _map_base_asset(_json_val(scenario.get("scenario_assets")) or {})
        or _select_map_base_asset(conn, scenario_id)
    )
    try:
        draft = await asyncio.wait_for(
            gen.generate_draft(scenes, base_asset),
            timeout=35,
        )
        generated_by = gen.last_generated_by
    except TimeoutError:
        logger.warning("AI map generation timed out for scenario %s; using local fallback", scenario_id)
        fallback = MapGenerator(api_key="", gateway=None)
        draft = await fallback.generate_draft(scenes, base_asset)
        generated_by = fallback.last_generated_by

    map_id = f"map_{scenario_id}_{str(uuid.uuid4())[:4]}"
    from .map_persistence import create_scenario_map
    result = create_scenario_map(
        conn, map_id, scenario_id, generated_by, draft["nodes"], draft["edges"],
        draft["map_type"], draft["base_asset"], draft["regions"], draft["paths"],
    )

    return _map_draft_payload(result)


@router.get("/scenarios/{scenario_id}/map")
async def admin_get_map(request: Request, scenario_id: str):
    """Get the current map draft for a scenario."""
    _require_admin(request)
    conn = request.app.state.db
    from .map_persistence import get_scenario_map_by_scenario
    mp = get_scenario_map_by_scenario(conn, scenario_id)
    if not mp:
        raise HTTPException(404, "该剧本暂无地图")
    return _map_draft_payload(mp)


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
    map_type = body.get("mapType", mp.get("map_type", "graph"))
    if map_type not in {"graph", "image", "hybrid"}:
        raise HTTPException(422, "mapType must be graph, image, or hybrid")
    base_asset = body.get("baseAsset", mp.get("base_asset", {}))
    regions = body.get("regions", mp.get("regions", []))
    paths = body.get("paths", mp.get("paths", []))
    update_scenario_map(conn, mp["map_id"], nodes, edges, map_type, base_asset, regions, paths)
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


@router.get("/ai/providers")
async def list_ai_providers(request: Request):
    _require_admin(request)
    from .ai.provider_config import AiProviderConfigStore

    return AiProviderConfigStore(request.app.state.db).list_public()


@router.post("/ai/providers")
async def create_ai_provider(request: Request):
    account = _require_admin(request)
    body = await request.json()
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError

    try:
        return AiProviderConfigStore(request.app.state.db).create(
            body,
            actor_id=account["account_id"],
        )
    except ProviderConfigError as exc:
        raise _provider_config_http_error(exc) from exc


@router.patch("/ai/providers/{provider_config_id}")
async def update_ai_provider(request: Request, provider_config_id: str):
    account = _require_admin(request)
    body = await request.json()
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError

    try:
        return AiProviderConfigStore(request.app.state.db).update(
            provider_config_id,
            body,
            actor_id=account["account_id"],
        )
    except ProviderConfigError as exc:
        raise _provider_config_http_error(exc) from exc


@router.delete("/ai/providers/{provider_config_id}")
async def delete_ai_provider(request: Request, provider_config_id: str):
    account = _require_admin(request)
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError

    store = AiProviderConfigStore(request.app.state.db)
    try:
        was_active = store.get_public(provider_config_id)["is_active"]
        store.delete(provider_config_id, actor_id=account["account_id"])
        return {"status": "deleted", "was_active": was_active}
    except ProviderConfigError as exc:
        raise _provider_config_http_error(exc) from exc


@router.post("/ai/providers/{provider_config_id}/test")
async def test_ai_provider(request: Request, provider_config_id: str):
    account = _require_admin(request)
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError
    from .ai.providers import ConfiguredOpenAIProvider

    store = AiProviderConfigStore(request.app.state.db)
    try:
        config = store.get_internal(provider_config_id)
        result = await ConfiguredOpenAIProvider(config).test_connection()
        store.record_test(
            provider_config_id,
            passed=bool(result["ok"]),
            latency_ms=int(result.get("latency_ms") or 0),
            actor_id=account["account_id"],
        )
        return result
    except ProviderConfigError as exc:
        raise _provider_config_http_error(exc) from exc


@router.post("/ai/providers/{provider_config_id}/activate")
async def activate_ai_provider(request: Request, provider_config_id: str):
    account = _require_admin(request)
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError

    try:
        return AiProviderConfigStore(request.app.state.db).activate(
            provider_config_id,
            actor_id=account["account_id"],
        )
    except ProviderConfigError as exc:
        raise _provider_config_http_error(exc) from exc


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
    rebuilt_by = _get_account_id(request)
    rebuilt_at = None
    from datetime import datetime, timezone
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
        rebuilt_at = datetime.now(timezone.utc).isoformat()

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

    return {
        "status": "reindexed",
        "counts": counts,
        "rebuilt_by": rebuilt_by,
        "rebuilt_at": rebuilt_at,
    }


@router.post("/rag/reindex-version")
async def rag_reindex_version(request: Request):
    account = _require_admin(request)
    conn = request.app.state.db
    rag = getattr(request.app.state, "rag", None)
    if not rag:
        raise HTTPException(503, "RAG not available")

    body = await request.json()
    scenario_version_id = str(body.get("scenario_version_id") or "").strip()
    if not scenario_version_id:
        raise HTTPException(400, "scenario_version_id required")

    version = conn.execute(
        "SELECT scenario_id FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()
    if not version:
        raise HTTPException(404, "剧本版本不存在")

    rows = conn.execute(
        """
        SELECT sp.source_part_id, sp.part_kind, sp.page_number, sp.text_content,
               sp.mime_type, sp.anchor, sd.source_filename
        FROM scenario_version_sources svs
        JOIN source_documents sd
          ON sd.source_document_id = svs.source_document_id
        JOIN source_parts sp
          ON sp.source_document_id = sd.source_document_id
        WHERE svs.scenario_version_id = %s
        ORDER BY svs.ordinal, sp.ordinal
        """,
        (scenario_version_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(409, "剧本版本尚未绑定可索引来源")

    parts = []
    for row in rows:
        source_filename = os.path.basename(
            str(row.get("source_filename") or "source").replace("\\", "/")
        )
        page_number = row.get("page_number")
        source_ref = source_filename
        if page_number is not None:
            source_ref = f"{source_ref}#page={page_number}"
        parts.append({
            "source_part_id": row["source_part_id"],
            "text": row.get("text_content") or "",
            "part_kind": row.get("part_kind") or "text",
            "mime_type": row.get("mime_type") or "",
            "page_number": page_number,
            "source_ref": source_ref,
            "anchor": _json_val(row.get("anchor")) or {},
        })

    rebuild_id = str(uuid.uuid4())
    embedding_model, embedding_dimensions = _rag_embedding_metadata(rag)
    conn.execute(
        """
        INSERT INTO rag_rebuild_records (
            rebuild_id, scenario_version_id, status, embedding_model,
            embedding_dimensions, requested_by
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            rebuild_id,
            scenario_version_id,
            "running",
            embedding_model,
            embedding_dimensions,
            account.get("account_id", "unknown"),
        ),
    )

    try:
        chunk_count = rag.index_scenario_version(
            version["scenario_id"],
            scenario_version_id,
            parts,
            visibility="internal",
        )
        embedding_model, embedding_dimensions = _rag_embedding_metadata(rag)
        with conn.transaction() as tx:
            tx.execute(
                """
                UPDATE scenario_versions
                SET rag_index_version = %s
                WHERE scenario_version_id = %s
                """,
                (rebuild_id, scenario_version_id),
            )
            tx.execute(
                """
                UPDATE rag_rebuild_records
                SET status = %s, chunk_count = %s, embedding_model = %s,
                    embedding_dimensions = %s, completed_at = NOW()
                WHERE rebuild_id = %s
                """,
                (
                    "complete",
                    chunk_count,
                    embedding_model,
                    embedding_dimensions,
                    rebuild_id,
                ),
            )
    except Exception as exc:
        conn.execute(
            """
            UPDATE rag_rebuild_records
            SET status = %s, error_message = %s, completed_at = NOW()
            WHERE rebuild_id = %s
            """,
            ("failed", str(exc)[:1000], rebuild_id),
        )
        logger.exception("RAG version rebuild failed: %s", scenario_version_id)
        raise HTTPException(500, "RAG 版本重建失败") from exc
    return {
        "status": "complete",
        "scenario_id": version["scenario_id"],
        "scenario_version_id": scenario_version_id,
        "rebuild_id": rebuild_id,
        "chunks_indexed": chunk_count,
    }


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
    """Rebuild sensitive item index for a scenario. Admin-only. Idempotent."""
    _require_admin(request)
    conn = request.app.state.db
    from .engine.spoiler_guard import SpoilerGuard
    from datetime import datetime, timezone
    sg = SpoilerGuard(conn)
    count = sg.rebuild_index(scenario_id)
    rebuilt_by = _get_account_id(request)
    rebuilt_at = datetime.now(timezone.utc).isoformat()
    return {
        "scenario_id": scenario_id,
        "items_indexed": count,
        "rebuilt_by": rebuilt_by,
        "rebuilt_at": rebuilt_at,
    }


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
        "character_id": r.get("character_id"),
        "room_id": r.get("room_id"),
        "player_name": r.get("player_name"),
        "xlsx_data": xlsx,
        "is_ready": r.get("is_ready"),
        "account_id": r.get("account_id"),
        "status": r.get("status"),
        "summary": _char_summary(r),
    }


def _json_val(value):
    if value is None: return None
    if isinstance(value, (dict, list)): return value
    if isinstance(value, str):
        try: return json.loads(value)
        except json.JSONDecodeError: return None
    return value


def _rag_embedding_metadata(rag) -> tuple[str | None, int | None]:
    embedding = getattr(rag, "embedding", None)
    if embedding is None:
        return None, None
    model_name = str(
        getattr(embedding, "model_name", "") or type(embedding).__name__
    )
    raw_dimensions = getattr(embedding, "dimension", None)
    try:
        dimensions = int(raw_dimensions) if raw_dimensions is not None else None
    except (TypeError, ValueError):
        dimensions = None
    return model_name, dimensions


def _provider_config_http_error(exc: Exception) -> HTTPException:
    code = str(exc)
    if code == "provider_config_not_found":
        return HTTPException(404, code)
    if code in {"provider_test_required", "key_unavailable"}:
        return HTTPException(409, code)
    return HTTPException(400, code)
