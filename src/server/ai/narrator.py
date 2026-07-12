from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ..models import NarrationResultDTO, ResolutionResult

_DENIED_CONTEXT_KEYS = {
    "room_id",
    "roomId",
    "character_id",
    "characterId",
    "truth",
    "endings",
    "ending",
    "hidden_source",
    "raw_text",
    "rawText",
    "original_text",
    "originalText",
    "source_text",
    "full_text",
    "state_patch",
    "mutations",
}

def build_narrator_context(
    conn,
    action: dict[str, Any],
    character: dict[str, Any],
    room: dict[str, Any],
    resolution: ResolutionResult,
) -> dict[str, Any]:
    params = _json_object(action.get("params"))
    director_plan = _json_object(params.get("director_plan"))
    runtime_package = _latest_runtime_package(conn, room.get("scenario_version_id"))
    current_scene = _current_scene(conn, room.get("room_id"))
    current_scene_key = str(
        current_scene.get("current_scene")
        or current_scene.get("node_id")
        or current_scene.get("scene_id")
        or ""
    )
    scene_brief = _scene_brief(runtime_package, current_scene, current_scene_key)
    visible_changes = _visible_state_changes(resolution)
    runtime_allowed_facts = _runtime_allowed_facts(runtime_package)
    interactables = _interactable_names(runtime_package.get("interactable_objects"))
    allowed_facts = _allowed_facts(
        conn,
        runtime_package,
        room.get("scenario_version_id"),
        scene_brief,
        interactables,
        visible_changes,
        _investigator_name(character),
        runtime_allowed_facts,
    )
    context = {
        "investigator_name": _investigator_name(character),
        "scene_brief": scene_brief,
        "declared_intent": action.get("declared_intent") or "",
        "director_summary": _director_summary(director_plan),
        "deterministic_rule_outcome": {
            "mechanic": resolution.mechanic,
            "is_success": resolution.is_success,
            "summary": _rule_summary(resolution),
        },
        "allowed_facts": allowed_facts,
        "visible_state_changes": visible_changes,
        "spoiler_constraints": _safe_spoiler_constraints(runtime_package),
        "runtime_package_style_pack": _json_object(runtime_package.get("style_pack")),
        "redacted_citations": _redacted_citations(director_plan, runtime_package),
        "interactable_objects": interactables,
        "context_version": int(room.get("state_version") or 0),
        "director_plan_digest": _director_plan_digest(director_plan),
    }
    return _strip_denied(context)


def validate_narration_result(
    result: NarrationResultDTO,
    context: dict[str, Any],
) -> str | None:
    if result.status != "completed":
        return "narrator_invalid_response"
    text = result.narrative_text or ""
    if re.search(r"(条目|轉到條目|转到条目)\s*\d+", text):
        return "narrator_numbered_entry_leak"
    required_ref_fields = {
        "narrative_text",
        "environment_changes",
        "interactable_objects",
        "open_question",
    }
    if set(result.fact_refs) != required_ref_fields:
        return "narrator_fact_violation"
    allowed_refs = {
        str(item.get("fact_ref") or "")
        for item in context.get("allowed_facts") or []
        if isinstance(item, dict) and item.get("fact_ref")
    }
    if not allowed_refs:
        return "narrator_fact_violation"
    for key in required_ref_fields:
        refs = result.fact_refs.get(key)
        if not isinstance(refs, list) or not refs:
            return "narrator_fact_violation"
        if any(str(ref) not in allowed_refs for ref in refs):
            return "narrator_fact_violation"
    return None


def build_manual_action_hints(conn, character: dict[str, Any]) -> dict[str, list[str]]:
    room = conn.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (character["room_id"],),
    ).fetchone()
    runtime_package = _latest_runtime_package(
        conn,
        room.get("scenario_version_id") if room else None,
    )
    current_scene = _current_scene(conn, character["room_id"])
    scene_key = str(current_scene.get("current_scene") or current_scene.get("node_id") or "")
    scene_brief = _scene_brief(runtime_package, current_scene, scene_key)
    interactables = _string_list(runtime_package.get("interactable_objects"))[:3]
    sheet = _json_object(character.get("xlsx_data"))
    abilities = _string_list(sheet.get("abilities"))[:2]
    focus = interactables or [scene_brief or "当前可见场景"]
    examples = [
        f"我想仔细观察{focus[0]}，看看有什么可见细节。",
        f"我靠近{focus[min(1, len(focus) - 1)]}，尝试找到能互动的地方。",
        "我停下来整理线索，并说明下一步想验证什么。",
    ]
    if abilities:
        examples.append(f"我运用{abilities[0]}，从当前可见线索里寻找突破口。")
    if len(focus) > 2:
        examples.append(f"我比较{focus[0]}和{focus[2]}之间是否有关联。")
    return {"hints": examples[:5]}


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


