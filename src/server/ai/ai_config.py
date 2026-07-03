"""AI configuration persistence — global and per-room overrides."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_AI_CONFIG = {
    "provider_order": "deepseek,mcp,local",
    "timeout_seconds": 30,
    "permissions": {
        "direct": ["narrative", "tactical_prompts", "scene_transition", "npc_reaction", "add_status_tag"],
        "validate": ["san_loss", "hp_loss", "mp_loss", "luck_change", "gain_clue", "gain_item",
                     "move_location", "combat_suggestion"],
        "block": ["attribute_change", "skill_value_change", "credit_rating_change"],
    },
}


def _json_val(field: Any) -> dict:
    if field is None:
        return {}
    if isinstance(field, dict):
        return field
    if isinstance(field, str):
        try:
            return json.loads(field)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


# ── Global AI Config ──

def get_global_ai_config(conn) -> dict:
    """Get global AI config from host_states table (key='ai_global_config')."""
    try:
        row = conn.execute(
            "SELECT state FROM host_states WHERE room_id = %s", ("_global_",)
        ).fetchone()
        if row:
            state = _json_val(row.get("state"))
            cfg = state.get("ai_config", {})
            return {**DEFAULT_AI_CONFIG, **cfg}
    except Exception as e:
        logger.debug("Failed to load global AI config: %s", e)
    return dict(DEFAULT_AI_CONFIG)


def update_global_ai_config(conn, config: dict):
    """Update global AI config. Persists to host_states with room_id='_global_'."""
    try:
        existing = get_global_ai_config(conn)
        merged = {**existing, **config}
        state_json = json.dumps({"ai_config": merged}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO host_states (room_id, state) VALUES ('_global_', %s) "
            "ON CONFLICT (room_id) DO UPDATE SET state = %s, updated_at = NOW()",
            (state_json, state_json),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to update global AI config: %s", e)
        raise


# ── Room-level AI Config ──

def get_room_ai_config(conn, room_id: str) -> dict | None:
    """Get room-level AI config override. Returns None if not set."""
    try:
        row = conn.execute(
            "SELECT state FROM host_states WHERE room_id = %s", (room_id,)
        ).fetchone()
        if row:
            state = _json_val(row.get("state"))
            cfg = state.get("ai_config")
            if cfg:
                return cfg
    except Exception as e:
        logger.debug("Failed to load room AI config: %s", e)
    return None


def update_room_ai_config(conn, room_id: str, config: dict):
    """Set room-level AI config override."""
    try:
        row = conn.execute(
            "SELECT state FROM host_states WHERE room_id = %s", (room_id,)
        ).fetchone()
        existing_state = _json_val(row["state"]) if row else {}
        existing_state["ai_config"] = config
        state_json = json.dumps(existing_state, ensure_ascii=False)
        conn.execute(
            "INSERT INTO host_states (room_id, state) VALUES (%s, %s) "
            "ON CONFLICT (room_id) DO UPDATE SET state = %s, updated_at = NOW()",
            (room_id, state_json, state_json),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to update room AI config: %s", e)
        raise
