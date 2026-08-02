import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import (
    ActionDraftAnalyzeRequest,
    ActionDraftDTO,
    ActionDraftStepDTO,
    ActionDraftUpdateRequest,
    ActionReceiptV2,
    ActionStatusEventDTO,
    IntentContractDTO,
)
from ..events.events_registry import event_type


_ATTACK_WORDS = ("攻击", "射击", "开枪", "砍", "刺", "殴打", "战斗")
_MOVE_WORDS = ("移动", "前往", "走到", "走向", "跑到", "前去", "赶往", "进入", "离开")
_RESOURCE_WORDS = ("使用", "消耗", "喝下", "点燃", "丢弃")
_ROLL_WORDS = ("检定", "掷骰", "投骰", "判定")
_SECRET_WORDS = ("秘密", "偷偷", "瞒着", "私下")
_INNER_THOUGHT_WORDS = ("心里", "内心", "心想", "默想")
_LOOK_WORDS = ("看看", "观察", "环顾", "阅读", "查阅", "翻查", "检查", "询问", "交谈", "搜索")
_LUCK_SPEND_WORDS = ("花幸运", "消耗幸运", "使用幸运", "幸运改")
_PUSHED_ROLL_WORDS = ("孤注一掷", "重投", "重新检定", "再掷一次")
_PREPARED_CONDITION_WORDS = ("如果", "若", "一旦", "当", "等到")
_PREPARED_TRIGGER_KINDS = {
    "enemy_public_attack_declared",
    "enemy_enters_melee_range",
    "ally_publicly_hurt",
    "combat_started",
}
_PREPARED_REACTION_KINDS = {"take_cover", "withdraw", "protect_ally"}
_AI_INTENT_TYPES = {
    "voice_command",
    "dialogue",
    "skill_check",
    "move",
    "use_item",
    "show_item",
    "combat_action",
    "chase_action",
    "prepared_action",
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
    "prepared_action",
    "visibility_change",
}
_ALLOWED_INTENT_PARAMS = {
    "actionKind",
    "bonusDice",
    "collaborationContractId",
    "dependsOnCharacterIds",
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
    "triggerKind",
    "reactionKind",
    "nonMechanical",
    "policyDisclosures",
    "policyOutcome",
    "policyReason",
    "timeoutChoice",
}
_COMPOSITE_STEP_INTENT_TYPES = {
    "dialogue",
    "skill_check",
    "move",
    "use_item",
    "show_item",
    "combat_action",
    "chase_action",
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


def _infer_prepared_action_params(text: str) -> dict:
    if not any(word in text for word in _PREPARED_CONDITION_WORDS):
        return {}
    if any(word in text for word in ("公开攻击", "开枪攻击", "向我开枪", "敌人攻击")):
        trigger_kind = "enemy_public_attack_declared"
    elif any(word in text for word in ("进入近战", "靠近我", "逼近", "贴近")):
        trigger_kind = "enemy_enters_melee_range"
    elif any(word in text for word in ("队友受伤", "盟友受伤", "同伴受伤")):
        trigger_kind = "ally_publicly_hurt"
    elif any(word in text for word in ("战斗开始", "开战", "遭遇开始")):
        trigger_kind = "combat_started"
    else:
        return {}
    if any(word in text for word in ("躲", "掩体", "柱子", "防御")):
        reaction_kind = "take_cover"
    elif any(word in text for word in ("撤退", "后退", "撤离", "逃离")):
        reaction_kind = "withdraw"
    else:
        return {}
    return {
        "triggerKind": trigger_kind,
        "reactionKind": reaction_kind,
    }


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
    prepared_params: dict = {}
    is_inner_thought = any(word in text for word in _INNER_THOUGHT_WORDS) and not any(
        word in text
        for word in (
            *_ATTACK_WORDS,
            *_MOVE_WORDS,
            *_RESOURCE_WORDS,
            *_ROLL_WORDS,
            *_LUCK_SPEND_WORDS,
            *_PUSHED_ROLL_WORDS,
        )
    )

    inferred_prepared_params = _infer_prepared_action_params(text)
    if is_inner_thought:
        intent_type = "dialogue"
        risk = "low"
        requirements = []
        visibility = "private"
        confidence = 0.95
        summary_prefix = "你在表达仅自己可见的内心感受，不产生机械效果"
    elif body.intent_type == "prepared_action" or inferred_prepared_params:
        intent_type = "prepared_action"
        prepared_params = _sanitize_prepared_action_params(body.params) or inferred_prepared_params
        risk = "high"
        requirements = ["prepared_action", "state_change"]
        confidence = 0.86 if prepared_params else 0.45
        summary_prefix = "你想预先布置一个只由公开规则事件触发的反应"
    elif body.intent_type == "retroactive_item_claim":
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
    intent_contract = _build_intent_contract(
        text,
        intent_type=intent_type,
        suggested_skill=suggested_skill,
        resource_impacts=resource_impacts,
        visibility=visibility,
        movement_target=movement_target,
        params=body.params,
    )
    clarification_required = risk == "high" and bool(intent_contract.ambiguities)
    if clarification_required:
        requirements = []
        resolution_route = "host_exception"

    params = prepared_params if intent_type == "prepared_action" else _sanitize_intent_params(body.params)
    if is_inner_thought:
        params["nonMechanical"] = True
    draft = ActionDraftDTO(
        base_state_version=body.base_state_version,
        status="analyzing" if clarification_required else "awaiting_confirmation",
        intent_type=intent_type,
        declared_intent=text,
        params=params,
        understanding_summary=f"{summary_prefix}：{text}",
        risk=risk,
        intent_contract=intent_contract,
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
        adjudication_stage=(
            "player_clarification_required" if clarification_required else "local_analysis"
        ),
    )
    return apply_engine_action_policy(draft)


def apply_engine_action_policy(
    draft: ActionDraftDTO,
    *,
    current_state: dict[str, Any] | None = None,
    risk_contract: dict[str, Any] | None = None,
) -> ActionDraftDTO:
    from ..engine.action_policy import evaluate_action_policy

    decision = evaluate_action_policy(
        {
            "intent_type": draft.intent_type,
            "declared_intent": draft.declared_intent,
            "visibility": draft.visibility,
            "target": draft.intent_contract.target or draft.movement_target,
            "params": draft.params,
            "ambiguities": draft.intent_contract.ambiguities,
            "ambiguity_scope": draft.params.get("ambiguityScope"),
            "candidate_interpretations": draft.candidate_interpretations,
        },
        current_state=current_state or {},
        risk_contract=risk_contract or {},
    )
    params = dict(draft.params)
    if decision.outcome == "allow":
        if not decision.disclosures:
            return draft
        params["policyDisclosures"] = decision.disclosures
        return draft.model_copy(update={"params": params})
    params["policyOutcome"] = decision.outcome
    if decision.reason_code:
        params["policyReason"] = decision.reason_code
    return draft.model_copy(
        update={
            "status": "analyzing",
            "params": params,
            "resource_impacts": [],
            "confirmation_requirements": [],
            "requires_confirmation": False,
            "resolution_route": "local",
            "candidate_interpretations": decision.candidates[:3],
            "adjudication_stage": "player_clarification_required",
        }
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
    alternative_skills = _sanitize_alternative_skills(
        raw.get("alternative_skills"),
        suggested_skill,
    )
    composite_steps = _sanitize_composite_steps(raw.get("action_steps"), local)
    movement_target = raw.get("movement_target")
    if movement_target is None:
        movement_target = local.movement_target
    else:
        movement_target = str(movement_target)[:200]
    intent_contract = _sanitize_intent_contract(
        raw.get("intent_contract"),
        local.intent_contract,
    )
    clarification_required = risk == "high" and bool(intent_contract.ambiguities)
    return ActionDraftDTO.model_validate({
        **local.model_dump(mode="json"),
        "intent_type": intent_type,
        "understanding_summary": summary,
        "risk": risk,
        "intent_contract": intent_contract.model_dump(mode="json"),
        "suggested_skill": suggested_skill,
        "alternative_skills": alternative_skills,
        "composite_steps": composite_steps,
        "difficulty": difficulty,
        "resource_impacts": resource_impacts,
        "visibility": visibility,
        "movement_target": movement_target,
        "status": "analyzing" if clarification_required else local.status,
        "confirmation_requirements": [] if clarification_required else requirements,
        "requires_confirmation": (
            False if clarification_required
            else bool(requirements) or bool(alternative_skills) or bool(composite_steps)
        ),
        "confidence": confidence,
        "citations": citations,
        "analysis_source": "configured_provider",
        "resolution_route": (
            "host_exception" if clarification_required
            else "ai" if confidence >= 0.75 else "host_exception"
        ),
        "adjudication_stage": (
            "player_clarification_required" if clarification_required
            else local.adjudication_stage
        ),
    })


def apply_room_runtime_policy(
    conn,
    room_id: str,
    draft: ActionDraftDTO,
) -> ActionDraftDTO:
    if draft.resolution_route != "host_exception":
        return draft
    row = conn.execute(
        "SELECT packages.runtime_package FROM rooms "
        "LEFT JOIN runtime_package_versions AS packages "
        "ON packages.runtime_package_version_id = rooms.runtime_package_version_id "
        "WHERE rooms.room_id = %s",
        (room_id,),
    ).fetchone()
    runtime_package = _json_value(row.get("runtime_package") if row else None) or {}
    runtime_policy = _json_value(runtime_package.get("runtime_policy")) or {}
    if runtime_policy.get("session_mode") != "ai_only":
        return draft

    ambiguities = list(draft.intent_contract.ambiguities)
    if not ambiguities:
        ambiguities.append("目标、方法或规则影响仍需玩家明确")
    intent_contract = draft.intent_contract.model_copy(
        update={"ambiguities": ambiguities[:8]}
    )
    candidates = list(draft.candidate_interpretations)
    if len(candidates) < 2:
        candidates = [
            {
                "label": "补充具体目标、方法与愿意承担的风险",
                "interpreted_intent": "clarify_action",
            },
            {
                "label": "取消本次行动，不产生任何效果",
                "interpreted_intent": "cancel_action",
            },
        ]
    return draft.model_copy(
        update={
            "status": "analyzing",
            "intent_contract": intent_contract,
            "confirmation_requirements": [],
            "requires_confirmation": False,
            "resolution_route": "local",
            "candidate_interpretations": candidates[:3],
            "adjudication_stage": "player_clarification_required",
        }
    )


def _build_intent_contract(
    text: str,
    *,
    intent_type: str,
    suggested_skill: str | None,
    resource_impacts: list[dict],
    visibility: str,
    movement_target: str | None,
    params: dict[str, Any] | None,
) -> IntentContractDTO:
    target = movement_target or _extract_intent_target(text)
    method = suggested_skill or {
        "move": "移动",
        "use_item": "使用物品",
        "skill_check": "检定",
        "combat_action": "战斗行动",
        "chase_action": "追逐行动",
    }.get(intent_type)
    raw_params = params if isinstance(params, dict) else {}
    object_name = next(
        (
            str(raw_params[key]).strip()[:200]
            for key in ("itemName", "item", "object", "target")
            if isinstance(raw_params.get(key), str) and raw_params[key].strip()
        ),
        None,
    )
    conditions = [
        f"如果{match.strip()[:120]}"
        for match in re.findall(r"(?:如果|若|当)([^，,。；;]{1,120})", text)
        if match.strip()
    ][:8]
    constraints = []
    if visibility == "private":
        constraints.append("保持私密")
    if "不要" in text or "不惊动" in text:
        constraints.append("避免引起额外注意")
    resources = [
        str(impact.get("kind") or impact.get("resource") or "资源")[:100]
        for impact in resource_impacts
        if isinstance(impact, dict)
    ][:8]
    ambiguities = []
    if not target and any(marker in text for marker in ("它", "他", "她", "那里", "那个")):
        ambiguities.append("目标指代不明确")
    return IntentContractDTO(
        target=target,
        method=method,
        object=object_name,
        constraints=list(dict.fromkeys(constraints)),
        resources=list(dict.fromkeys(resources)),
        conditions=list(dict.fromkeys(conditions)),
        visibility=visibility if visibility in {"public", "party", "private"} else "public",
        ambiguities=ambiguities,
    )


def _extract_intent_target(text: str) -> str | None:
    patterns = (
        r"(?:朝|向|对)([^，,。；;]{1,80}?)(?:射击|开枪|攻击|砍|刺|殴打)",
        r"(?:检查|观察|搜索|询问|阅读)([^，,。；;]{1,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match and match.group(1).strip():
            return match.group(1).strip()[:200]
    return None


def _sanitize_intent_contract(
    value: Any,
    fallback: IntentContractDTO,
) -> IntentContractDTO:
    raw = value if isinstance(value, dict) else {}

    def clean_text(key: str, fallback_value: str | None) -> str | None:
        candidate = raw.get(key)
        if not isinstance(candidate, str) or not candidate.strip():
            return fallback_value
        return redact_backstage_references(candidate.strip()[:200])

    def clean_list(key: str, fallback_values: list[str]) -> list[str]:
        candidate = raw.get(key)
        if not isinstance(candidate, list):
            return fallback_values
        values = [
            redact_backstage_references(item.strip()[:200])
            for item in candidate
            if isinstance(item, str) and item.strip()
        ]
        return list(dict.fromkeys(values))[:8] or fallback_values

    visibility_order = {"public": 0, "party": 1, "private": 2}
    candidate_visibility = raw.get("visibility")
    if candidate_visibility not in visibility_order:
        candidate_visibility = fallback.visibility
    visibility = max((fallback.visibility, candidate_visibility), key=visibility_order.__getitem__)
    return IntentContractDTO(
        target=clean_text("target", fallback.target),
        method=clean_text("method", fallback.method),
        object=clean_text("object", fallback.object),
        constraints=clean_list("constraints", fallback.constraints),
        resources=clean_list("resources", fallback.resources),
        conditions=clean_list("conditions", fallback.conditions),
        visibility=visibility,
        ambiguities=clean_list("ambiguities", fallback.ambiguities),
    )


def _sanitize_alternative_skills(value: Any, suggested_skill: str | None) -> list[str]:
    if not isinstance(value, list):
        return []
    candidates: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()[:100]
        if not normalized or normalized == suggested_skill or normalized in candidates:
            continue
        candidates.append(normalized)
        if len(candidates) >= 2:
            break
    return candidates


def _sanitize_composite_steps(value: Any, local: ActionDraftDTO) -> list[ActionDraftStepDTO]:
    if not isinstance(value, list) or len(value) < 2:
        return []
    steps: list[ActionDraftStepDTO] = []
    for index, item in enumerate(value[:2], start=1):
        if not isinstance(item, dict):
            return []
        intent_type = str(item.get("intent_type") or "").strip()
        if intent_type not in _COMPOSITE_STEP_INTENT_TYPES:
            return []
        step_id = str(item.get("step_id") or f"step_{index}").strip()[:80]
        summary = redact_backstage_references(
            str(item.get("summary") or item.get("declared_intent") or "").strip()[:500]
        )
        declared_intent = redact_backstage_references(
            str(item.get("declared_intent") or summary).strip()[:2000]
        )
        if not step_id or not summary or not declared_intent or any(
            existing.step_id == step_id for existing in steps
        ):
            return []
        params = _sanitize_intent_params(item.get("params") or {})
        if index == 1:
            intent_type = local.intent_type
            params = {**local.params, **params}
        failure_policy = str(item.get("on_previous_failure") or "cancel")
        if failure_policy not in {"cancel", "continue"}:
            failure_policy = "cancel"
        execution_condition = str(item.get("execution_condition") or (
            "always" if failure_policy == "continue" else "previous_step_success"
        ))
        if execution_condition not in {
            "always",
            "previous_step_success",
            "previous_step_failure",
        }:
            return []
        if execution_condition == "always":
            failure_policy = "continue"
        steps.append(
            ActionDraftStepDTO(
                step_id=step_id,
                summary=summary,
                declared_intent=declared_intent,
                intent_type=intent_type,
                params=params,
                execution_condition=(execution_condition if index == 2 else "always"),
                on_previous_failure=failure_policy if index == 2 else "cancel",
            )
        )
    return steps if len(steps) == 2 else []


def _apply_selected_skill(
    action_params: dict[str, Any],
    analysis: dict[str, Any],
    selected_skill: str | None,
) -> None:
    alternatives = _sanitize_alternative_skills(
        analysis.get("alternative_skills"),
        str(analysis.get("suggested_skill") or "") or None,
    )
    if not alternatives:
        if selected_skill is not None:
            raise ActionDraftError(409, {"code": "skill_selection_invalid"})
        return

    selected = str(selected_skill or "").strip()
    if not selected:
        raise ActionDraftError(409, {"code": "skill_selection_required"})
    suggested = str(analysis.get("suggested_skill") or "").strip()
    if selected not in {suggested, *alternatives}:
        raise ActionDraftError(409, {"code": "skill_selection_invalid"})
    action_params["skillName"] = selected


def _apply_composite_steps(
    action_params: dict[str, Any],
    analysis: dict[str, Any],
    selected_order: list[str],
) -> None:
    raw_steps = analysis.get("composite_steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        if selected_order:
            raise ActionDraftError(409, {"code": "composite_order_invalid"})
        return
    try:
        steps = [ActionDraftStepDTO.model_validate(item) for item in raw_steps]
    except (TypeError, ValueError):
        raise ActionDraftError(409, {"code": "composite_steps_invalid"}) from None
    if len(steps) != 2 or len({step.step_id for step in steps}) != 2:
        raise ActionDraftError(409, {"code": "composite_steps_invalid"})
    if selected_order:
        if len(selected_order) != 2 or set(selected_order) != {step.step_id for step in steps}:
            raise ActionDraftError(409, {"code": "composite_order_invalid"})
        by_id = {step.step_id: step for step in steps}
        steps = [by_id[step_id] for step_id in selected_order]
    action_params["composite_steps"] = [step.model_dump(mode="json") for step in steps]


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


def _sanitize_prepared_action_params(value: dict) -> dict:
    params = _sanitize_intent_params(value)
    trigger_kind = params.get("triggerKind")
    reaction_kind = params.get("reactionKind")
    if trigger_kind not in _PREPARED_TRIGGER_KINDS or reaction_kind not in _PREPARED_REACTION_KINDS:
        return {}
    prepared_params = {
        "triggerKind": trigger_kind,
        "reactionKind": reaction_kind,
    }
    if reaction_kind == "protect_ally":
        target_id = params.get("targetId")
        if not isinstance(target_id, str) or not target_id.strip():
            return {}
        prepared_params["targetId"] = target_id.strip()
    return prepared_params


def _validated_prepared_action_params(value: dict) -> dict:
    params = _sanitize_prepared_action_params(value)
    if not params:
        raise ActionDraftError(422, {"code": "prepared_action_invalid"})
    return params


def _validate_prepared_action_target(
    tx,
    *,
    room_id: str,
    character_id: str,
    params: dict,
) -> None:
    if params.get("reactionKind") != "protect_ally":
        return
    target_id = params.get("targetId")
    if not isinstance(target_id, str) or target_id == character_id:
        raise ActionDraftError(422, {"code": "prepared_action_target_invalid"})
    target = tx.execute(
        "SELECT 1 FROM characters WHERE character_id = %s AND room_id = %s",
        (target_id, room_id),
    ).fetchone()
    if not target:
        raise ActionDraftError(422, {"code": "prepared_action_target_invalid"})


def _normalize_collaboration_dependencies(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ActionDraftError(422, {"code": "invalid_collaboration_dependencies"})
    dependencies = [item.strip() for item in value]
    if len(set(dependencies)) != len(dependencies):
        raise ActionDraftError(422, {"code": "duplicate_collaboration_dependency"})
    return dependencies


def _validate_collaboration_draft_params(
    tx,
    *,
    character_id: str,
    previous_params: dict,
    requested_params: dict,
) -> dict:
    contract_id = previous_params.get("collaborationContractId")
    if not isinstance(contract_id, str) or not contract_id:
        return _sanitize_intent_params(requested_params)

    dependencies = _normalize_collaboration_dependencies(
        requested_params.get("dependsOnCharacterIds", previous_params.get("dependsOnCharacterIds"))
    )
    participant_rows = tx.execute(
        "SELECT character_id FROM collaboration_contract_drafts WHERE contract_id = %s",
        (contract_id,),
    ).fetchall()
    participant_ids = {str(item["character_id"]) for item in participant_rows}
    if character_id in dependencies or any(item not in participant_ids for item in dependencies):
        raise ActionDraftError(422, {"code": "collaboration_dependency_not_participant"})

    dependency_graph: dict[str, list[str]] = {participant_id: [] for participant_id in participant_ids}
    draft_rows = tx.execute(
        "SELECT links.character_id, drafts.params FROM collaboration_contract_drafts AS links "
        "JOIN action_drafts AS drafts ON drafts.draft_id = links.draft_id "
        "WHERE links.contract_id = %s FOR UPDATE",
        (contract_id,),
    ).fetchall()
    for item in draft_rows:
        participant_id = str(item["character_id"])
        if participant_id == character_id:
            dependency_graph[participant_id] = dependencies
            continue
        params = _json_value(item.get("params")) or {}
        dependency_graph[participant_id] = _normalize_collaboration_dependencies(
            params.get("dependsOnCharacterIds")
        )
    if _contains_dependency_cycle(dependency_graph):
        raise ActionDraftError(409, {"code": "collaboration_dependency_cycle"})
    params = _sanitize_intent_params(requested_params)
    params["collaborationContractId"] = contract_id
    if dependencies:
        params["dependsOnCharacterIds"] = dependencies
    return params


def _contains_dependency_cycle(graph: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(character_id: str) -> bool:
        if character_id in visiting:
            return True
        if character_id in visited:
            return False
        visiting.add(character_id)
        if any(
            dependency in graph and visit(dependency)
            for dependency in graph.get(character_id, [])
        ):
            return True
        visiting.remove(character_id)
        visited.add(character_id)
        return False

    return any(visit(character_id) for character_id in graph)


def _preserve_collaboration_draft_guards(draft: ActionDraftDTO, params: dict) -> ActionDraftDTO:
    contract_id = params.get("collaborationContractId")
    if not isinstance(contract_id, str) or not contract_id:
        return draft
    intent_contract = draft.intent_contract.model_copy(update={"visibility": "party"})
    requirements = sorted(set([*draft.confirmation_requirements, "collaboration_contract"]))
    return draft.model_copy(
        update={
            "params": params,
            "risk": "high",
            "visibility": "party",
            "intent_contract": intent_contract,
            "requires_confirmation": True,
            "confirmation_requirements": requirements,
        }
    )


def insert_action_draft(
    tx,
    character: dict,
    draft: ActionDraftDTO,
    *,
    draft_id: str | None = None,
    expires_at: datetime | None = None,
) -> str:
    draft_id = draft_id or str(uuid.uuid4())
    revision_id = str(uuid.uuid4())
    expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(days=30))
    payload = draft.model_dump(mode="json")
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
    return draft_id


def persist_action_draft(conn, character: dict, draft: ActionDraftDTO) -> ActionDraftDTO:
    with conn.transaction() as tx:
        draft_id = insert_action_draft(tx, character, draft)
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
        previous_params = _json_value(row.get("params")) or previous_analysis.get("params", {})
        requested_params = body.params if body.params is not None else previous_params
        revision_params = _validate_collaboration_draft_params(
            tx,
            character_id=character["character_id"],
            previous_params=previous_params,
            requested_params=requested_params,
        )
        analyzed = analyze_action_draft(
            ActionDraftAnalyzeRequest(
                declared_intent=body.declared_intent,
                intent_type=body.intent_type,
                base_state_version=body.base_state_version or row.get("base_state_version", 0),
                params=revision_params,
            )
        ).model_copy(update={"draft_id": draft_id, "revision": revision})
        analyzed = _preserve_collaboration_draft_guards(analyzed, revision_params)
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


def _expire_action_draft_if_needed(
    conn,
    character_id: str,
    draft_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT intent_type, declared_intent, params, analysis FROM action_drafts "
        "WHERE draft_id = %s AND character_id = %s "
        "AND status IN ('analyzing', 'awaiting_confirmation') "
        "AND expires_at IS NOT NULL AND expires_at <= NOW()",
        (draft_id, character_id),
    ).fetchone()
    if not row:
        return None
    from ..engine.action_policy import evaluate_action_policy

    params = _json_value(row.get("params")) or {}
    phase = (
        "combat"
        if row["intent_type"] in {"combat_action", "chase_action"}
        else "investigation"
    )
    decision = evaluate_action_policy(
        {
            "intent_type": row["intent_type"],
            "declared_intent": row.get("declared_intent") or "",
            "params": params,
        },
        current_state={"phase": phase},
        risk_contract={},
        timed_out=True,
    )
    analysis = _json_value(row.get("analysis")) or {}
    analysis["timeout_safe_effect"] = decision.safe_effect
    with conn.transaction() as tx:
        cursor = tx.execute(
            "UPDATE action_drafts SET status = 'timeout', analysis = %s, updated_at = NOW() "
            "WHERE draft_id = %s AND character_id = %s "
            "AND status IN ('analyzing', 'awaiting_confirmation') "
            "AND expires_at IS NOT NULL AND expires_at <= NOW()",
            (json.dumps(analysis, ensure_ascii=False), draft_id, character_id),
        )
    if cursor.rowcount == 0:
        return None
    return {
        "code": "draft_timed_out",
        "safe_effect": decision.safe_effect,
    }


def confirm_action_draft(
    conn,
    character: dict,
    draft_id: str,
    idempotency_key: str,
    confirmations: list[str],
    selected_skill: str | None = None,
    composite_step_order: list[str] | None = None,
) -> ActionReceiptV2:
    existing = conn.execute(
        "SELECT action_id, draft_id FROM actions WHERE character_id = %s AND idempotency_key = %s",
        (character["character_id"], idempotency_key),
    ).fetchone()
    if existing:
        if existing.get("draft_id") != draft_id:
            raise ActionDraftError(409, {"code": "idempotency_key_reused"})
        return build_action_receipt(conn, character["character_id"], existing["action_id"])

    timeout_detail = _expire_action_draft_if_needed(
        conn,
        character["character_id"],
        draft_id,
    )
    if timeout_detail:
        raise ActionDraftError(409, timeout_detail)

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
        intent_contract = _json_value(analysis.get("intent_contract")) or {}
        from ..engine.action_policy import evaluate_action_policy

        policy = evaluate_action_policy(
            {
                "intent_type": draft["intent_type"],
                "declared_intent": draft.get("declared_intent") or "",
                "visibility": analysis.get("visibility") or intent_contract.get("visibility"),
                "target": intent_contract.get("target"),
                "params": _json_value(draft.get("params")) or {},
                "ambiguities": intent_contract.get("ambiguities") or [],
                "candidate_interpretations": analysis.get("candidate_interpretations") or [],
            },
            current_state={},
            risk_contract={},
        )
        if policy.outcome != "allow":
            raise ActionDraftError(
                409,
                {
                    "code": "action_policy_rejected",
                    "reason": policy.reason_code,
                },
            )
        required = analysis.get("confirmation_requirements") or []
        missing = [item for item in required if item not in confirmations]
        if missing:
            raise ActionDraftError(409, {"code": "confirmation_required", "missing": missing})

        room = tx.execute(
            "SELECT status, state_version, risk_contract_version, risk_contract_hash "
            "FROM rooms WHERE room_id = %s FOR UPDATE",
            (character["room_id"],),
        ).fetchone()
        if not room or room["status"] in {"completed", "archived"}:
            raise ActionDraftError(409, {"code": "room_not_active"})
        if room["status"] == "active" and room.get("risk_contract_hash"):
            confirmed = tx.execute(
                "SELECT 1 FROM session_zero_confirmations "
                "WHERE room_id = %s AND character_id = %s AND step = 'safety' "
                "AND contract_version = %s AND contract_hash = %s",
                (
                    character["room_id"],
                    character["character_id"],
                    room.get("risk_contract_version"),
                    room.get("risk_contract_hash"),
                ),
            ).fetchone()
            if not confirmed:
                raise ActionDraftError(
                    409,
                    {
                        "code": "risk_contract_confirmation_required",
                        "contract_version": room.get("risk_contract_version"),
                        "contract_hash": room.get("risk_contract_hash"),
                    },
                )
        if room and draft.get("base_state_version", 0) != room.get("state_version", 0):
            raise ActionDraftError(
                409,
                {
                    "code": "sync_required",
                    "base_state_version": draft.get("base_state_version", 0),
                    "current_state_version": room.get("state_version", 0),
                },
            )
        is_prepared_action = draft["intent_type"] == "prepared_action"
        turn_id = None
        if room and room["status"] == "active" and not is_prepared_action:
            if _has_active_combat_turn(tx, character["room_id"]):
                turn_id = _ensure_collecting_turn(tx, character["room_id"])
                submitted = tx.execute(
                    "SELECT action_id FROM actions WHERE turn_id = %s AND character_id = %s "
                    "AND status NOT IN ('rejected', 'canceled', 'timeout')",
                    (turn_id, character["character_id"]),
                ).fetchone()
            else:
                submitted = tx.execute(
                    "SELECT action_id FROM actions WHERE room_id = %s AND character_id = %s "
                    "AND status NOT IN ('completed', 'rejected', 'canceled', 'timeout')",
                    (character["room_id"], character["character_id"]),
                ).fetchone()
            if submitted:
                raise ActionDraftError(
                    409,
                    {"code": "action_already_submitted", "action_id": submitted["action_id"]},
                )

        action_params = _json_value(draft.get("params")) or {}
        if is_prepared_action:
            action_params = _validated_prepared_action_params(action_params)
            _validate_prepared_action_target(
                tx,
                room_id=character["room_id"],
                character_id=character["character_id"],
                params=action_params,
            )
        action_params["analysis"] = analysis
        action_params["confirmations"] = confirmations
        _apply_selected_skill(action_params, analysis, selected_skill)
        _apply_composite_steps(action_params, analysis, composite_step_order or [])
        director_plan = action_params.get("director_plan")
        exception_reason = (
            director_plan.get("exception_reason")
            if isinstance(director_plan, dict)
            else None
        ) or "ambiguous_without_ai"
        action_id = str(uuid.uuid4())
        initial_status = "armed" if is_prepared_action else "queued"
        tx.execute(
            "INSERT INTO actions (action_id, room_id, character_id, draft_id, idempotency_key, "
            "revision_number, turn_id, intent_type, declared_intent, params, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
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
                initial_status,
            ),
        )
        tx.execute(
            "UPDATE action_drafts SET status = 'confirmed', updated_at = NOW() WHERE draft_id = %s",
            (draft_id,),
        )
        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, %s, %s)",
            (action_id, initial_status, json.dumps({"draft_id": draft_id}, ensure_ascii=False)),
        )
        if is_prepared_action:
            try:
                tx.execute(
                    "INSERT INTO prepared_rule_actions "
                    "(action_id, room_id, character_id, trigger_kind, reaction_kind) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        action_id,
                        character["room_id"],
                        character["character_id"],
                        action_params["triggerKind"],
                        action_params["reactionKind"],
                    ),
                )
            except Exception as exc:
                if "idx_prepared_rule_actions_one_armed_per_character" in str(exc):
                    raise ActionDraftError(409, {"code": "prepared_action_already_armed"}) from exc
                raise
        collaboration_contract_id = action_params.get("collaborationContractId")
        if isinstance(collaboration_contract_id, str) and collaboration_contract_id:
            _stage_collaboration_action(
                tx,
                contract_id=collaboration_contract_id,
                room_id=character["room_id"],
                action_id=action_id,
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
        if not collaboration_contract_id and analysis.get("resolution_route") == "host_exception":
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


def _stage_collaboration_action(tx, *, contract_id: str, room_id: str, action_id: str) -> None:
    contract = tx.execute(
        "SELECT room_id, status FROM collaboration_contracts WHERE contract_id = %s FOR UPDATE",
        (contract_id,),
    ).fetchone()
    if (
        not contract
        or contract["room_id"] != room_id
        or contract["status"] != "accepted"
    ):
        raise ActionDraftError(409, {"code": "collaboration_contract_not_active"})
    cursor = tx.execute(
        "UPDATE actions SET status = 'batched' WHERE action_id = %s AND status = 'queued'",
        (action_id,),
    )
    if cursor.rowcount != 1:
        raise ActionDraftError(409, {"code": "collaboration_action_not_batchable"})
    tx.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, 'batched', %s)",
        (
            action_id,
            json.dumps(
                {"contract_id": contract_id, "waiting_for_confirmations": True},
                ensure_ascii=False,
            ),
        ),
    )
    rows = tx.execute(
        "SELECT links.draft_id, links.character_id, actions.action_id, actions.status, actions.params, "
        "participants.invite_order "
        "FROM collaboration_contract_drafts AS links "
        "LEFT JOIN actions ON actions.draft_id = links.draft_id "
        "JOIN collaboration_contract_participants AS participants "
        "ON participants.contract_id = links.contract_id AND participants.character_id = links.character_id "
        "WHERE links.contract_id = %s "
        "ORDER BY participants.invite_order, links.character_id FOR UPDATE OF links",
        (contract_id,),
    ).fetchall()
    action_ids = [str(row["action_id"]) for row in rows if row.get("action_id")]
    if len(action_ids) != len(rows) or any(row.get("status") != "batched" for row in rows):
        return
    action_ids = _bind_and_order_collaboration_dependencies(tx, rows)
    tx.execute(
        "INSERT INTO collaboration_contract_batches (contract_id, room_id, action_ids) "
        "VALUES (%s, %s, %s) ON CONFLICT (contract_id) DO NOTHING",
        (contract_id, room_id, json.dumps(action_ids, ensure_ascii=False)),
    )
    for linked_action_id in action_ids:
        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, 'batched', %s)",
            (
                linked_action_id,
                json.dumps(
                    {"contract_id": contract_id, "all_confirmations_received": True},
                    ensure_ascii=False,
                ),
            ),
        )


