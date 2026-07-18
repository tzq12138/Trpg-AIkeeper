import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from ..models import (
    ActionDraftAnalyzeRequest,
    ActionDraftDTO,
    ActionDraftUpdateRequest,
    ActionReceiptV2,
    ActionStatusEventDTO,
)
from ..events.events_registry import event_type


_ATTACK_WORDS = ("攻击", "射击", "开枪", "砍", "刺", "殴打", "战斗")
_MOVE_WORDS = ("移动", "前往", "走到", "走向", "跑到", "前去", "赶往", "进入", "离开")
_RESOURCE_WORDS = ("使用", "消耗", "喝下", "点燃", "丢弃")
_ROLL_WORDS = ("检定", "掷骰", "投骰", "判定")
_SECRET_WORDS = ("秘密", "偷偷", "瞒着", "私下")
_LOOK_WORDS = ("看看", "观察", "环顾", "阅读", "查阅", "翻查", "检查", "询问", "交谈", "搜索")
_LUCK_SPEND_WORDS = ("花幸运", "消耗幸运", "使用幸运", "幸运改")
_PUSHED_ROLL_WORDS = ("孤注一掷", "重投", "重新检定", "再掷一次")
_AI_INTENT_TYPES = {
    "voice_command",
    "dialogue",
    "skill_check",
    "move",
    "use_item",
    "show_item",
    "combat_action",
    "chase_action",
    "retroactive_item_claim",
}
_AI_CONFIRMATIONS = {
    "attack",
    "dice_roll",
    "irreversible_consequence",
    "luck_spend",
    "movement",
    "pushed_roll",
    "resource_change",
    "secret_action",
    "state_change",
    "stateful_action",
    "visibility_change",
}
_ALLOWED_INTENT_PARAMS = {
    "actionKind",
    "bonusDice",
    "difficulty",
    "encounterId",
    "fromNodeId",
    "itemId",
    "pushed",
    "secretMove",
    "skillName",
    "spendLuck",
    "targetId",
    "targetNodeId",
    "claimedItemName",
    "justificationText",
}
_BACKSTAGE_LINK_PATTERN = re.compile(
    r"[\"“”']?(?:转到|跳转到|前往)\s*(?:(?:条目|节点)\s*)?[（(]?\s*\d+\s*[）)]?[\"“”']?"
)
_BACKSTAGE_PARENTHETICAL_PATTERN = re.compile(
    r"[（(]\s*(?:条目|节点)\s*\d+\s*[）)]"
)
_BACKSTAGE_PREFIXED_REFERENCE_PATTERN = re.compile(r"(?:条目|节点)\s*\d+")
_BACKSTAGE_SUFFIXED_REFERENCE_PATTERN = re.compile(r"(?<!\d)\d+\s*(?:条目|节点)")


def _semantic_intent_type(requested_type: str | None, inferred_type: str) -> str:
    """Treat the player's free-text intent as authoritative over the UI default."""
    return inferred_type if requested_type in (None, "", "dialogue") else requested_type


def redact_backstage_references(value: str) -> str:
    """Keep compiler entry identifiers out of player-facing AI summaries."""
    text = str(value or "")
    text = _BACKSTAGE_LINK_PATTERN.sub("继续前进", text)
    text = _BACKSTAGE_PARENTHETICAL_PATTERN.sub("", text)
    text = _BACKSTAGE_SUFFIXED_REFERENCE_PATTERN.sub("场景", text)
    return _BACKSTAGE_PREFIXED_REFERENCE_PATTERN.sub("场景", text)


