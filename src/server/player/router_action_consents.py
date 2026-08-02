from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request

from ..engine.action_consent import (
    ActionConsentError,
    expire_pending_action_consents,
    respond_to_action_consent,
)


router = APIRouter(prefix="/api/player")


class ActionConsentResponseRequest(BaseModel):
    accepted: bool


def _require_character(request: Request) -> dict:
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    character = request.app.state.db.execute(
        "SELECT character_id, room_id, status FROM characters WHERE player_token = %s",
        (token,),
    ).fetchone()
    if not character or character.get("status") not in {"joined", "ready"}:
        raise HTTPException(403, "Invalid token")
    return dict(character)


def _consent_projection(row: dict) -> dict:
    return {
        "consentId": row["consent_id"],
        "actionId": row["action_id"],
        "requesterCharacterId": row["requester_character_id"],
        "consentKind": row["consent_kind"],
        "decision": row["decision"],
        "declaredIntent": row.get("declared_intent") or "",
        "expiresAt": str(row["expires_at"]),
    }


@router.get("/action-consents")
async def list_pending_action_consents(request: Request):
    character = _require_character(request)
    conn = request.app.state.db
    action_ids = conn.execute(
        "SELECT DISTINCT action_id FROM action_consents "
        "WHERE affected_character_id = %s AND decision = 'pending'",
        (character["character_id"],),
    ).fetchall()
    for row in action_ids:
        expire_pending_action_consents(conn, row["action_id"])
    rows = conn.execute(
        "SELECT consents.*, actions.declared_intent FROM action_consents AS consents "
        "JOIN actions ON actions.action_id = consents.action_id "
        "WHERE consents.affected_character_id = %s AND consents.decision = 'pending' "
        "AND actions.status = 'awaiting_player_consent' ORDER BY consents.created_at",
        (character["character_id"],),
    ).fetchall()
    return {"items": [_consent_projection(dict(row)) for row in rows]}


@router.post("/action-consents/{consent_id}")
async def answer_action_consent(
    request: Request,
    consent_id: str,
    body: ActionConsentResponseRequest,
):
    character = _require_character(request)
    try:
        result = respond_to_action_consent(
            request.app.state.db,
            consent_id=consent_id,
            character_id=character["character_id"],
            accepted=body.accepted,
        )
    except ActionConsentError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail) from exc

    newly_ready = bool(result.pop("_newlyReady", False))
    if newly_ready and result["actionStatus"] == "queued":
        from .action_service import stage_collaboration_action_after_consent

        result["actionStatus"] = stage_collaboration_action_after_consent(
            request.app.state.db,
            result["actionId"],
        )
        from .router_actions_v2 import (
            _ready_collaboration_batch_id,
            _schedule_action_resolution,
            _schedule_collaboration_batch_resolution,
        )

        if result["actionStatus"] == "batched":
            contract_id = _ready_collaboration_batch_id(
                request.app.state.db, result["actionId"]
            )
            if contract_id:
                _schedule_collaboration_batch_resolution(
                    request.app,
                    request.app.state.db,
                    contract_id,
                )
        else:
            _schedule_action_resolution(
                request.app,
                request.app.state.db,
                result["actionId"],
            )
    return result