def _bind_and_order_collaboration_dependencies(tx, rows: list[dict]) -> list[str]:
    action_by_character = {
        str(row["character_id"]): str(row["action_id"])
        for row in rows
    }
    order = [str(row["action_id"]) for row in rows]
    dependencies_by_action: dict[str, list[str]] = {}
    for row in rows:
        action_id = str(row["action_id"])
        params = _json_value(row.get("params")) or {}
        requested_character_ids = _normalize_collaboration_dependencies(
            params.get("dependsOnCharacterIds")
        )
        dependency_action_ids = [
            action_by_character[character_id]
            for character_id in requested_character_ids
            if character_id in action_by_character and action_by_character[character_id] != action_id
        ]
        dependencies_by_action[action_id] = dependency_action_ids
        if dependency_action_ids:
            params["depends_on_action_ids"] = dependency_action_ids
        else:
            params.pop("depends_on_action_ids", None)
        tx.execute(
            "UPDATE actions SET params = %s WHERE action_id = %s",
            (json.dumps(params, ensure_ascii=False), action_id),
        )
    ordered = _stable_topological_action_order(order, dependencies_by_action)
    if ordered is None:
        raise ActionDraftError(409, {"code": "collaboration_dependency_cycle"})
    return ordered


def _stable_topological_action_order(
    action_ids: list[str],
    dependencies_by_action: dict[str, list[str]],
) -> list[str] | None:
    remaining = set(action_ids)
    resolved: set[str] = set()
    ordered: list[str] = []
    while remaining:
        next_action_id = next(
            (
                action_id
                for action_id in action_ids
                if action_id in remaining
                and set(dependencies_by_action.get(action_id, [])).issubset(resolved)
            ),
            None,
        )
        if next_action_id is None:
            return None
        remaining.remove(next_action_id)
        resolved.add(next_action_id)
        ordered.append(next_action_id)
    return ordered


