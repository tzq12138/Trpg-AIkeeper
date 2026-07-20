"""Encounter persistence layer — PostgreSQL CRUD for encounters and participants.
Mirrors map_persistence.py pattern: conn-first params, JSONB auto-coercion helpers.
NPCs use character_id = "npc:{uuid}" format and do not reference the characters table.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Distance band order for chase mechanics
DISTANCE_BAND_ORDER = ["engaged", "near", "short", "medium", "long", "escaped"]


def _json_val(field: Any) -> list | dict:
    if field is None:
        return {}
    if isinstance(field, (list, dict)):
        return field
    if isinstance(field, str):
        try:
            return json.loads(field)
        except (json.JSONDecodeError, TypeError):
            return []
    return field


def _ensure_json(val: list | dict) -> str:
    return json.dumps(val, ensure_ascii=False)


# ── Encounter CRUD ──

def get_encounter(conn, encounter_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM encounters WHERE encounter_id = %s", (encounter_id,)
    ).fetchone()
    if not row:
        return None
    return dict(row)


def get_active_encounter(conn, room_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM encounters WHERE room_id = %s AND status IN ('suggested', 'active') "
        "ORDER BY created_at DESC LIMIT 1",
        (room_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def create_encounter(
    conn, encounter_id: str, room_id: str,
    enc_type: str = "combat", status: str = "suggested",
    summary: str = "",
) -> dict:
    conn.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, summary) "
        "VALUES (%s, %s, %s, %s, %s)",
        (encounter_id, room_id, enc_type, status, summary),
    )
    conn.commit()
    return get_encounter(conn, encounter_id)


def update_encounter_status(conn, encounter_id: str, status: str, summary: str | None = None):
    if summary is not None:
        conn.execute(
            "UPDATE encounters SET status = %s, summary = %s WHERE encounter_id = %s",
            (status, summary, encounter_id),
        )
    else:
        conn.execute(
            "UPDATE encounters SET status = %s WHERE encounter_id = %s",
            (status, encounter_id),
        )
    if status == "resolved":
        conn.execute(
            "UPDATE encounters SET resolved_at = NOW() WHERE encounter_id = %s",
            (encounter_id,),
        )
    conn.commit()


def update_encounter_round(conn, encounter_id: str, round_num: int):
    conn.execute(
        "UPDATE encounters SET current_round = %s WHERE encounter_id = %s",
        (round_num, encounter_id),
    )
    conn.commit()


# ── Participant CRUD ──

def get_participants(conn, encounter_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM encounter_participants WHERE encounter_id = %s ORDER BY side, character_id",
        (encounter_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_participant(conn, encounter_id: str, character_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM encounter_participants WHERE encounter_id = %s AND character_id = %s",
        (encounter_id, character_id),
    ).fetchone()
    return dict(row) if row else None


def add_participant(
    conn, encounter_id: str, character_id: str,
    side: str = "player", hp: int = 10, hp_max: int = 10,
    san: int = 50, san_max: int = 50, dex: int = 50, mov: int = 7,
    distance_band: str = "medium", current_position: str = "",
    weapon_name: str = "", damage_expression: str = "1d3",
    main_skill: str = "", notes: str = "",
    display_name: str = "",
    public_visibility: str = "hidden",
    public_label: str = "",
    last_observed_position: str = "",
) -> dict:
    conn.execute(
        "INSERT INTO encounter_participants "
        "(encounter_id, character_id, side, hp, hp_max, san, san_max, dex, mov, "
        "current_position, distance_band, status_tags, acted_this_round, "
        "weapon_name, damage_expression, main_skill, notes, display_name, "
        "public_visibility, public_label, last_observed_position) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (encounter_id, character_id, side, hp, hp_max, san, san_max, dex, mov,
         current_position, distance_band, _ensure_json([]), False,
         weapon_name, damage_expression, main_skill, notes, display_name,
         public_visibility, public_label, last_observed_position),
    )
    conn.commit()
    return get_participant(conn, encounter_id, character_id)


def update_participant(conn, encounter_id: str, character_id: str, **fields):
    """Update specific participant fields. Only non-None values are applied."""
    if not fields:
        return
    allowed = {"hp", "hp_max", "san", "san_max", "dex", "mov",
               "current_position", "distance_band", "status_tags",
               "acted_this_round", "weapon_name", "damage_expression",
               "main_skill", "notes", "side", "public_visibility",
               "public_label", "last_observed_position"}
    set_parts = []
    params = []
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        col = k
        val = _ensure_json(v) if k == "status_tags" else v
        set_parts.append(f"{col} = %s")
        params.append(val)
    if not set_parts:
        return
    params.extend([encounter_id, character_id])
    conn.execute(
        f"UPDATE encounter_participants SET {', '.join(set_parts)} "
        "WHERE encounter_id = %s AND character_id = %s",
        tuple(params),
    )
    conn.commit()


def remove_participant(conn, encounter_id: str, character_id: str):
    conn.execute(
        "DELETE FROM encounter_participants WHERE encounter_id = %s AND character_id = %s",
        (encounter_id, character_id),
    )
    conn.commit()


def reset_round_actions(conn, encounter_id: str):
    conn.execute(
        "UPDATE encounter_participants SET acted_this_round = FALSE "
        "WHERE encounter_id = %s",
        (encounter_id,),
    )
    conn.commit()


# ── Chase helpers ──

def compute_distance_change(mov: int, skill_value: int, roll_success: bool, success_level: str = "regular") -> int:
    """Returns the number of distance bands to shift (positive = away, negative = closer)."""
    if not roll_success:
        return 0
    if success_level == "critical":
        return 2
    if success_level == "extreme":
        return 2
    if success_level == "hard":
        return 1
    return 1  # regular success


def shift_band(current_band: str, delta: int) -> str:
    """Shift distance band by delta steps. Clamped to valid range."""
    if current_band not in DISTANCE_BAND_ORDER:
        return current_band
    idx = DISTANCE_BAND_ORDER.index(current_band)
    new_idx = max(0, min(len(DISTANCE_BAND_ORDER) - 1, idx + delta))
    return DISTANCE_BAND_ORDER[new_idx]
