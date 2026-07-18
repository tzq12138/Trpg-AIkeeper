import asyncio
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request, Response

from ..models import (
    ActionDraftAnalyzeRequest,
    ActionDraftConfirmRequest,
    ActionDraftDTO,
    ActionDraftUpdateRequest,
    ActionHintsDTO,
    ActionReceiptV2,
)
from ..ai.director import (
    apply_director_plan,
    build_director_context,
    normalize_director_plan,
    resolve_conditional_solo_target,
)
from ..ai.narrator import build_manual_action_hints
from ..events.events_registry import event_type
from ..engine.projection import ProjectionDispatcher
from ..engine.solo_combat_reactions import (
    SoloCombatReactionError,
    get_pending_reaction,
    reaction_projection,
    resolve_pending_reaction,
)
from ..encounter_persistence import get_encounter, get_participants
from ..scenario.solo_runtime import (
    SoloAdventureRuntime,
    extract_solo_daily_penalty_die,
    extract_solo_damage_transition,
    extract_solo_fixed_damage,
    extract_solo_fixed_healing,
    extract_solo_fixed_sanity_loss,
    extract_solo_skill_check,
    infer_otherwise_solo_target,
    infer_visible_solo_target,
    render_player_safe_solo_narrative,
)
from .action_service import (
    ActionDraftError,
    apply_ai_action_analysis,
    analyze_action_draft,
    cancel_action,
    cancel_action_draft,
    confirm_action_draft,
    get_current_action_draft,
    persist_action_draft,
    revise_action_draft,
)
from .router_player_settings import get_effective_draft_analysis_enabled
from .router_campaign_v2 import claim_controller_device, record_campaign_activity


router = APIRouter(prefix="/api/player")
logger = logging.getLogger(__name__)

_SOLO_PROGRESS_WORDS = ("继续", "出发", "上车", "登上", "前进", "前往", "启程")
_SOLO_BEAR_ATTACK_WORDS = ("攻击", "砍", "刺", "斗殴", "搏斗", "出刀", "小刀")
_DIRECTOR_ANALYSIS_TIMEOUT_SECONDS = 30


def _require_character(request: Request) -> dict:
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    character = request.app.state.db.execute(
        "SELECT * FROM characters WHERE player_token = %s",
        (token,),
    ).fetchone()
    if not character:
        raise HTTPException(403, "Invalid token")
    return dict(character)


