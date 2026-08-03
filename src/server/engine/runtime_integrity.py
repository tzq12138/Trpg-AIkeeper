"""Deterministic runtime checkpoint hashing, validation, and recovery tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import date, datetime
from typing import Any


CHECKPOINT_SCHEMA_VERSION = 2

_PUBLIC_INTEGRITY_REASONS = {
    "provider_unavailable",
    "checkpoint_hash_mismatch",
    "checkpoint_signature_mismatch",
    "checkpoint_payload_hash_mismatch",
    "checkpoint_schema_unsupported",
    "checkpoint_apply_failed",
    "risk_contract_changed",
    "room_run_binding_changed",
    "state_service_unavailable",
    "state_persistence_failed",
}


def public_runtime_integrity(room: dict[str, Any] | None) -> dict[str, Any]:
    """Project only stable, player-safe runtime pause state."""
    status = str((room or {}).get("integrity_status") or "healthy")
    if status not in {"healthy", "read_only_recovery", "paused_provider"}:
        status = "read_only_recovery"
    raw_reason = str((room or {}).get("integrity_reason") or "")
    reason = raw_reason if raw_reason in _PUBLIC_INTEGRITY_REASONS else (
        "runtime_integrity_failed" if status != "healthy" else ""
    )
    allowed_actions = (
        ["read", "mechanical_action"]
        if status == "healthy"
        else ["read", "export", "wait_for_recovery"]
    )
    return {
        "status": status,
        "reasonCode": reason or None,
        "allowedActions": allowed_actions,
    }


class CheckpointIntegrityError(ValueError):
    """Raised when a checkpoint cannot be proven safe to inspect or restore."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


ROOM_SNAPSHOT_COLUMNS = (
    "room_id",
    "scenario_id",
    "scenario_version_id",
    "runtime_package_version_id",
    "status",
    "spoiler_level",
    "state_version",
    "player_experience_version",
    "action_pacing_preset",
    "action_timing",
    "draft_analysis_enabled",
    "speech_routing",
    "host_autonomy_policy",
    "risk_contract_version",
    "risk_contract_hash",
    "started_at",
)


SNAPSHOT_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "characters": ("character_id", "room_id", "is_ready", "status"),
    "character_runtime_state": (
        "character_id", "room_id", "hp", "hp_max", "san", "san_max",
        "mp", "mp_max", "luck", "status_tags", "temp_modifiers",
        "visibility", "version", "updated_at",
    ),
    "room_scene_state": (
        "room_id", "current_scene", "visited_scenes", "triggered_triggers",
        "public_facts", "scene_variables", "current_bgm", "current_asset_url",
        "version", "updated_at",
    ),
    "clues": (
        "clue_id", "room_id", "character_id", "text", "source", "is_private",
        "discovered_at", "version",
    ),
    "clue_shares": (
        "share_id", "clue_id", "shared_by", "shared_at", "public_version", "room_id",
    ),
    "inventory": (
        "id", "character_id", "room_id", "name", "description", "quantity",
        "is_secret", "source", "acquired_at", "version",
    ),
    "objectives": (
        "objective_id", "room_id", "character_id", "text", "type", "status", "assigned_at",
    ),
    "room_map_state": (
        "room_id", "map_id", "explored_nodes", "hidden_nodes", "state_version",
        "updated_at", "fog_regions", "token_visibility",
    ),
    "character_map_positions": ("character_id", "room_id", "node_id", "updated_at"),
    "encounters": (
        "encounter_id", "room_id", "type", "status", "current_round", "summary",
        "created_at", "resolved_at", "version",
    ),
    "encounter_participants": (
        "encounter_id", "character_id", "side", "hp", "hp_max", "san", "san_max",
        "dex", "mov", "current_position", "distance_band", "status_tags",
        "acted_this_round", "weapon_name", "damage_expression", "main_skill", "notes",
        "version", "display_name", "public_visibility", "public_label",
        "last_observed_position",
    ),
    "encounter_pending_reactions": (
        "reaction_id", "room_id", "encounter_id", "source_action_id", "character_id",
        "attacker_id", "round_number", "attack_index", "attack_name",
        "damage_expression", "status", "choice", "result", "created_at", "resolved_at",
    ),
    "room_turns": (
        "turn_id", "room_id", "turn_index", "status", "mode", "encounter_id",
        "combat_plan", "combat_summary", "base_state_version", "started_at",
        "resolved_at", "summary",
    ),
}


SNAPSHOT_INSERT_ORDER = (
    "characters",
    "character_runtime_state",
    "room_scene_state",
    "clues",
    "clue_shares",
    "inventory",
    "objectives",
    "room_map_state",
    "character_map_positions",
    "encounters",
    "encounter_participants",
    "encounter_pending_reactions",
    "room_turns",
)


SNAPSHOT_DELETE_ORDER = (
    "encounter_pending_reactions",
    "encounter_participants",
    "room_turns",
    "clue_shares",
    "character_map_positions",
    "inventory",
    "objectives",
    "clues",
    "room_scene_state",
    "character_runtime_state",
    "room_map_state",
    "encounters",
)


_SENSITIVE_KEYS = {
    "account_id",
    "owner_account_id",
    "owner_token",
    "player_token",
    "access_token",
    "refresh_token",
    "password_hash",
    "api_key",
    "api_key_ciphertext",
    "raw_safety_text",
    "raw_safety_boundary_text",
    "raw_security_boundary_text",
    "safety_boundary_text",
    "safety_boundaries",
    "raw_text_ciphertext",
    "original_text",
    "unrevealed_secret",
    "unrevealed_secrets",
    "secret_text",
    "keeper_notes",
    "gm_notes",
}


