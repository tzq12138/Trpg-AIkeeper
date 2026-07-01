"""Map persistence layer — PostgreSQL-backed CRUD for scenario maps, room map state,
and character positions. Replaces the in-memory map_store.py module.

All functions accept a PgConnection (or compatible) as the first argument.
JSONB fields are read/written as Python lists/dicts via the adapter's auto-coercion.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── helpers ──

def _json_val(field: Any) -> list | dict:
    """Parse a JSONB field that may already be a Python object or a JSON string."""
    if field is None:
        return {}
    if isinstance(field, (list, dict)):
        return field
    if isinstance(field, str):
        try:
            return json.loads(field)
        except (json.JSONDecodeError, TypeError):
            return {} if field.startswith("[") else []
    return field


def _ensure_json(val: list | dict) -> str:
    """Serialize a Python value for JSONB storage."""
    return json.dumps(val, ensure_ascii=False)


# ── Scenario map CRUD ──

def get_scenario_map(conn, map_id: str) -> dict | None:
    row = conn.execute(
        "SELECT *, nodes::text AS nodes_text, edges::text AS edges_text FROM scenario_maps WHERE map_id = %s",
        (map_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "map_id": row["map_id"],
        "scenario_id": row["scenario_id"],
        "generated_by": row.get("generated_by", "python"),
        "status": row.get("status", "draft"),
        "nodes": _json_val(row.get("nodes", [])),
        "edges": _json_val(row.get("edges", [])),
        "created_at": str(row.get("created_at", "")),
        "confirmed_at": str(row.get("confirmed_at", "")),
    }


def get_scenario_map_by_scenario(conn, scenario_id: str) -> dict | None:
    row = conn.execute(
        "SELECT map_id FROM scenario_maps WHERE scenario_id = %s ORDER BY created_at DESC LIMIT 1",
        (scenario_id,),
    ).fetchone()
    if not row:
        return None
    return get_scenario_map(conn, row["map_id"])


def create_scenario_map(
    conn, map_id: str, scenario_id: str,
    generated_by: str, nodes: list[dict], edges: list[dict],
) -> dict:
    conn.execute(
        "INSERT INTO scenario_maps (map_id, scenario_id, generated_by, status, nodes, edges) "
        "VALUES (%s, %s, %s, 'draft', %s, %s)",
        (map_id, scenario_id, generated_by, _ensure_json(nodes), _ensure_json(edges)),
    )
    conn.commit()
    return get_scenario_map(conn, map_id)


def update_scenario_map(conn, map_id: str, nodes: list[dict], edges: list[dict]):
    conn.execute(
        "UPDATE scenario_maps SET nodes = %s, edges = %s WHERE map_id = %s AND status = 'draft'",
        (_ensure_json(nodes), _ensure_json(edges), map_id),
    )
    conn.commit()


def confirm_scenario_map(conn, map_id: str) -> dict:
    conn.execute(
        "UPDATE scenario_maps SET status = 'confirmed', confirmed_at = NOW() WHERE map_id = %s",
        (map_id,),
    )
    conn.commit()
    return get_scenario_map(conn, map_id)


# ── Room map state CRUD ──

def init_room_map_state(conn, room_id: str, map_id: str) -> dict:
    """Create room_map_state from a confirmed scenario map. Idempotent."""
    existing = conn.execute(
        "SELECT room_id FROM room_map_state WHERE room_id = %s", (room_id,)
    ).fetchone()
    if existing:
        return {
            "room_id": room_id, "map_id": existing.get("map_id", map_id),
            "explored_nodes": [], "hidden_nodes": [], "state_version": 0,
        }

    conn.execute(
        "INSERT INTO room_map_state (room_id, map_id) VALUES (%s, %s)",
        (room_id, map_id),
    )
    conn.commit()
    return {
        "room_id": room_id, "map_id": map_id,
        "explored_nodes": [], "hidden_nodes": [], "state_version": 0,
    }


def get_room_map_state(conn, room_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM room_map_state WHERE room_id = %s", (room_id,)
    ).fetchone()
    if not row:
        return None
    return {
        "room_id": row["room_id"],
        "map_id": row["map_id"],
        "explored_nodes": _json_val(row.get("explored_nodes", [])),
        "hidden_nodes": _json_val(row.get("hidden_nodes", [])),
        "state_version": row.get("state_version", 0),
        "updated_at": str(row.get("updated_at", "")),
    }


def mark_node_explored(conn, room_id: str, node_id: str):
    """Add a node to the team-shared explored list. Idempotent."""
    state = get_room_map_state(conn, room_id)
    if not state:
        return
    explored: list = state.get("explored_nodes", [])
    if node_id not in explored:
        explored.append(node_id)
        conn.execute(
            "UPDATE room_map_state SET explored_nodes = %s, state_version = state_version + 1, updated_at = NOW() WHERE room_id = %s",
            (_ensure_json(explored), room_id),
        )
        conn.commit()


def is_node_explored(conn, room_id: str, node_id: str) -> bool:
    state = get_room_map_state(conn, room_id)
    if not state:
        return False
    return node_id in (state.get("explored_nodes", []) or [])


def is_node_hidden(conn, room_id: str, node_id: str) -> bool:
    state = get_room_map_state(conn, room_id)
    if not state:
        return False
    return node_id in (state.get("hidden_nodes", []) or [])


def host_set_node_visible(conn, room_id: str, node_id: str, visible: bool):
    """Reveal or hide a node (Host operation)."""
    state = get_room_map_state(conn, room_id)
    if not state:
        return
    hidden: list = state.get("hidden_nodes", [])
    if visible and node_id in hidden:
        hidden.remove(node_id)
        conn.execute(
            "UPDATE room_map_state SET hidden_nodes = %s, state_version = state_version + 1, updated_at = NOW() WHERE room_id = %s",
            (_ensure_json(hidden), room_id),
        )
        conn.commit()
    elif not visible and node_id not in hidden:
        hidden.append(node_id)
        conn.execute(
            "UPDATE room_map_state SET hidden_nodes = %s, state_version = state_version + 1, updated_at = NOW() WHERE room_id = %s",
            (_ensure_json(hidden), room_id),
        )
        conn.commit()


# ── Character position CRUD ──

def get_character_position(conn, character_id: str, room_id: str) -> str | None:
    row = conn.execute(
        "SELECT node_id FROM character_map_positions WHERE character_id = %s AND room_id = %s",
        (character_id, room_id),
    ).fetchone()
    return row["node_id"] if row else None


def set_character_position(conn, character_id: str, room_id: str, node_id: str):
    conn.execute(
        "INSERT INTO character_map_positions (character_id, room_id, node_id, updated_at) "
        "VALUES (%s, %s, %s, NOW()) "
        "ON CONFLICT (character_id, room_id) DO UPDATE SET node_id = %s, updated_at = NOW()",
        (character_id, room_id, node_id, node_id),
    )
    conn.commit()


def get_all_positions_in_room(conn, room_id: str) -> dict[str, str]:
    """Return {character_id: node_id} for all characters in the room."""
    rows = conn.execute(
        "SELECT character_id, node_id FROM character_map_positions WHERE room_id = %s",
        (room_id,),
    ).fetchall()
    return {r["character_id"]: r["node_id"] for r in rows}


# ── Graph helpers ──

def are_nodes_adjacent(
    nodes: list[dict], edges: list[dict], from_id: str, to_id: str,
) -> bool:
    """Check if two nodes are connected by an edge (bidirectional)."""
    if from_id == to_id:
        return True
    for e in edges:
        ef = e.get("from_node", e.get("fromNode", ""))
        et = e.get("to_node", e.get("toNode", ""))
        is_one_way = e.get("is_one_way", e.get("isOneWay", False))
        if ef == from_id and et == to_id:
            return True
        if not is_one_way and ef == to_id and et == from_id:
            return True
    return False


def get_adjacent_nodes(nodes: list[dict], edges: list[dict], node_id: str) -> set[str]:
    """Return the set of node_ids adjacent to the given node."""
    adjacent = set()
    for e in edges:
        ef = e.get("from_node", e.get("fromNode", ""))
        et = e.get("to_node", e.get("toNode", ""))
        is_one_way = e.get("is_one_way", e.get("isOneWay", False))
        if ef == node_id:
            adjacent.add(et)
        if not is_one_way and et == node_id:
            adjacent.add(ef)
    return adjacent


# ── Player view builder (team-shared fog of war) ──

def build_player_map_view(conn, room_id: str, character_id: str) -> dict:
    """Assemble the fog-of-war filtered map view for a player."""
    state = get_room_map_state(conn, room_id)
    if not state:
        return {
            "roomId": room_id, "nodes": [],
            "currentNodeId": None, "hiddenCount": 0, "mapStatus": "no_map",
        }

    # Load scenario map
    scenario_map = get_scenario_map(conn, state["map_id"])
    if not scenario_map:
        return {
            "roomId": room_id, "nodes": [],
            "currentNodeId": None, "hiddenCount": 0, "mapStatus": "no_map",
        }

    nodes: list = scenario_map.get("nodes", [])
    edges: list = scenario_map.get("edges", [])
    explored: list = state.get("explored_nodes", [])
    hidden: list = state.get("hidden_nodes", [])
    current_pos = get_character_position(conn, character_id, room_id)

    if not current_pos:
        # Auto-place at start node
        start_node = None
        for n in nodes:
            if n.get("is_start") or n.get("isStart"):
                start_node = n.get("node_id", n.get("nodeId", ""))
                break
        if not start_node and nodes:
            start_node = nodes[0].get("node_id", nodes[0].get("nodeId", ""))
        if start_node:
            set_character_position(conn, character_id, room_id, start_node)
            mark_node_explored(conn, room_id, start_node)
            current_pos = start_node
            explored = [start_node]

    adjacent_set = get_adjacent_nodes(nodes, edges, current_pos) if current_pos else set()

    view_nodes = []
    total_nodes = len(nodes)
    visible_count = 0

    for n in nodes:
        nid = n.get("node_id", n.get("nodeId", ""))
        is_explored = nid in explored
        is_current = nid == current_pos
        is_adjacent = nid in adjacent_set
        is_hidden_by_host = nid in hidden

        if is_hidden_by_host and not is_explored:
            continue  # Host-hidden nodes invisible unless already explored

        if is_explored:
            # Full detail
            view_nodes.append({
                "nodeId": nid,
                "name": n.get("name", ""),
                "description": n.get("description", ""),
                "npcsPresent": n.get("npcs_present", n.get("npcsPresent", [])),
                "cluesAvailable": n.get("clues_available", n.get("cluesAvailable", [])),
                "position": n.get("position", {"x": 0, "y": 0}),
                "isStart": n.get("is_start", n.get("isStart", False)),
                "explored": True,
                "isCurrent": is_current,
                "isAdjacent": is_adjacent,
                "hasClues": bool(n.get("clues_available", n.get("cluesAvailable", []))),
                "hasNpcs": bool(n.get("npcs_present", n.get("npcsPresent", []))),
            })
        elif is_adjacent:
            # Adjacent but unexplored: show name + hint only
            view_nodes.append({
                "nodeId": nid,
                "name": n.get("name", ""),
                "description": "???",  # hidden
                "npcsPresent": [],
                "cluesAvailable": [],
                "position": n.get("position", {"x": 0, "y": 0}),
                "isStart": n.get("is_start", n.get("isStart", False)),
                "explored": False,
                "isCurrent": False,
                "isAdjacent": True,
                "hasClues": False,  # hidden
                "hasNpcs": False,  # hidden
            })
        # Non-adjacent, unexplored nodes: not included in view

        visible_count += 1

    hidden_count = total_nodes - visible_count

    return {
        "roomId": room_id,
        "nodes": view_nodes,
        "currentNodeId": current_pos,
        "hiddenCount": max(0, hidden_count),
        "mapStatus": state.get("status", "active") or "active",
    }


# ── Load scenario map for a room ──

def _load_map_for_room(conn, room_id: str) -> dict | None:
    """Get the scenario map associated with a room's room_map_state."""
    state = get_room_map_state(conn, room_id)
    if not state:
        return None
    return get_scenario_map(conn, state["map_id"])
