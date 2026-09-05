from typing import Any


def build_player_action_context(conn, character: dict[str, Any]) -> dict[str, Any]:
    room_id = character["room_id"]
    character_id = character["character_id"]
    room = conn.execute(
        "SELECT room_id, state_version, status FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone() or {}
    own_clues = conn.execute(
        "SELECT clue_id, text, source FROM clues WHERE room_id = %s AND character_id = %s "
        "ORDER BY discovered_at, clue_id LIMIT 25",
        (room_id, character_id),
    ).fetchall()
    shared_clues = conn.execute(
        "SELECT c.clue_id, cs.public_version AS text, c.source FROM clue_shares cs "
        "JOIN clues c ON c.clue_id = cs.clue_id WHERE c.room_id = %s "
        "ORDER BY cs.shared_at, c.clue_id LIMIT 25",
        (room_id,),
    ).fetchall()
    clues = _unique_rows(own_clues, shared_clues, key="clue_id")
    objectives = conn.execute(
        "SELECT objective_id, text, type, status FROM objectives WHERE room_id = %s "
        "AND (type = 'team' OR character_id = %s) AND status = 'active' "
        "ORDER BY assigned_at, objective_id LIMIT 20",
        (room_id, character_id),
    ).fetchall()
    inventory = conn.execute(
        "SELECT id, name, description, quantity FROM inventory WHERE room_id = %s "
        "AND character_id = %s ORDER BY acquired_at, id LIMIT 30",
        (room_id, character_id),
    ).fetchall()
    evidence = conn.execute(
        "SELECT evidence_card_id, title, body, card_type, fact_status FROM evidence_cards "
        "WHERE room_id = %s AND visibility IN ('party', 'public') "
        "ORDER BY updated_at DESC, evidence_card_id LIMIT 25",
        (room_id,),
    ).fetchall()
    return {
        "policy": "player_visible_only",
        "viewer": {
            "character_id": character_id,
            "player_name": character.get("player_name", ""),
        },
        "room": {
            "room_id": room.get("room_id", room_id),
            "state_version": room.get("state_version", 0),
            "status": room.get("status", ""),
        },
        "known": {
            "clues": _public_rows(clues, ("clue_id", "text", "source")),
            "objectives": _public_rows(objectives, ("objective_id", "text", "type", "status")),
            "inventory": _public_rows(inventory, ("id", "name", "description", "quantity")),
            "evidence": _public_rows(
                evidence,
                ("evidence_card_id", "title", "body", "card_type", "fact_status"),
            ),
        },
    }


def _public_rows(rows: list[Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    return [{field: row.get(field) for field in fields} for row in rows]


def _unique_rows(*row_groups: list[Any], key: str) -> list[Any]:
    unique: dict[str, Any] = {}
    for rows in row_groups:
        for row in rows:
            unique.setdefault(str(row.get(key, "")), row)
    return list(unique.values())
