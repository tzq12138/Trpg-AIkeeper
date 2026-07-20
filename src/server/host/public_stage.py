"""Safe, public-only data contract for a room's display stage."""

from __future__ import annotations

import json
from typing import Any

from ..models import HostHUD, PlayerPublicStatus, RevealTransaction


_ENGINE_STATUS_TEXT = {
    "thinking": "KP 正在理解行动",
    "busy": "KP 正在演绎结果",
    "idle": "等待调查员行动",
}

_PUBLIC_STAGE_PLAYER_LIMIT = 6


def _condition(player: PlayerPublicStatus) -> tuple[str, str]:
    hp_ratio = player.hp / player.hp_max if player.hp_max > 0 else 1
    san_ratio = player.san / player.san_max if player.san_max > 0 else 1
    lowest_ratio = min(hp_ratio, san_ratio)
    if player.hp_max > 0 and player.hp <= 0:
        return "失去意识", "danger"
    if player.san_max > 0 and player.san <= 0:
        return "精神崩溃", "danger"
    if lowest_ratio <= 0.25:
        return "濒危", "danger"
    if lowest_ratio <= 0.5:
        return "受伤", "warning"
    return "情况稳定", "stable"


def build_public_stage_projection(
    hud: HostHUD,
    public_events: list[dict[str, Any]],
    combat_round: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Remove host-only values before they can reach the public display."""
    players = []
    for player in hud.players[:_PUBLIC_STAGE_PLAYER_LIMIT]:
        condition, condition_tone = _condition(player)
        players.append({
            "characterId": player.character_id,
            "playerName": player.player_name,
            "investigatorName": player.investigator_name,
            "condition": condition,
            "conditionTone": condition_tone,
        })

    recent_events = [
        {
            "text": str(event.get("text", "")),
            "issuedAt": str(event.get("issued_at", event.get("issuedAt", ""))),
        }
        for event in public_events
        if event.get("text")
    ][-5:]

    projection = {
        "roomId": hud.room_id,
        "sceneImageUrl": hud.scene_image_url,
        "statusText": _ENGINE_STATUS_TEXT.get(hud.engine_state, "等待调查员行动"),
        "teamObjectives": list(hud.team_objectives),
        "sceneTime": hud.scene_time,
        "players": players,
        "recentEvents": recent_events,
    }
    if combat_round:
        projection["combatRound"] = combat_round
    return projection


def build_public_combat_round_projection(
    conn,
    room_id: str,
    *,
    total_players: int,
) -> dict[str, Any] | None:
    """Return only the live combat fields that are safe for a public stage."""
    turn = conn.execute(
        """
        SELECT t.turn_id, t.status, t.combat_plan, e.current_round, e.encounter_id
        FROM room_turns t
        JOIN encounters e ON e.encounter_id = t.encounter_id
        WHERE t.room_id = %s
          AND t.mode = 'combat'
          AND e.type = 'combat'
          AND e.status = 'active'
        ORDER BY t.turn_index DESC
        LIMIT 1
        """,
        (room_id,),
    ).fetchone()
    if not turn:
        return None

    phase = {
        "collecting": "declaration",
        "resolving": "resolution",
        "resolved": "summary",
        "blocked": "blocked",
    }.get(str(turn.get("status") or ""))
    if not phase:
        return None

    submitted = conn.execute(
        """
        SELECT COUNT(DISTINCT character_id) AS count
        FROM actions
        WHERE turn_id = %s
          AND status NOT IN ('rejected', 'canceled', 'timeout')
        """,
        (turn["turn_id"],),
    ).fetchone()
    submitted_count = int((submitted or {}).get("count") or 0)
    public_total = max(0, int(total_players or 0))
    plan = _json_object(turn.get("combat_plan"))
    payload = {
        "roundNumber": max(1, int(turn.get("current_round") or 1)),
        "phase": phase,
        "submittedCount": min(submitted_count, public_total),
        "totalPlayers": public_total,
    }
    if phase in {"resolution", "blocked"}:
        conflict = _public_combat_conflict(plan)
        if conflict:
            payload["currentConflict"] = conflict
    units = build_public_combat_units_for_encounter(conn, str(turn["encounter_id"]))
    if units:
        payload["publicUnits"] = units
    return payload


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _public_combat_conflict(plan: dict[str, Any]) -> str | None:
    for cluster in plan.get("presentation_clusters", []):
        if not isinstance(cluster, dict) or cluster.get("visibility") == "private":
            continue
        title = cluster.get("public_title")
        if isinstance(title, str) and title.strip():
            return " ".join(title.split())[:80]
    return None


def build_public_combat_units_for_encounter(conn, encounter_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT side, display_name, hp, hp_max, distance_band,
               public_visibility, public_label, last_observed_position
        FROM encounter_participants
        WHERE encounter_id = %s
        ORDER BY CASE WHEN side = 'player' THEN 0 ELSE 1 END, character_id
        """,
        (encounter_id,),
    ).fetchall()
    return build_public_combat_unit_projection([dict(row) for row in rows])