def analyze_action_draft(body: ActionDraftAnalyzeRequest) -> ActionDraftDTO:
    text = body.declared_intent.strip()
    intent_type = body.intent_type or "dialogue"
    risk = "medium"
    requirements: list[str] = ["stateful_action"]
    suggested_skill = None
    difficulty = None
    resource_impacts: list[dict] = []
    visibility = "public"
    movement_target = None
    confidence = 0.68
    summary_prefix = "你想执行一项需要确认的行动"

    if body.intent_type == "retroactive_item_claim":
        intent_type = "retroactive_item_claim"
        risk = "medium"
        requirements = ["resource_change", "state_change"]
        resource_impacts = [
            {"kind": "inventory", "direction": "increase", "amount": "pending_rule"}
        ]
        confidence = 0.7
        summary_prefix = "你想根据角色背景主张一件物品"
    elif any(word in text for word in _LUCK_SPEND_WORDS):
        intent_type = _semantic_intent_type(body.intent_type, "skill_check")
        risk = "high"
        requirements = ["luck_spend", "state_change"]
        resource_impacts = [
            {"kind": "luck", "direction": "decrease", "amount": "pending_roll"}
        ]
        confidence = 0.92
        summary_prefix = "你想消耗幸运改变一次失败判定"
    elif any(word in text for word in _PUSHED_ROLL_WORDS):
        intent_type = _semantic_intent_type(body.intent_type, "skill_check")
        risk = "high"
        requirements = ["pushed_roll", "irreversible_consequence"]
        confidence = 0.92
        summary_prefix = "你想孤注一掷重新进行失败判定"
    elif any(word in text for word in _ATTACK_WORDS):
        intent_type = _semantic_intent_type(body.intent_type, "combat_action")
        risk = "high"
        requirements = ["attack", "state_change"]
        suggested_skill = "射击" if any(word in text for word in ("射击", "开枪", "手枪", "步枪")) else "格斗"
        difficulty = "regular"
        confidence = 0.9
        summary_prefix = "你想发起战斗行动"
    elif any(word in text for word in _SECRET_WORDS):
        is_secret_move = any(word in text for word in _MOVE_WORDS)
        intent_type = _semantic_intent_type(
            body.intent_type,
            "move" if is_secret_move else "dialogue",
        )
        risk = "high"
        requirements = (
            ["movement", "secret_action", "state_change"]
            if is_secret_move else ["secret_action", "visibility_change"]
        )
        visibility = "private"
        movement_target = _extract_movement_target(text) if is_secret_move else None
        confidence = 0.86
        summary_prefix = "你想秘密移动角色" if is_secret_move else "你想执行仅自己可见的秘密行动"
    elif any(word in text for word in _MOVE_WORDS):
        intent_type = _semantic_intent_type(body.intent_type, "move")
        risk = "medium"
        requirements = ["movement", "state_change"]
        movement_target = _extract_movement_target(text)
        confidence = 0.82
        summary_prefix = "你想移动角色"
    elif any(word in text for word in _RESOURCE_WORDS):
        intent_type = _semantic_intent_type(body.intent_type, "use_item")
        risk = "medium"
        requirements = ["resource_change", "state_change"]
        resource_impacts = [{"kind": "resource", "direction": "decrease", "amount": "pending_rule"}]
        confidence = 0.78
        summary_prefix = "你想使用或消耗资源"
    elif any(word in text for word in _ROLL_WORDS):
        intent_type = _semantic_intent_type(body.intent_type, "skill_check")
        risk = "medium"
        requirements = ["dice_roll"]
        difficulty = "regular"
        confidence = 0.8
        summary_prefix = "你想进行一次规则判定"
    elif any(word in text for word in _LOOK_WORDS):
        intent_type = body.intent_type or "dialogue"
        risk = "low"
        requirements = []
        confidence = 0.76
        summary_prefix = "你想获取当前场景中的可见信息"

    resolution_route = "local" if confidence >= 0.75 else "host_exception"

    return ActionDraftDTO(
        base_state_version=body.base_state_version,
        intent_type=intent_type,
        declared_intent=text,
        params=_sanitize_intent_params(body.params),
        understanding_summary=f"{summary_prefix}：{text}",
        risk=risk,
        suggested_skill=suggested_skill,
        difficulty=difficulty,
        resource_impacts=resource_impacts,
        visibility=visibility,
        movement_target=movement_target,
        confirmation_requirements=requirements,
        requires_confirmation=bool(requirements),
        confidence=confidence,
        citations=[],
        analysis_source="local_fallback",
        resolution_route=resolution_route,
        ephemeral=body.ephemeral,
    )


