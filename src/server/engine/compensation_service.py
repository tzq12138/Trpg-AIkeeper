import json
import uuid

from ..events.event_log import EventLog
from ..models import CharacterMutationItem, StateChangeSet
from .state_service import StateService


class ActionReviewAlreadyResolved(Exception):
    pass


def resolve_action_review(
    app_state,
    conn,
    review: dict,
    *,
    decision: str,
    reason: str,
    mutations: list[dict],
) -> dict:
    resolution = {
        "decision": decision,
        "reason": reason,
        "mutations": mutations,
    }
    transaction_id = str(uuid.uuid4()) if mutations else None
    with conn.transaction() as tx:
        locked = tx.execute(
            "SELECT status FROM action_review_requests "
            "WHERE review_request_id = %s FOR UPDATE",
            (review["review_request_id"],),
        ).fetchone()
        if not locked or locked["status"] != "pending":
            raise ActionReviewAlreadyResolved(review["review_request_id"])

        if mutations:
            payload = {"mutations": mutations}
            tx.execute(
                "INSERT INTO compensation_transactions "
                "(transaction_id, room_id, character_id, review_request_id, transaction_type, payload, reason, status) "
                "VALUES (%s, %s, %s, %s, 'state_mutation', %s, %s, 'applying')",
                (
                    transaction_id,
                    review["room_id"],
                    review["character_id"],
                    review["review_request_id"],
                    json.dumps(payload, ensure_ascii=False),
                    reason,
                ),
            )
            state_service = getattr(app_state, "state_service", None) or StateService(conn)
            state_service.apply_change(
                room_id=review["room_id"],
                actor={
                    "character_id": review["character_id"],
                    "action_id": review["action_id"],
                    "review_request_id": review["review_request_id"],
                },
                changes=StateChangeSet(
                    characterMutations=[
                        CharacterMutationItem(
                            characterId=review["character_id"],
                            mutations=mutations,
                        )
                    ]
                ),
                reason=reason,
                transaction=tx,
            )
            tx.execute(
                "UPDATE compensation_transactions SET status = 'applied', applied_at = NOW() "
                "WHERE transaction_id = %s",
                (transaction_id,),
            )

        tx.execute(
            "UPDATE action_review_requests SET status = %s, host_resolution = %s, resolved_at = NOW() "
            "WHERE review_request_id = %s",
            (decision, json.dumps(resolution, ensure_ascii=False), review["review_request_id"]),
        )
        _notify_player(tx, review, decision)
    return {"status": decision, "compensation_transaction_id": transaction_id}


def _notify_player(conn, review: dict, decision: str) -> None:
    EventLog(conn).log_event(
        review["room_id"],
        "s2c_action_review_resolved",
        "player",
        {
            "reviewRequestId": review["review_request_id"],
            "actionId": review["action_id"],
            "characterId": review["character_id"],
            "status": decision,
        },
        commit=False,
    )
