"""HUD builder — builds HostHUD from current database state (never stale)."""

import json
import logging

logger = logging.getLogger(__name__)


def _parse_xlsx(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def build_hud(conn, room_id: str):
    """Build a HostHUD dict from the current database state.

    Queries characters + character_runtime_state directly so the result is
    always fresh — not dependent on in-memory HostStore.players.
    """
    from ..models import HostHUD, PlayerPublicStatus

    chars = conn.execute(
        """SELECT c.character_id, c.player_name, c.xlsx_data, c.status, c.is_ready,
                  crs.hp, crs.hp_max, crs.san, crs.san_max,
                  crs.mp, crs.mp_max, crs.luck, crs.status_tags
           FROM characters c
           LEFT JOIN character_runtime_state crs
             ON c.character_id = crs.character_id AND c.room_id = crs.room_id
           WHERE c.room_id = %s AND c.status != 'left'
           ORDER BY c.character_id""",
        (room_id,)
    ).fetchall()

    players = []
    for c in chars:
        xlsx = _parse_xlsx(c.get("xlsx_data"))
        status_tags = c.get("status_tags")
        if isinstance(status_tags, str):
            try:
                status_tags = json.loads(status_tags)
            except json.JSONDecodeError:
                status_tags = []
        # Fall back to xlsx_data when character_runtime_state has no row
        xlsx_hp = xlsx.get("hp") if isinstance(xlsx, dict) else None
        xlsx_san = xlsx.get("san") if isinstance(xlsx, dict) else None
        xlsx_mp = xlsx.get("mp") if isinstance(xlsx, dict) else None
        xlsx_luck = xlsx.get("luck") if isinstance(xlsx, dict) else None

        players.append(PlayerPublicStatus(
            character_id=c["character_id"],
            player_name=c["player_name"],
            investigator_name=xlsx.get("name", "") if isinstance(xlsx, dict) else "",
            hp=c.get("hp") or xlsx_hp or 0,
            hp_max=c.get("hp_max") or (xlsx.get("max_hp") if isinstance(xlsx, dict) else None) or (xlsx_hp or 0),
            san=c.get("san") or xlsx_san or 0,
            san_max=c.get("san_max") or (xlsx.get("max_san") if isinstance(xlsx, dict) else None) or (xlsx_san or 0),
            mp=c.get("mp") or xlsx_mp or 0,
            mp_max=c.get("mp_max") or (xlsx.get("max_mp") if isinstance(xlsx, dict) else None) or (xlsx_mp or 0),
            luck=c.get("luck") or xlsx_luck or 0,
            status_tags=list(status_tags or []),
        ))

    objective_rows = conn.execute(
        "SELECT text FROM objectives WHERE room_id = %s AND type = 'team' AND status = 'active' "
        "ORDER BY assigned_at ASC LIMIT 3",
        (room_id,),
    ).fetchall()
    scene_time = "时间未定"
    scene_row = conn.execute(
        "SELECT scene_variables FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if scene_row:
        scene_variables = _parse_xlsx(scene_row.get("scene_variables"))
        for key in ("public_time", "scene_time", "time"):
            value = scene_variables.get(key) if isinstance(scene_variables, dict) else None
            if isinstance(value, str) and value.strip():
                scene_time = value.strip()
                break

    return HostHUD(
        room_id=room_id,
        players=players,
        scene_image_url=None,
        engine_state="idle",
        queue_status={"normal": 0, "urgent": 0},
        team_objectives=[str(row["text"]) for row in objective_rows if row.get("text")],
        scene_time=scene_time,
    )
