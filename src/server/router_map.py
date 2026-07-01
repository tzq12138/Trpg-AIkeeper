"""Map router — player map view with team-shared fog of war, move via engine intent."""
import asyncio
import logging

from fastapi import APIRouter, Request, HTTPException

from .models import PlayerIntent
from .map_persistence import (
    build_player_map_view,
    get_room_map_state,
    get_scenario_map,
    get_character_position,
    set_character_position,
    mark_node_explored,
    are_nodes_adjacent,
    is_node_hidden,
    get_adjacent_nodes,
)
from .player.router_player import _get_character

router = APIRouter(prefix="/api/map")
logger = logging.getLogger(__name__)


@router.get("/{room_id}")
async def get_map_view(request: Request, room_id: str):
    """Player map view with team-shared fog of war."""
    token = request.headers.get("X-Room-Token", "")
    character_id = None
    if token:
        try:
            char = _get_character(request)
            character_id = char["character_id"]
        except HTTPException:
            pass  # anonymous viewer

    conn = request.app.state.db

    # Check room has initialized map
    map_state = get_room_map_state(conn, room_id)
    if not map_state:
        return {
            "roomId": room_id, "nodes": [],
            "currentNodeId": None, "hiddenCount": 0, "mapStatus": "no_map",
        }

    if character_id:
        # Auto-place player at start node if not yet positioned
        pos = get_character_position(conn, character_id, room_id)
        if not pos:
            scenario_map = get_scenario_map(conn, map_state["map_id"])
            if scenario_map:
                nodes = scenario_map.get("nodes", [])
                start_node = next(
                    (n for n in nodes if n.get("is_start") or n.get("isStart")), None
                )
                start_id = start_node.get("node_id", start_node.get("nodeId", "")) if start_node else (
                    nodes[0].get("node_id", nodes[0].get("nodeId", "")) if nodes else ""
                )
                if start_id:
                    set_character_position(conn, character_id, room_id, start_id)
                    mark_node_explored(conn, room_id, start_id)

        return build_player_map_view(conn, room_id, character_id)

    # Anonymous: return basic layout without fog filtering
    scenario_map = get_scenario_map(conn, map_state["map_id"])
    if not scenario_map:
        return {
            "roomId": room_id, "nodes": [],
            "currentNodeId": None, "hiddenCount": 0, "mapStatus": "no_map",
        }
    return {
        "roomId": room_id,
        "nodes": scenario_map.get("nodes", []),
        "currentNodeId": None,
        "hiddenCount": 0,
        "mapStatus": map_state.get("status", "active") or "active",
    }


@router.post("/{room_id}/move")
async def move_player(request: Request, room_id: str):
    """Submit a move intent through the engine (not direct position update)."""
    char = _get_character(request)
    character_id = char["character_id"]

    body = await request.json()
    target_node_id = (body.get("target_node_id") or body.get("targetNodeId") or "").strip()
    from_node_id = (body.get("from_node_id") or body.get("fromNodeId") or "").strip()

    if not target_node_id:
        raise HTTPException(400, "target_node_id is required")

    conn = request.app.state.db

    # Quick pre-validation
    map_state = get_room_map_state(conn, room_id)
    if not map_state:
        raise HTTPException(400, "No map in this room")

    scenario_map = get_scenario_map(conn, map_state["map_id"])
    if not scenario_map:
        raise HTTPException(400, "Map not found")

    nodes = scenario_map.get("nodes", [])
    edges = scenario_map.get("edges", [])

    # Determine current position
    current_pos = from_node_id or get_character_position(conn, character_id, room_id)
    if not current_pos:
        # Auto-place then try again
        start_node = next((n for n in nodes if n.get("is_start") or n.get("isStart")), None)
        start_id = start_node.get("node_id", start_node.get("nodeId", "")) if start_node else (
            nodes[0].get("node_id", nodes[0].get("nodeId", "")) if nodes else ""
        )
        if start_id:
            set_character_position(conn, character_id, room_id, start_id)
            mark_node_explored(conn, room_id, start_id)
            current_pos = start_id
        else:
            raise HTTPException(400, "Character has no current position and no start node")

    # Adjacency check
    if not are_nodes_adjacent(nodes, edges, current_pos, target_node_id):
        raise HTTPException(400, f"Cannot move from {current_pos} to {target_node_id}: not adjacent")

    # Hidden check
    if is_node_hidden(conn, room_id, target_node_id):
        raise HTTPException(400, "Target node is hidden")

    # Submit intent through engine
    engine = request.app.state.engine
    intent = PlayerIntent(
        intent_type="move",
        declared_intent=f"移动到 {target_node_id}",
        params={
            "targetNodeId": target_node_id,
            "fromNodeId": current_pos,
            "roomId": room_id,
        },
    )
    result = engine.submit_intent(room_id, character_id, intent)

    if result.get("status") == "accepted":
        # Trigger background resolution
        pipeline = getattr(request.app.state, "pipeline", None)
        if pipeline:
            asyncio.create_task(pipeline.resolve_action(intent.action_id))

    return {
        "status": "submitted",
        "action_id": intent.action_id,
        "currentNodeId": current_pos,
        "targetNodeId": target_node_id,
    }
