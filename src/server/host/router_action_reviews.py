import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..engine.action_lifecycle import complete_action, transition_action
from ..engine.compensation_service import (
    ActionReviewAlreadyResolved,
    ActionReviewRecalculationError,
    recalculate_action_review,
    resolve_action_review,
)
from ..events.event_log import EventLog
from ..runtime_lifecycle import character_lifecycle_guard
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


class ActionReviewRecalculation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    difficulty: Literal["regular", "hard", "extreme"]
    reason: str = Field(min_length=1, max_length=2000)


class ActionExceptionResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["request_player_choice", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/{room_id}/action-reviews")
async def list_action_reviews(request: Request, room_id: str):
    _verify_owner(request, room_id)
    rows = request.app.state.db.execute(
        "SELECT arr.review_request_id, arr.action_id, arr.character_id, arr.original_intent, "
        "arr.objection, arr.status, arr.ai_suggestion, arr.created_at, "
        "a.declared_intent, a.intent_type, a.params, a.rule_set_version_id, "
        "bundle.rule_explanation "
        "FROM action_review_requests arr JOIN actions a ON a.action_id = arr.action_id "
        "LEFT JOIN resolution_bundles bundle ON bundle.action_id = arr.action_id "
        "WHERE a.room_id = %s AND arr.status = 'pending' ORDER BY arr.created_at",
        (room_id,),
    ).fetchall()
    return {"items": [_build_review_packet(dict(row)) for row in rows]}


def _build_review_packet(row: dict[str, Any]) -> dict[str, Any]:
    params = _json_object(row.get("params"))
    analysis = _json_object(params.get("analysis"))
    director_plan = _json_object(params.get("director_plan"))
    explanation = _json_object(row.get("rule_explanation"))
    item = {
        key: row.get(key)
        for key in (
            "review_request_id",
            "action_id",
            "character_id",
            "original_intent",
            "objection",
            "status",
            "ai_suggestion",
            "created_at",
        )
    }
    item["original_action_text"] = str(row.get("declared_intent") or "")
    contract = _review_intent_contract(analysis)
    item["intent_contract"] = {
        "intentType": str(row.get("intent_type") or ""),
        "understandingSummary": _string_value(analysis, "understanding_summary", "understandingSummary"),
        "risk": _string_value(analysis, "risk"),
        "visibility": _string_value(analysis, "visibility"),
        "confirmationRequirements": _string_list(
            analysis.get("confirmation_requirements", analysis.get("confirmationRequirements"))
        ),
        **contract,
    }
    item["director_plan"] = _public_director_plan(director_plan)
    item["rule_plan"] = _rule_plan(explanation, row.get("rule_set_version_id"))
    item["state_diff"] = {
        "before": _json_object(explanation.get("state_before")),
        "after": _json_object(explanation.get("state_after")),
    }
    item["citations"] = _review_citations(explanation, director_plan)
    return item


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


def _string_value(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str):
            return value
    return ""


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _review_intent_contract(analysis: dict[str, Any]) -> dict[str, Any]:
    contract = _json_object(analysis.get("intent_contract", analysis.get("intentContract")))
    return {
        "target": _string_value(contract, "target") or None,
        "method": _string_value(contract, "method") or None,
        "object": _string_value(contract, "object") or None,
        "constraints": _string_list(contract.get("constraints"))[:8],
        "resources": _string_list(contract.get("resources"))[:8],
        "conditions": _string_list(contract.get("conditions"))[:8],
        "ambiguities": _string_list(contract.get("ambiguities"))[:8],
    }


def _public_director_plan(plan: dict[str, Any]) -> dict[str, Any]:
    mechanic = _json_object(plan.get("mechanic_plan", plan.get("mechanicPlan")))
    return {
        "contextVersion": plan.get("context_version", plan.get("contextVersion")),
        "interpretedIntent": _string_value(plan, "interpreted_intent", "interpretedIntent"),
        "mechanic": {
            "name": _string_value(mechanic, "mechanic"),
            "skillName": _string_value(mechanic, "skill_name", "skillName"),
            "difficulty": _string_value(mechanic, "difficulty"),
        },
        "preconditions": [item for item in plan.get("preconditions", []) if isinstance(item, dict)],
        "permissions": [item for item in plan.get("permissions", []) if isinstance(item, dict)],
    }


def _rule_plan(explanation: dict[str, Any], rule_set_version: Any) -> dict[str, Any]:
    inputs = _json_object(explanation.get("authoritative_inputs"))
    authoritative_inputs = {
        "intentType": _string_value(inputs, "intent_type", "intentType"),
        "skillName": _string_value(inputs, "skill_name", "skillName"),
        "skillValue": inputs.get("skill_value", inputs.get("skillValue")),
        "rawRolls": inputs.get("raw_rolls", inputs.get("rawRolls", [])),
    }
    return {
        "ruleSetVersion": str(explanation.get("rule_set_version") or rule_set_version or "unversioned"),
        "authoritativeInputs": authoritative_inputs,
        "modifiers": _json_object(explanation.get("modifiers")),
        "formula": _string_value(explanation, "formula"),
    }


def _review_citations(explanation: dict[str, Any], director_plan: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for value in [
        *_dict_list(explanation.get("citations")),
        *_dict_list(director_plan.get("citations")),
    ]:
        if not isinstance(value, dict):
            continue
        citation: dict[str, Any] = {}
        for key in ("source", "location"):
            if isinstance(value.get(key), str) and value[key]:
                citation[key] = value[key]
        if isinstance(value.get("page"), int):
            citation["page"] = value["page"]
        elif isinstance(value.get("page_number"), int):
            citation["pageNumber"] = value["page_number"]
        if citation:
            citations.append(citation)
    return citations


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


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


@router.post("/{room_id}/action-reviews/{review_request_id}/recalculate")
async def recalculate_review(
    request: Request,
    room_id: str,
    review_request_id: str,
    body: ActionReviewRecalculation,
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
    try:
        result = recalculate_action_review(
            conn,
            dict(review),
            difficulty=body.difficulty,
            reason=body.reason.strip(),
        )
    except ActionReviewAlreadyResolved as exc:
        raise HTTPException(409, detail={"code": "review_already_resolved"}) from exc
    except ActionReviewRecalculationError as exc:
        raise HTTPException(422, detail={"code": exc.code}) from exc
    return {
        "review_request_id": review_request_id,
        "status": result["status"],
        "compensation_transaction_id": result["compensation_transaction_id"],
        "recalculation": result["recalculation"],
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

    async with character_lifecycle_guard(
        [str(action["character_id"])],
        conn=conn,
    ):
        current = conn.execute(
            "SELECT action_id, character_id, status FROM actions "
            "WHERE action_id = %s AND room_id = %s",
            (action_id, room_id),
        ).fetchone()
        if not current:
            raise HTTPException(404, detail={"code": "action_not_found"})
        if current["status"] != "awaiting_host_exception":
            raise HTTPException(
                409,
                detail={"code": "exception_already_resolved"},
            )
        return _resolve_action_exception_locked(
            conn,
            room_id=room_id,
            action=dict(current),
            body=body,
        )


def _resolve_action_exception_locked(
    conn,
    *,
    room_id: str,
    action: dict[str, Any],
    body: ActionExceptionResolution,
):
    action_id = str(action["action_id"])

    if body.decision == "request_player_choice":
        with conn.transaction() as tx:
            transitioned = transition_action(
                conn,
                action_id,
                from_statuses=("awaiting_host_exception",),
                to_status="awaiting_player_choice",
                metadata={"reason": body.reason.strip()},
                transaction=tx,
            )
            if not transitioned:
                raise HTTPException(
                    409,
                    detail={"code": "exception_already_resolved"},
                )
            EventLog(tx).log_event(
                room_id,
                "s2c_action_choice_requested",
                "player",
                {
                    "actionId": action_id,
                    "characterId": action["character_id"],
                    "status": "awaiting_player_choice",
                    "reason": body.reason.strip(),
                },
                commit=False,
            )
        return {"action_id": action_id, "status": "awaiting_player_choice"}
    else:
        from ..ai.decision_audit import finalize_terminal_decision_audit

        with conn.transaction() as tx:
            transitioned = complete_action(
                conn,
                action_id,
                from_statuses=("awaiting_host_exception",),
                to_status="rejected",
                result={"reason": body.reason.strip()},
                metadata={"reason_code": "host_exception_rejected"},
                transaction=tx,
            )
            if not transitioned:
                raise HTTPException(
                    409,
                    detail={"code": "exception_already_resolved"},
                )
            finalize_terminal_decision_audit(
                tx,
                action_id,
                action_status="rejected",
                reason_code="host_exception_rejected",
            )
            EventLog(tx).log_event(
                room_id,
                "s2c_action_completed",
                "player",
                {
                    "actionId": action_id,
                    "characterId": action["character_id"],
                    "status": "rejected",
                    "reason": body.reason.strip(),
                },
                commit=False,
            )
        return {"action_id": action_id, "status": "rejected"}
