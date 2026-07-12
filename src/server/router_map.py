"""Map router — player-safe semantic map projection."""
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse

from .map_persistence import (
    build_player_map_view,
    get_room_map_state,
    get_character_position,
)
from .player.router_player import _get_character

router = APIRouter(prefix="/api/map")
maps_router = APIRouter(prefix="/api/maps")
logger = logging.getLogger(__name__)


def _sanitize_player_scene_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?:转到|轉到)\s*(?:条目\s*)?\d+\s*[。.!！]?", "", text)
    return text.strip()


def _safe_player_scene_name(value: str) -> str:
    name = str(value or "").strip()
    if re.fullmatch(r"(?:条目|條目|entry)\s*\d+", name, flags=re.IGNORECASE):
        return "当前场景"
    return name or "当前场景"


def _safe_text_scene_view(conn, room_id: str) -> dict:
    try:
        from .scenario.solo_runtime import SoloAdventureRuntime
        solo_scene = SoloAdventureRuntime(conn).current(room_id)
        if solo_scene:
            return {
                "name": _safe_player_scene_name(solo_scene["title"]),
                "description": _sanitize_player_scene_text(solo_scene["text"]),
                "visibleExits": [],
            }
    except Exception:
        logger.exception("failed to build solo adventure player projection room=%s", room_id)
    row = conn.execute(
        "SELECT s.knowledge_graph, rss.current_scene FROM rooms r "
        "JOIN scenarios s ON s.scenario_id = r.scenario_id "
        "LEFT JOIN room_scene_state rss ON rss.room_id = r.room_id "
        "WHERE r.room_id = %s",
        (room_id,),
    ).fetchone()
    default = {
        "name": "当前场景",
        "description": "本团使用文字场景模式。请根据 AI KP 的叙事、当前目标与已公开线索行动。",
        "visibleExits": [],
    }
    if not row:
        return default
    knowledge_graph = row.get("knowledge_graph") or {}
    if isinstance(knowledge_graph, str):
        try:
            knowledge_graph = json.loads(knowledge_graph)
        except (TypeError, ValueError):
            return default
    if not isinstance(knowledge_graph, dict):
        return default
    current_scene = row.get("current_scene") or ""
    safe_scenes = [
        scene for scene in knowledge_graph.get("scenes", []) or []
        if isinstance(scene, dict) and not scene.get("is_hidden", False)
    ]
    scene = next(
        (
            candidate for candidate in safe_scenes
            if current_scene and current_scene in {
                candidate.get("sceneId", ""),
                candidate.get("scene_id", ""),
                candidate.get("id", ""),
                candidate.get("name", ""),
            }
        ),
        safe_scenes[0] if safe_scenes else None,
    )
    if not scene:
        return default
    visible_exits = []
    for raw_exit in scene.get("visibleExits", scene.get("visible_exits", [])) or []:
        if isinstance(raw_exit, str) and raw_exit:
            visible_exits.append(raw_exit)
        elif isinstance(raw_exit, dict) and not raw_exit.get("is_hidden", False):
            label = raw_exit.get("label", raw_exit.get("name", raw_exit.get("to", "")))
            if isinstance(label, str) and label:
                visible_exits.append(label)
    return {
        "name": scene.get("public_name", scene.get("name", "当前场景")),
        "description": scene.get("public_description", scene.get("description", "")),
        "visibleExits": visible_exits[:12],
    }


@router.get("/{room_id}")
async def get_map_view(request: Request, room_id: str):
    """Player map view — pure read, no side-effects. Requires valid player token."""
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "需要玩家身份令牌")

    # Validate token and get character — no anonymous fallback
    try:
        char = _get_character(request)
    except HTTPException:
        raise HTTPException(403, "无效或过期的玩家令牌")

    character_id = char["character_id"]
    conn = request.app.state.db

    # Verify character belongs to this room (cross-room check)
    if char.get("room_id") != room_id:
        raise HTTPException(403, "无权访问此房间的地图")

    # Check room has initialized map
    map_state = get_room_map_state(conn, room_id)
    if not map_state:
        return {
            "roomId": room_id,
            "mapStatus": "text_mode",
            "mapType": "text",
            "baseAsset": {},
            "knownLocations": [],
            "knownConnections": [],
            "partyPosition": None,
            "fogOfWar": [],
            "textScene": _safe_text_scene_view(conn, room_id),
        }

    # Check player has a current position (no auto-placement on GET)
    pos = get_character_position(conn, character_id, room_id)
    if not pos:
        return {
            "roomId": room_id,
            "mapStatus": "no_current_position",
            "mapType": "graph",
            "baseAsset": {},
            "knownLocations": [],
            "knownConnections": [],
            "partyPosition": None,
            "fogOfWar": [],
        }

    view = build_player_map_view(conn, room_id, character_id)

    # Filter hidden NPCs from player map nodes
    try:
        room_row = conn.execute(
            "SELECT scenario_id FROM rooms WHERE room_id = %s", (room_id,)
        ).fetchone()
        if room_row:
            scenario_row = conn.execute(
                "SELECT knowledge_graph FROM scenarios WHERE scenario_id = %s",
                (room_row["scenario_id"],),
            ).fetchone()
            if scenario_row:
                kg = scenario_row["knowledge_graph"]
                if isinstance(kg, str):
                    kg = json.loads(kg)
                hidden_npc_names = set()
                for npc in (kg or {}).get("npcs", []):
                    if npc.get("is_hidden"):
                        hidden_npc_names.add(npc.get("name", ""))
                        hidden_npc_names.add(npc.get("public_name", ""))
                for node in view.get("nodes", []):
                    raw_npcs = node.get("npcsPresent", [])
                    if raw_npcs:
                        node["npcsPresent"] = [
                            n for n in raw_npcs if n not in hidden_npc_names
                        ]
    except Exception:
        pass

    # Strip cluesAvailable from player view (only visible via clue system)
    for node in view.get("nodes", []):
        node.pop("cluesAvailable", None)

    view["textScene"] = _safe_text_scene_view(conn, room_id)

    return view


@maps_router.get("/{room_id}")
async def get_map_view_v2(request: Request, room_id: str):
    return await get_map_view(request, room_id)


@maps_router.get("/{room_id}/assets/{asset_id}")
async def get_player_map_asset(request: Request, room_id: str, asset_id: str):
    char = _get_character(request)
    if char.get("room_id") != room_id:
        raise HTTPException(403, "无权访问此房间的地图素材")
    conn = request.app.state.db
    asset = conn.execute(
        "SELECT a.mime_type, a.relative_path FROM scenario_assets a "
        "JOIN rooms r ON r.scenario_id = a.scenario_id "
        "WHERE r.room_id = %s AND a.asset_id = %s "
        "AND a.visibility IN ('player', 'party', 'public')",
        (room_id, asset_id),
    ).fetchone()
    if not asset:
        raise HTTPException(404, "地图素材不存在或未公开")
    project_root = Path(__file__).resolve().parents[2]
    target = (project_root / asset["relative_path"]).resolve()
    if project_root not in target.parents or not target.is_file():
        raise HTTPException(404, "地图素材不可用")
    return FileResponse(
        target,
        media_type=asset["mime_type"],
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/{room_id}/move")
async def move_player(request: Request, room_id: str):
    """Reject direct map movement; players must use natural-language actions."""
    raise HTTPException(
        status_code=410,
        detail={
            "code": "use_action_draft",
            "message": "Map movement must be submitted as a natural-language action draft.",
        },
    )