def apply_ai_action_analysis(local: ActionDraftDTO, raw: dict) -> ActionDraftDTO:
    if not isinstance(raw, dict):
        return local
    intent_type = raw.get("intent_type")
    if intent_type not in _AI_INTENT_TYPES or local.intent_type in {
        "skill_check",
        "move",
        "use_item",
        "combat_action",
        "chase_action",
        "retroactive_item_claim",
    } or local.risk == "high":
        intent_type = local.intent_type
    risk_order = {"low": 0, "medium": 1, "high": 2}
    ai_risk = raw.get("risk") if raw.get("risk") in risk_order else local.risk
    risk = max((local.risk, ai_risk), key=risk_order.__getitem__)
    visibility_order = {"public": 0, "party": 1, "private": 2}
    ai_visibility = (
        raw.get("visibility")
        if raw.get("visibility") in visibility_order
        else local.visibility
    )
    visibility = (
        max((local.visibility, ai_visibility), key=visibility_order.__getitem__)
    )
    requirements = raw.get("confirmation_requirements")
    if isinstance(requirements, list):
        ai_requirements = [
            item for item in requirements if isinstance(item, str) and item in _AI_CONFIRMATIONS
        ]
        requirements = list(dict.fromkeys([*local.confirmation_requirements, *ai_requirements]))
    else:
        requirements = local.confirmation_requirements
    confidence = raw.get("confidence", local.confidence)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = local.confidence
    difficulty = raw.get("difficulty")
    if difficulty is None or difficulty not in {"regular", "hard", "extreme"}:
        difficulty = local.difficulty
    ai_resource_impacts = raw.get("resource_impacts")
    if not isinstance(ai_resource_impacts, list):
        resource_impacts = local.resource_impacts
    else:
        resource_impacts = [
            *local.resource_impacts,
            *(item for item in ai_resource_impacts if isinstance(item, dict)),
        ][:10]
    citations = raw.get("citations")
    if not isinstance(citations, list):
        citations = local.citations
    else:
        citations = [_sanitize_citation(item) for item in citations if isinstance(item, dict)][:10]
    summary = redact_backstage_references(
        str(raw.get("understanding_summary") or local.understanding_summary)[:500]
    )
    suggested_skill = raw.get("suggested_skill")
    if suggested_skill is None:
        suggested_skill = local.suggested_skill
    else:
        suggested_skill = str(suggested_skill)[:100]
    movement_target = raw.get("movement_target")
    if movement_target is None:
        movement_target = local.movement_target
    else:
        movement_target = str(movement_target)[:200]
    return ActionDraftDTO.model_validate({
        **local.model_dump(mode="json"),
        "intent_type": intent_type,
        "understanding_summary": summary,
        "risk": risk,
        "suggested_skill": suggested_skill,
        "difficulty": difficulty,
        "resource_impacts": resource_impacts,
        "visibility": visibility,
        "movement_target": movement_target,
        "confirmation_requirements": requirements,
        "requires_confirmation": bool(requirements),
        "confidence": confidence,
        "citations": citations,
        "analysis_source": "configured_provider",
        "resolution_route": "ai" if confidence >= 0.75 else "host_exception",
    })


def _sanitize_citation(value: dict) -> dict:
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


def _sanitize_intent_params(value: dict) -> dict:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if key in _ALLOWED_INTENT_PARAMS}


