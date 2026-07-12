from __future__ import annotations

import json
from typing import Any

from ..models import ActionDraftDTO, DirectorPlanDTO


def build_director_context(conn, character: dict, draft: ActionDraftDTO) -> dict[str, Any]:
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s",
        (character["room_id"],),
    ).fetchone()
    room_dict = dict(room) if room else {"room_id": character["room_id"], "state_version": 0}
    actor = _actor_context(character)
    current_scene = _current_scene(conn, character["room_id"])
    runtime_package = _compact_runtime_package(
        _latest_runtime_package(conn, room_dict.get("scenario_version_id")),
        current_scene,
    )
    context_version = int(room_dict.get("state_version") or draft.base_state_version or 0)
    return {
        "room": _json_safe(room_dict),
        "context_version": context_version,
        "actor": actor,
        "actor_display_name": actor["display_name"],
        "character": actor,
        "declared_intent": draft.declared_intent,
        "intent_type": draft.intent_type,
        "local_analysis": draft.model_dump(mode="json"),
        "current_scene": current_scene,
        "runtime_package": runtime_package,
        "public_facts": _content_facts(conn, room_dict.get("scenario_version_id"), "public"),
        "hidden_facts": _content_facts(conn, room_dict.get("scenario_version_id"), "hidden"),
        "semantic_map": (runtime_package.get("semantic_map") or {}),
        "npc_state": (runtime_package.get("npc_states") or []),
        "rule_version": _rule_version(conn, character["room_id"]),
        "recent_events": _recent_events(conn, character["room_id"]),
        "inventory": _inventory(conn, character["character_id"]),
    }


def normalize_director_plan(raw: dict[str, Any], context: dict[str, Any]) -> DirectorPlanDTO:
    data = dict(raw or {})
    data.setdefault("context_version", context.get("context_version", 0))
    data.setdefault("actor_display_name", context.get("actor_display_name", ""))
    data.setdefault("declared_intent", context.get("declared_intent", ""))
    data.setdefault("interpreted_intent", context.get("declared_intent", ""))
    data.setdefault("intent_type", context.get("intent_type") or "dialogue")
    return DirectorPlanDTO(**data)


def apply_director_plan(
    conn,
    character: dict,
    draft: ActionDraftDTO,
    plan: DirectorPlanDTO,
    context: dict[str, Any],
) -> ActionDraftDTO:
    params = dict(draft.params)
    plan_payload = plan.model_dump(mode="json")
    plan_payload["state_patch_authority"] = "advisory_only"
    params["director_plan"] = plan_payload

    citations = [_sanitize_citation(item) for item in plan.citations]
    basis_refs = [_sanitize_citation(item) for item in plan.basis_refs]
    candidate_interpretations = _candidate_interpretations(plan)
    semantic_progression = _validate_semantic_progression(conn, character, plan, context)
    update: dict[str, Any] = {
        "context_version": plan.context_version,
        "intent_type": plan.intent_type or draft.intent_type,
        "understanding_summary": plan.interpreted_intent or draft.understanding_summary,
        "confidence": _clamp_confidence(plan.confidence),
        "citations": (citations or basis_refs)[:10],
        "semantic_progression": semantic_progression,
        "candidate_interpretations": candidate_interpretations,
        "npc_reactions": plan.npc_reactions[:10],
        "time_impact": plan.time_impact,
        "visibility": plan.visibility,
        "analysis_source": plan.analysis_source,
        "params": params,
    }

    if semantic_progression.get("validated"):
        progression_params = dict(params)
        progression_params.update({
            "fromNodeId": semantic_progression["fromNodeId"],
            "targetNodeId": semantic_progression["targetNodeId"],
        })
        update.update({
            "intent_type": "move",
            "params": progression_params,
            "movement_target": "下一场景",
            "confirmation_requirements": ["movement", "state_change"],
            "requires_confirmation": True,
            "adjudication_stage": "director_plan_validated",
            "resolution_route": "ai",
        })
    elif semantic_progression.get("rejected"):
        update.update({
            "adjudication_stage": "host_exception_required",
            "resolution_route": "host_exception",
            "confirmation_requirements": [],
            "requires_confirmation": False,
        })
    elif plan.requires_player_clarification or plan.confidence < 0.6:
        update.update({
            "status": "analyzing",
            "adjudication_stage": "player_clarification_required",
            "resolution_route": "host_exception",
            "confirmation_requirements": [],
            "requires_confirmation": False,
        })
    elif plan.requires_host_exception:
        update.update({
            "adjudication_stage": "host_exception_required",
            "resolution_route": "host_exception",
            "confirmation_requirements": ["host_exception"],
            "requires_confirmation": True,
        })
    else:
        update.update({
            "adjudication_stage": "director_plan_validated",
            "resolution_route": "ai",
        })
    return draft.model_copy(update=update)