def _apply_visible_solo_transition(
    conn,
    character: dict,
    draft: ActionDraftDTO,
    *,
    allow_implicit_single_target: bool = False,
) -> ActionDraftDTO:
    if draft.params.get("targetNodeId") or draft.params.get("solo_adventure_damage"):
        return draft
    scene = SoloAdventureRuntime(conn).current(character["room_id"])
    targets = list(scene.get("target_node_ids") or []) if scene else []
    if not scene:
        return draft
    target_node_id = (
        infer_otherwise_solo_target(scene, draft.declared_intent)
        or infer_visible_solo_target(scene, draft.declared_intent)
        or resolve_conditional_solo_target(character, {
            "text": scene.get("text") or "",
            "target_node_ids": targets,
        })
    )
    if not target_node_id and len(targets) == 1 and (
        allow_implicit_single_target
        or any(word in draft.declared_intent for word in _SOLO_PROGRESS_WORDS)
    ):
        target_node_id = str(targets[0])
    if not target_node_id and not any(word in draft.declared_intent for word in _SOLO_PROGRESS_WORDS):
        return draft
    elif not target_node_id:
        return draft
    params = dict(draft.params)
    params.update({
        "fromNodeId": str(scene["node_id"]),
        "targetNodeId": target_node_id,
    })
    fixed_healing = extract_solo_fixed_healing(scene)
    fixed_damage = extract_solo_fixed_damage(scene)
    fixed_sanity_loss = extract_solo_fixed_sanity_loss(scene)
    daily_penalty_die = extract_solo_daily_penalty_die(scene)
    resource_impacts = list(draft.resource_impacts)
    understanding_summary = "你想沿当前唯一可见方向继续"
    confirmation_requirements = ["movement", "state_change"]
    if fixed_healing and fixed_healing["target_node_id"] == target_node_id:
        params["solo_fixed_healing"] = fixed_healing
        resource_impacts.append({
            "resource": "hp",
            "label": f"生命恢复 {fixed_healing['amount']} 点",
        })
        understanding_summary = "你要先完成当前场景的固定治疗，再继续前行"
    if fixed_damage and fixed_damage["target_node_id"] == target_node_id:
        params["solo_fixed_damage"] = fixed_damage
        resource_impacts.append({
            "resource": "hp",
            "label": f"生命损失 {fixed_damage['amount']} 点",
        })
        understanding_summary = "你将承受当前场景的固定伤害，再继续前行"
        confirmation_requirements = ["damage", "state_change"]
    if fixed_sanity_loss and fixed_sanity_loss["target_node_id"] == target_node_id:
        params["solo_fixed_sanity_loss"] = fixed_sanity_loss
        resource_impacts.append({"resource": "san", "label": f"理智损失 {fixed_sanity_loss['loss_dice']}"})
    if daily_penalty_die and daily_penalty_die["target_node_id"] == target_node_id:
        params["solo_daily_penalty_die"] = daily_penalty_die
        resource_impacts.append({"resource": "rule", "label": "惩罚骰 1 颗"})
        understanding_summary = "你将获得一颗惩罚骰后，再继续前行"
    citation = scene.get("citation") or {}
    update = {
        **draft.model_dump(mode="json"),
        "intent_type": "move",
        "params": params,
        "understanding_summary": understanding_summary,
        "risk": "high" if fixed_damage and fixed_damage["target_node_id"] == target_node_id else "medium",
        "movement_target": "下一场景",
        "resource_impacts": resource_impacts,
        "confirmation_requirements": confirmation_requirements,
        "requires_confirmation": True,
        "confidence": max(draft.confidence, 0.9),
        "citations": [citation] if citation else draft.citations,
        "resolution_route": "local",
    }
    if allow_implicit_single_target:
        update.update({
            "status": "awaiting_confirmation",
            "adjudication_stage": "director_plan_validated",
        })
    return ActionDraftDTO.model_validate(update)


def _apply_visible_solo_damage_transition(
    conn,
    character: dict,
    draft: ActionDraftDTO,
) -> ActionDraftDTO:
    if draft.params.get("targetNodeId") or draft.params.get("solo_adventure_damage"):
        return draft
    scene = SoloAdventureRuntime(conn).current(character["room_id"])
    rule = extract_solo_damage_transition(scene or {})
    if not rule:
        return draft
    params = dict(draft.params)
    params.update({
        "fromNodeId": rule["from_node_id"],
        "solo_adventure_damage": rule,
    })
    citation = rule["citation"]
    return ActionDraftDTO.model_validate({
        **draft.model_dump(mode="json"),
        "intent_type": "move",
        "params": params,
        "understanding_summary": "你将承受当前场景的固定伤害，结果决定后续处境。",
        "risk": "high",
        "resource_impacts": [{
            "resource": "hp",
            "label": "生命",
            "dice": rule["damage_dice"],
        }],
        "confirmation_requirements": ["damage", "dice_roll", "state_change"],
        "requires_confirmation": True,
        "confidence": max(draft.confidence, 0.95),
        "citations": [citation] if citation else draft.citations,
        "analysis_source": "local_fallback",
        "resolution_route": "local",
    })


