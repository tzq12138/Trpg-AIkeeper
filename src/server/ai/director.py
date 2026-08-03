from __future__ import annotations

import json
import re
from typing import Any

from ..events.event_log import EventLog
from ..engine.runtime_integrity import sanitize_checkpoint_value
from ..models import ActionDraftDTO, DirectorPlanDTO, RedactedCitation, redact_citation
from ..player.action_service import (
    _sanitize_composite_steps,
    _sanitize_intent_contract,
    redact_backstage_references,
)


_CONDITIONAL_SOLO_BRANCH_RE = re.compile(
    r"如果你的[“\"']?(?P<attribute>体型|力量|体质|敏捷|外貌|智力|意志|教育|幸运|"
    r"STR|CON|SIZ|DEX|APP|INT|POW|EDU|LUCK)[”\"']?\s*"
    r"(?P<operator>是|为|等于|高于|低于|不低于|不高于|至少|至多)\s*"
    r"(?P<value>\d+)\s*[，,。；;]?\s*转到\s*(?P<target>\d+)",
    re.IGNORECASE,
)
_ATTRIBUTE_NAME_PATTERN = (
    r"体型|力量|体质|敏捷|外貌|智力|意志|教育|幸运|"
    r"STR|CON|SIZ|DEX|APP|INT|POW|EDU|LUCK"
)
_COMPARATIVE_SOLO_CONTEXT_RE = re.compile(
    rf"比较你的[“\"']?(?P<first>{_ATTRIBUTE_NAME_PATTERN})[”\"']?\s*(?:和|与)\s*"
    rf"[“\"']?(?P<second>{_ATTRIBUTE_NAME_PATTERN})[”\"']?",
    re.IGNORECASE,
)
_COMPARATIVE_SOLO_BRANCH_RE = re.compile(
    rf"如果你的[“\"']?(?P<attribute>{_ATTRIBUTE_NAME_PATTERN})[”\"']?\s*(?:较高|较大)"
    r"\s*[，,。；;]?\s*转到\s*(?P<target>\d+)",
    re.IGNORECASE,
)

_SOLO_ATTRIBUTE_KEYS = {
    "体型": ("siz", "size", "体型"),
    "力量": ("str", "力量"),
    "体质": ("con", "体质"),
    "敏捷": ("dex", "敏捷"),
    "外貌": ("app", "外貌"),
    "智力": ("int", "智力"),
    "意志": ("pow", "意志"),
    "教育": ("edu", "教育"),
    "幸运": ("luck", "幸运"),
    "str": ("str", "力量"),
    "con": ("con", "体质"),
    "siz": ("siz", "size", "体型"),
    "dex": ("dex", "敏捷"),
    "app": ("app", "外貌"),
    "int": ("int", "智力"),
    "pow": ("pow", "意志"),
    "edu": ("edu", "教育"),
    "luck": ("luck", "幸运"),
}


