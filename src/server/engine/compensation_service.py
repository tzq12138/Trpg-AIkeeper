import json
import uuid

from ..events.event_log import EventLog
from ..models import CharacterMutationItem, StateChangeSet
from .roll_receipt import verify_roll_receipt
from .skill_check import _compute_threshold, _determine_success, is_success_for_difficulty
from .state_service import StateService


class ActionReviewAlreadyResolved(Exception):
    pass


class ActionReviewRecalculationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


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


def recalculate_action_review(
    conn,
    review: dict,
    *,
    difficulty: str,
    reason: str,
) -> dict:
    """Reinterpret one verified CoC7 skill roll without rerolling or changing world state."""
    if difficulty not in {"regular", "hard", "extreme"}:
        raise ActionReviewRecalculationError("recalculation_parameter_invalid")
    transaction_id = str(uuid.uuid4())
    with conn.transaction() as tx:
        locked = tx.execute(
            "SELECT status FROM action_review_requests "
            "WHERE review_request_id = %s FOR UPDATE",
            (review["review_request_id"],),
        ).fetchone()
        if not locked or locked["status"] != "pending":
            raise ActionReviewAlreadyResolved(review["review_request_id"])
        action = tx.execute(
            "SELECT intent_type, rule_set_version_id FROM actions WHERE action_id = %s",
            (review["action_id"],),
        ).fetchone()
        bundle = tx.execute(
            """SELECT rule_explanation FROM resolution_bundles
               WHERE action_id = %s AND room_id = %s""",
            (review["action_id"], review["room_id"]),
        ).fetchone()
        if not action or action.get("intent_type") != "skill_check" or not bundle:
            raise ActionReviewRecalculationError("recalculation_not_supported")

        explanation = _json_object(bundle.get("rule_explanation"))
        raw_rolls, roll, skill_value = _verified_skill_roll(
            explanation,
            action_id=review["action_id"],
            rule_set_version=action.get("rule_set_version_id"),
        )
        target = _compute_threshold(skill_value, difficulty)
        success_level = _determine_success(roll, target, skill_value)
        recalculation = {
            "roll": roll,
            "skillValue": skill_value,
            "difficulty": difficulty,
            "target": target,
            "successLevel": success_level,
            "isSuccess": is_success_for_difficulty(success_level, difficulty),
        }
        state_row = tx.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s",
            (review["room_id"],),
        ).fetchone()
        state_version = int(state_row.get("state_version") or 0) if state_row else 0
        payload = {
            "source_action_id": review["action_id"],
            "original_rolls": raw_rolls,
            "parameter_patch": {"difficulty": difficulty},
            "recalculation": recalculation,
            "state_version_before": state_version,
            "state_version_after": state_version,
        }
        tx.execute(
            "INSERT INTO compensation_transactions "
            "(transaction_id, room_id, character_id, review_request_id, transaction_type, payload, reason, status, applied_at) "
            "VALUES (%s, %s, %s, %s, 'roll_recalculation', %s, %s, 'applied', NOW())",
            (
                transaction_id,
                review["room_id"],
                review["character_id"],
                review["review_request_id"],
                json.dumps(payload, ensure_ascii=False),
                reason,
            ),
        )
        resolution = {
            "decision": "modified",
            "reason": reason,
            "recalculation": recalculation,
            "compensation_transaction_id": transaction_id,
        }
        tx.execute(
            "UPDATE action_review_requests SET status = 'modified', host_resolution = %s, resolved_at = NOW() "
            "WHERE review_request_id = %s",
            (json.dumps(resolution, ensure_ascii=False), review["review_request_id"]),
        )
        _notify_player(tx, review, "modified")
    return {
        "status": "modified",
        "compensation_transaction_id": transaction_id,
        "recalculation": recalculation,
    }


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _verified_skill_roll(
    explanation: dict,
    *,
    action_id: str,
    rule_set_version: str | None,
) -> tuple[list[dict], int, int]:
    receipt = _json_object(explanation.get("verification_receipt"))
    try:
        receipt_valid = verify_roll_receipt(receipt)
    except RuntimeError as exc:
        raise ActionReviewRecalculationError("roll_receipt_unavailable") from exc
    if not receipt_valid:
        raise ActionReviewRecalculationError("roll_receipt_invalid")
    if receipt.get("action_id") != action_id:
        raise ActionReviewRecalculationError("roll_receipt_action_mismatch")
    explanation_version = explanation.get("rule_set_version")
    if (
        not isinstance(explanation_version, str)
        or receipt.get("rule_set_version") != explanation_version
        or (rule_set_version and rule_set_version != explanation_version)
    ):
        raise ActionReviewRecalculationError("roll_receipt_rule_set_mismatch")
    inputs = _json_object(explanation.get("authoritative_inputs"))
    if inputs.get("intent_type") != "skill_check":
        raise ActionReviewRecalculationError("recalculation_not_supported")
    try:
        skill_value = max(0, int(inputs.get("skill_value")))
    except (TypeError, ValueError) as exc:
        raise ActionReviewRecalculationError("roll_receipt_invalid") from exc
    raw_rolls = receipt.get("raw_rolls")
    if not isinstance(raw_rolls, list):
        raise ActionReviewRecalculationError("roll_receipt_invalid")
    d100_rolls = [item for item in raw_rolls if isinstance(item, dict) and item.get("dice") == "d100"]
    if len(d100_rolls) != 1:
        raise ActionReviewRecalculationError("recalculation_not_supported")
    roll_record = d100_rolls[0]
    trace = _json_object(roll_record.get("values"))
    try:
        roll = int(roll_record.get("result"))
    except (TypeError, ValueError) as exc:
        raise ActionReviewRecalculationError("roll_receipt_invalid") from exc
    candidates = trace.get("candidates")
    if (
        not isinstance(candidates, list)
        or roll not in candidates
        or roll < 1
        or roll > 100
    ):
        raise ActionReviewRecalculationError("roll_receipt_invalid")
    return raw_rolls, roll, skill_value


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