def _apply_visible_solo_skill_check(
    conn,
    character: dict,
    draft: ActionDraftDTO,
) -> ActionDraftDTO:
    if draft.params.get("targetNodeId") or draft.params.get("solo_adventure_check"):
        return draft
    scene = SoloAdventureRuntime(conn).current(character["room_id"])
    rule = extract_solo_skill_check(scene or {}, draft.declared_intent)
    if not rule:
        return draft
    citation = rule["citation"]
    params = dict(draft.params)
    if rule.get("mechanic") == "sanity_check":
        solo_check = {
            "mechanic": "sanity_check",
            "fromNodeId": rule["from_node_id"],
            "successLoss": rule["success_loss"],
            "failureLoss": rule["failure_loss"],
            "citation": citation,
        }
        if rule.get("target_node_id"):
            solo_check["targetNodeId"] = rule["target_node_id"]
        else:
            solo_check["successTargetNodeId"] = rule["success_target_node_id"]
            solo_check["failureTargetNodeId"] = rule["failure_target_node_id"]
    else:
        solo_check = {
            "fromNodeId": rule["from_node_id"],
            "successTargetNodeId": rule["success_target_node_id"],
            "failureTargetNodeId": rule["failure_target_node_id"],
            "citation": citation,
        }
        if rule.get("damage_dice"):
            solo_check["damageDice"] = rule["damage_dice"]
            solo_check["damageEndsOnZero"] = bool(rule.get("damage_ends_on_zero"))
    params.update({
        "skillName": rule["skill_name"],
        "difficulty": rule["difficulty"],
        "solo_adventure_check": solo_check,
    })
    scene_variables = scene.get("scene_variables") if isinstance(scene, dict) else {}
    active_bonus_dice = 0
    if isinstance(scene_variables, dict):
        try:
            active_bonus_dice = int(scene_variables.get("solo_skill_bonus_dice") or 0)
        except (TypeError, ValueError):
            active_bonus_dice = 0
    skill_name = str(rule["skill_name"]).strip().casefold()
    applies_daily_penalty_die = (
        active_bonus_dice < 0
        and rule.get("mechanic") != "sanity_check"
        and skill_name not in {"幸运", "luck"}
    )
    if applies_daily_penalty_die:
        try:
            existing_bonus_dice = int(params.get("bonusDice") or 0)
        except (TypeError, ValueError):
            existing_bonus_dice = 0
        params["bonusDice"] = existing_bonus_dice + active_bonus_dice
    damage_dice = rule.get("damage_dice")
    resource_impacts = (
        [{"resource": "hp", "label": "生命", "dice": damage_dice}]
        if damage_dice
        else list(draft.resource_impacts)
    )
    if applies_daily_penalty_die:
        resource_impacts.append({"resource": "rule", "label": "惩罚骰 1 颗"})
    understanding_summary = (
        f"当前场景会先受到{damage_dice}点伤害，再进行一次{rule['skill_name']}检定"
        if damage_dice
        else f"当前场景要求进行一次{rule['skill_name']}检定"
    )
    if applies_daily_penalty_die:
        understanding_summary = f"{understanding_summary}（带一颗惩罚骰）"
    return ActionDraftDTO.model_validate({
        **draft.model_dump(mode="json"),
        "intent_type": "skill_check",
        "params": params,
        "understanding_summary": understanding_summary,
        "risk": "high" if damage_dice else "medium",
        "suggested_skill": rule["skill_name"],
        "difficulty": rule["difficulty"],
        "resource_impacts": resource_impacts,
        "confirmation_requirements": (
            ["damage", "dice_roll", "state_change"]
            if damage_dice
            else ["dice_roll", "state_change"]
        ),
        "requires_confirmation": True,
        "confidence": max(draft.confidence, 0.95),
        "citations": [citation] if citation else draft.citations,
        "analysis_source": "local_fallback",
        "resolution_route": "local",
    })


def _apply_visible_solo_black_bear_combat(
    conn,
    character: dict,
    draft: ActionDraftDTO,
) -> ActionDraftDTO:
    """Compile explicit attacks in the scripted bear scene without an AI round-trip."""
    if draft.params.get("solo_black_bear_combat"):
        return draft
    scene = SoloAdventureRuntime(conn).current(character["room_id"])
    text = str((scene or {}).get("text") or "")
    normalized_intent = draft.declared_intent.replace(" ", "")
    if (
        not scene
        or not all(marker in text for marker in ("黑熊", "生命值", "爪击"))
        or not any(word in normalized_intent for word in _SOLO_BEAR_ATTACK_WORDS)
    ):
        return draft
    params = dict(draft.params)
    params.update({
        "actionKind": "attack",
        "solo_black_bear_combat": True,
    })
    citation = scene.get("citation") or {}
    return ActionDraftDTO.model_validate({
        **draft.model_dump(mode="json"),
        "intent_type": "combat_action",
        "params": params,
        "understanding_summary": "你要用近战武器攻击当前可见的黑熊。",
        "risk": "high",
        "suggested_skill": "格斗（斗殴）",
        "difficulty": "regular",
        "resource_impacts": [{"resource": "hp", "label": "可能承受黑熊反击"}],
        "confirmation_requirements": ["dice_roll", "damage", "state_change"],
        "requires_confirmation": True,
        "confidence": max(draft.confidence, 0.95),
        "citations": [citation] if citation else draft.citations,
        "analysis_source": "local_fallback",
        "resolution_route": "local",
    })