def _actor_context(character: dict[str, Any]) -> dict[str, Any]:
    sheet = _json_object(character.get("xlsx_data"))
    display_name = (
        sheet.get("name")
        or sheet.get("investigator_name")
        or character.get("player_name")
        or character.get("character_name")
        or "Player"
    )
    return {
        "character_id": character["character_id"],
        "display_name": str(display_name),
        "player_name": character.get("player_name") or "",
        "sheet": sheet,
    }


def _latest_runtime_package(conn, scenario_version_id: str | None) -> dict[str, Any]:
    if not scenario_version_id:
        return {}
    row = conn.execute(
        """
        SELECT runtime_package
        FROM runtime_package_versions
        WHERE scenario_version_id = %s AND gate_status = 'ready'
        ORDER BY package_version_number DESC
        LIMIT 1
        """,
        (scenario_version_id,),
    ).fetchone()
    return _json_object(row.get("runtime_package") if row else None)


def _compact_runtime_package(
    runtime_package: dict[str, Any],
    current_scene: dict[str, Any],
) -> dict[str, Any]:
    if not runtime_package:
        return {}
    progression_rules = _json_object(runtime_package.get("semantic_progression_rules"))
    solo = _json_object(progression_rules.get("solo_adventure"))
    nodes = [item for item in (solo.get("nodes") or []) if isinstance(item, dict)]
    current_node_id = str(current_scene.get("node_id") or "")
    current_node = next(
        (item for item in nodes if str(item.get("node_id") or "") == current_node_id),
        None,
    )
    visible_node_ids = {current_node_id} if current_node_id else set()
    if current_node:
        visible_node_ids.update(str(item) for item in current_node.get("target_node_ids") or [])
    compact_nodes = [
        {
            "node_id": str(node.get("node_id") or ""),
            "title": str(node.get("title") or "")[:200],
            "text": str(node.get("text") or "")[:1200],
            "target_node_ids": [str(item) for item in (node.get("target_node_ids") or [])][:20],
            "citation": _object_dict(node.get("citation")),
        }
        for node in nodes
        if str(node.get("node_id") or "") in visible_node_ids
    ]
    evidence = [
        item
        for item in runtime_package.get("story_evidence_nodes") or []
        if isinstance(item, dict)
        and str(item.get("logical_key") or "") in visible_node_ids
    ]
    return {
        "package_kind": runtime_package.get("package_kind"),
        "schema_version": runtime_package.get("schema_version"),
        "scenario_version_id": runtime_package.get("scenario_version_id"),
        "scenario_title": runtime_package.get("scenario_title"),
        "world_book": _compact_value(runtime_package.get("world_book"), max_items=20),
        "semantic_scenes": _compact_value(runtime_package.get("semantic_scenes"), max_items=10),
        "npc_states": _compact_value(runtime_package.get("npc_states"), max_items=20),
        "clue_dependencies": _compact_value(runtime_package.get("clue_dependencies"), max_items=20),
        "rule_triggers": _compact_value(runtime_package.get("rule_triggers"), max_items=20),
        "semantic_map": _compact_value(runtime_package.get("semantic_map"), max_items=30),
        "style_pack": _compact_value(runtime_package.get("style_pack"), max_items=20),
        "story_evidence_nodes": _compact_value(evidence, max_items=20),
        "semantic_progression_rules": {
            "solo_adventure": {
                "root_node_id": solo.get("root_node_id"),
                "nodes": compact_nodes,
            }
        },
    }


def _compact_value(value: Any, *, max_items: int) -> Any:
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, list):
        return [_compact_value(item, max_items=max_items) for item in value[:max_items]]
    if isinstance(value, dict):
        return {
            str(key): _compact_value(item, max_items=max_items)
            for key, item in list(value.items())[:max_items]
        }
    return value


