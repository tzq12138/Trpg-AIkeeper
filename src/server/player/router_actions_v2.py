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
)
from ..ai.narrator import build_manual_action_hints
from ..events.events_registry import event_type
from .action_service import (
    ActionDraftError,
    apply_ai_action_analysis,
    analyze_action_draft,
    cancel_action,
    cancel_action_draft,
    confirm_action_draft,
    persist_action_draft,
    revise_action_draft,
)
from .router_player_settings import get_effective_draft_analysis_enabled
from .router_campaign_v2 import claim_controller_device, record_campaign_activity


router = APIRouter(prefix="/api/player")
logger = logging.getLogger(__name__)

_SOLO_PROGRESS_WORDS = ("继续", "出发", "上车", "登上", "前进", "前往", "启程")


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


def _apply_visible_solo_transition(conn, character: dict, draft: ActionDraftDTO) -> ActionDraftDTO:
    if draft.params.get("targetNodeId"):
        return draft
    from ..scenario.solo_runtime import SoloAdventureRuntime

    scene = SoloAdventureRuntime(conn).current(character["room_id"])
    targets = list(scene.get("target_node_ids") or []) if scene else []
    if len(targets) != 1 or not any(
        word in draft.declared_intent for word in _SOLO_PROGRESS_WORDS
    ):
        return draft
    target_node_id = str(targets[0])
    params = dict(draft.params)
    params.update({
        "fromNodeId": str(scene["node_id"]),
        "targetNodeId": target_node_id,
    })
    citation = scene.get("citation") or {}
    return ActionDraftDTO.model_validate({
        **draft.model_dump(mode="json"),
        "intent_type": "move",
        "params": params,
        "understanding_summary": "你想沿当前唯一可见方向继续",
        "risk": "medium",
        "movement_target": "下一场景",
        "confirmation_requirements": ["movement", "state_change"],
        "requires_confirmation": True,
        "confidence": max(draft.confidence, 0.9),
        "citations": [citation] if citation else draft.citations,
        "resolution_route": "local",
    })


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
    if body.base_state_version == 0 and room:
        body = body.model_copy(update={"base_state_version": room["state_version"]})
    draft = analyze_action_draft(body)
    draft = _apply_visible_solo_transition(request.app.state.db, character, draft)
    gateway = getattr(request.app.state, "gateway", None)
    if gateway and hasattr(gateway, "analyze_director_action"):
        try:
            director_context = build_director_context(
                request.app.state.db,
                character,
                draft,
            )
            ai_result = await gateway.analyze_director_action(
                {
                    **director_context,
                    "suppress_response_log": body.ephemeral,
                },
                room_id=character["room_id"],
            )
            if isinstance(ai_result, dict):
                director_plan = normalize_director_plan(ai_result, director_context)
                draft = apply_director_plan(
                    request.app.state.db,
                    character,
                    draft,
                    director_plan,
                    director_context,
                )
        except Exception as exc:
            logger.warning(
                "Director analysis failed room=%s character=%s error_type=%s",
                character["room_id"],
                character["character_id"],
                type(exc).__name__,
            )
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
