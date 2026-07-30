"""AI configuration persistence — global and per-room overrides."""

import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from .rule_policy_compiler import (
    RULE_POLICY_COMPILER_VERSION as RUNTIME_RULE_COMPILER_VERSION,
    compile_rule_policy_sources,
    compiled_rule_artifact_id,
    rule_policy_sources_signature,
)

logger = logging.getLogger(__name__)

RUNTIME_BINDING_VERSION = "m0-runtime-binding-v1"
RUNTIME_PROMPT_TEMPLATE_VERSION = "m0-runtime-v1"


class RoomAiConfigLockedError(RuntimeError):
    pass


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


def configured_provider_signature(config: dict) -> str:
    material = {
        key: config.get(key)
        for key in (
            "api_base_url",
            "protocol",
            "model",
            "supports_image",
            "api_key_ciphertext",
        )
    }
    return hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def frozen_rule_policy_sources(
    conn,
    room_id: str,
    scenario_version_id: str | None,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if scenario_version_id:
        rows = conn.execute(
            """
            SELECT rsv.rule_set_version_id, rsv.metadata, rs.is_base,
                   srb.priority
            FROM scenario_rule_bindings srb
            JOIN rule_set_versions rsv
              ON rsv.rule_set_version_id = srb.rule_set_version_id
            JOIN rule_sets rs ON rs.rule_set_id = rsv.rule_set_id
            WHERE srb.scenario_version_id = %s
            ORDER BY CASE WHEN rs.is_base THEN 0 ELSE 1 END,
                     srb.priority, rsv.rule_set_version_id
            """,
            (scenario_version_id,),
        ).fetchall()
        sources.extend(
            {
                "scope": "base" if row.get("is_base") else "scenario",
                "rule_set_version_id": str(row["rule_set_version_id"]),
                "metadata": _json_val(row.get("metadata")),
            }
            for row in rows
        )
    else:
        rows = conn.execute(
            """
            SELECT rsv.rule_set_version_id, rsv.metadata
            FROM rule_set_versions rsv
            JOIN rule_sets rs ON rs.rule_set_id = rsv.rule_set_id
            WHERE rs.system = 'coc7' AND rs.is_base = TRUE
              AND rs.status = 'published' AND rsv.status = 'published'
            ORDER BY rsv.version_number, rsv.rule_set_version_id
            """
        ).fetchall()
        sources.extend(
            {
                "scope": "base",
                "rule_set_version_id": str(row["rule_set_version_id"]),
                "metadata": _json_val(row.get("metadata")),
            }
            for row in rows
        )
    room_rows = conn.execute(
        """
        SELECT rsv.rule_set_version_id, rsv.metadata, rrb.priority
        FROM room_rule_bindings rrb
        JOIN rule_set_versions rsv
          ON rsv.rule_set_version_id = rrb.rule_set_version_id
        WHERE rrb.room_id = %s
        ORDER BY rrb.priority, rsv.rule_set_version_id
        """,
        (room_id,),
    ).fetchall()
    sources.extend(
        {
            "scope": "room",
            "rule_set_version_id": str(row["rule_set_version_id"]),
            "metadata": _json_val(row.get("metadata")),
        }
        for row in room_rows
    )
    return sources


rule_policy_signature = rule_policy_sources_signature


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
        existing_config = get_room_ai_config(conn, room_id) or {}
        binding = _json_val(existing_config.get("runtime_binding"))
        if binding.get("locked") is True:
            raise RoomAiConfigLockedError(
                "房间 AI 运行版本已固定，不能静默切换"
            )
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
    except RoomAiConfigLockedError:
        raise
    except Exception as e:
        logger.error("Failed to update room AI config: %s", e)
        raise


def pin_room_ai_runtime(
    conn,
    room_id: str,
    *,
    scenario_version_id: str | None,
    runtime_package_version_id: str | None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Persist the immutable AI/runtime binding used by one room run."""
    effective = get_global_ai_config(conn)
    configured = conn.execute(
        "SELECT provider_config_id, api_base_url, protocol, model, "
        "supports_image, api_key_ciphertext "
        "FROM ai_provider_configs "
        "WHERE is_active = TRUE AND test_status = 'passed' "
        "LIMIT 1"
    ).fetchone()
    provider_order = str(
        effective.get("provider_order")
        or DEFAULT_AI_CONFIG["provider_order"]
    )
    configured_provider_id = (
        str(configured["provider_config_id"])
        if configured
        else ""
    )
    configured_provider_signature_value = (
        configured_provider_signature(dict(configured))
        if configured
        else ""
    )
    runtime_settings = settings or Settings.from_env()
    if configured:
        primary_provider = f"configured:{configured_provider_id}"
        primary_model = str(configured["model"])
    else:
        primary_provider = next(
            (
                item.strip()
                for item in provider_order.split(",")
                if (
                    item.strip() == "local"
                    or (
                        item.strip() == "deepseek"
                        and bool(runtime_settings.deepseek_api_key)
                    )
                )
            ),
            "local",
        )
        if primary_provider == "deepseek":
            primary_model = runtime_settings.deepseek_model
        else:
            primary_model = "deterministic-local"

    runtime_package_artifact_id = str(
        runtime_package_version_id
        or scenario_version_id
        or "unversioned"
    )
    rule_policy_sources = frozen_rule_policy_sources(
        conn,
        room_id,
        scenario_version_id,
    )
    compiled_rule_policy = compile_rule_policy_sources(
        rule_policy_sources,
        compiler_version=RUNTIME_RULE_COMPILER_VERSION,
    )
    rule_policy_signature_value = compiled_rule_policy["source_signature"]
    compiled_rule_artifact_id_value = compiled_rule_artifact_id(
        runtime_package_artifact_id,
        compiled_rule_policy,
    )
    from .gateway import runtime_prompt_template_signature

    binding = {
        "binding_version": RUNTIME_BINDING_VERSION,
        "locked": True,
        "primary_provider": primary_provider,
        "primary_model": primary_model,
        "configured_provider_id": configured_provider_id,
        "configured_provider_signature": configured_provider_signature_value,
        "prompt_template_version": RUNTIME_PROMPT_TEMPLATE_VERSION,
        "prompt_template_signature": runtime_prompt_template_signature(
            RUNTIME_PROMPT_TEMPLATE_VERSION
        ),
        "rule_compiler_version": RUNTIME_RULE_COMPILER_VERSION,
        "runtime_package_artifact_id": runtime_package_artifact_id,
        "rule_policy_sources": rule_policy_sources,
        "rule_policy_signature": rule_policy_signature_value,
        "compiled_rule_policy": compiled_rule_policy,
        "compiled_rule_artifact_id": compiled_rule_artifact_id_value,
        "pinned_at": datetime.now(timezone.utc).isoformat(),
    }
    room_config = {
        **effective,
        "provider_order": provider_order,
        "runtime_binding": binding,
    }
    row = conn.execute(
        "SELECT state FROM host_states WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    state = _json_val(row["state"]) if row else {}
    state["ai_config"] = room_config
    state_json = json.dumps(state, ensure_ascii=False)
    conn.execute(
        "INSERT INTO host_states (room_id, state) VALUES (%s, %s) "
        "ON CONFLICT (room_id) DO UPDATE SET state = %s, updated_at = NOW()",
        (room_id, state_json, state_json),
    )
    return room_config