def cancel_action(conn, character_id: str, action_id: str) -> ActionReceiptV2:
    with conn.transaction() as tx:
        action = tx.execute(
            "SELECT action_id, status, params, turn_id FROM actions "
            "WHERE action_id = %s AND character_id = %s FOR UPDATE",
            (action_id, character_id),
        ).fetchone()
        if not action:
            raise ActionDraftError(404, {"code": "action_not_found"})
        if action.get("turn_id"):
            turn = tx.execute(
                "SELECT mode, status FROM room_turns WHERE turn_id = %s FOR UPDATE",
                (action["turn_id"],),
            ).fetchone()
            if turn and turn.get("mode") == "combat" and turn.get("status") in {"resolving", "blocked"}:
                raise ActionDraftError(409, {"code": "action_round_locked"})
        if not _can_cancel_action_record(action):
            raise ActionDraftError(409, {"code": "action_not_cancelable"})
        params = _json_value(action.get("params")) or {}
        contract_id = params.get("collaborationContractId")
        if isinstance(contract_id, str) and contract_id:
            _cancel_collaboration_batch(tx, contract_id)
        else:
            tx.execute(
                "UPDATE actions SET status = 'canceled', canceled_at = NOW() WHERE action_id = %s",
                (action_id,),
            )
            tx.execute(
                "UPDATE prepared_rule_actions SET status = 'canceled' "
                "WHERE action_id = %s AND status = 'armed'",
                (action_id,),
            )
            tx.execute(
                "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, 'canceled', '{}')",
                (action_id,),
            )
    return build_action_receipt(conn, character_id, action_id)