def _can_use_local_director_fallback(draft: ActionDraftDTO) -> bool:
    return draft.resolution_route == "local" and draft.risk != "high"


def _apply_local_director_plan(
    conn,
    character: dict,
    draft: ActionDraftDTO,
    director_context: dict,
) -> ActionDraftDTO:
    semantic_progression = _local_generic_scene_progression(draft, director_context)
    plan = normalize_director_plan(
        {
            "interpreted_intent": draft.understanding_summary,
            "intent_type": "move" if semantic_progression else draft.intent_type,
            "confidence": draft.confidence,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "local_verified",
            "analysis_source": "local_fallback",
            "semantic_progression": semantic_progression,
        },
        director_context,
    )
    applied = apply_director_plan(conn, character, draft, plan, director_context)
    return applied.model_copy(update={
        "analysis_source": "local_fallback",
        "resolution_route": "local",
    })


def _local_generic_scene_progression(
    draft: ActionDraftDTO,
    director_context: dict,
) -> dict:
    if draft.intent_type != "move":
        return {}
    runtime_package = director_context.get("runtime_package")
    if not isinstance(runtime_package, dict):
        return {}
    current_scene = director_context.get("current_scene")
    if not isinstance(current_scene, dict):
        return {}
    current_scene_id = str(current_scene.get("current_scene") or "")
    rules = runtime_package.get("semantic_progression_rules")
    edges = rules.get("edges") if isinstance(rules, dict) else []
    scenes = runtime_package.get("semantic_scenes")
    if not isinstance(edges, list) or not isinstance(scenes, list):
        return {}
    declared = _normalize_scene_name(draft.declared_intent)
    matching_targets: list[tuple[str, dict]] = []
    for edge in edges:
        if (
            not isinstance(edge, dict)
            or edge.get("relation_type") != "transitions_to"
            or str(edge.get("from_scene_id") or "") != current_scene_id
        ):
            continue
        target_scene_id = str(edge.get("to_scene_id") or "")
        if not target_scene_id:
            continue
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            payload = scene.get("payload") if isinstance(scene.get("payload"), dict) else {}
            identifiers = {
                str(scene.get("scene_id") or ""),
                str(scene.get("logical_key") or ""),
                str(payload.get("scene_id") or ""),
                str(payload.get("id") or ""),
            }
            if target_scene_id not in identifiers:
                continue
            names = (
                scene.get("name"),
                scene.get("title"),
                payload.get("name"),
                payload.get("title"),
            )
            if any(
                normalized_name and normalized_name in declared
                for normalized_name in (_normalize_scene_name(name) for name in names)
            ):
                matching_targets.append((target_scene_id, edge))
            break
    unique_targets = {target_scene_id for target_scene_id, _ in matching_targets}
    if len(unique_targets) != 1:
        return {}
    target_scene_id = unique_targets.pop()
    edge = next(edge for target, edge in matching_targets if target == target_scene_id)
    citation = _local_director_citation(edge.get("citation"))
    if not citation:
        return {}
    return {
        "targetNodeId": target_scene_id,
        "citation": citation,
    }


def _normalize_scene_name(value) -> str:
    return "".join(char.casefold() for char in str(value or "") if char.isalnum())


def _local_director_citation(value) -> dict:
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key in ("source", "source_part_id", "content_item_id", "page_number", "location")
        if value.get(key) is not None
    }


def _can_apply_local_director_plan(
    draft: ActionDraftDTO,
    director_context: dict,
) -> bool:
    return bool(
        draft.params.get("targetNodeId")
        or draft.params.get("solo_adventure_check")
        or _local_generic_scene_progression(draft, director_context)
    )