def persist_action_draft(conn, character: dict, draft: ActionDraftDTO) -> ActionDraftDTO:
    draft_id = str(uuid.uuid4())
    revision_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    payload = draft.model_dump(mode="json")
    with conn.transaction() as tx:
        tx.execute(
            "INSERT INTO action_drafts (draft_id, room_id, character_id, base_state_version, intent_type, declared_intent, params, "
            "status, risk_level, analysis, current_revision, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s)",
            (
                draft_id,
                character["room_id"],
                character["character_id"],
                draft.base_state_version,
                draft.intent_type,
                draft.declared_intent,
                json.dumps(draft.params, ensure_ascii=False),
                draft.status,
                draft.risk,
                json.dumps(payload, ensure_ascii=False),
                expires_at,
            ),
        )
        tx.execute(
            "INSERT INTO action_draft_revisions (revision_id, draft_id, revision_number, declared_intent, analysis) "
            "VALUES (%s, %s, 1, %s, %s)",
            (revision_id, draft_id, draft.declared_intent, json.dumps(payload, ensure_ascii=False)),
        )
    return draft.model_copy(update={"draft_id": draft_id})


def get_current_action_draft(conn, character: dict) -> ActionDraftDTO | None:
    row = conn.execute(
        "SELECT action_drafts.* FROM action_drafts "
        "JOIN rooms ON rooms.room_id = action_drafts.room_id "
        "WHERE action_drafts.character_id = %s "
        "AND action_drafts.status = 'awaiting_confirmation' "
        "AND action_drafts.base_state_version = rooms.state_version "
        "AND action_drafts.expires_at > NOW() "
        "ORDER BY action_drafts.updated_at DESC LIMIT 1",
        (character["character_id"],),
    ).fetchone()
    if not row:
        return None
    analysis = _json_value(row.get("analysis")) or {}
    if not isinstance(analysis, dict):
        return None
    return ActionDraftDTO.model_validate({
        **analysis,
        "draft_id": row["draft_id"],
        "revision": int(row.get("current_revision") or 1),
        "base_state_version": int(row.get("base_state_version") or 0),
        "status": row["status"],
        "intent_type": row["intent_type"],
        "declared_intent": row["declared_intent"],
        "params": _json_value(row.get("params")) or {},
        "risk": row["risk_level"],
        "ephemeral": False,
    })


