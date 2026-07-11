from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..engine.action_lifecycle import complete_action, transition_action
from ..engine.compensation_service import ActionReviewAlreadyResolved, resolve_action_review
from ..events.event_log import EventLog
from .router_host import _verify_owner


router = APIRouter(prefix="/api/host")


class CompensationMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["replace"]
    path: Literal[
        "/character/hp",
        "/character/san",
        "/character/mp",
        "/character/luck",
    ]
    value: int


class ActionReviewResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "modified", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)
    mutations: list[CompensationMutation] = Field(default_factory=list)


class ActionExceptionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["request_player_choice", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/{room_id}/action-reviews")
async def list_action_reviews(request: Request, room_id: str):
    _verify_owner(request, room_id)
    rows = request.app.state.db.execute(
        "SELECT arr.review_request_id, arr.action_id, arr.character_id, arr.original_intent, "
        "arr.objection, arr.status, arr.ai_suggestion, arr.created_at "
        "FROM action_review_requests arr JOIN actions a ON a.action_id = arr.action_id "
        "WHERE a.room_id = %s AND arr.status = 'pending' ORDER BY arr.created_at",
        (room_id,),
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/{room_id}/action-reviews/{review_request_id}/resolve")
async def resolve_review(
    request: Request,
    room_id: str,
    review_request_id: str,
    body: ActionReviewResolution,
):
    _verify_owner(request, room_id)
    conn = request.app.state.db
    review = conn.execute(
        "SELECT arr.*, a.room_id FROM action_review_requests arr "
        "JOIN actions a ON a.action_id = arr.action_id "
        "WHERE arr.review_request_id = %s AND a.room_id = %s",
        (review_request_id, room_id),
    ).fetchone()
    if not review:
        raise HTTPException(404, detail={"code": "review_not_found"})
    if review["status"] != "pending":
        raise HTTPException(409, detail={"code": "review_already_resolved"})
    mutations = [item.model_dump() for item in body.mutations]
    if body.decision == "rejected" and mutations:
        raise HTTPException(422, detail={"code": "rejected_review_cannot_mutate"})
    try:
        result = resolve_action_review(
            request.app.state,
            conn,
            dict(review),
            decision=body.decision,
            reason=body.reason.strip(),
            mutations=mutations,
        )
    except ActionReviewAlreadyResolved as exc:
        raise HTTPException(409, detail={"code": "review_already_resolved"}) from exc
    return {
        "review_request_id": review_request_id,
        "status": result["status"],
        "compensation_transaction_id": result["compensation_transaction_id"],
    }


@router.get("/{room_id}/action-exceptions")
async def list_action_exceptions(request: Request, room_id: str):
    _verify_owner(request, room_id)
    rows = request.app.state.db.execute(
        "SELECT action_id, character_id, intent_type, declared_intent, status, created_at "
        "FROM actions WHERE room_id = %s AND status = 'awaiting_host_exception' "
        "ORDER BY created_at",
        (room_id,),
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/{room_id}/action-exceptions/{action_id}/resolve")
async def resolve_action_exception(
    request: Request,
    room_id: str,
    action_id: str,
    body: ActionExceptionResolution,
):
    _verify_owner(request, room_id)
    conn = request.app.state.db
    action = conn.execute(
        "SELECT action_id, character_id, status FROM actions "
        "WHERE action_id = %s AND room_id = %s",
        (action_id, room_id),
    ).fetchone()
    if not action:
        raise HTTPException(404, detail={"code": "action_not_found"})
    if action["status"] != "awaiting_host_exception":
        raise HTTPException(409, detail={"code": "exception_already_resolved"})

    if body.decision == "request_player_choice":
        transitioned = transition_action(
            conn,
            action_id,
            from_statuses=("awaiting_host_exception",),
            to_status="awaiting_player_choice",
            metadata={"reason": body.reason.strip()},
        )
        status = "awaiting_player_choice"
    else:
        transitioned = complete_action(
            conn,
            action_id,
            from_statuses=("awaiting_host_exception",),
            to_status="rejected",
            result={"reason": body.reason.strip()},
            metadata={"reason_code": "host_exception_rejected"},
        )
        status = "rejected"
    if not transitioned:
        raise HTTPException(409, detail={"code": "exception_already_resolved"})
    EventLog(conn).log_event(
        room_id,
        "s2c_action_choice_requested" if status == "awaiting_player_choice" else "s2c_action_completed",
        "player",
        {
            "actionId": action_id,
            "characterId": action["character_id"],
            "status": status,
            "reason": body.reason.strip(),
        },
    )
    return {"action_id": action_id, "status": status}