def build_director_context(conn, character: dict, draft: ActionDraftDTO) -> dict[str, Any]:
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s",
        (character["room_id"],),
    ).fetchone()
    room_dict = dict(room) if room else {"room_id": character["room_id"], "state_version": 0}
    actor = _actor_context(character)
    current_scene = _current_scene(conn, character["room_id"])
    runtime_package = _compact_runtime_package(
        _latest_runtime_package(
            conn,
            room_dict.get("scenario_version_id"),
            room_dict.get("runtime_package_version_id"),
        ),
        current_scene,
    )
    relevant_content_keys = _relevant_content_keys(current_scene, runtime_package)
    context_version = int(room_dict.get("state_version") or draft.base_state_version or 0)
    authorized_facts = _authorized_knowledge_facts(
        conn,
        character["room_id"],
        character["character_id"],
        current_scene,
    )
    context = {
        "room": _director_room_context(room_dict),
        "context_version": context_version,
        "actor": actor,
        "actor_display_name": actor["display_name"],
        "character": actor,
        "declared_intent": draft.declared_intent,
        "intent_type": draft.intent_type,
        "local_analysis": draft.model_dump(mode="json"),
        "current_scene": current_scene,
        "runtime_package": runtime_package,
        "public_facts": [
            fact for fact in authorized_facts if fact.get("audience") == "party"
        ],
        "private_facts": [
            fact for fact in authorized_facts if fact.get("audience") == "player"
        ],
        "hidden_facts": _content_facts(
            conn,
            room_dict.get("scenario_version_id"),
            "hidden",
            relevant_content_keys,
        ),
        "semantic_map": (runtime_package.get("semantic_map") or {}),
        "npc_state": (runtime_package.get("npc_states") or []),
        "rule_version": _rule_version(conn, character["room_id"]),
        "recent_events": _recent_events(
            conn,
            character["room_id"],
            character["character_id"],
        ),
        "inventory": _inventory(conn, character["character_id"]),
        "player_hypotheses": _player_hypotheses(
            conn,
            character["room_id"],
            character["character_id"],
            draft.declared_intent,
        ),
    }
    return sanitize_checkpoint_value(context)


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

    citations = [
        RedactedCitation(**redact_citation(_sanitize_citation(item)))
        for item in plan.citations
    ]
    basis_refs = [
        RedactedCitation(**redact_citation(_sanitize_citation(item)))
        for item in plan.basis_refs
    ]
    candidate_interpretations = _candidate_interpretations(plan)
    semantic_progression = _validate_semantic_progression(conn, character, plan, context)
    composite_steps = _sanitize_composite_steps(
        [step.model_dump(mode="json") for step in plan.action_steps],
        draft,
    )
    intent_contract = _sanitize_intent_contract(
        plan.intent_contract.model_dump(mode="json"),
        draft.intent_contract,
    )
    update: dict[str, Any] = {
        "context_version": plan.context_version,
        "intent_type": plan.intent_type or draft.intent_type,
        "understanding_summary": redact_backstage_references(
            plan.interpreted_intent or draft.understanding_summary
        ),
        "confidence": _clamp_confidence(plan.confidence),
        "citations": (citations or basis_refs)[:10],
        "semantic_progression": semantic_progression,
        "candidate_interpretations": candidate_interpretations,
        "npc_reactions": plan.npc_reactions[:10],
        "time_impact": plan.time_impact,
        "visibility": plan.visibility,
        "analysis_source": plan.analysis_source,
        "params": params,
        "composite_steps": composite_steps,
        "intent_contract": intent_contract,
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
    elif (
        plan.requires_player_clarification and candidate_interpretations
    ) or plan.confidence < 0.6:
        update.update({
            "status": "analyzing",
            "adjudication_stage": "player_clarification_required",
            "resolution_route": "host_exception",
            "confirmation_requirements": [],
            "requires_confirmation": False,
        })
    elif plan.requires_host_exception and str(plan.exception_reason or "").strip():
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
    if composite_steps and update.get("resolution_route") == "ai":
        update.update({
            "requires_confirmation": True,
            "confirmation_requirements": ["stateful_action"],
        })
    if draft.risk == "high" and intent_contract.ambiguities:
        update.update({
            "status": "analyzing",
            "adjudication_stage": "player_clarification_required",
            "resolution_route": "host_exception",
            "confirmation_requirements": [],
            "requires_confirmation": False,
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


def _director_room_context(room: dict[str, Any]) -> dict[str, Any]:
    return {
        "room_id": str(room.get("room_id") or ""),
        "scenario_id": str(room.get("scenario_id") or ""),
        "scenario_version_id": str(room.get("scenario_version_id") or ""),
        "runtime_package_version_id": str(room.get("runtime_package_version_id") or ""),
        "status": str(room.get("status") or ""),
        "state_version": int(room.get("state_version") or 0),
    }


def _latest_runtime_package(
    conn,
    scenario_version_id: str | None,
    runtime_package_version_id: str | None = None,
) -> dict[str, Any]:
    if not scenario_version_id:
        return {}
    if runtime_package_version_id:
        row = conn.execute(
            """
            SELECT runtime_package
            FROM runtime_package_versions
            WHERE runtime_package_version_id = %s
              AND scenario_version_id = %s
              AND gate_status = 'ready'
            """,
            (runtime_package_version_id, scenario_version_id),
        ).fetchone()
    else:
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
    generic_edges = [
        {
            "from_scene_id": str(edge.get("from_scene_id") or ""),
            "to_scene_id": str(edge.get("to_scene_id") or ""),
            "relation_type": str(edge.get("relation_type") or ""),
            "conditions": _compact_value(edge.get("conditions"), max_items=20),
            "citation": _sanitize_citation(edge.get("citation") or {}),
        }
        for edge in progression_rules.get("edges") or []
        if isinstance(edge, dict)
        and edge.get("relation_type") == "transitions_to"
        and str(edge.get("from_scene_id") or "") == str(current_scene.get("current_scene") or "")
    ][:20]
    evidence = [
        item
        for item in runtime_package.get("story_evidence_nodes") or []
        if isinstance(item, dict)
        and str(item.get("logical_key") or "") in visible_node_ids
    ]
    current_keys = {
        str(current_scene.get(key) or "").strip()
        for key in ("current_scene", "scene_id", "node_id")
    }
    current_keys.update(visible_node_ids)
    current_keys.discard("")
    visible_scene_keys = set(current_keys)
    visible_scene_keys.update(
        str(edge.get("to_scene_id") or "").strip()
        for edge in generic_edges
    )
    visible_scene_keys.update(
        str(node.get("target_scene_id") or node.get("targetSceneId") or "").strip()
        for node in progression_rules.get("recovery_nodes") or []
        if isinstance(node, dict)
        and str(current_scene.get("current_scene") or "")
        in {
            str(value)
            for value in (node.get("from_scene_ids") or node.get("fromSceneIds") or [])
        }
    )
    visible_scene_keys.discard("")

    def matching_items(
        values: Any,
        allowed_keys: set[str],
    ) -> list[dict[str, Any]]:
        if not isinstance(values, list):
            return []
        result = []
        for item in values:
            if not isinstance(item, dict):
                continue
            payload = _json_object(item.get("payload"))
            identifiers = {
                str(item.get(key) or "").strip()
                for key in (
                    "logical_key", "scene_id", "node_id", "location_id",
                    "current_scene",
                )
            }
            identifiers.update({
                str(payload.get(key) or "").strip()
                for key in ("scene_id", "node_id", "location_id")
            })
            identifiers.discard("")
            if allowed_keys.intersection(identifiers):
                result.append(item)
        return result

    def scene_identity_items(values: Any) -> list[dict[str, Any]]:
        result = []
        for item in matching_items(values, visible_scene_keys):
            projected = {
                key: value
                for key in (
                    "id", "logical_key", "scene_id", "node_id", "location_id",
                    "name", "title",
                )
                if (value := item.get(key)) is not None
                and isinstance(value, (str, int, float, bool))
            }
            payload = _json_object(item.get("payload"))
            projected_payload = {
                key: value
                for key in (
                    "id", "scene_id", "node_id", "location_id", "name", "title",
                )
                if (value := payload.get(key)) is not None
                and isinstance(value, (str, int, float, bool))
            }
            if projected_payload:
                projected["payload"] = projected_payload
            if projected:
                result.append(projected)
        return result

    world_book = _json_object(runtime_package.get("world_book"))
    public_world_book = {}
    synopsis = world_book.get("synopsis")
    if isinstance(synopsis, str) and synopsis.strip():
        public_world_book["synopsis"] = synopsis[:1200]
    return {
        "package_kind": runtime_package.get("package_kind"),
        "schema_version": runtime_package.get("schema_version"),
        "scenario_version_id": runtime_package.get("scenario_version_id"),
        "scenario_title": runtime_package.get("scenario_title"),
        "world_book": public_world_book,
        "semantic_scenes": _compact_value(
            scene_identity_items(runtime_package.get("semantic_scenes")),
            max_items=10,
        ),
        "npc_states": _compact_value(
            matching_items(runtime_package.get("npc_states"), current_keys),
            max_items=20,
        ),
        "clue_dependencies": _compact_value(
            matching_items(runtime_package.get("clue_dependencies"), current_keys),
            max_items=20,
        ),
        "rule_triggers": _compact_value(
            matching_items(runtime_package.get("rule_triggers"), current_keys),
            max_items=20,
        ),
        "semantic_map": {},
        "style_pack": _compact_value(runtime_package.get("style_pack"), max_items=20),
        "story_evidence_nodes": _compact_value(evidence, max_items=20),
        "semantic_progression_rules": {
            "edges": generic_edges,
            "solo_adventure": {
                "root_node_id": solo.get("root_node_id"),
                "nodes": compact_nodes,
            },
            "critical_progression": _compact_value(
                progression_rules.get("critical_progression"),
                max_items=20,
            ),
            "alternative_paths": _compact_value(
                progression_rules.get("alternative_paths"),
                max_items=20,
            ),
            "recovery_nodes": _compact_value(
                progression_rules.get("recovery_nodes"),
                max_items=20,
            ),
            "true_failure_conditions": _compact_value(
                progression_rules.get("true_failure_conditions"),
                max_items=20,
            ),
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
        "SELECT current_scene, visited_scenes, public_facts, scene_variables, version "
        "FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    return _json_safe(dict(row)) if row else {}


def _relevant_content_keys(
    current_scene: dict[str, Any],
    runtime_package: dict[str, Any],
) -> list[str]:
    keys = {
        str(current_scene.get(field) or "").strip()
        for field in ("current_scene", "scene_id", "node_id")
    }
    return sorted(key for key in keys if key)


def _content_facts(
    conn,
    scenario_version_id: str | None,
    visibility: str,
    logical_keys: list[str],
) -> list[dict[str, Any]]:
    if not scenario_version_id or not logical_keys:
        return []
    key_filter = "(" + ",".join(["%s"] * len(logical_keys)) + ")"
    rows = conn.execute(
        f"""
        SELECT content_item_id, item_type, logical_key, title, citation
        FROM content_items
        WHERE scenario_version_id = %s
          AND visibility = %s
          AND logical_key IN {key_filter}
        ORDER BY ordinal, logical_key
        LIMIT 40
        """,
        (scenario_version_id, visibility, *logical_keys),
    ).fetchall()
    return [
        {
            **_json_safe(dict(row)),
            "fact_id": str(row.get("content_item_id") or ""),
            "epistemic_status": "engine_hidden_candidate",
        }
        for row in rows
    ]


def _authorized_knowledge_facts(
    conn,
    room_id: str,
    character_id: str,
    current_scene: dict[str, Any],
) -> list[dict[str, Any]]:
    from ..engine.reveal_ledger import RevealLedger

    try:
        records = RevealLedger(conn).project_facts(
            room_id,
            audience="director",
            character_id=character_id,
        )
    except Exception:
        records = []
    facts = []
    for record in records:
        text = str(record.get("fact_text") or "").strip()
        if not text:
            continue
        facts.append({
            "fact_id": str(record.get("fact_id") or ""),
            "content_item_id": str(record.get("content_item_id") or ""),
            "item_type": "revealed_fact",
            "logical_key": str(record.get("fact_id") or ""),
            "title": text,
            "citation": _json_object(record.get("citation")),
            "audience": str(record.get("audience") or "party"),
            "status": str(record.get("status") or "revealed"),
            "epistemic_status": "engine_revealed_fact",
        })
    scene_facts = current_scene.get("public_facts")
    if isinstance(scene_facts, str):
        try:
            scene_facts = json.loads(scene_facts)
        except json.JSONDecodeError:
            scene_facts = []
    for index, value in enumerate(scene_facts or [], start=1):
        text = str(value or "").strip()
        if text:
            facts.append({
                "fact_id": f"scene-public:{index}",
                "item_type": "runtime_public_fact",
                "logical_key": str(current_scene.get("current_scene") or ""),
                "title": text[:1200],
                "citation": {},
                "audience": "party",
                "status": "revealed",
                "epistemic_status": "engine_public_state",
            })
    return facts[:40]


def _player_hypotheses(
    conn,
    room_id: str,
    character_id: str,
    declared_intent: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT evidence_card_id, title, body FROM evidence_cards "
        "WHERE room_id = %s AND fact_status = 'hypothesis' "
        "AND source = 'player' AND "
        "(visibility = 'party' OR created_by_character_id = %s) "
        "ORDER BY updated_at DESC LIMIT 20",
        (room_id, character_id),
    ).fetchall()
    intent_key = _normalized_relevance_text(declared_intent)
    result = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        title_key = _normalized_relevance_text(title)
        if title_key and intent_key and not _texts_overlap(title_key, intent_key):
            continue
        result.append({
            "evidence_card_id": str(row["evidence_card_id"]),
            "title": title[:300],
            "body": str(row.get("body") or "")[:1000],
            "epistemic_status": "player_hypothesis_not_world_truth",
        })
    return result[:5]


def _normalized_relevance_text(value: Any) -> str:
    return "".join(
        char.casefold() for char in str(value or "") if char.isalnum()
    )


def _texts_overlap(left: str, right: str) -> bool:
    if left in right or right in left:
        return True
    return any(left[index:index + 2] in right for index in range(len(left) - 1))


def _rule_version(conn, room_id: str) -> str:
    try:
        from .ai_config import get_room_ai_config
        from .rule_policy_compiler import validate_compiled_rule_artifact

        room_ai_config = get_room_ai_config(conn, room_id) or {}
        binding = room_ai_config.get("runtime_binding")
        if isinstance(binding, dict) and binding.get("locked") is True:
            sources = binding.get("rule_policy_sources")
            compiled = binding.get("compiled_rule_policy")
            artifact_id = str(
                binding.get("compiled_rule_artifact_id") or ""
            )
            if (
                isinstance(sources, list)
                and isinstance(compiled, dict)
                and validate_compiled_rule_artifact(
                    runtime_package_artifact_id=str(
                        binding.get("runtime_package_artifact_id") or ""
                    ),
                    sources=sources,
                    compiled_rule_policy=compiled,
                    artifact_id=artifact_id,
                )
            ):
                return artifact_id
            return "unversioned"
    except Exception:
        return "unversioned"
    try:
        version_row = conn.execute(
            "SELECT player_experience_version FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
    except Exception:
        return "unversioned"
    if (
        not version_row
        or str(version_row.get("player_experience_version") or "") != "v1"
    ):
        return "unversioned"
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


def _recent_events(conn, room_id: str, character_id: str) -> list[dict[str, Any]]:
    events = EventLog(conn).get_events_for_player(
        room_id,
        character_id,
        limit=100,
        latest=True,
    )
    return [
        sanitize_checkpoint_value({
            **event.model_dump(mode="json"),
            "epistemic_status": "authorized_observation_not_world_truth",
        })
        for event in events[-10:]
    ]


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
    provider_citation_supplied = (
        plan.semantic_progression.citation is not None or bool(plan.citations)
    )
    citation = _sanitize_citation(progression.get("citation") or (plan.citations[0] if plan.citations else {}))
    current = context.get("current_scene") if isinstance(context.get("current_scene"), dict) else {}
    from_node = str(current.get("node_id") or "")
    runtime_package = context.get("runtime_package") if isinstance(context.get("runtime_package"), dict) else {}
    rules = runtime_package.get("semantic_progression_rules") if isinstance(runtime_package, dict) else {}
    current_scene_id = str(current.get("current_scene") or "")
    generic_edges = (
        rules.get("edges") if isinstance(rules, dict) else []
    )
    if current_scene_id and isinstance(generic_edges, list):
        for edge in generic_edges:
            if not isinstance(edge, dict) or edge.get("relation_type") != "transitions_to":
                continue
            from_scene_id = str(edge.get("from_scene_id") or "")
            to_scene_id = str(edge.get("to_scene_id") or "")
            if from_scene_id != current_scene_id or to_scene_id != target:
                continue
            rule_citation = _sanitize_citation(edge.get("citation") or {})
            conditions_met = _generic_edge_conditions_are_met(
                conn,
                str(character.get("room_id") or ""),
                edge.get("conditions"),
            )
            if (
                citation
                and rule_citation
                and _citation_matches(citation, [rule_citation])
                and conditions_met
            ):
                return {
                    "targetNodeId": target,
                    "fromNodeId": current_scene_id,
                    "citation": citation,
                    "ruleCitation": rule_citation,
                    "validated": True,
                }
            if (
                not citation
                and not provider_citation_supplied
                and rule_citation
                and conditions_met
                and plan.confidence >= 0.7
                and str(plan.interpreted_intent or "").strip()
            ):
                return {
                    "targetNodeId": target,
                    "fromNodeId": current_scene_id,
                    "citation": rule_citation,
                    "ruleCitation": rule_citation,
                    "providerCitationMissing": True,
                    "validated": True,
                }
        recovery = select_progression_recovery(
            conn,
            str(character.get("room_id") or ""),
            current_scene_id,
            runtime_package,
        )
        if recovery.get("status") == "recovery":
            return {
                key: value
                for key, value in recovery.items()
                if key != "status"
            }
        if recovery.get("status") in {
            "revealed_unresolved_facts",
            "no_change",
        }:
            return {
                "targetNodeId": target,
                "fromNodeId": current_scene_id,
                **recovery,
            }
    solo = _json_object(rules.get("solo_adventure") if isinstance(rules, dict) else None)
    allowed = False
    matched_rule_citation: dict[str, Any] = {}
    matched_node: dict[str, Any] = {}
    target_node_citation: dict[str, Any] = {}
    for node in solo.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if str(node.get("node_id") or "") == target:
            target_node_citation = _sanitize_citation(node.get("citation") or {})
        if str(node.get("node_id") or "") != from_node:
            continue
        matched_rule_citation = _sanitize_citation(node.get("citation") or {})
        matched_node = node
        if target in [str(item) for item in (node.get("target_node_ids") or [])]:
            allowed = True
    forced_targets = [str(item) for item in (matched_node.get("target_node_ids") or [])]
    if not allowed and len(forced_targets) == 1 and matched_rule_citation:
        return {
            "targetNodeId": forced_targets[0],
            "fromNodeId": from_node,
            "citation": matched_rule_citation,
            "ruleCitation": matched_rule_citation,
            "providerTargetDeferred": True,
            "validated": True,
        }
    if allowed and citation and _citation_matches(citation, [matched_rule_citation]):
        return {
            "targetNodeId": target,
            "fromNodeId": from_node,
            "citation": citation,
            "ruleCitation": matched_rule_citation,
            "validated": True,
        }
    if allowed and citation and _citation_matches(citation, [target_node_citation]):
        return {
            "targetNodeId": target,
            "fromNodeId": from_node,
            "citation": matched_rule_citation,
            "ruleCitation": matched_rule_citation,
            "providerCitationTargetMatched": True,
            "validated": True,
        }
    if allowed and citation and _citation_page_matches(citation, target_node_citation):
        return {
            "targetNodeId": target,
            "fromNodeId": from_node,
            "citation": matched_rule_citation,
            "ruleCitation": matched_rule_citation,
            "providerCitationTargetPageMatched": True,
            "validated": True,
        }
    if allowed and _conditional_solo_branch_matches(character, matched_node, target):
        return {
            "targetNodeId": target,
            "fromNodeId": from_node,
            "citation": matched_rule_citation,
            "ruleCitation": matched_rule_citation,
            "conditionValidated": True,
            "validated": True,
        }
    if (
        allowed
        and citation
        and matched_rule_citation
        and len(matched_node.get("target_node_ids") or []) == 1
        and plan.confidence >= 0.8
        and str(plan.interpreted_intent or "").strip()
    ):
        return {
            "targetNodeId": target,
            "fromNodeId": from_node,
            "citation": matched_rule_citation,
            "ruleCitation": matched_rule_citation,
            "providerCitationReplaced": True,
            "validated": True,
        }
    if (
        allowed
        and not citation
        and not provider_citation_supplied
        and matched_rule_citation
        and (
            len(matched_node.get("target_node_ids") or []) == 1
            or plan.confidence >= 0.7
        )
        and str(plan.interpreted_intent or "").strip()
    ):
        return {
            "targetNodeId": target,
            "fromNodeId": from_node,
            "citation": matched_rule_citation,
            "ruleCitation": matched_rule_citation,
            "providerCitationMissing": True,
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


def select_progression_recovery(
    conn,
    room_id: str,
    current_scene_id: str,
    runtime_package: dict[str, Any],
) -> dict[str, Any]:
    rules = _json_object(runtime_package.get("semantic_progression_rules"))
    edges = rules.get("edges") if isinstance(rules.get("edges"), list) else []
    for edge in edges:
        if (
            isinstance(edge, dict)
            and edge.get("relation_type") == "transitions_to"
            and str(edge.get("from_scene_id") or "") == current_scene_id
            and _generic_edge_conditions_are_met(conn, room_id, edge.get("conditions"))
        ):
            return {
                "status": "path_available",
                "validated": False,
                "rejected": True,
                "reason": "compiled_progression_path_available",
                "revealedFactIds": [],
                "stateChanged": False,
            }

    candidates: list[tuple[int, str, dict[str, Any]]] = []
    recovery_nodes = (
        rules.get("recovery_nodes")
        if isinstance(rules.get("recovery_nodes"), list)
        else []
    )
    declared_recoveries = {
        progression_id: {
            str(value)
            for value in progression.get("recovery_node_ids") or []
            if str(value)
        }
        for progression in rules.get("critical_progression") or []
        if isinstance(progression, dict)
        and (
            progression_id := str(
                progression.get("progression_id") or progression.get("id") or ""
            ).strip()
        )
    }
    for node in recovery_nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(
            node.get("recovery_node_id") or node.get("node_id") or node.get("id") or ""
        ).strip()
        progression_id = str(node.get("progression_id") or "").strip()
        if node_id not in declared_recoveries.get(progression_id, set()):
            continue
        from_scene_ids = node.get("from_scene_ids") or node.get("fromSceneIds") or []
        if not isinstance(from_scene_ids, list):
            from_scene_ids = []
        if current_scene_id not in {str(value) for value in from_scene_ids}:
            continue
        target_scene_id = str(
            node.get("target_scene_id") or node.get("targetSceneId") or ""
        ).strip()
        citation = _sanitize_citation(node.get("citation") or {})
        cost_boundary = _object_dict(
            node.get("cost_boundary") or node.get("costBoundary")
        )
        amount = cost_boundary.get("amount")
        if (
            not node_id
            or not target_scene_id
            or not citation
            or str(cost_boundary.get("kind") or "").strip() != "time"
            or not isinstance(amount, int)
            or isinstance(amount, bool)
            or amount <= 0
            or not _generic_edge_conditions_are_met(
                conn,
                room_id,
                node.get("conditions"),
            )
        ):
            continue
        priority = node.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            priority = 0
        candidates.append((priority, node_id, node))

    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        top_priority = candidates[0][0]
        top = [candidate for candidate in candidates if candidate[0] == top_priority]
        if len(top) == 1:
            _, node_id, node = top[0]
            citation = _sanitize_citation(node.get("citation") or {})
            return {
                "status": "recovery",
                "validated": True,
                "fromNodeId": current_scene_id,
                "targetNodeId": str(
                    node.get("target_scene_id") or node.get("targetSceneId") or ""
                ),
                "recoveryNodeId": node_id,
                "citation": citation,
                "ruleCitation": citation,
                "costBoundary": _object_dict(
                    node.get("cost_boundary") or node.get("costBoundary")
                ),
            }

    revealed_rows = conn.execute(
        "SELECT DISTINCT fact_id FROM fact_reveals "
        "WHERE room_id = %s AND audience = 'party' "
        "AND status = 'revealed' AND record_kind = 'reveal' "
        "ORDER BY fact_id",
        (room_id,),
    ).fetchall()
    revealed_fact_ids = [
        str(row.get("fact_id") or "")
        for row in revealed_rows
        if str(row.get("fact_id") or "")
    ]
    if revealed_fact_ids:
        return {
            "status": "revealed_unresolved_facts",
            "validated": False,
            "rejected": True,
            "reason": "progression_exhausted_revealed_facts_only",
            "revealedFactIds": revealed_fact_ids,
            "stateChanged": False,
        }
    return {
        "status": "no_change",
        "validated": False,
        "rejected": True,
        "reason": "progression_exhausted_no_information",
        "revealedFactIds": [],
        "stateChanged": False,
    }


def _generic_edge_conditions_are_met(conn, room_id: str, conditions: Any) -> bool:
    if not conditions:
        return True
    if not room_id or not isinstance(conditions, list):
        return False
    for condition in conditions:
        if not isinstance(condition, dict):
            return False
        kind = str(condition.get("kind") or "")
        identifier = str(condition.get("id") or "")
        if not identifier:
            return False
        if kind == "clue":
            discovered = conn.execute(
                "SELECT 1 FROM clues WHERE room_id = %s AND clue_id = %s",
                (room_id, identifier),
            ).fetchone()
            if not discovered:
                return False
            continue
        if kind == "scene":
            state = conn.execute(
                "SELECT current_scene, visited_scenes FROM room_scene_state WHERE room_id = %s",
                (room_id,),
            ).fetchone()
            visited = _json_list(state.get("visited_scenes") if state else [])
            if not state or (
                str(state.get("current_scene") or "") != identifier
                and identifier not in visited
            ):
                return False
            continue
        return False
    return True


def _conditional_solo_branch_matches(
    character: dict[str, Any],
    node: dict[str, Any],
    target: str,
) -> bool:
    sheet = _json_object(character.get("xlsx_data"))
    attributes = _json_object(sheet.get("attributes"))
    normalized_attributes = {
        str(key).lower(): value
        for key, value in attributes.items()
    }
    text = re.sub(r"\s+", "", str(node.get("text") or ""))
    for comparison in _COMPARATIVE_SOLO_CONTEXT_RE.finditer(text):
        first = comparison.group("first").lower()
        second = comparison.group("second").lower()
        for branch in _COMPARATIVE_SOLO_BRANCH_RE.finditer(text[comparison.end():]):
            if branch.group("target") != target:
                continue
            winner = branch.group("attribute").lower()
            if winner not in {first, second}:
                continue
            other = second if winner == first else first
            winner_value = _solo_attribute_value(normalized_attributes, winner)
            other_value = _solo_attribute_value(normalized_attributes, other)
            if winner_value is not None and other_value is not None and winner_value > other_value:
                return True
    for match in _CONDITIONAL_SOLO_BRANCH_RE.finditer(text):
        if match.group("target") != target:
            continue
        attribute_name = match.group("attribute").lower()
        value = _solo_attribute_value(normalized_attributes, attribute_name)
        if value is None:
            continue
        threshold = int(match.group("value"))
        operator = match.group("operator")
        if operator in {"是", "为", "等于"} and value == threshold:
            return True
        if operator == "高于" and value > threshold:
            return True
        if operator == "低于" and value < threshold:
            return True
        if operator in {"不低于", "至少"} and value >= threshold:
            return True
        if operator in {"不高于", "至多"} and value <= threshold:
            return True
    return False


def _solo_attribute_value(attributes: dict[str, Any], attribute_name: str) -> int | None:
    value = next(
        (
            attributes.get(key.lower())
            for key in _SOLO_ATTRIBUTE_KEYS.get(attribute_name, ())
            if attributes.get(key.lower()) is not None
        ),
        None,
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_conditional_solo_target(character: dict[str, Any], node: dict[str, Any]) -> str | None:
    matches = [
        str(target)
        for target in node.get("target_node_ids") or []
        if _conditional_solo_branch_matches(character, node, str(target))
    ]
    return matches[0] if len(matches) == 1 else None


def _citation_matches(citation: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
    if not citation:
        return False
    stable_fields = {
        "source",
        "source_ref",
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


def _citation_page_matches(citation: dict[str, Any], candidate: dict[str, Any]) -> bool:
    page_number = citation.get("page_number")
    return page_number not in (None, "") and page_number == candidate.get("page_number")


def _sanitize_citation(value: dict[str, Any]) -> dict[str, Any]:
    value = _object_dict(value)
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if item not in (None, "")
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


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
