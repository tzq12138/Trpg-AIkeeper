"""Per-action affected-player consent and fail-closed group decisions."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


PVP_EFFECTS = {
    "damage",
    "resource_take",
    "restrict_action",
    "status_change",
}
GROUP_DECISION_KINDS = {
    "reversible_route",
    "shared_resource",
    "ending",
    "abandon_ally",
    "risk_expansion",
}
UNANIMOUS_GROUP_DECISIONS = GROUP_DECISION_KINDS - {"reversible_route"}


class ActionConsentError(Exception):
    def __init__(self, status_code: int, detail: dict[str, Any]):
        super().__init__(str(detail.get("code") or "action_consent_error"))
        self.status_code = status_code
        self.detail = detail


def evaluate_group_decision(
    decisions: Iterable[str],
    decision_kind: str,
    *,
    final: bool = False,
) -> dict[str, Any]:
    """Evaluate a group vote without treating silence as consent.

    Reversible routing uses a strict majority. Decisions that spend major shared
    resources, select an ending, abandon an ally, or expand accepted risk require
    unanimity. At a deadline, pending responses are abstentions and fail closed.
    """

    normalized = [str(value or "pending").lower() for value in decisions]
    total = len(normalized)
    approvals = normalized.count("accepted")
    pending = sum(value == "pending" for value in normalized)
    if decision_kind in UNANIMOUS_GROUP_DECISIONS:
        required = total
        if total and approvals == total:
            outcome = "approved"
        elif not final and pending and all(value in {"accepted", "pending"} for value in normalized):
            outcome = "pending"
        else:
            outcome = "no_effect"
    else:
        required = total // 2 + 1
        if total and approvals >= required:
            outcome = "approved"
        elif not final and approvals + pending >= required:
            outcome = "pending"
        else:
            outcome = "safer_result"
    return {
        "outcome": outcome,
        "requiredApprovals": required,
        "approvals": approvals,
        "total": total,
    }


def consent_requirements_for_action(
    conn,
    *,
    room_id: str,
    actor_character_id: str,
    intent_type: str,
    params: dict[str, Any],
) -> list[dict[str, str]]:
    """Return consent rows required by this concrete action.

    A character target is distinguished from an NPC by a same-room character
    record. Collaboration membership and room-level settings are intentionally
    not consulted: neither is a substitute for consent to this action.
    """

    requirements: list[dict[str, str]] = []
    target_id = str(params.get("targetId") or "").strip()
    effect = str(params.get("pvpEffect") or "").strip()
    if not effect and target_id and intent_type == "combat_action":
        effect = "damage"
    if target_id and effect in PVP_EFFECTS and target_id != actor_character_id:
        target = conn.execute(
            "SELECT character_id FROM characters "
            "WHERE character_id = %s AND room_id = %s AND status != 'left'",
            (target_id, room_id),
        ).fetchone()
        if target:
            requirements.append(
                {
                    "affected_character_id": str(target["character_id"]),
                    "consent_kind": f"pvp_{effect}",
                    "decision": "pending",
                }
            )

    decision_kind = str(params.get("groupDecisionKind") or "").strip()
    if decision_kind in GROUP_DECISION_KINDS:
        active = conn.execute(
            "SELECT character_id FROM characters WHERE room_id = %s "
            "AND status IN ('joined', 'ready') ORDER BY character_id",
            (room_id,),
        ).fetchall()
        active_ids = [str(row["character_id"]) for row in active]
        # The client cannot narrow the electorate. Until the authoritative state
        # engine supplies a smaller affected set, every active room character is
        # treated as affected; this is the fail-closed interpretation.
        for character_id in active_ids:
            requirements.append(
                {
                    "affected_character_id": character_id,
                    "consent_kind": f"group_{decision_kind}",
                    "decision": "accepted" if character_id == actor_character_id else "pending",
                }
            )

    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for item in requirements:
        key = (item["affected_character_id"], item["consent_kind"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def requirements_need_response(requirements: list[dict[str, str]]) -> bool:
    if not requirements:
        return False
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in requirements:
        grouped[item["consent_kind"]].append(item["decision"])
    for kind, decisions in grouped.items():
        if kind.startswith("pvp_") and any(value != "accepted" for value in decisions):
            return True
        if kind.startswith("group_"):
            result = evaluate_group_decision(decisions, kind.removeprefix("group_"))
            if result["outcome"] != "approved":
                return True
    return False


def insert_action_consents(
    tx,
    *,
    action_id: str,
    room_id: str,
    requester_character_id: str,
    requirements: list[dict[str, str]],
    expires_in_seconds: int = 120,
) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
    for requirement in requirements:
        consent_id = str(uuid.uuid4())
        tx.execute(
            "INSERT INTO action_consents "
            "(consent_id, action_id, room_id, requester_character_id, "
            "affected_character_id, consent_kind, decision, expires_at, responded_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, "
            "CASE WHEN %s = 'accepted' THEN NOW() ELSE NULL END)",
            (
                consent_id,
                action_id,
                room_id,
                requester_character_id,
                requirement["affected_character_id"],
                requirement["consent_kind"],
                requirement["decision"],
                expires_at,
                requirement["decision"],
            ),
        )
        if requirement["decision"] == "pending":
            tx.execute(
                "INSERT INTO events (room_id, event_type, audience, payload) "
                "VALUES (%s, 's2c_private_notice', 'player', %s)",
                (
                    room_id,
                    json.dumps(
                        {
                            "kind": "action_consent_requested",
                            "actionId": action_id,
                            "characterId": requirement["affected_character_id"],
                            "consentId": consent_id,
                            "consentKind": requirement["consent_kind"],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )


def _set_terminal_no_effect(tx, action_id: str, status: str, reason: str, outcome: str) -> str:
    from ..ai.decision_audit import finalize_terminal_decision_audit

    result = {"outcome": outcome, "reason": reason}
    cursor = tx.execute(
        "UPDATE actions SET status = %s, result = %s, completed_at = NOW() "
        "WHERE action_id = %s AND status IN ('awaiting_player_consent', 'queued', 'batched')",
        (status, json.dumps(result, ensure_ascii=False), action_id),
    )
    if cursor.rowcount:
        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) VALUES (%s, %s, %s)",
            (
                action_id,
                status,
                json.dumps({"reason_code": reason, "effect": outcome}, ensure_ascii=False),
            ),
        )
        finalize_terminal_decision_audit(
            tx,
            action_id,
            action_status=status,
            reason_code=reason,
            effect=outcome,
        )
    return status


def _evaluate_action_rows(tx, action_id: str, *, final: bool) -> str:
    action = tx.execute(
        "SELECT action_id, status FROM actions WHERE action_id = %s FOR UPDATE",
        (action_id,),
    ).fetchone()
    if not action:
        raise ActionConsentError(404, {"code": "action_not_found"})
    rows = tx.execute(
        "SELECT consent_kind, decision FROM action_consents "
        "WHERE action_id = %s ORDER BY consent_kind, affected_character_id FOR UPDATE",
        (action_id,),
    ).fetchall()
    if not rows:
        return str(action["status"])

    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        grouped[str(row["consent_kind"])].append(str(row["decision"]))

    all_approved = True
    for kind, decisions in grouped.items():
        if kind.startswith("pvp_"):
            if "rejected" in decisions:
                return _set_terminal_no_effect(
                    tx, action_id, "rejected", "player_consent_rejected", "no_effect"
                )
            if "expired" in decisions:
                return _set_terminal_no_effect(
                    tx, action_id, "timeout", "player_consent_expired", "no_effect"
                )
            all_approved = all_approved and all(value == "accepted" for value in decisions)
            continue
        decision_kind = kind.removeprefix("group_")
        result = evaluate_group_decision(decisions, decision_kind, final=final)
        if result["outcome"] == "no_effect":
            return _set_terminal_no_effect(
                tx, action_id, "rejected", "group_decision_not_unanimous", "no_effect"
            )
        if result["outcome"] == "safer_result":
            return _set_terminal_no_effect(
                tx, action_id, "rejected", "group_decision_threshold_not_met", "safer_result"
            )
        all_approved = all_approved and result["outcome"] == "approved"

    if all_approved and action["status"] == "awaiting_player_consent":
        tx.execute(
            "UPDATE actions SET status = 'queued' WHERE action_id = %s",
            (action_id,),
        )
        tx.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) "
            "VALUES (%s, 'queued', %s)",
            (
                action_id,
                json.dumps({"source": "affected_player_consent"}, ensure_ascii=False),
            ),
        )
        return "queued"
    return str(action["status"])


def respond_to_action_consent(
    conn,
    *,
    consent_id: str,
    character_id: str,
    accepted: bool,
) -> dict[str, Any]:
    expired = False
    with conn.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM action_consents WHERE consent_id = %s",
            (consent_id,),
        ).fetchone()
        if not row:
            raise ActionConsentError(404, {"code": "action_consent_not_found"})
        if row["affected_character_id"] != character_id:
            raise ActionConsentError(403, {"code": "action_consent_response_forbidden"})
        # Serialize every response for an action on the action row first. Locking
        # separate consent rows before the shared action would permit a deadlock
        # when two affected players answer at the same time.
        action_lock = tx.execute(
            "SELECT status FROM actions WHERE action_id = %s FOR UPDATE",
            (row["action_id"],),
        ).fetchone()
        if not action_lock:
            raise ActionConsentError(404, {"code": "action_not_found"})
        prior_action_status = str(action_lock["status"])
        row = tx.execute(
            "SELECT * FROM action_consents WHERE consent_id = %s FOR UPDATE",
            (consent_id,),
        ).fetchone()
        if not row:
            raise ActionConsentError(404, {"code": "action_consent_not_found"})

        desired = "accepted" if accepted else "rejected"
        decision = str(row["decision"])
        if decision in {"accepted", "rejected"}:
            if decision != desired:
                raise ActionConsentError(409, {"code": "action_consent_already_decided"})
            action = tx.execute(
                "SELECT status FROM actions WHERE action_id = %s",
                (row["action_id"],),
            ).fetchone()
            return {
                "consentId": consent_id,
                "actionId": row["action_id"],
                "decision": decision,
                "actionStatus": action["status"] if action else "missing",
                "_newlyReady": False,
            }
        if decision == "expired":
            expired = True
        else:
            expired_row = tx.execute(
                "UPDATE action_consents SET decision = 'expired', responded_at = NOW() "
                "WHERE consent_id = %s AND decision = 'pending' AND expires_at <= NOW() "
                "RETURNING action_id",
                (consent_id,),
            ).fetchone()
            if expired_row:
                expired = True
            else:
                tx.execute(
                    "UPDATE action_consents SET decision = %s, responded_at = NOW() "
                    "WHERE consent_id = %s AND decision = 'pending'",
                    (desired, consent_id),
                )
                decision = desired
        action_status = _evaluate_action_rows(tx, row["action_id"], final=expired)

    if expired:
        raise ActionConsentError(409, {"code": "action_consent_expired"})
    return {
        "consentId": consent_id,
        "actionId": row["action_id"],
        "decision": decision,
        "actionStatus": action_status,
        "_newlyReady": (
            prior_action_status == "awaiting_player_consent" and action_status == "queued"
        ),
    }


def expire_pending_action_consents(conn, action_id: str) -> str:
    with conn.transaction() as tx:
        expired = tx.execute(
            "UPDATE action_consents SET decision = 'expired', responded_at = NOW() "
            "WHERE action_id = %s AND decision = 'pending' AND expires_at <= NOW()",
            (action_id,),
        ).rowcount
        return _evaluate_action_rows(tx, action_id, final=bool(expired))


def enforce_action_consent_gate(conn, action_id: str) -> bool:
    """Return True only when every consent gate is satisfied.

    The resolution pipeline calls this before claiming the action, which keeps
    RNG and state writes behind the consent boundary even if a queued row was
    produced by old code or manual database intervention.
    """

    count = conn.execute(
        "SELECT COUNT(*) AS count FROM action_consents WHERE action_id = %s",
        (action_id,),
    ).fetchone()["count"]
    if not count:
        return True
    status = expire_pending_action_consents(conn, action_id)
    if status in {"rejected", "timeout"}:
        return False
    rows = conn.execute(
        "SELECT consent_kind, decision FROM action_consents WHERE action_id = %s",
        (action_id,),
    ).fetchall()
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        grouped[str(row["consent_kind"])].append(str(row["decision"]))
    for kind, decisions in grouped.items():
        if kind.startswith("pvp_") and not all(value == "accepted" for value in decisions):
            return False
        if kind.startswith("group_") and evaluate_group_decision(
            decisions, kind.removeprefix("group_")
        )["outcome"] != "approved":
            return False
    return True
