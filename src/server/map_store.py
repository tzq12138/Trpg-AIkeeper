"""DEPRECATED — replaced by map_persistence.py + PostgreSQL tables.
Kept temporarily for backward-compat; do not add new callers."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MapTile:
    id: str
    name: str
    description: str = ""
    neighbors: list[str] = field(default_factory=list)  # tile ids
    clues: list[str] = field(default_factory=list)
    npcs: list[str] = field(default_factory=list)


@dataclass
class MapState:
    room_id: str
    tiles: list[MapTile] = field(default_factory=list)
    player_positions: dict[str, str] = field(default_factory=dict)  # character_id → tile_id
    explored: dict[str, set[str]] = field(default_factory=dict)     # character_id → set[tile_id]


# In-memory store — lost on server restart (acceptable for session-scoped map)
_maps: dict[str, MapState] = {}


def get_map(room_id: str) -> MapState:
    if room_id not in _maps:
        _maps[room_id] = MapState(room_id=room_id)
    return _maps[room_id]


def init_map(room_id: str, tiles: list[dict]) -> MapState:
    """Initialize map from scenario knowledge graph scenes."""
    state = get_map(room_id)
    state.tiles = [
        MapTile(
            id=t.get("id", f"tile_{i}"),
            name=t.get("name", f"区域{i+1}"),
            description=t.get("description", ""),
            neighbors=t.get("neighbors", []),
            clues=t.get("clues_available", []),
            npcs=t.get("npcs_present", []),
        )
        for i, t in enumerate(tiles)
    ]
    return state


def set_player_position(room_id: str, character_id: str, tile_id: str):
    state = get_map(room_id)
    state.player_positions[character_id] = tile_id
    state.explored.setdefault(character_id, set()).add(tile_id)


def get_player_position(room_id: str, character_id: str) -> str | None:
    return get_map(room_id).player_positions.get(character_id)


def get_explored(room_id: str, character_id: str) -> set[str]:
    return get_map(room_id).explored.get(character_id, set())


def remove_room(room_id: str):
    _maps.pop(room_id, None)


def map_to_dict(state: MapState, character_id: str | None = None) -> dict[str, Any]:
    explored = get_explored(state.room_id, character_id) if character_id else set()
    current_pos = get_player_position(state.room_id, character_id) if character_id else None
    return {
        "room_id": state.room_id,
        "tiles": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "neighbors": t.neighbors,
                "explored": t.id in explored,
                "is_current": t.id == current_pos,
                "has_clues": len(t.clues) > 0,
                "has_npcs": len(t.npcs) > 0,
            }
            for t in state.tiles
        ],
        "current_tile": current_pos,
    }
