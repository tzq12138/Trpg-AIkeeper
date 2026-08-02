from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_LEVELS = {"low", "medium", "high"}
_DECLARATION_SOURCES = {"compiled_rule", "engine_policy", "public_roll"}
_SAFE_ALTERNATIVES = {"fade_to_black", "replace_scene", "no_effect", "safe_abort"}
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def normalize_risk_contract(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    categories_by_name: dict[str, str] = {}
    for item in raw.get("categories") or []:
        if not isinstance(item, dict):
            continue
        category = _tag(item.get("category"))
        level = str(item.get("max_level") or "").strip().lower()
        if category and level in _LEVELS:
            categories_by_name[category] = level

    excluded_tags = sorted({
        tag
        for item in raw.get("excluded_tags") or []
        if (tag := _tag(item))
    })
    default_harm_raw = raw.get("default_harm")
    if not isinstance(default_harm_raw, dict):
        default_harm_raw = {}
    default_harm = {
        scope: level
        for scope in ("npc", "scene")
        if (level := str(default_harm_raw.get(scope) or "").strip().lower())
        in _LEVELS
    }
    irreversible_controls = sorted({
        control
        for item in raw.get("irreversible_controls") or []
        if (control := _tag(item))
    })
    hidden_raw = raw.get("hidden_checks")
    if not isinstance(hidden_raw, dict):
        hidden_raw = {}
    declaration_source = str(
        hidden_raw.get("declaration_source") or "compiled_rule"
    ).strip()
    if declaration_source not in _DECLARATION_SOURCES:
        declaration_source = "compiled_rule"
    hidden_checks = {
        "allowed": hidden_raw.get("allowed") is True,
        "declaration_source": declaration_source,
    }
    alternatives_raw = raw.get("safe_alternatives")
    if not isinstance(alternatives_raw, dict):
        alternatives_raw = {}
    safe_alternatives = {
        tag: alternative
        for key, raw_alternative in alternatives_raw.items()
        if (tag := _tag(key)) in excluded_tags
        and (alternative := str(raw_alternative or "").strip()) in _SAFE_ALTERNATIVES
    }
    safe_abort_rule = _tag(raw.get("safe_abort_rule"))

    normalized = {
        "schema_version": "risk_contract.v1",
        "categories": [
            {"category": category, "max_level": categories_by_name[category]}
            for category in sorted(categories_by_name)
        ],
        "excluded_tags": excluded_tags,
        "default_harm": default_harm,
        "irreversible_controls": irreversible_controls,
        "hidden_checks": hidden_checks,
        "safe_alternatives": dict(sorted(safe_alternatives.items())),
        "safe_abort_rule": safe_abort_rule,
    }
    normalized["contract_hash"] = _contract_hash(normalized)
    return normalized


def public_risk_contract(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value.get("contract_hash"):
        return None
    normalized = normalize_risk_contract(value)
    return {
        "schema_version": normalized["schema_version"],
        "contract_hash": normalized["contract_hash"],
        "categories": normalized["categories"],
        "excluded_tags": normalized["excluded_tags"],
        "default_harm": normalized["default_harm"],
        "irreversible_controls": normalized["irreversible_controls"],
        "hidden_checks_allowed": normalized["hidden_checks"]["allowed"],
        "safe_alternative_tags": sorted(normalized["safe_alternatives"]),
        "safe_abort_available": bool(normalized["safe_abort_rule"]),
    }


def runtime_package_risk_contract(
    conn,
    runtime_package_version_id: str | None,
    scenario_version_id: str | None,
) -> dict[str, Any] | None:
    if not runtime_package_version_id or not scenario_version_id:
        return None
    row = conn.execute(
        "SELECT runtime_package FROM runtime_package_versions "
        "WHERE runtime_package_version_id = %s AND scenario_version_id = %s "
        "AND gate_status = 'ready'",
        (runtime_package_version_id, scenario_version_id),
    ).fetchone()
    package = _json_object(row.get("runtime_package") if row else None)
    if "risk_contract" not in package:
        return None
    return normalize_risk_contract(package.get("risk_contract"))


def current_risk_contract_confirmation(conn, character: dict[str, Any]) -> dict[str, Any] | None:
    room = conn.execute(
        "SELECT status, risk_contract_version, risk_contract_hash "
        "FROM rooms WHERE room_id = %s",
        (character["room_id"],),
    ).fetchone()
    if not room or room.get("status") != "active" or not room.get("risk_contract_hash"):
        return None
    confirmed = conn.execute(
        "SELECT 1 FROM session_zero_confirmations "
        "WHERE room_id = %s AND character_id = %s AND step = 'safety' "
        "AND contract_version = %s AND contract_hash = %s",
        (
            character["room_id"],
            character["character_id"],
            room["risk_contract_version"],
            room["risk_contract_hash"],
        ),
    ).fetchone()
    if confirmed:
        return None
    return {
        "code": "risk_contract_confirmation_required",
        "contract_version": room["risk_contract_version"],
        "contract_hash": room["risk_contract_hash"],
    }


def excluded_risk_boundary(conn, room_id: str, params: Any) -> dict[str, Any] | None:
    if not isinstance(params, dict):
        return None
    supplied_tags = params.get("riskTags", params.get("risk_tags"))
    if not isinstance(supplied_tags, list):
        return None
    requested_tags = sorted({tag for item in supplied_tags if (tag := _tag(item))})
    if not requested_tags:
        return None
    row = conn.execute(
        "SELECT risk_contract FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    contract = _json_object(row.get("risk_contract") if row else None)
    excluded = set(contract.get("excluded_tags") or [])
    blocked = [tag for tag in requested_tags if tag in excluded]
    if not blocked:
        return None
    alternatives = contract.get("safe_alternatives")
    if not isinstance(alternatives, dict):
        alternatives = {}
    return {
        "code": "risk_contract_boundary",
        "risk_tags": blocked,
        "safe_alternative": alternatives.get(blocked[0], "no_effect"),
    }


def _contract_hash(value: dict[str, Any]) -> str:
    canonical = {
        key: item
        for key, item in value.items()
        if key != "contract_hash"
    }
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tag(value: Any) -> str:
    tag = str(value or "").strip().lower()
    return tag if _TAG_RE.fullmatch(tag) else ""


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}