def revise_action_draft(conn, character: dict, draft_id: str, body: ActionDraftUpdateRequest) -> ActionDraftDTO:
    with conn.transaction() as tx:
        row = _get_owned_draft(tx, character["character_id"], draft_id, for_update=True)
        if row["status"] not in ("analyzing", "awaiting_confirmation"):
            raise ActionDraftError(409, {"code": "draft_not_editable"})
        revision = row["current_revision"] + 1
        previous_analysis = _json_value(row.get("analysis")) or {}
        analyzed = analyze_action_draft(
            ActionDraftAnalyzeRequest(
                declared_intent=body.declared_intent,
                intent_type=body.intent_type,
                base_state_version=body.base_state_version or row.get("base_state_version", 0),
                params=body.params if body.params is not None else previous_analysis.get("params", {}),
            )
        ).model_copy(update={"draft_id": draft_id, "revision": revision})
        payload = analyzed.model_dump(mode="json")
        tx.execute(
            "UPDATE action_drafts SET base_state_version = %s, intent_type = %s, declared_intent = %s, params = %s, status = %s, "
            "risk_level = %s, analysis = %s, current_revision = %s, updated_at = NOW() "
            "WHERE draft_id = %s",
            (
                analyzed.base_state_version,
                analyzed.intent_type,
                analyzed.declared_intent,
                json.dumps(analyzed.params, ensure_ascii=False),
                analyzed.status,
                analyzed.risk,
                json.dumps(payload, ensure_ascii=False),
                revision,
                draft_id,
            ),
        )
        tx.execute(
            "INSERT INTO action_draft_revisions "
            "(revision_id, draft_id, revision_number, declared_intent, analysis) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                draft_id,
                revision,
                analyzed.declared_intent,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
    return analyzed


def cancel_action_draft(conn, character: dict, draft_id: str) -> None:
    cursor = conn.execute(
        "UPDATE action_drafts SET status = 'canceled', updated_at = NOW() "
        "WHERE draft_id = %s AND character_id = %s AND status IN ('analyzing', 'awaiting_confirmation')",
        (draft_id, character["character_id"]),
    )
    if cursor.rowcount == 0:
        existing = conn.execute(
            "SELECT draft_id FROM action_drafts WHERE draft_id = %s AND character_id = %s",
            (draft_id, character["character_id"]),
        ).fetchone()
        if not existing:
            raise ActionDraftError(404, {"code": "draft_not_found"})
        raise ActionDraftError(409, {"code": "draft_not_cancelable"})


def confirm_action_draft(
    conn,
    character: dict,
    draft_id: str,
    idempotency_key: str,
    confirmations: list[str],
) -> ActionReceiptV2:
    existing = conn.execute(
        "SELECT action_id, draft_id FROM actions WHERE character_id = %s AND idempotency_key = %s",
        (character["character_id"], idempotency_key),
    ).fetchone()
    if existing:
        if existing.get("draft_id") != draft_id:
            raise ActionDraftError(409, {"code": "idempotency_key_reused"})
        return build_action_receipt(conn, character["character_id"], existing["action_id"])

    with conn.transaction() as tx:
        tx.execute(
            "SELECT character_id FROM characters WHERE character_id = %s FOR UPDATE",
            (character["character_id"],),
        ).fetchone()
        existing = tx.execute(
            "SELECT action_id, draft_id FROM actions WHERE character_id = %s AND idempotency_key = %s",
            (character["character_id"], idempotency_key),
        ).fetchone()
        if existing:
            if existing.get("draft_id") != draft_id:
                raise ActionDraftError(409, {"code": "idempotency_key_reused"})
            existing_action_id = existing["action_id"]
        else:
            existing_action_id = None
        if existing_action_id:
            return build_action_receipt(
                tx,
                character["character_id"],
                existing_action_id,
            )
        draft = _get_owned_draft(tx, character["character_id"], draft_id, for_update=True)
        if draft["status"] != "awaiting_confirmation":
            raise ActionDraftError(409, {"code": "draft_not_confirmable"})
        analysis = _json_value(draft.get("analysis")) or {}
        required = analysis.get("confirmation_requirements") or []
        missing = [item for item in required if item not in confirmations]
        if missing:
            raise ActionDraftError(409, {"code": "confirmation_required", "missing": missing})

        room = tx.execute(
            "SELECT status, state_version FROM rooms WHERE room_id = %s FOR UPDATE",
            (character["room_id"],),
        ).fetchone()
        if not room or room["status"] in {"completed", "archived"}:
            raise ActionDraftError(409, {"code": "room_not_active"})
        if room and draft.get("base_state_version", 0) != room.get("state_version", 0):
            raise ActionDraftError(
                409,
                {
                    "code": "sync_required",
                    "base_state_version": draft.get("base_state_version", 0),
                    "current_state_version": room.get("state_version", 0),
                },
            )
        turn_id = None
        if room and room["status"] == "active":
            turn_id = _ensure_collecting_turn(tx, character["room_id"])
            submitted = tx.execute(
                "SELECT action_id FROM actions WHERE turn_id = %s AND character_id = %s "
                "AND status NOT IN ('rejected', 'canceled', 'timeout')",
                (turn_id, character["character_id"]),
            ).fetchone()
            if submitted:
                raise ActionDraftError(
                    409,
                    {"code": "action_already_submitted", "action_id": submitted["action_id"]},
                )

        action_params = _json_value(draft.get("params")) or {}
        action_params["analysis"] = analysis
        action_params["confirmations"] = confirmations
        director_plan = action_params.get("director_plan")
        exception_reason = (
            director_plan.get("exception_reason")
            if isinstance(director_plan, dict)
            else None
        ) or "ambiguous_without_ai"
        action_id = str(uuid.uuid4())
        tx.execute(
            "INSERT INTO actions (action_id, room_id, character_id, draft_id, idempotency_key, "
            "revision_number, turn_id, intent_type, declared_intent, params, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued')",
            (
                action_id,
                character["room_id"],
                character["character_id"],
                draft_id,
                idempotency_key,
                draft["current_revision"],
                turn_id,
                draft["intent_type"],
                draft["declared_intent"],
                json.dumps(action_params, ensure_ascii=False),
            ),
        )
        tx.execute(
            "UPDATE action_drafts SET status = 'confirmed', updated_at = NOW() WHERE draft_id = %s",
            (draft_id,),
        )
        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, 'queued', %s)",
            (action_id, json.dumps({"draft_id": draft_id}, ensure_ascii=False)),
        )
        if isinstance(director_plan, dict):
            tx.execute(
                "INSERT INTO events (room_id, event_type, audience, payload) "
                "VALUES (%s, %s, 'host', %s)",
                (
                    character["room_id"],
                    event_type("s2c_director_plan_validated"),
                    json.dumps(
                        {
                            "actionId": action_id,
                            "draftId": draft_id,
                            "contextVersion": director_plan.get("context_version"),
                            "statePatchAuthority": "advisory_only",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        if analysis.get("resolution_route") == "host_exception":
            tx.execute(
                "UPDATE actions SET status = 'awaiting_host_exception' WHERE action_id = %s",
                (action_id,),
            )
            tx.execute(
                "INSERT INTO action_status_events (action_id, status, metadata) "
                "VALUES (%s, 'resolving', %s)",
                (action_id, json.dumps({"source": "local_fallback"}, ensure_ascii=False)),
            )
            tx.execute(
                "INSERT INTO action_status_events (action_id, status, metadata) "
                "VALUES (%s, 'awaiting_host_exception', %s)",
                (
                    action_id,
                    json.dumps(
                        {"reason_code": exception_reason, "ai_stage": "recovering"},
                        ensure_ascii=False,
                    ),
                ),
            )
            tx.execute(
                "INSERT INTO events (room_id, event_type, audience, payload) "
                "VALUES (%s, %s, 'host', %s)",
                (
                    character["room_id"],
                    event_type("s2c_action_exception_requested"),
                    json.dumps(
                        {
                            "actionId": action_id,
                            "characterId": character["character_id"],
                            "reasonCode": exception_reason,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            tx.execute(
                "INSERT INTO events (room_id, event_type, audience, payload) "
                "VALUES (%s, %s, 'player', %s)",
                (
                    character["room_id"],
                    event_type("s2c_ai_recovery_required"),
                    json.dumps(
                        {
                            "actionId": action_id,
                            "characterId": character["character_id"],
                            "reasonCode": exception_reason,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
    return build_action_receipt(conn, character["character_id"], action_id)


def cancel_action(conn, character_id: str, action_id: str) -> ActionReceiptV2:
    with conn.transaction() as tx:
        action = tx.execute(
            "SELECT action_id, status, params FROM actions "
            "WHERE action_id = %s AND character_id = %s FOR UPDATE",
            (action_id, character_id),
        ).fetchone()
        if not action:
            raise ActionDraftError(404, {"code": "action_not_found"})
        if not _can_cancel_action_record(action):
            raise ActionDraftError(409, {"code": "action_not_cancelable"})
        tx.execute(
            "UPDATE actions SET status = 'canceled', canceled_at = NOW() WHERE action_id = %s",
            (action_id,),
        )
        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, 'canceled', '{}')",
            (action_id,),
        )
    return build_action_receipt(conn, character_id, action_id)


def build_action_receipt(conn, character_id: str, action_id: str) -> ActionReceiptV2:
    action = conn.execute(
        "SELECT action_id, draft_id, revision_number, declared_intent, status, params, result, receipt "
        "FROM actions WHERE action_id = %s AND character_id = %s",
        (action_id, character_id),
    ).fetchone()
    if not action:
        raise ActionDraftError(404, {"code": "action_not_found"})
    rows = conn.execute(
        "SELECT status, metadata, created_at FROM action_status_events "
        "WHERE action_id = %s ORDER BY status_event_id",
        (action_id,),
    ).fetchall()
    timeline = [
        ActionStatusEventDTO(
            status=row["status"],
            metadata=_json_value(row.get("metadata")) or {},
            created_at=str(row["created_at"]),
        )
        for row in rows
    ]
    status = action["status"]
    return ActionReceiptV2(
        action_id=action["action_id"],
        draft_id=action.get("draft_id"),
        status=status,
        declared_intent=action.get("declared_intent") or "",
        revision=action.get("revision_number") or 1,
        result=_sanitize_player_action_result(_json_value(action.get("result"))),
        timeline=timeline,
        can_cancel=_can_cancel_action_record(action),
        can_review=status in (
            "resolving",
            "awaiting_player_choice",
            "awaiting_host_exception",
            "completed",
            "resolved",
            "rejected",
            "timeout",
            "sync_required",
        ),
        rule_explanation=_json_value(action.get("receipt")),
    )


def _can_cancel_action_record(action: dict) -> bool:
    if action.get("status") in ("queued", "batched"):
        return True
    if action.get("status") != "awaiting_host_exception":
        return False
    params = _json_value(action.get("params")) or {}
    analysis = _json_value(params.get("analysis")) or {}
    progression = analysis.get("semantic_progression") or {}
    return progression.get("reason") == "semantic_progression_evidence_required"


class ActionDraftError(Exception):
    def __init__(self, status_code: int, detail: dict):
        super().__init__(detail.get("code", "action_draft_error"))
        self.status_code = status_code
        self.detail = detail


def _sanitize_player_action_result(value):
    if not isinstance(value, dict):
        return value
    sanitized = dict(value)
    metadata = sanitized.get("metadata")
    if isinstance(metadata, dict):
        metadata = dict(metadata)
        hidden_modifiers = metadata.get("hidden_modifiers")
        if isinstance(hidden_modifiers, list):
            metadata["hidden_modifiers"] = [
                {
                    key: item
                    for key, item in modifier.items()
                    if key != "source"
                }
                | {"source": "hidden"}
                for modifier in hidden_modifiers
                if isinstance(modifier, dict)
            ]
        sanitized["metadata"] = metadata
    return sanitized


def _get_owned_draft(conn, character_id: str, draft_id: str, for_update: bool = False):
    suffix = " FOR UPDATE" if for_update else ""
    row = conn.execute(
        "SELECT * FROM action_drafts WHERE draft_id = %s AND character_id = %s" + suffix,
        (draft_id, character_id),
    ).fetchone()
    if not row:
        raise ActionDraftError(404, {"code": "draft_not_found"})
    return row


def _ensure_collecting_turn(conn, room_id: str) -> str:
    turn = conn.execute(
        "SELECT turn_id FROM room_turns WHERE room_id = %s AND status = 'collecting' "
        "ORDER BY turn_index DESC LIMIT 1 FOR UPDATE",
        (room_id,),
    ).fetchone()
    if turn:
        return turn["turn_id"]
    max_row = conn.execute(
        "SELECT COALESCE(MAX(turn_index), 0) AS max_idx FROM room_turns WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    room = conn.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    turn_id = str(uuid.uuid4())[:8]
    conn.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, base_state_version) "
        "VALUES (%s, %s, %s, 'collecting', %s)",
        (
            turn_id,
            room_id,
            max_row["max_idx"] + 1,
            int(room["state_version"]) if room else 0,
        ),
    )
    return turn_id


def _json_value(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _extract_movement_target(text: str) -> str | None:
    match = re.search(r"(?:移动到|前往|走到|走向|跑到|前去|赶往|进入)\s*([^，。！？]+)", text)
    if not match:
        return None
    target = match.group(1).strip()
    return target or None
