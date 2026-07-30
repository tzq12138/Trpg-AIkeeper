"""Deterministic combat-round planning before resolution."""
from __future__ import annotations

import re
import hashlib
import json
from copy import deepcopy
from typing import Any


def build_combat_round_plan(
    *,
    turn_id: str,
    encounter_id: str,
    round_number: int,
    actions: list[dict[str, Any]],
    prepared_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    active_actions = [action for action in actions if action.get("intent_type") != "system_skip"]
    dexterity_order = sorted(
        active_actions,
        key=lambda action: (
            -_effective_dex(action),
            -_combat_skill(action),
            str(action.get("action_id") or ""),
        ),
    )
    ordered_actions = dexterity_order
    prepared_constraints = _prepared_rule_constraints(prepared_actions or [])
    steps = [
        {
            "global_order": index,
            "cluster_id": _cluster_id(action),
            "action_id": action["action_id"],
            "character_id": action["character_id"],
            "effective_dex": _effective_dex(action),
            "depends_on": _declared_dependencies(action, ordered_actions),
            "advisory_depends_on": [],
            "rule_binding": action.get("intent_type") or "combat_action",
            "visibility": _visibility(action),
            "segments": _declared_segments(action.get("declared_intent") or ""),
        }
        for index, action in enumerate(ordered_actions, start=1)
    ]
    return {
        "plan_version": "combat-round-v1",
        "turn_id": turn_id,
        "encounter_id": encounter_id,
        "round_number": round_number,
        "steps": steps,
        "presentation_clusters": _presentation_clusters(steps),
        "prepared_rule_actions": prepared_constraints,
        "observable_preparations": _observable_preparations(active_actions, prepared_constraints),
        "absent_policies": _absent_policies(actions),
    }


def build_combat_round_ai_context(
    plan: dict[str, Any],
    actions: list[dict[str, Any]],
    *,
    replan_after_resolution: bool = False,
) -> dict[str, Any]:
    """Build a provider-safe combat-planning prompt from public declarations only."""
    actions_by_id = {str(action.get("action_id")): action for action in actions}
    completed_public_facts = _completed_public_facts(plan)
    completed_action_ids = {
        fact["action_id"]
        for fact in completed_public_facts
    }
    public_actions = []
    for step in plan.get("steps", []):
        if step.get("visibility") != "public":
            continue
        action_id = str(step.get("action_id") or "")
        if replan_after_resolution and action_id in completed_action_ids:
            continue
        action = actions_by_id.get(action_id)
        if not isinstance(action, dict):
            continue
        public_actions.append(
            {
                "action_id": action_id,
                "global_order": step.get("global_order"),
                "rule_binding": step.get("rule_binding"),
                "declared_intent": str(action.get("declared_intent") or ""),
            }
        )
    return {
        "round_number": plan.get("round_number"),
        "encounter_id": plan.get("encounter_id"),
        "public_actions": public_actions,
        "public_prepared_actions": [
            {
                "actor_name": str(item.get("actor_name") or "一名调查员"),
                "trigger_kind": str(item.get("trigger_kind") or ""),
                "reaction_kind": str(item.get("reaction_kind") or ""),
            }
            for item in plan.get("prepared_rule_actions", [])
            if isinstance(item, dict)
        ],
        "completed_public_facts": completed_public_facts,
        "replan_after_resolution": replan_after_resolution,
        "system_prompt": (
            "You are a TRPG combat presentation planner. Return JSON only with clusters and dependencies. "
            "Use only supplied public action_id values. You may group public actions and write a short publicTitle. "
            "You must not add, remove, reorder, or alter actions, rules, dice, state, targets, or visibility. "
            "Dependencies are advisory only and must use supplied public action_id values. "
            "prepared_rule_actions are immutable rule constraints: do not trigger, remove, change, or invent them. "
            "completed_public_facts are immutable facts: do not restate hidden information or invent future outcomes."
        ),
    }


def apply_combat_round_suggestions(
    plan: dict[str, Any],
    suggestion: dict[str, Any] | None,
    *,
    eligible_action_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Apply provider output as non-authoritative public presentation metadata."""
    enriched = deepcopy(plan)
    if not isinstance(suggestion, dict):
        return enriched

    public_steps = [
        step
        for step in enriched.get("steps", [])
        if step.get("visibility") == "public"
        and (eligible_action_ids is None or str(step.get("action_id")) in eligible_action_ids)
    ]
    public_ids = {str(step.get("action_id")) for step in public_steps}
    steps_by_id = {str(step.get("action_id")): step for step in public_steps}

    for dependency in suggestion.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        action_id = str(dependency.get("actionId") or dependency.get("action_id") or "")
        step = steps_by_id.get(action_id)
        raw_dependencies = dependency.get("dependsOnActionIds", dependency.get("depends_on_action_ids", []))
        if not step or not isinstance(raw_dependencies, list):
            continue
        step["advisory_depends_on"] = [
            dependency_id
            for dependency_id in (str(value) for value in raw_dependencies)
            if dependency_id in public_ids and dependency_id != action_id
        ]

    suggested_clusters = []
    for cluster in suggestion.get("clusters", []):
        if not isinstance(cluster, dict):
            continue
        raw_action_ids = cluster.get("actionIds", cluster.get("action_ids", []))
        if not isinstance(raw_action_ids, list):
            continue
        action_ids = [str(action_id) for action_id in raw_action_ids if str(action_id) in public_ids]
        if not action_ids:
            continue
        title = _safe_public_title(cluster.get("publicTitle", cluster.get("public_title")))
        if not title:
            continue
        suggested_clusters.append(
            {
                "cluster_id": steps_by_id[action_ids[0]]["cluster_id"],
                "public_title": title,
                "action_ids": action_ids,
                "completed_public_facts": [],
            }
        )
    if suggested_clusters:
        covered_action_ids = {
            action_id
            for cluster in suggested_clusters
            for action_id in cluster["action_ids"]
        }
        remaining_clusters = []
        for cluster in enriched.get("presentation_clusters", []):
            remaining_ids = [
                action_id
                for action_id in cluster.get("action_ids", [])
                if action_id not in covered_action_ids
            ]
            if remaining_ids:
                remaining_clusters.append({**cluster, "action_ids": remaining_ids})
        enriched["presentation_clusters"] = suggested_clusters + remaining_clusters
    return enriched


def record_combat_round_public_fact(
    plan: dict[str, Any],
    *,
    action_id: str,
    narrative_text: str,
) -> dict[str, Any]:
    """Persist one verified, publicly visible result without changing the locked plan."""
    enriched = deepcopy(plan)
    text = narrative_text.strip()
    if not text:
        return enriched

    public_action_ids = {
        str(step.get("action_id"))
        for step in enriched.get("steps", [])
        if isinstance(step, dict) and step.get("visibility") == "public"
    }
    if action_id not in public_action_ids:
        return enriched

    existing_facts = enriched.get("resolved_public_facts")
    resolved_facts = [
        fact
        for fact in existing_facts
        if isinstance(fact, dict) and isinstance(fact.get("action_id"), str) and isinstance(fact.get("text"), str)
    ] if isinstance(existing_facts, list) else []
    if any(fact["action_id"] == action_id for fact in resolved_facts):
        return enriched

    resolved_facts.append({"action_id": action_id, "text": text[:2000]})
    enriched["resolved_public_facts"] = resolved_facts
    return enriched


def _completed_public_facts(plan: dict[str, Any]) -> list[dict[str, str]]:
    raw_facts = plan.get("resolved_public_facts")
    if not isinstance(raw_facts, list):
        return []
    public_action_ids = {
        str(step.get("action_id"))
        for step in plan.get("steps", [])
        if isinstance(step, dict) and step.get("visibility") == "public"
    }
    completed_facts = []
    for fact in raw_facts:
        if not isinstance(fact, dict):
            continue
        action_id = str(fact.get("action_id") or "")
        text = fact.get("text")
        if action_id not in public_action_ids or not isinstance(text, str) or not text.strip():
            continue
        completed_facts.append({"action_id": action_id, "text": text.strip()[:2000]})
    return completed_facts


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _visibility(action: dict[str, Any]) -> str:
    params = _action_params(action)
    if isinstance(params, dict) and params.get("visibility") == "private":
        return "private"
    return "public"


def _declared_dependencies(action: dict[str, Any], ordered_actions: list[dict[str, Any]]) -> list[str]:
    params = _action_params(action)
    raw_dependencies = params.get("depends_on_action_ids", []) if isinstance(params, dict) else []
    valid_ids = {str(item.get("action_id")) for item in ordered_actions}
    if not isinstance(raw_dependencies, list):
        return []
    return [str(action_id) for action_id in raw_dependencies if str(action_id) in valid_ids]


def dependency_resolution_order(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order execution prerequisites first without changing the public DEX plan."""
    action_ids = [str(action.get("action_id") or "") for action in actions]
    known_action_ids = set(action_ids)
    dependencies = {
        str(action.get("action_id") or ""): [
            dependency
            for dependency in _declared_dependencies(action, actions)
            if dependency in known_action_ids
        ]
        for action in actions
    }
    remaining = {str(action.get("action_id") or ""): action for action in actions}
    resolved: set[str] = set()
    ordered: list[dict[str, Any]] = []
    while remaining:
        next_action_id = next(
            (
                action_id
                for action_id in action_ids
                if action_id in remaining and set(dependencies[action_id]).issubset(resolved)
            ),
            None,
        )
        if next_action_id is None:
            return actions
        ordered.append(remaining.pop(next_action_id))
        resolved.add(next_action_id)
    return ordered


def _declared_segments(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[，,、；;]|(?:然后|再|并且|并)", text) if part.strip()]
    return parts[:1] or ["本轮行动"]


def _action_params(action: dict[str, Any]) -> dict[str, Any]:
    params = action.get("params")
    if isinstance(params, dict):
        return params
    if isinstance(params, str):
        try:
            parsed = json.loads(params)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _effective_dex(action: dict[str, Any]) -> int:
    dex = _as_int(action.get("dex"))
    params = _action_params(action)
    ready_firearm = bool(
        params.get("readyFirearm", params.get("ready_firearm", False))
    )
    weapon_type = str(
        params.get("weaponType", params.get("weapon_type", ""))
    ).lower()
    if ready_firearm and weapon_type in {"firearm", "枪械", "火器"}:
        return dex + 50
    return dex


def _combat_skill(action: dict[str, Any]) -> int:
    params = _action_params(action)
    return _as_int(
        action.get(
            "combat_skill",
            params.get("combatSkill", params.get("combat_skill", 0)),
        )
    )


def _cluster_id(action: dict[str, Any]) -> str:
    declared_intent = str(action.get("declared_intent") or "")
    normalized = re.sub(r"\s+", "", declared_intent) or str(action["action_id"])
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"conflict:{digest}"


def _presentation_clusters(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: dict[str, dict[str, Any]] = {}
    for step in steps:
        if step["visibility"] != "public":
            continue
        cluster = clusters.setdefault(
            step["cluster_id"],
            {
                "cluster_id": step["cluster_id"],
                "public_title": "当前冲突",
                "action_ids": [],
                "completed_public_facts": [],
            },
        )
        cluster["action_ids"].append(step["action_id"])
    return list(clusters.values())


def _prepared_rule_constraints(prepared_actions: list[dict[str, Any]]) -> list[dict[str, str]]:
    constraints: list[dict[str, str]] = []
    for prepared in prepared_actions:
        if not isinstance(prepared, dict):
            continue
        character_id = str(prepared.get("character_id") or "").strip()
        trigger_kind = str(prepared.get("trigger_kind") or "").strip()
        reaction_kind = str(prepared.get("reaction_kind") or "").strip()
        if not character_id or not trigger_kind or not reaction_kind:
            continue
        actor_name = str(prepared.get("player_name") or "一名调查员").strip()[:80]
        constraints.append(
            {
                "character_id": character_id,
                "actor_name": actor_name or "一名调查员",
                "trigger_kind": trigger_kind,
                "reaction_kind": reaction_kind,
            }
        )
    return sorted(
        constraints,
        key=lambda item: (item["actor_name"], item["character_id"], item["trigger_kind"]),
    )


def _observable_preparations(
    actions: list[dict[str, Any]],
    prepared_constraints: list[dict[str, str]],
) -> list[str]:
    observations = []
    visible_actions = [action for action in actions if _visibility(action) == "public"]
    for action in sorted(
        visible_actions,
        key=lambda item: (
            str(item.get("player_name") or item.get("character_id") or ""),
            str(item.get("action_id") or ""),
        ),
    ):
        actor_name = str(action.get("player_name") or "一名调查员").strip()[:80]
        intent_type = str(action.get("intent_type") or "")
        if intent_type == "combat_action":
            observation = f"{actor_name}举起武器，保持警戒。"
        elif intent_type == "move":
            observation = f"{actor_name}正调整位置，留意周围。"
        elif intent_type == "skill_check":
            observation = f"{actor_name}正仔细观察周围。"
        elif intent_type in {"use_item", "show_item"}:
            observation = f"{actor_name}正摆弄手中的物品。"
        else:
            observation = f"{actor_name}正留意局势变化。"
        observations.append(observation)
    prepared_observations = {
        "take_cover": "保持戒备，随时寻找掩护。",
        "withdraw": "留意撤离路线，保持戒备。",
        "protect_ally": "关注同伴动向，保持戒备。",
    }
    for prepared in prepared_constraints:
        actor_name = str(prepared.get("actor_name") or "一名调查员")[:80]
        suffix = prepared_observations.get(
            str(prepared.get("reaction_kind") or ""),
            "保持戒备，留意局势变化。",
        )
        observations.append(f"{actor_name} {suffix}")
    return observations[:8]


def _safe_public_title(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:80]


def _absent_policies(actions: list[dict[str, Any]]) -> list[dict[str, str]]:
    policies = []
    for action in actions:
        if action.get("intent_type") != "system_skip":
            continue
        declared = str(action.get("declared_intent") or "")
        policy = "maintain_existing" if "maintain_existing" in declared else "idle"
        policies.append({"character_id": str(action["character_id"]), "policy": policy})
    return policies
