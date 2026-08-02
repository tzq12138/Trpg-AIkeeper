"""Deterministic evaluation for cited, declarative scenario endings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


_CONDITION_KEYS = {"all_clues", "any_clues", "entered_scenes", "event_types", "room_status"}
_ENDING_TYPES = {"victory", "defeat", "mixed", "safe_abort"}
_PRESENTATION_ONLY_EVENT_TYPES = {
    "s2c_action_completed",
    "s2c_ai_stage_changed",
    "s2c_narration_completed",
    "s2c_public_observation",
    "s2c_reveal_transaction",
    "s2c_scene_sync",
    "s2c_state_patch",
}


@dataclass(frozen=True)
class EndingDecision:
    ending_id: str
    ending_type: str
    citation: dict[str, Any]
    room_status: str
    priority: int = 0
    exclusive_group: str = "campaign_ending"


def evaluate_ending_conditions(conn, room_id: str, ending_conditions: Any) -> EndingDecision | None:
    """Return exactly one matching ending, or ``None`` when evidence is incomplete or ambiguous."""
    if not isinstance(ending_conditions, list):
        return None
    room = conn.execute(
        "SELECT status FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    if not room:
        return None

    facts = _persisted_facts(conn, room_id, str(room.get("status") or ""))
    matches = [
        decision
        for ending in ending_conditions
        if (decision := _matching_decision(ending, facts)) is not None
    ]
    if not matches:
        return None
    highest_priority = max(decision.priority for decision in matches)
    highest = [
        decision for decision in matches if decision.priority == highest_priority
    ]
    return highest[0] if len(highest) == 1 else None


def _matching_decision(ending: Any, facts: dict[str, Any]) -> EndingDecision | None:
    if not isinstance(ending, dict):
        return None
    ending_id = str(ending.get("ending_id") or ending.get("id") or "").strip()
    ending_type = str(ending.get("type") or "mixed").strip()
    citation = ending.get("citation")
    conditions = ending.get("completion_conditions")
    declared_priority = ending.get("priority", 0)
    exclusive_group = str(ending.get("exclusive_group") or "campaign_ending").strip()
    if (
        not ending_id
        or ending_type not in _ENDING_TYPES
        or not _has_citation(citation)
        or not _conditions_are_valid(conditions)
        or not isinstance(declared_priority, int)
        or isinstance(declared_priority, bool)
        or not exclusive_group
    ):
        return None
    if not _conditions_match(conditions, facts):
        return None
    priority = (
        1_000_000
        if ending_type == "safe_abort"
        else min(int(declared_priority), 999_999)
    )
    return EndingDecision(
        ending_id,
        ending_type,
        dict(citation),
        str(facts["room_status"]),
        int(priority),
        exclusive_group,
    )


def _persisted_facts(conn, room_id: str, room_status: str) -> dict[str, Any]:
    scene = conn.execute(
        "SELECT current_scene, visited_scenes FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone() or {}
    visited = set(_string_list(scene.get("visited_scenes")))
    current_scene = str(scene.get("current_scene") or "").strip()
    if current_scene:
        visited.add(current_scene)
    clue_rows = conn.execute(
        "SELECT clue_id, source FROM clues WHERE room_id = %s", (room_id,)
    ).fetchall()
    event_rows = conn.execute(
        "SELECT event_type FROM events WHERE room_id = %s", (room_id,)
    ).fetchall()
    return {
        "room_status": room_status,
        "entered_scenes": visited,
        "clue_ids": {
            canonical_id
            for row in clue_rows
            for canonical_id in (
                str(row.get("clue_id") or ""),
                _runtime_clue_id(row.get("source")),
            )
            if canonical_id
        },
        "event_types": {str(row.get("event_type") or "") for row in event_rows},
    }


def _runtime_clue_id(source: Any) -> str:
    value = str(source or "")
    return value.removeprefix("runtime:") if value.startswith("runtime:") else ""


def _conditions_are_valid(value: Any) -> bool:
    if not isinstance(value, dict) or not value or set(value) - _CONDITION_KEYS:
        return False
    for key, expected in value.items():
        if key == "room_status":
            if not isinstance(expected, str) or not expected.strip():
                return False
            continue
        if not isinstance(expected, list) or not expected or not all(
            isinstance(item, str) and item.strip() for item in expected
        ):
            return False
        if key == "event_types" and any(
            item in _PRESENTATION_ONLY_EVENT_TYPES for item in expected
        ):
            return False
    return True


def _conditions_match(conditions: dict[str, Any], facts: dict[str, Any]) -> bool:
    if "room_status" in conditions and facts["room_status"] != conditions["room_status"]:
        return False
    if "all_clues" in conditions and not set(conditions["all_clues"]).issubset(facts["clue_ids"]):
        return False
    if "any_clues" in conditions and not set(conditions["any_clues"]) & facts["clue_ids"]:
        return False
    if "entered_scenes" in conditions and not set(conditions["entered_scenes"]).issubset(facts["entered_scenes"]):
        return False
    if "event_types" in conditions and not set(conditions["event_types"]).issubset(facts["event_types"]):
        return False
    return True


def _has_citation(value: Any) -> bool:
    return isinstance(value, dict) and bool(
        value.get("source_part_id") or value.get("source_ref")
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []
