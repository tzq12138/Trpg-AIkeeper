import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..events.event_log import EventLog
from .router_actions_v2 import _require_character


router = APIRouter(prefix="/api/player")


class ActionReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_intent: str = Field(default="", max_length=2000)
    objection: str = Field(min_length=1, max_length=2000)


@router.post("/actions/{action_id}/review-requests", status_code=201)
async def create_action_review(request: Request, action_id: str, body: ActionReviewCreate):
    character = _require_character(request)
    conn = request.app.state.db
    action = conn.execute(
        "SELECT action_id, room_id, character_id, declared_intent, status, result "
        "FROM actions WHERE action_id = %s AND character_id = %s",
        (action_id, character["character_id"]),
    ).fetchone()
    if not action:
        raise HTTPException(404, detail={"code": "action_not_found"})
    if action["status"] not in (
        "resolving",
        "awaiting_player_choice",
        "awaiting_host_exception",
        "completed",
        "resolved",
        "rejected",
        "timeout",
        "sync_required",
    ):
        raise HTTPException(409, detail={"code": "review_not_available"})
    pending = conn.execute(
        "SELECT review_request_id FROM action_review_requests "
        "WHERE action_id = %s AND character_id = %s AND status = 'pending'",
        (action_id, character["character_id"]),
    ).fetchone()
    if pending:
        raise HTTPException(
            409,
            detail={"code": "review_already_pending", "review_request_id": pending["review_request_id"]},
        )

    review_request_id = str(uuid.uuid4())
    suggestion = {
        "source": "local_fallback",
        "requires_host_review": True,
        "summary": "对照玩家原意与权威结算，并决定是否需要补偿。",
        "mutations": [],
    }
    original_intent = body.original_intent.strip() or action.get("declared_intent") or ""
    conn.execute(
        "INSERT INTO action_review_requests "
        "(review_request_id, action_id, character_id, original_intent, objection, status, ai_suggestion) "
        "VALUES (%s, %s, %s, %s, %s, 'pending', %s)",
        (
            review_request_id,
            action_id,
            character["character_id"],
            original_intent,
            body.objection.strip(),
            json.dumps(suggestion, ensure_ascii=False),
        ),
    )
    EventLog(conn).log_event(
        action["room_id"],
        "s2c_action_review_requested",
        "host",
        {
            "reviewRequestId": review_request_id,
            "actionId": action_id,
            "characterId": character["character_id"],
        },
    )
    return {
        "review_request_id": review_request_id,
        "action_id": action_id,
        "status": "pending",
        "original_intent": original_intent,
        "objection": body.objection.strip(),
        "ai_suggestion": suggestion,
    }