def _cancel_collaboration_batch(tx, contract_id: str) -> None:
    batch = tx.execute(
        "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s FOR UPDATE",
        (contract_id,),
    ).fetchone()
    if batch and batch["status"] == "resolving":
        raise ActionDraftError(409, {"code": "collaboration_batch_locked"})
    tx.execute(
        "UPDATE collaboration_contracts SET status = 'canceled', canceled_at = NOW(), updated_at = NOW() "
        "WHERE contract_id = %s AND status = 'accepted'",
        (contract_id,),
    )
    if batch:
        tx.execute(
            "UPDATE collaboration_contract_batches SET status = 'canceled', updated_at = NOW() "
            "WHERE contract_id = %s AND status = 'queued'",
            (contract_id,),
        )
    rows = tx.execute(
        "SELECT actions.action_id FROM collaboration_contract_drafts AS links "
        "JOIN actions ON actions.draft_id = links.draft_id "
        "WHERE links.contract_id = %s AND actions.status = 'batched' FOR UPDATE",
        (contract_id,),
    ).fetchall()
    for row in rows:
        linked_action_id = row["action_id"]
        tx.execute(
            "UPDATE actions SET status = 'canceled', canceled_at = NOW() "
            "WHERE action_id = %s AND status = 'batched'",
            (linked_action_id,),
        )
        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, 'canceled', %s)",
            (
                linked_action_id,
                json.dumps(
                    {"reason_code": "collaboration_participant_canceled"},
                    ensure_ascii=False,
                ),
            ),
        )
    tx.execute(
        "UPDATE action_drafts SET status = 'canceled', updated_at = NOW() "
        "WHERE draft_id IN (SELECT draft_id FROM collaboration_contract_drafts WHERE contract_id = %s) "
        "AND status = 'awaiting_confirmation'",
        (contract_id,),
    )