def _can_recover_local_draft_after_rejected_progression(
    local_draft: ActionDraftDTO,
    applied_draft: ActionDraftDTO,
) -> bool:
    return bool(
        _can_use_local_director_fallback(local_draft)
        and applied_draft.semantic_progression.get("rejected")
    )


def _should_use_implicit_single_target_fallback(conn, character: dict, plan) -> bool:
    scene = SoloAdventureRuntime(conn).current(character["room_id"])
    targets = list(scene.get("target_node_ids") or []) if scene else []
    if len(targets) != 1:
        return False
    target = str(
        getattr(plan.semantic_progression, "target_node_id", "")
        or getattr(plan.semantic_progression, "targetNodeId", "")
        or ""
    )
    return not target or target == str(scene.get("node_id") or "")


@router.post("/action-drafts/analyze", response_model=ActionDraftDTO)
async def analyze_draft(request: Request, body: ActionDraftAnalyzeRequest):
    character = _require_character(request)
    if body.ephemeral and not get_effective_draft_analysis_enabled(
        request.app.state.db, character
    ):
        raise HTTPException(403, detail={"code": "draft_analysis_disabled"})
    room = request.app.state.db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (character["room_id"],),
    ).fetchone()
    if room:
        body = body.model_copy(update={"base_state_version": room["state_version"]})
    draft = analyze_action_draft(body)
    draft = _apply_visible_solo_damage_transition(
        request.app.state.db, character, draft,
    )
    draft = _apply_visible_solo_transition(request.app.state.db, character, draft)
    draft = _apply_visible_solo_skill_check(request.app.state.db, character, draft)
    draft = _apply_visible_solo_black_bear_combat(
        request.app.state.db, character, draft,
    )
    gateway = getattr(request.app.state, "gateway", None)
    if gateway and hasattr(gateway, "analyze_director_action"):
        director_context = build_director_context(
            request.app.state.db,
            character,
            draft,
        )
        if (
            draft.params.get("solo_black_bear_combat")
            or draft.params.get("solo_adventure_damage")
            or draft.params.get("solo_adventure_check")
            or draft.params.get("solo_fixed_damage")
        ):
            citations = draft.citations
            draft = _apply_local_director_plan(
                request.app.state.db,
                character,
                draft,
                director_context,
            )
            draft = draft.model_copy(update={
                "citations": citations,
                "resolution_route": "local",
            })
        elif _can_use_local_director_fallback(draft) and _can_apply_local_director_plan(
            draft,
            director_context,
        ):
            draft = _apply_local_director_plan(
                request.app.state.db,
                character,
                draft,
                director_context,
            )
        else:
            try:
                ai_result = await asyncio.wait_for(
                    gateway.analyze_director_action(
                        {
                            **director_context,
                            "suppress_response_log": body.ephemeral,
                        },
                        room_id=character["room_id"],
                    ),
                    timeout=_DIRECTOR_ANALYSIS_TIMEOUT_SECONDS,
                )
                if isinstance(ai_result, dict):
                    director_plan = normalize_director_plan(ai_result, director_context)
                    applied_draft = apply_director_plan(
                        request.app.state.db,
                        character,
                        draft,
                        director_plan,
                        director_context,
                    )
                    if _can_recover_local_draft_after_rejected_progression(
                        draft,
                        applied_draft,
                    ):
                        draft = _apply_local_director_plan(
                            request.app.state.db,
                            character,
                            draft,
                            director_context,
                        )
                    else:
                        draft = applied_draft
                    if _should_use_implicit_single_target_fallback(
                        request.app.state.db,
                        character,
                        director_plan,
                    ):
                        draft = _apply_visible_solo_transition(
                            request.app.state.db,
                            character,
                            draft,
                            allow_implicit_single_target=True,
                        )
                elif _can_use_local_director_fallback(draft):
                    draft = _apply_local_director_plan(
                        request.app.state.db,
                        character,
                        draft,
                        director_context,
                    )
            except Exception as exc:
                logger.warning(
                    "Director analysis failed room=%s character=%s error_type=%s",
                    character["room_id"],
                    character["character_id"],
                    type(exc).__name__,
                )
                if _can_use_local_director_fallback(draft):
                    draft = _apply_local_director_plan(
                        request.app.state.db,
                        character,
                        draft,
                        director_context,
                    )
                else:
                    draft = draft.model_copy(update={
                        "adjudication_stage": "host_exception_required",
                        "resolution_route": "host_exception",
                        "confirmation_requirements": ["host_exception"],
                        "requires_confirmation": True,
                        "analysis_source": "local_fallback",
                        "confidence": min(draft.confidence, 0.5),
                    })
    elif gateway and hasattr(gateway, "analyze_action_draft"):
        try:
            ai_result = await gateway.analyze_action_draft(
                {
                    "declared_intent": draft.declared_intent,
                    "intent_type": draft.intent_type,
                    "base_state_version": draft.base_state_version,
                    "local_analysis": draft.model_dump(mode="json"),
                    "suppress_response_log": body.ephemeral,
                },
                room_id=character["room_id"],
            )
            if isinstance(ai_result, dict):
                draft = apply_ai_action_analysis(draft, ai_result)
        except Exception:
            pass
    if body.ephemeral:
        return draft
    persisted = persist_action_draft(request.app.state.db, character, draft)
    _emit_director_draft_events(request.app.state.db, character, persisted)
    return persisted


