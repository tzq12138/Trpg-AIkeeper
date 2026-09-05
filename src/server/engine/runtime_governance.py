"""Persistent governance for a room's session mode and runtime version set."""

from __future__ import annotations

import hashlib
import json
from typing import Any


VERSION_BUNDLE_FIELDS = (
    "runtime_package_version_id",
    "rule_version_id",
    "prompt_bundle_version",
    "scenario_package_hash",
    "ai_policy_version",
)


class RoomRuntimeContractError(ValueError):
    """A room cannot enter authoritative play without a frozen contract."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _canonical_hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def runtime_package_session_mode(conn, runtime_package_version_id: str | None) -> str | None:
    """Read the mode declared by a selected runtime package."""
    if not runtime_package_version_id:
        return None
    row = conn.execute(
        "SELECT runtime_package FROM runtime_package_versions "
        "WHERE runtime_package_version_id = %s",
        (runtime_package_version_id,),
    ).fetchone()
    package = _json_object(row.get("runtime_package") if row else None)
    policy = _json_object(package.get("runtime_policy"))
    mode = str(policy.get("session_mode") or "").strip()
    return mode or None


def runtime_package_supported_session_modes(
    conn,
    runtime_package_version_id: str | None,
) -> set[str]:
    """Return modes explicitly supported by the selected runtime package."""
    if not runtime_package_version_id:
        return set()
    row = conn.execute(
        "SELECT runtime_package FROM runtime_package_versions "
        "WHERE runtime_package_version_id = %s",
        (runtime_package_version_id,),
    ).fetchone()
    package = _json_object(row.get("runtime_package") if row else None)
    policy = _json_object(package.get("runtime_policy"))
    declared = policy.get("supported_session_modes")
    if isinstance(declared, list):
        values = {str(value).strip() for value in declared if str(value).strip()}
        if values:
            return values
    mode = str(policy.get("session_mode") or "").strip()
    return {mode} if mode else set()


def room_version_bundle(conn, room_id: str) -> dict[str, str]:
    """Build the deterministic version bundle from the room's bound artifacts."""
    room = conn.execute(
        "SELECT room_id, scenario_version_id, runtime_package_version_id "
        "FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if not room:
        raise RoomRuntimeContractError("room_not_found")
    package_id = str(room.get("runtime_package_version_id") or "")
    package = conn.execute(
        "SELECT input_checksum FROM runtime_package_versions "
        "WHERE runtime_package_version_id = %s",
        (package_id,),
    ).fetchone()
    rule = conn.execute(
        "SELECT rule_set_version_id FROM room_rule_bindings "
        "WHERE room_id = %s ORDER BY priority, rule_set_version_id LIMIT 1",
        (room_id,),
    ).fetchone()
    from ..ai.provider_health import current_runtime_binding

    binding = current_runtime_binding(conn, room_id)
    bundle = {
        "runtime_package_version_id": package_id,
        "rule_version_id": str(rule.get("rule_set_version_id") or "") if rule else "",
        "prompt_bundle_version": str(binding.get("prompt_template_version") or ""),
        "scenario_package_hash": str(package.get("input_checksum") or "") if package else "",
        "ai_policy_version": str(
            binding.get("rule_policy_signature")
            or binding.get("binding_version")
            or ""
        ),
    }
    missing = [field for field in VERSION_BUNDLE_FIELDS if not bundle[field]]
    if missing:
        raise RoomRuntimeContractError("version_bundle_incomplete")
    return bundle


def freeze_room_runtime_contract(
    conn,
    room_id: str,
    *,
    reason: str,
    action_id: str | None = None,
) -> dict[str, str]:
    """Freeze mode and all authoritative versions once for an AI-only room."""
    room = conn.execute(
        "SELECT room_id, runtime_package_version_id, session_mode, "
        "session_mode_frozen_at, version_bundle "
        "FROM rooms WHERE room_id = %s FOR UPDATE",
        (room_id,),
    ).fetchone()
    if not room:
        raise RoomRuntimeContractError("room_not_found")
    existing = _json_object(room.get("version_bundle"))
    if room.get("session_mode_frozen_at"):
        return existing

    session_mode = str(room.get("session_mode") or "").strip()
    if not session_mode:
        session_mode = runtime_package_session_mode(
            conn,
            room.get("runtime_package_version_id"),
        ) or ""
    if not session_mode:
        raise RoomRuntimeContractError("session_mode_missing")
    bundle = room_version_bundle(conn, room_id)
    bundle_hash = _canonical_hash(bundle)
    conn.execute(
        "UPDATE rooms SET session_mode = %s, session_mode_frozen_at = NOW(), "
        "session_mode_frozen_reason = %s, version_bundle = %s, "
        "version_bundle_hash = %s, version_bundle_locked_at = NOW() "
        "WHERE room_id = %s",
        (
            session_mode,
            reason,
            json.dumps(bundle, ensure_ascii=False),
            bundle_hash,
            room_id,
        ),
    )
    from ..events.event_log import EventLog

    EventLog(conn).log_event(
        room_id,
        "s2c_session_mode_frozen",
        "system",
        {
            "session_mode": session_mode,
            "reason": reason,
            "version_bundle": bundle,
            "version_bundle_hash": bundle_hash,
        },
        commit=False,
        action_id=action_id,
    )
    return bundle