def choose_composite_action_continuation(
    conn,
    character_id: str,
    action_id: str,
    proceed: bool,
) -> ActionReceiptV2:
    with conn.transaction() as tx:
        action = tx.execute(
            "SELECT * FROM actions WHERE action_id = %s AND character_id = %s FOR UPDATE",
            (action_id, character_id),
        ).fetchone()
        if not action:
            raise ActionDraftError(404, {"code": "action_not_found"})
        if action["status"] != "awaiting_player_choice":
            raise ActionDraftError(409, {"code": "composite_choice_not_pending"})
        params = _json_value(action.get("params")) or {}
        progress = params.get("composite_progress")
        if (
            not isinstance(progress, dict)
            or not progress.get("pending_step_id")
            or not isinstance(progress.get("first_resolution"), dict)
        ):
            raise ActionDraftError(409, {"code": "composite_choice_not_pending"})
        if progress.get("decision") in {"continue", "cancel"}:
            raise ActionDraftError(409, {"code": "composite_choice_already_submitted"})
        progress["decision"] = "continue" if proceed else "cancel"
        params["composite_progress"] = progress
        tx.execute(
            "UPDATE actions SET params = %s WHERE action_id = %s",
            (json.dumps(params, ensure_ascii=False), action_id),
        )
    return build_action_receipt(conn, character_id, action_id)