@router.get("/action-drafts/current", response_model=ActionDraftDTO | None)
async def get_current_draft(request: Request):
    return get_current_action_draft(request.app.state.db, _require_character(request))


@router.patch("/action-drafts/{draft_id}", response_model=ActionDraftDTO)
async def revise_draft(request: Request, draft_id: str, body: ActionDraftUpdateRequest):
    character = _require_character(request)
    try:
        return revise_action_draft(request.app.state.db, character, draft_id, body)
    except ActionDraftError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.delete("/action-drafts/{draft_id}", status_code=204)
async def delete_draft(request: Request, draft_id: str):
    character = _require_character(request)
    try:
        cancel_action_draft(request.app.state.db, character, draft_id)
    except ActionDraftError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return Response(status_code=204)


@router.post("/action-drafts/{draft_id}/confirm", response_model=ActionReceiptV2)
async def confirm_draft(
    request: Request,
    draft_id: str,
    body: ActionDraftConfirmRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
    device_id: str = Header(default="", alias="X-Device-Id", max_length=128),
):
    character = _require_character(request)
    try:
        claim_controller_device(
            request.app.state.db,
            character,
            device_id or f"legacy:{character['character_id']}",
        )
        receipt = confirm_action_draft(
            request.app.state.db,
            character,
            draft_id,
            idempotency_key,
            body.confirmations,
        )
        record_campaign_activity(request.app.state.db, character)
        if receipt.status == "queued":
            _schedule_action_resolution(
                request.app,
                request.app.state.db,
                receipt.action_id,
            )
        return receipt
    except ActionDraftError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post("/actions/{action_id}/cancel", response_model=ActionReceiptV2)
async def cancel_confirmed_action(request: Request, action_id: str):
    character = _require_character(request)
    try:
        return cancel_action(request.app.state.db, character["character_id"], action_id)
    except ActionDraftError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post("/action-hints", response_model=ActionHintsDTO)
async def manual_action_hints(request: Request):
    character = _require_character(request)
    return build_manual_action_hints(request.app.state.db, character)


@router.get("/encounter-reactions/pending")
async def get_pending_encounter_reaction(request: Request):
    character = _require_character(request)
    reaction = get_pending_reaction(
        request.app.state.db,
        character["character_id"],
        room_id=character["room_id"],
    )
    return {"reaction": reaction_projection(reaction) if reaction else None}


