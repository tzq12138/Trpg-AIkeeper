import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from ..events.events_registry import event_type
from ..models import (
    ActionDraftAnalyzeRequest,
    CollaborationContractCreateRequest,
    CollaborationContractDTO,
    CollaborationContractResponseRequest,
)
from .action_service import (
    analyze_action_draft,
    insert_action_draft,
    redact_backstage_references,
)


router = APIRouter(prefix="/api/player")

_ACTIVE_ACTION_STATUSES = {
    "awaiting_player_consent",
    "queued",
    "batched",
    "resolving",
    "awaiting_player_choice",
    "awaiting_host_exception",
}


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


def _contract_dto(conn, contract_id: str) -> CollaborationContractDTO:
    contract = conn.execute(
        "SELECT * FROM collaboration_contracts WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()
    if not contract:
        raise HTTPException(404, detail={"code": "collaboration_contract_not_found"})
    participants = conn.execute(
        "SELECT character_id, decision FROM collaboration_contract_participants "
        "WHERE contract_id = %s "
        "ORDER BY invite_order, character_id",
        (contract_id,),
    ).fetchall()
    linked_drafts = conn.execute(
        "SELECT links.character_id, links.draft_id, drafts.status "
        "FROM collaboration_contract_drafts AS links "
        "JOIN action_drafts AS drafts ON drafts.draft_id = links.draft_id "
        "WHERE links.contract_id = %s ORDER BY links.character_id",
        (contract_id,),
    ).fetchall()
    return CollaborationContractDTO(
        contractId=contract["contract_id"],
        roomId=contract["room_id"],
        initiatorCharacterId=contract["initiator_character_id"],
        sharedIntent=contract["shared_intent"],
        status=contract["status"],
        participantCharacterIds=[row["character_id"] for row in participants],
        pendingCharacterIds=[
            row["character_id"] for row in participants if row["decision"] == "pending"
        ],
        linkedDrafts=[
            {
                "characterId": row["character_id"],
                "draftId": row["draft_id"],
                "status": row["status"],
            }
            for row in linked_drafts
        ],
        expiresAt=contract["expires_at"],
    )


def _participant_has_action_conflict(tx, character_id: str) -> bool:
    draft = tx.execute(
        "SELECT draft_id FROM action_drafts WHERE character_id = %s "
        "AND status IN ('analyzing', 'awaiting_confirmation') FOR UPDATE",
        (character_id,),
    ).fetchone()
    if draft:
        return True
    action = tx.execute(
        "SELECT action_id FROM actions WHERE character_id = %s AND status = ANY(%s) FOR UPDATE",
        (character_id, list(_ACTIVE_ACTION_STATUSES)),
    ).fetchone()
    return bool(action)


def _build_linked_draft(contract: dict, character: dict, state_version: int):
    draft = analyze_action_draft(
        ActionDraftAnalyzeRequest(
            declared_intent=f"协同行动：{contract['shared_intent']}",
            intent_type="action",
            base_state_version=state_version,
            params={"collaborationContractId": contract["contract_id"]},
        )
    )
    intent_contract = draft.intent_contract.model_copy(update={"visibility": "party"})
    requirements = sorted(set(draft.confirmation_requirements + ["collaboration_contract"]))
    return draft.model_copy(
        update={
            "risk": "high",
            "visibility": "party",
            "intent_contract": intent_contract,
            "understanding_summary": f"你已同意协同行动：{contract['shared_intent']}",
            "requires_confirmation": True,
            "confirmation_requirements": requirements,
            "params": {"collaborationContractId": contract["contract_id"]},
        }
    )


def _expire_if_needed(tx, contract: dict) -> bool:
    if contract["status"] != "pending":
        return contract["status"] == "expired"
    cursor = tx.execute(
        "UPDATE collaboration_contracts SET status = 'expired', updated_at = NOW() "
        "WHERE contract_id = %s AND status = 'pending' AND expires_at <= NOW()",
        (contract["contract_id"],),
    )
    return cursor.rowcount > 0


@router.post("/collaboration-contracts", response_model=CollaborationContractDTO, status_code=201)
async def create_collaboration_contract(
    request: Request,
    body: CollaborationContractCreateRequest,
):
    character = _require_character(request)
    conn = request.app.state.db
    invitees = list(dict.fromkeys(body.invitee_character_ids))
    if len(invitees) != len(body.invitee_character_ids):
        raise HTTPException(422, detail={"code": "duplicate_collaboration_invitee"})
    if character["character_id"] in invitees:
        raise HTTPException(422, detail={"code": "initiator_cannot_invite_self"})
    shared_intent = redact_backstage_references(body.shared_intent).strip()
    if not shared_intent:
        raise HTTPException(422, detail={"code": "collaboration_intent_required"})
    contract_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=body.expires_in_seconds)

    with conn.transaction() as tx:
        participant_ids = [character["character_id"], *invitees]
        for participant_id in participant_ids:
            participant = tx.execute(
                "SELECT character_id, room_id FROM characters WHERE character_id = %s FOR UPDATE",
                (participant_id,),
            ).fetchone()
            if not participant or participant["room_id"] != character["room_id"]:
                raise HTTPException(409, detail={"code": "collaboration_invitee_not_in_room"})
            if _participant_has_action_conflict(tx, participant_id):
                raise HTTPException(409, detail={"code": "collaboration_action_conflict"})
        tx.execute(
            "INSERT INTO collaboration_contracts "
            "(contract_id, room_id, initiator_character_id, shared_intent, expires_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                contract_id,
                character["room_id"],
                character["character_id"],
                shared_intent,
                expires_at,
            ),
        )
        tx.execute(
            "INSERT INTO collaboration_contract_participants "
            "(contract_id, character_id, role, invite_order, decision, responded_at) "
            "VALUES (%s, %s, 'initiator', 0, 'accepted', NOW())",
            (contract_id, character["character_id"]),
        )
        for invite_order, invitee_id in enumerate(invitees, start=1):
            tx.execute(
                "INSERT INTO collaboration_contract_participants "
                "(contract_id, character_id, role, invite_order) VALUES (%s, %s, 'invitee', %s)",
                (contract_id, invitee_id, invite_order),
            )
            tx.execute(
                "INSERT INTO events (room_id, event_type, audience, payload) "
                "VALUES (%s, %s, 'player', %s)",
                (
                    character["room_id"],
                    event_type("s2c_private_notice"),
                    json.dumps(
                        {
                            "kind": "collaboration_invite",
                            "contractId": contract_id,
                            "sharedIntent": shared_intent,
                            "characterId": invitee_id,
                            "expiresAt": expires_at.isoformat(),
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
    return _contract_dto(conn, contract_id)


@router.get("/collaboration-contracts", response_model=dict)
async def list_collaboration_contracts(request: Request):
    character = _require_character(request)
    conn = request.app.state.db
    conn.execute(
        "UPDATE collaboration_contracts AS contracts SET status = 'expired', updated_at = NOW() "
        "WHERE contracts.status = 'pending' AND contracts.expires_at <= NOW() "
        "AND EXISTS (SELECT 1 FROM collaboration_contract_participants AS participants "
        "WHERE participants.contract_id = contracts.contract_id AND participants.character_id = %s)",
        (character["character_id"],),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT contracts.contract_id FROM collaboration_contracts AS contracts "
        "JOIN collaboration_contract_participants AS participants "
        "ON participants.contract_id = contracts.contract_id "
        "WHERE participants.character_id = %s AND contracts.room_id = %s "
        "ORDER BY contracts.created_at DESC",
        (character["character_id"], character["room_id"]),
    ).fetchall()
    return {"items": [_contract_dto(conn, row["contract_id"]).model_dump(by_alias=True) for row in rows]}


@router.get("/collaboration-contracts/participants", response_model=dict)
async def list_collaboration_participants(request: Request):
    character = _require_character(request)
    rows = request.app.state.db.execute(
        "SELECT character_id, player_name FROM characters "
        "WHERE room_id = %s AND status != 'left' ORDER BY character_id",
        (character["room_id"],),
    ).fetchall()
    return {
        "items": [
            {"characterId": row["character_id"], "playerName": row["player_name"]}
            for row in rows
        ]
    }


@router.post(
    "/collaboration-contracts/{contract_id}/responses",
    response_model=CollaborationContractDTO,
)
async def respond_to_collaboration_contract(
    request: Request,
    contract_id: str,
    body: CollaborationContractResponseRequest,
):
    character = _require_character(request)
    conn = request.app.state.db
    expired = False
    conflict = False
    with conn.transaction() as tx:
        contract = tx.execute(
            "SELECT * FROM collaboration_contracts WHERE contract_id = %s FOR UPDATE",
            (contract_id,),
        ).fetchone()
        if not contract or contract["room_id"] != character["room_id"]:
            raise HTTPException(404, detail={"code": "collaboration_contract_not_found"})
        contract = dict(contract)
        participant = tx.execute(
            "SELECT * FROM collaboration_contract_participants "
            "WHERE contract_id = %s AND character_id = %s FOR UPDATE",
            (contract_id, character["character_id"]),
        ).fetchone()
        if not participant:
            raise HTTPException(403, detail={"code": "collaboration_response_forbidden"})
        expired = _expire_if_needed(tx, contract)
        if not expired and contract["status"] == "pending":
            if body.decision == "decline":
                tx.execute(
                    "UPDATE collaboration_contract_participants SET decision = 'declined', responded_at = NOW() "
                    "WHERE contract_id = %s AND character_id = %s",
                    (contract_id, character["character_id"]),
                )
                tx.execute(
                    "UPDATE collaboration_contracts SET status = 'canceled', canceled_at = NOW(), updated_at = NOW() "
                    "WHERE contract_id = %s",
                    (contract_id,),
                )
            else:
                tx.execute(
                    "UPDATE collaboration_contract_participants SET decision = 'accepted', responded_at = NOW() "
                    "WHERE contract_id = %s AND character_id = %s",
                    (contract_id, character["character_id"]),
                )
                pending = tx.execute(
                    "SELECT COUNT(*) AS count FROM collaboration_contract_participants "
                    "WHERE contract_id = %s AND decision = 'pending'",
                    (contract_id,),
                ).fetchone()["count"]
                if pending == 0:
                    participants = tx.execute(
                        "SELECT characters.character_id, characters.room_id "
                        "FROM collaboration_contract_participants AS membership "
                        "JOIN characters ON characters.character_id = membership.character_id "
                        "WHERE membership.contract_id = %s ORDER BY characters.character_id FOR UPDATE",
                        (contract_id,),
                    ).fetchall()
                    conflict = any(
                        _participant_has_action_conflict(tx, participant_row["character_id"])
                        for participant_row in participants
                    )
                    if conflict:
                        tx.execute(
                            "UPDATE collaboration_contracts SET status = 'canceled', canceled_at = NOW(), updated_at = NOW() "
                            "WHERE contract_id = %s",
                            (contract_id,),
                        )
                    else:
                        room = tx.execute(
                            "SELECT state_version FROM rooms WHERE room_id = %s FOR UPDATE",
                            (contract["room_id"],),
                        ).fetchone()
                        for participant_row in participants:
                            participant_dict = dict(participant_row)
                            draft = _build_linked_draft(
                                contract,
                                participant_dict,
                                int(room["state_version"]),
                            )
                            draft_id = insert_action_draft(tx, participant_dict, draft)
                            tx.execute(
                                "INSERT INTO collaboration_contract_drafts "
                                "(contract_id, character_id, draft_id) VALUES (%s, %s, %s)",
                                (contract_id, participant_dict["character_id"], draft_id),
                            )
                        tx.execute(
                            "UPDATE collaboration_contracts SET status = 'accepted', accepted_at = NOW(), updated_at = NOW() "
                            "WHERE contract_id = %s",
                            (contract_id,),
                        )
    if expired:
        raise HTTPException(409, detail={"code": "collaboration_contract_expired"})
    if conflict:
        raise HTTPException(409, detail={"code": "collaboration_action_conflict"})
    return _contract_dto(conn, contract_id)


@router.post("/collaboration-contracts/{contract_id}/cancel", response_model=CollaborationContractDTO)
async def cancel_collaboration_contract(request: Request, contract_id: str):
    character = _require_character(request)
    conn = request.app.state.db
    with conn.transaction() as tx:
        contract = tx.execute(
            "SELECT * FROM collaboration_contracts WHERE contract_id = %s FOR UPDATE",
            (contract_id,),
        ).fetchone()
        if not contract or contract["room_id"] != character["room_id"]:
            raise HTTPException(404, detail={"code": "collaboration_contract_not_found"})
        if contract["initiator_character_id"] != character["character_id"]:
            raise HTTPException(403, detail={"code": "collaboration_cancel_forbidden"})
        if _expire_if_needed(tx, dict(contract)):
            pass
        elif contract["status"] != "pending":
            raise HTTPException(409, detail={"code": "collaboration_contract_not_cancelable"})
        else:
            tx.execute(
                "UPDATE collaboration_contracts SET status = 'canceled', canceled_at = NOW(), updated_at = NOW() "
                "WHERE contract_id = %s",
                (contract_id,),
            )
    return _contract_dto(conn, contract_id)