def build_action_receipt(conn, character_id: str, action_id: str) -> ActionReceiptV2:
    action = conn.execute(
        "SELECT actions.action_id, actions.room_id, actions.draft_id, actions.revision_number, actions.declared_intent, "
        "actions.status, actions.params, actions.result, actions.receipt, turns.mode AS turn_mode, "
        "turns.status AS turn_status FROM actions LEFT JOIN room_turns AS turns "
        "ON turns.turn_id = actions.turn_id WHERE actions.action_id = %s AND actions.character_id = %s",
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
    result = _sanitize_player_action_result(_json_value(action.get("result")))
    rule_explanation = _json_value(action.get("receipt"))
    transaction_id = None
    room_state = conn.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (action["room_id"],),
    ).fetchone()
    state_version = int(room_state["state_version"]) if room_state else None
    if status in ("completed", "resolved"):
        bundle_row = conn.execute(
            "SELECT actor_projection, rule_explanation, canonical_result, host_console FROM resolution_bundles "
            "WHERE action_id = %s AND character_id = %s AND release_status = 'released'",
            (action_id, character_id),
        ).fetchone()
        if bundle_row:
            actor_projection = _json_value(bundle_row.get("actor_projection")) or {}
            if isinstance(actor_projection, dict):
                if isinstance(actor_projection.get("result"), dict):
                    result = actor_projection["result"]
                elif isinstance(actor_projection.get("action_completed"), dict):
                    result = actor_projection["action_completed"]
            stored_explanation = _json_value(bundle_row.get("rule_explanation"))
            if isinstance(stored_explanation, dict):
                rule_explanation = stored_explanation
            canonical_result = _json_value(bundle_row.get("canonical_result"))
            if isinstance(canonical_result, dict) and isinstance(canonical_result.get("stateVersion"), int):
                state_version = canonical_result["stateVersion"]
            host_projection = _json_value(bundle_row.get("host_console"))
            if isinstance(host_projection, dict) and isinstance(host_projection.get("transactionId"), str):
                transaction_id = host_projection["transactionId"]
    return ActionReceiptV2(
        action_id=action["action_id"],
        transaction_id=transaction_id,
        state_version=state_version,
        draft_id=action.get("draft_id"),
        status=status,
        declared_intent=action.get("declared_intent") or "",
        revision=action.get("revision_number") or 1,
        result=result,
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
        rule_explanation=rule_explanation,
    )


