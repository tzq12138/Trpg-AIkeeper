import json
import uuid
from typing import Any

from ..models import ResolutionBundleDTO, ResolutionResult


def build_resolution_bundle(
    action: dict[str, Any],
    resolution: ResolutionResult,
    *,
    final_text: str,
    spoiler_status: str,
    rule_explanation: dict[str, Any] | None,
    action_completed: dict[str, Any],
) -> ResolutionBundleDTO:
    host_steps = []
    for step in resolution.reveal_steps:
        kind = "roll" if step.get("kind") == "roll" else "status_delta"
        host_steps.append({"kind": kind, "payload": step})
    host_steps.append({"kind": "narrative_text", "payload": {"text": final_text}})
    state_patch = None
    if resolution.mutations:
        state_patch = {
            "actionId": action["action_id"],
            "patches": resolution.mutations,
            "cascadingStateChanges": resolution.cascading_state_changes,
        }
    stage_projection = {"actionId": action["action_id"], "text": final_text}
    if spoiler_status != "none":
        stage_projection["spoilerStatus"] = spoiler_status
    return ResolutionBundleDTO(
        actionId=action["action_id"],
        roomId=action["room_id"],
        characterId=action["character_id"],
        canonicalResult=resolution.model_dump(by_alias=True),
        ruleExplanation=rule_explanation or {},
        actorProjection={
            "statePatch": state_patch,
            "actionCompleted": action_completed,
        },
        stageProjection=stage_projection,
        hostConsole={
            "transactionId": str(uuid.uuid4()),
            "actionId": action["action_id"],
            "priority": "normal",
            "steps": host_steps,
            "summaryText": final_text,
        },
    )


def persist_resolution_bundle(conn, bundle: ResolutionBundleDTO) -> None:
    payload = bundle.model_dump(by_alias=True)
    conn.execute(
        "INSERT INTO resolution_bundles "
        "(action_id, room_id, character_id, canonical_result, rule_explanation, actor_projection, "
        "stage_projection, host_console, release_status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (action_id) DO UPDATE SET canonical_result = EXCLUDED.canonical_result, "
        "rule_explanation = EXCLUDED.rule_explanation, actor_projection = EXCLUDED.actor_projection, "
        "stage_projection = EXCLUDED.stage_projection, host_console = EXCLUDED.host_console, "
        "release_status = EXCLUDED.release_status, released_at = NULL",
        (
            payload["actionId"],
            payload["roomId"],
            payload["characterId"],
            json.dumps(payload["canonicalResult"], ensure_ascii=False),
            json.dumps(payload["ruleExplanation"], ensure_ascii=False),
            json.dumps(payload["actorProjection"], ensure_ascii=False),
            json.dumps(payload["stageProjection"], ensure_ascii=False),
            json.dumps(payload["hostConsole"], ensure_ascii=False),
            payload["releaseStatus"],
        ),
    )
    conn.commit()


def mark_resolution_bundle_released(conn, action_id: str) -> None:
    conn.execute(
        "UPDATE resolution_bundles SET release_status = 'released', released_at = NOW() "
        "WHERE action_id = %s AND release_status = 'ready'",
        (action_id,),
    )
    conn.commit()


def resolution_bundle_from_row(row: dict[str, Any]) -> ResolutionBundleDTO:
    return ResolutionBundleDTO(
        actionId=row["action_id"],
        roomId=row["room_id"],
        characterId=row["character_id"],
        canonicalResult=_json_object(row.get("canonical_result")),
        ruleExplanation=_json_object(row.get("rule_explanation")),
        actorProjection=_json_object(row.get("actor_projection")),
        stageProjection=_json_object(row.get("stage_projection")),
        hostConsole=_json_object(row.get("host_console")),
        releaseStatus=row.get("release_status", "ready"),
    )


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