def _current_scene(conn, room_id: str | None) -> dict[str, Any]:
    if not room_id:
        return {}
    row = conn.execute(
        "SELECT current_scene, visited_scenes, scene_variables, version FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    return _json_safe(dict(row)) if row else {}


def _scene_brief(
    runtime_package: dict[str, Any],
    current_scene: dict[str, Any],
    current_scene_key: str,
) -> str:
    briefs = _json_object(runtime_package.get("scene_briefs"))
    if current_scene_key and briefs.get(current_scene_key):
        return str(briefs[current_scene_key])[:600]
    if current_scene.get("title"):
        return str(current_scene.get("title"))[:300]
    value = current_scene.get("current_scene")
    return str(value or "")[:300]


def _allowed_facts(
    conn,
    runtime_package: dict[str, Any],
    scenario_version_id: str | None,
    scene_brief: str,
    interactables: list[str],
    visible_changes: list[str],
    investigator_name: str,
    runtime_allowed_facts: list[dict[str, str]],
) -> list[dict[str, str]]:
    facts: list[dict[str, str]] = list(runtime_allowed_facts)
    facts.extend(_facts_from_texts("fact:interactable", interactables))
    facts.extend(_facts_from_texts("fact:visible-change", visible_changes))
    if investigator_name:
        facts.append({"fact_ref": "fact:investigator", "text": investigator_name})
    if scene_brief:
        facts.append({"fact_ref": "fact:scene-brief", "text": scene_brief})
    if scenario_version_id:
        rows = conn.execute(
            """
            SELECT title, logical_key
            FROM content_items
            WHERE scenario_version_id = %s AND visibility = 'public'
            ORDER BY ordinal, logical_key
            LIMIT 40
            """,
            (scenario_version_id,),
        ).fetchall()
        for row in rows:
            logical_key = str(row.get("logical_key") or "").strip()
            title = str(row.get("title") or "").strip()
            if logical_key and title:
                facts.append({
                    "fact_ref": f"fact:content:{logical_key}",
                    "text": title,
                })
    deduped: dict[str, dict[str, str]] = {}
    for fact in facts:
        fact_ref = str(fact.get("fact_ref") or "").strip()
        text = str(fact.get("text") or "").strip()
        if fact_ref and text and fact_ref not in deduped:
            deduped[fact_ref] = {"fact_ref": fact_ref, "text": text}
    return list(deduped.values())


def _director_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "interpreted_intent": str(plan.get("interpreted_intent") or "")[:500],
        "intent_type": str(plan.get("intent_type") or "")[:80],
        "narration_mode": str(plan.get("narration_mode") or "")[:80],
        "visibility": str(plan.get("visibility") or "public")[:80],
    }


def _rule_summary(resolution: ResolutionResult) -> str:
    metadata = resolution.metadata or {}
    return str(
        metadata.get("rule_summary")
        or metadata.get("summary")
        or ("success" if resolution.is_success else "failure")
    )[:500]


def _visible_state_changes(resolution: ResolutionResult) -> list[str]:
    metadata = resolution.metadata or {}
    visible = metadata.get("visible_state_changes")
    changes = _string_list(visible)
    changes.extend(_string_list(resolution.cascading_state_changes))
    return [item for item in dict.fromkeys(changes) if item]


def _redacted_citations(
    director_plan: dict[str, Any],
    runtime_package: dict[str, Any],
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for item in director_plan.get("citations") or []:
        citations.append(_sanitize_citation(item))
    for item in runtime_package.get("citations") or []:
        citations.append(_sanitize_citation(item))
    return [item for item in citations if item][:10]


def _safe_spoiler_constraints(runtime_package: dict[str, Any]) -> list[str]:
    constraints = _string_list(runtime_package.get("spoiler_constraints"))
    if not constraints:
        return []
    return ["Follow runtime spoiler constraints without exposing hidden facts or endings."]


def _sanitize_citation(value: Any) -> dict[str, Any]:
    citation = _json_object(value)
    denied = {
        "absolute_path",
        "storage_path",
        "raw_text",
        "source_text",
        "full_text",
        "original_text",
        "text",
        "content",
    }
    return {
        str(key): item
        for key, item in citation.items()
        if str(key).lower() not in denied and not str(key).lower().endswith("_path")
    }


def _director_plan_digest(plan: dict[str, Any]) -> str:
    stable = {
        "interpreted_intent": plan.get("interpreted_intent"),
        "intent_type": plan.get("intent_type"),
        "narration_mode": plan.get("narration_mode"),
        "citations": [_sanitize_citation(item) for item in plan.get("citations") or []],
    }
    payload = json.dumps(stable, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _investigator_name(character: dict[str, Any]) -> str:
    sheet = _json_object(character.get("xlsx_data"))
    return str(
        sheet.get("name")
        or sheet.get("investigator_name")
        or character.get("player_name")
        or "Investigator"
    )


def _strip_denied(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_denied(item)
            for key, item in value.items()
            if key not in _DENIED_CONTEXT_KEYS
        }
    if isinstance(value, list):
        return [_strip_denied(item) for item in value]
    return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _runtime_allowed_facts(runtime_package: dict[str, Any]) -> list[dict[str, str]]:
    raw = runtime_package.get("allowed_facts")
    if not isinstance(raw, list):
        return []
    facts: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("label") or "").strip()
            fact_ref = str(item.get("fact_ref") or item.get("ref") or "").strip()
        else:
            text = str(item).strip()
            fact_ref = ""
        if not text:
            continue
        if not fact_ref:
            fact_ref = f"fact:runtime:{_stable_slug(text, index)}"
        facts.append({"fact_ref": fact_ref, "text": text})
    return facts


def _interactable_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("label") or item.get("text") or "").strip()
        else:
            name = str(item).strip()
        if name:
            names.append(name)
    return names


def _facts_from_texts(prefix: str, values: list[str]) -> list[dict[str, str]]:
    return [
        {"fact_ref": f"{prefix}:{_stable_slug(value, index)}", "text": value}
        for index, value in enumerate(values, start=1)
        if value
    ]


def _stable_slug(value: str, index: int) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{index}:{digest}"


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