@router.post("/encounter-reactions/{reaction_id}/resolve")
async def resolve_encounter_reaction(
    request: Request,
    reaction_id: str,
    body: dict,
):
    character = _require_character(request)
    try:
        resolved = resolve_pending_reaction(
            request.app.state.db,
            reaction_id=reaction_id,
            character_id=character["character_id"],
            choice=str(body.get("choice") or ""),
        )
    except SoloCombatReactionError as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc

    reaction = resolved["reaction"]
    encounter = get_encounter(request.app.state.db, reaction["encounter_id"])
    participants = get_participants(request.app.state.db, reaction["encounter_id"])
    dispatcher = ProjectionDispatcher(request.app.state.db)
    await dispatcher.emit(
        character["room_id"],
        event_type("s2c_encounter_updated"),
        "party",
        {
            "encounterId": reaction["encounter_id"],
            "encounter": _event_safe_record(encounter) if encounter else {},
            "participants": [_event_safe_record(item) for item in participants],
        },
    )
    next_reaction = resolved.get("next_reaction")
    if next_reaction:
        await dispatcher.emit(
            character["room_id"],
            event_type("s2c_solo_combat_reaction_requested"),
            "player",
            {"reaction": reaction_projection(next_reaction)},
            character_id=character["character_id"],
        )
    elif encounter and encounter.get("status") == "resolved":
        await dispatcher.emit(
            character["room_id"],
            event_type("s2c_encounter_resolved"),
            "party",
            {
                "encounterId": reaction["encounter_id"],
                "reason": encounter.get("summary") or "遭遇结束",
            },
        )
    solo_transition = resolved.get("solo_transition")
    if solo_transition:
        scene = SoloAdventureRuntime(request.app.state.db).current(character["room_id"])
        await dispatcher.emit(
            character["room_id"],
            event_type("s2c_scene_sync"),
            "party",
            {"currentScene": solo_transition["current_scene"]},
        )
        if scene and scene.get("text"):
            await dispatcher.emit(
                character["room_id"],
                event_type("s2c_public_observation"),
                "party",
                {"text": render_player_safe_solo_narrative(scene)},
            )
    return {
        "reaction": reaction_projection(reaction),
        "result": resolved["result"],
        "nextReaction": reaction_projection(next_reaction) if next_reaction else None,
        "soloTransition": solo_transition,
        "idempotent": resolved["idempotent"],
    }


def _event_safe_record(value: dict) -> dict:
    return {
        key: item.isoformat() if hasattr(item, "isoformat") else item
        for key, item in value.items()
    }


def _schedule_action_resolution(app, conn, action_id: str) -> None:
    if not getattr(app.state, "pipeline", None) and not getattr(app.state, "pg_db", None):
        return
    action = conn.execute(
        "SELECT a.turn_id, r.status AS room_status, a.room_id "
        "FROM actions a JOIN rooms r ON r.room_id = a.room_id WHERE a.action_id = %s",
        (action_id,),
    ).fetchone()
    if not action:
        return
    from .router_player import _resolve_action_background, _settle_turn_background

    if action["room_status"] == "active" and action.get("turn_id"):
        from ..turn_manager import TurnManager

        if TurnManager(conn).all_submitted(action["room_id"]):
            asyncio.create_task(
                _settle_turn_background(app, action["room_id"], action["turn_id"])
            )
        return
    asyncio.create_task(_resolve_action_background(app, action_id))


def _emit_director_draft_events(conn, character: dict, draft: ActionDraftDTO) -> None:
    if not draft.adjudication_stage.startswith(("director", "player_", "host_")):
        return
    payload = {
        "draftId": draft.draft_id,
        "characterId": character["character_id"],
        "adjudicationStage": draft.adjudication_stage,
        "contextVersion": draft.context_version,
    }
    conn.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'player', %s)",
        (
            character["room_id"],
            event_type("s2c_ai_stage_changed"),
            json.dumps(payload, ensure_ascii=False),
        ),
    )
    if draft.adjudication_stage == "player_clarification_required":
        conn.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'player', %s)",
            (
                character["room_id"],
                event_type("s2c_player_clarification_required"),
                json.dumps(
                    {**payload, "candidateInterpretations": draft.candidate_interpretations},
                    ensure_ascii=False,
                ),
            ),
        )
    if draft.adjudication_stage == "host_exception_required":
        conn.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'player', %s)",
            (
                character["room_id"],
                event_type("s2c_ai_recovery_required"),
                json.dumps(
                    {**payload, "reasonCode": "director_analysis_failed"},
                    ensure_ascii=False,
                ),
            ),
        )
    conn.commit()