def _current_scene(conn, room_id: str) -> dict[str, Any]:
    try:
        from ..scenario.solo_runtime import SoloAdventureRuntime

        scene = SoloAdventureRuntime(conn).current(room_id)
        if scene:
            return scene
    except Exception:
        pass
    row = conn.execute(
        "SELECT current_scene, visited_scenes, scene_variables, version FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    return _json_safe(dict(row)) if row else {}


def _content_facts(conn, scenario_version_id: str | None, visibility: str) -> list[dict[str, Any]]:
    if not scenario_version_id:
        return []
    rows = conn.execute(
        """
        SELECT item_type, logical_key, title, citation
        FROM content_items
        WHERE scenario_version_id = %s AND visibility = %s
        ORDER BY ordinal, logical_key
        LIMIT 40
        """,
        (scenario_version_id, visibility),
    ).fetchall()
    return [_json_safe(dict(row)) for row in rows]


def _rule_version(conn, room_id: str) -> str:
    row = conn.execute(
        """
        SELECT rule_set_version_id
        FROM room_rule_bindings
        WHERE room_id = %s
        ORDER BY priority, rule_set_version_id
        LIMIT 1
        """,
        (room_id,),
    ).fetchone()
    return str(row["rule_set_version_id"]) if row else "unversioned"


def _recent_events(conn, room_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT event_type, audience, payload, sequence
        FROM events
        WHERE room_id = %s
        ORDER BY sequence DESC
        LIMIT 10
        """,
        (room_id,),
    ).fetchall()
    return [_json_safe(dict(row)) for row in rows]


def _inventory(conn, character_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM inventory WHERE character_id = %s ORDER BY acquired_at DESC LIMIT 50",
        (character_id,),
    ).fetchall()
    return [_json_safe(dict(row)) for row in rows]


def _candidate_interpretations(plan: DirectorPlanDTO) -> list[dict[str, Any]]:
    options = plan.clarification_options if isinstance(plan.clarification_options, list) else []
    return [item for item in options if isinstance(item, dict)][:3]


def _validate_semantic_progression(
    conn,
    character: dict[str, Any],
    plan: DirectorPlanDTO,
    context: dict[str, Any],
) -> dict[str, Any]:
    progression = _object_dict(plan.semantic_progression)
    target = str(progression.get("targetNodeId") or progression.get("target_node_id") or "")
    if not target:
        return {}
    citation = _sanitize_citation(progression.get("citation") or (plan.citations[0] if plan.citations else {}))
    current = context.get("current_scene") if isinstance(context.get("current_scene"), dict) else {}
    from_node = str(current.get("node_id") or "")
    runtime_package = context.get("runtime_package") if isinstance(context.get("runtime_package"), dict) else {}
    rules = runtime_package.get("semantic_progression_rules") if isinstance(runtime_package, dict) else {}
    solo = _json_object(rules.get("solo_adventure") if isinstance(rules, dict) else None)
    allowed = False
    matched_rule_citation: dict[str, Any] = {}
    for node in solo.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("node_id") or "") != from_node:
            continue
        if target in [str(item) for item in (node.get("target_node_ids") or [])]:
            allowed = True
            matched_rule_citation = _sanitize_citation(node.get("citation") or {})
            break
    if allowed and citation and _citation_matches(citation, [matched_rule_citation]):
        return {
            "targetNodeId": target,
            "fromNodeId": from_node,
            "citation": citation,
            "ruleCitation": matched_rule_citation,
            "validated": True,
        }
    return {
        "targetNodeId": target,
        "fromNodeId": from_node,
        "citation": citation,
        "validated": False,
        "rejected": True,
        "reason": "semantic_progression_evidence_required",
    }


def _citation_matches(citation: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
    if not citation:
        return False
    stable_fields = {
        "source",
        "source_part_id",
        "content_item_id",
        "page_number",
        "location",
    }
    effective = {
        key: value
        for key, value in citation.items()
        if key in stable_fields and value not in (None, "")
    }
    if not effective:
        return False
    for candidate in candidates:
        if all(candidate.get(key) == value for key, value in effective.items()):
            return True
    return False


def _sanitize_citation(value: dict[str, Any]) -> dict[str, Any]:
    value = _object_dict(value)
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if not str(key).lower().endswith("_path")
        and str(key).lower()
        not in {
            "absolute_path",
            "storage_path",
            "raw_text",
            "source_text",
            "full_text",
            "original_text",
            "text",
            "content",
        }
    }


def _object_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    return dict(value) if isinstance(value, dict) else {}


def _clamp_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


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


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
