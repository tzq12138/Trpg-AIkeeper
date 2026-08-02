import asyncio

from fastapi import APIRouter, Header, HTTPException, Request

from ..models import ActionReceiptV2, CocFollowUpDecisionRequest
from .action_service import ActionDraftError, submit_coc_followup_decision
from .router_actions_v2 import _require_character


router = APIRouter(prefix="/api/player")


@router.post("/actions/{action_id}/follow-up", response_model=ActionReceiptV2)
async def submit_coc_follow_up(
    request: Request,
    action_id: str,
    body: CocFollowUpDecisionRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=200),
):
    character = _require_character(request)
    try:
        receipt = submit_coc_followup_decision(
            request.app.state.db,
            character["character_id"],
            action_id,
            body.decision,
            idempotency_key,
        )
    except ActionDraftError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    if receipt.status == "awaiting_player_choice":
        from .router_player import _resolve_action_background

        asyncio.create_task(_resolve_action_background(request.app, action_id))
    return receipt