def _snake_key(value: Any) -> str:
    text = str(value or "")
    result = []
    for char in text:
        if char.isupper() and result:
            result.append("_")
        result.append(char.lower())
    return "".join(result).replace("-", "_")


def sanitize_checkpoint_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_checkpoint_value(item)
            for key, item in value.items()
            if _snake_key(key) not in _SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_checkpoint_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


def checkpoint_snapshot_hash(snapshot: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()


def validate_runtime_snapshot(snapshot: Any, room_id: str) -> dict[str, Any]:
    violations: list[str] = []
    counts: dict[str, int] = {}
    if not isinstance(snapshot, dict):
        return {"valid": False, "violations": ["snapshot_not_object"], "counts": {}}

    boundary = snapshot.get("_checkpoint")
    if not isinstance(boundary, dict):
        violations.append("checkpoint_boundary_missing")
    elif int(boundary.get("schemaVersion") or 0) != CHECKPOINT_SCHEMA_VERSION:
        violations.append("checkpoint_schema_unsupported")

    room = snapshot.get("room")
    if not isinstance(room, dict) or str(room.get("room_id") or "") != room_id:
        violations.append("room_identity_mismatch")
    elif isinstance(boundary, dict):
        try:
            if int(room.get("state_version") or 0) != int(boundary.get("stateVersion") or 0):
                violations.append("room_state_version_mismatch")
        except (TypeError, ValueError):
            violations.append("room_state_version_invalid")

    row_sets: dict[str, list[dict[str, Any]]] = {}
    for table, columns in SNAPSHOT_TABLE_COLUMNS.items():
        rows = snapshot.get(table, [])
        if not isinstance(rows, list):
            violations.append(f"{table}_not_list")
            rows = []
        valid_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                violations.append(f"{table}_row_not_object")
                continue
            unknown = set(row) - set(columns)
            if unknown:
                violations.append(f"{table}_unknown_columns")
            if "room_id" in columns and str(row.get("room_id") or "") != room_id:
                violations.append(f"{table}_room_mismatch")
            valid_rows.append(row)
        row_sets[table] = valid_rows
        counts[table] = len(valid_rows)

    character_ids = {
        str(row.get("character_id") or "")
        for row in row_sets["characters"]
        if row.get("character_id")
    }
    for table in (
        "character_runtime_state",
        "clues",
        "inventory",
        "character_map_positions",
    ):
        for row in row_sets[table]:
            if str(row.get("character_id") or "") not in character_ids:
                violations.append(f"{table}_character_missing")
    for row in row_sets["objectives"]:
        character_id = str(row.get("character_id") or "")
        if character_id and character_id not in character_ids:
            violations.append("objectives_character_missing")

    clue_ids = {str(row.get("clue_id") or "") for row in row_sets["clues"]}
    for row in row_sets["clue_shares"]:
        if str(row.get("clue_id") or "") not in clue_ids:
            violations.append("clue_share_clue_missing")

    encounter_ids = {
        str(row.get("encounter_id") or "")
        for row in row_sets["encounters"]
        if row.get("encounter_id")
    }
    for table in ("encounter_participants", "encounter_pending_reactions"):
        for row in row_sets[table]:
            if str(row.get("encounter_id") or "") not in encounter_ids:
                violations.append(f"{table}_encounter_missing")
    for row in row_sets["room_turns"]:
        encounter_id = str(row.get("encounter_id") or "")
        if encounter_id and encounter_id not in encounter_ids:
            violations.append("room_turn_encounter_missing")

    violations = sorted(set(violations))
    return {"valid": not violations, "violations": violations, "counts": counts}


def checkpoint_diff(current: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    sections = sorted(set(current) | set(target))
    changed = [
        section
        for section in sections
        if checkpoint_snapshot_hash(current.get(section))
        != checkpoint_snapshot_hash(target.get(section))
    ]
    return {
        "changedSections": changed,
        "currentHash": checkpoint_snapshot_hash(current),
        "targetHash": checkpoint_snapshot_hash(target),
    }


def recovery_proposal_hash(proposal: dict[str, Any], reason: str) -> str:
    return checkpoint_snapshot_hash({"proposal": proposal, "reason": reason})


def _recovery_secret() -> bytes:
    value = (
        os.getenv("RUNTIME_INTEGRITY_SECRET", "").strip()
        or os.getenv("JWT_SECRET", "").strip()
        or "aikeeper-change-me-in-production"
    )
    return value.encode("utf-8")


def issue_recovery_dry_run_token(claims: dict[str, Any], ttl_seconds: int = 600) -> str:
    payload = {**claims, "expiresAt": int(time.time()) + max(1, ttl_seconds)}
    encoded = base64.urlsafe_b64encode(canonical_json_bytes(payload)).decode().rstrip("=")
    signature = hmac.new(_recovery_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{encoded}.{encoded_signature}"


def verify_recovery_dry_run_token(token: str, expected: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded, encoded_signature = token.split(".", 1)
        signature = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        expected_signature = hmac.new(
            _recovery_secret(), encoded.encode("ascii"), hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("signature")
        payload_bytes = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(payload_bytes)
    except Exception as exc:
        raise CheckpointIntegrityError("dry_run_token_invalid") from exc
    if int(payload.get("expiresAt") or 0) < int(time.time()):
        raise CheckpointIntegrityError("dry_run_token_expired")
    for key, value in expected.items():
        if payload.get(key) != value:
            raise CheckpointIntegrityError("dry_run_token_mismatch")
    return payload
