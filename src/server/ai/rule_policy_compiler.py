from __future__ import annotations

import hashlib
import json
from typing import Any


RULE_POLICY_COMPILER_VERSION = "module-compiler-v1"


def rule_policy_sources_signature(sources: list[dict[str, Any]]) -> str:
    return _sha256_json(sources)


def compile_rule_policy_sources(
    sources: list[dict[str, Any]],
    *,
    compiler_version: str = RULE_POLICY_COMPILER_VERSION,
) -> dict[str, Any]:
    if compiler_version != RULE_POLICY_COMPILER_VERSION:
        raise ValueError(f"unsupported rule policy compiler: {compiler_version}")
    merged: dict[str, Any] = {}
    compiled_sources = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        policy = _compile_v1_metadata(source.get("metadata"))
        if not policy:
            continue
        merged.update(policy)
        compiled_sources.append({
            "scope": str(source.get("scope") or "room"),
            "rule_set_version_id": str(
                source.get("rule_set_version_id") or ""
            ),
        })
    return {
        "compiler_version": compiler_version,
        "source_signature": rule_policy_sources_signature(sources),
        "policy": merged,
        "sources": compiled_sources,
    }


def compiled_rule_artifact_id(
    runtime_package_artifact_id: str,
    compiled_rule_policy: dict[str, Any],
) -> str:
    return _sha256_json({
        "runtime_package_artifact_id": runtime_package_artifact_id,
        "compiled_rule_policy": compiled_rule_policy,
    })


def validate_compiled_rule_artifact(
    *,
    runtime_package_artifact_id: str,
    sources: list[dict[str, Any]],
    compiled_rule_policy: dict[str, Any],
    artifact_id: str,
) -> bool:
    return (
        compiled_rule_policy.get("compiler_version")
        == RULE_POLICY_COMPILER_VERSION
        and compiled_rule_policy.get("source_signature")
        == rule_policy_sources_signature(sources)
        and artifact_id
        == compiled_rule_artifact_id(
            runtime_package_artifact_id,
            compiled_rule_policy,
        )
    )


def _compile_v1_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if not isinstance(value, dict):
        return {}
    raw = value.get("deterministic_policy")
    if not isinstance(raw, dict):
        return {}
    policy: dict[str, Any] = {}
    if "max_bonus_dice" in raw:
        try:
            policy["max_bonus_dice"] = max(
                0,
                min(2, int(raw["max_bonus_dice"])),
            )
        except (TypeError, ValueError):
            pass
    for key in ("allow_luck_spend", "allow_pushed_roll"):
        if key in raw and isinstance(raw[key], bool):
            policy[key] = raw[key]
    if "low_skill_fumble_min" in raw:
        try:
            policy["low_skill_fumble_min"] = max(
                96,
                min(100, int(raw["low_skill_fumble_min"])),
            )
        except (TypeError, ValueError):
            pass
    return policy


def _sha256_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