def build_public_encounter_event_projection(
    encounter: dict[str, Any] | None,
    public_units: list[dict[str, Any]],
) -> dict[str, Any]:
    encounter = encounter or {}
    return {
        "encounterId": str(encounter.get("encounter_id") or ""),
        "encounter": {
            "type": str(encounter.get("type") or ""),
            "status": str(encounter.get("status") or ""),
            "currentRound": max(0, _safe_positive_int(encounter.get("current_round"))),
        },
        "publicUnits": public_units,
    }


def build_public_combat_unit_projection(participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only explicitly public combat unit descriptions.

    Enemy identity, exact resources, internal combat ordering and equipment are
    intentionally absent from this projection.
    """
    units: list[dict[str, Any]] = []
    for participant in participants:
        side = str(participant.get("side") or "")
        if side == "player":
            label = _safe_combat_text(participant.get("display_name")) or "调查员"
            unit = _public_visible_unit(label, participant, "investigator")
            if unit:
                units.append(unit)
            continue

        visibility = str(participant.get("public_visibility") or "hidden")
        label = _safe_combat_text(participant.get("public_label"))
        if visibility == "visible" and label:
            unit = _public_visible_unit(label, participant, "observed_enemy")
            if unit:
                units.append(unit)
        elif visibility == "lost" and label:
            unit = {
                "label": label,
                "kind": "observed_enemy",
                "condition": "失去踪迹",
            }
            last_position = _safe_combat_text(participant.get("last_observed_position"))
            if last_position:
                unit["lastObservedAt"] = last_position
            units.append(unit)
    return sorted(
        units,
        key=lambda unit: (
            0 if unit["kind"] == "investigator" else 1,
            1 if unit["condition"] == "失去踪迹" else 0,
            unit["label"],
        ),
    )[:12]


def _public_visible_unit(
    label: str,
    participant: dict[str, Any],
    kind: str,
) -> dict[str, Any] | None:
    hp = _safe_positive_int(participant.get("hp"))
    hp_max = _safe_positive_int(participant.get("hp_max"))
    if hp_max <= 0:
        return None
    health_segments = min(8, max(0, round((hp / hp_max) * 8)))
    unit = {
        "label": label,
        "kind": kind,
        "healthSegments": health_segments,
        "condition": _public_combat_condition(hp, hp_max),
    }
    distance_band = str(participant.get("distance_band") or "")
    if distance_band in {"engaged", "near", "short", "medium", "long"}:
        unit["distanceBand"] = distance_band
    return unit


def _public_combat_condition(hp: int, hp_max: int) -> str:
    if hp <= 0:
        return "失去意识"
    ratio = hp / hp_max
    if ratio <= 0.25:
        return "濒危"
    if ratio <= 0.5:
        return "重伤"
    if ratio <= 0.75:
        return "受伤"
    return "情况稳定"


def _safe_positive_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _safe_combat_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:80]


def build_public_presentation_projection(
    transaction: RevealTransaction | None,
    current_step_index: int,
    stage_projection: dict[str, Any] | None,
    version: int,
) -> dict[str, Any]:
    """Project one already-released narration step without reading host step payloads."""
    unavailable = {
        "available": False,
        "version": max(version, 0),
        "kind": None,
        "narrativeText": None,
    }
    if not transaction or not transaction.action_id or current_step_index <= 0:
        return unavailable
    if current_step_index > len(transaction.steps):
        return unavailable
    if transaction.steps[current_step_index - 1].kind != "narrative_text":
        return unavailable
    narrative = (stage_projection or {}).get("narrativeText")
    if not isinstance(narrative, str) or not narrative.strip():
        return unavailable
    return {
        "available": True,
        "version": max(version, 0),
        "kind": "narrative_text",
        "narrativeText": narrative.strip(),
    }