def _can_cancel_action_record(action: dict) -> bool:
    if action.get("turn_mode") == "combat" and action.get("turn_status") in {"resolving", "blocked"}:
        return False
    if action.get("status") in ("queued", "batched", "armed"):
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
    encounter = conn.execute(
        "SELECT encounter_id FROM encounters WHERE room_id = %s AND type = 'combat' AND status = 'active' "
        "ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
        (room_id,),
    ).fetchone()
    encounter_id = encounter["encounter_id"] if encounter else None
    locked_turn = conn.execute(
        "SELECT turn_id FROM room_turns WHERE room_id = %s AND mode = 'combat' "
        "AND status IN ('resolving', 'blocked') "
        "AND (encounter_id = %s OR (encounter_id IS NULL AND %s IS NULL)) "
        "ORDER BY turn_index DESC LIMIT 1 FOR UPDATE",
        (room_id, encounter_id, encounter_id),
    ).fetchone()
    if locked_turn:
        raise ActionDraftError(409, {"code": "action_round_locked"})
    turn = conn.execute(
        "SELECT turn_id FROM room_turns WHERE room_id = %s AND mode = 'combat' AND status = 'collecting' "
        "AND (encounter_id = %s OR (encounter_id IS NULL AND %s IS NULL)) "
        "ORDER BY turn_index DESC LIMIT 1 FOR UPDATE",
        (room_id, encounter_id, encounter_id),
    ).fetchone()
    if turn:
        return turn["turn_id"]
    if not encounter:
        raise ActionDraftError(409, {"code": "combat_turn_unavailable"})
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
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id, base_state_version) "
        "VALUES (%s, %s, %s, 'collecting', 'combat', %s, %s)",
        (
            turn_id,
            room_id,
            max_row["max_idx"] + 1,
            encounter["encounter_id"],
            int(room["state_version"]) if room else 0,
        ),
    )
    return turn_id


def _has_active_combat_turn(conn, room_id: str) -> bool:
    turn = conn.execute(
        "SELECT 1 FROM room_turns AS turns LEFT JOIN encounters AS encounters "
        "ON encounters.encounter_id = turns.encounter_id "
        "WHERE turns.room_id = %s AND turns.mode = 'combat' "
        "AND turns.status IN ('collecting', 'resolving', 'blocked') "
        "AND (turns.encounter_id IS NULL OR encounters.status = 'active') LIMIT 1",
        (room_id,),
    ).fetchone()
    if turn:
        return True
    encounter = conn.execute(
        "SELECT 1 FROM encounters WHERE room_id = %s AND type = 'combat' AND status = 'active' LIMIT 1",
        (room_id,),
    ).fetchone()
    return bool(encounter)


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
