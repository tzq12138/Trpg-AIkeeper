"""Deterministic consumption of player-confirmed prepared reactions."""

from dataclasses import dataclass
from contextlib import nullcontext
import json
import uuid
from typing import Literal


PreparedTriggerKind = Literal[
    "enemy_public_attack_declared",
    "enemy_enters_melee_range",
    "ally_publicly_hurt",
    "combat_started",
]

_TRIGGER_KINDS = {
    "enemy_public_attack_declared",
    "enemy_enters_melee_range",
    "ally_publicly_hurt",
    "combat_started",
}
_REACTION_DECLARATIONS = {
    "take_cover": "准备反应：立即寻找掩体",
    "withdraw": "准备反应：立即撤离危险位置",
    "protect_ally": "准备反应：保护受伤的盟友",
}
_REACTION_ACTION_KINDS = {
    "take_cover": "defend",
    "withdraw": "flee",
    "protect_ally": "assist",
}


@dataclass(frozen=True)
class PreparedRuleEvent:
    kind: PreparedTriggerKind
    visibility: Literal["public"] = "public"
    source: Literal["rule_engine"] = "rule_engine"
    encounter_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _TRIGGER_KINDS:
            raise ValueError("prepared_rule_event_kind_invalid")

    @classmethod
    def enemy_public_attack_declared(cls) -> "PreparedRuleEvent":
        return cls(kind="enemy_public_attack_declared")

    @classmethod
    def combat_started(cls, encounter_id: str) -> "PreparedRuleEvent":
        return cls(kind="combat_started", encounter_id=encounter_id)

    @classmethod
    def enemy_enters_melee_range(cls, encounter_id: str) -> "PreparedRuleEvent":
        return cls(kind="enemy_enters_melee_range", encounter_id=encounter_id)

    @classmethod
    def ally_publicly_hurt(cls, encounter_id: str) -> "PreparedRuleEvent":
        return cls(kind="ally_publicly_hurt", encounter_id=encounter_id)


def consume_prepared_actions_for_rule_event(
    conn,
    *,
    room_id: str,
    source_action_id: str,
    rule_event: PreparedRuleEvent,
    transaction=None,
) -> list[dict[str, str]]:
    """Consume matching armed records after an authoritative public rule event.

    The function intentionally rejects untyped input so neither player text nor
    an AI response can invoke a prepared action directly.
    """
    if not isinstance(rule_event, PreparedRuleEvent):
        return []
    if rule_event.visibility != "public" or rule_event.source != "rule_engine":
        return []

    triggered: list[dict[str, str]] = []
    with (
        nullcontext(transaction)
        if transaction is not None
        else conn.transaction()
    ) as tx:
        from ..campaign_archive import CampaignReadOnlyError, ensure_campaign_writable

        try:
            ensure_campaign_writable(tx, room_id)
        except CampaignReadOnlyError:
            return []
        source_action = tx.execute(
            "SELECT action_id, room_id, params, status FROM actions "
            "WHERE action_id = %s FOR UPDATE",
            (source_action_id,),
        ).fetchone()
        if (
            not source_action
            or source_action["room_id"] != room_id
            or source_action["status"] not in {"completed", "resolved"}
        ):
            return []

        tx.execute(
            "UPDATE prepared_rule_actions SET status = 'expired' "
            "WHERE room_id = %s AND status = 'armed' AND expires_at <= NOW()",
            (room_id,),
        )
        rows = tx.execute(
            "SELECT prepared.action_id, prepared.character_id, prepared.reaction_kind, actions.draft_id, "
            "actions.params AS prepared_params "
            "FROM prepared_rule_actions AS prepared "
            "JOIN actions ON actions.action_id = prepared.action_id "
            "WHERE prepared.room_id = %s AND prepared.status = 'armed' "
            "AND actions.status = 'armed' "
            "AND prepared.trigger_kind = %s AND prepared.expires_at > NOW() "
            "ORDER BY prepared.created_at, prepared.action_id FOR UPDATE",
            (room_id, rule_event.kind),
        ).fetchall()
        source_params = _json_value(source_action.get("params"))
        encounter_id = rule_event.encounter_id or (
            source_params.get("encounterId") if isinstance(source_params, dict) else None
        )

        for row in rows:
            reaction_kind = str(row["reaction_kind"])
            declaration = _REACTION_DECLARATIONS.get(reaction_kind)
            action_kind = _REACTION_ACTION_KINDS.get(reaction_kind)
            if not declaration or not action_kind:
                continue
            prepared_action_id = str(row["action_id"])
            reaction_action_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"aikeeper:prepared-reaction:{prepared_action_id}:{source_action_id}",
                )
            )
            consumed = tx.execute(
                "UPDATE prepared_rule_actions SET status = 'triggered', source_action_id = %s, triggered_at = NOW() "
                "WHERE action_id = %s AND status = 'armed'",
                (source_action_id, prepared_action_id),
            )
            if consumed.rowcount != 1:
                continue
            action_params = {
                "preparedActionId": prepared_action_id,
                "sourceActionId": source_action_id,
                "preparedRuleEvent": rule_event.kind,
                "preparedReaction": True,
                "reactionKind": reaction_kind,
                "actionKind": action_kind,
            }
            if reaction_kind == "protect_ally":
                prepared_params = _json_value(row.get("prepared_params"))
                target_id = prepared_params.get("targetId")
                if not isinstance(target_id, str) or not target_id:
                    continue
                action_params["targetId"] = target_id
            if isinstance(encounter_id, str) and encounter_id:
                action_params["encounterId"] = encounter_id
            tx.execute(
                "INSERT INTO actions (action_id, room_id, character_id, draft_id, idempotency_key, "
                "intent_type, declared_intent, params, status) "
                "VALUES (%s, %s, %s, %s, %s, 'combat_action', %s, %s, 'queued') "
                "ON CONFLICT (action_id) DO NOTHING",
                (
                    reaction_action_id,
                    room_id,
                    row["character_id"],
                    None,
                    f"prepared:{prepared_action_id}:{source_action_id}",
                    declaration,
                    json.dumps(action_params, ensure_ascii=False),
                ),
            )
            tx.execute(
                "INSERT INTO action_status_events (action_id, status, metadata) "
                "VALUES (%s, 'queued', %s) ON CONFLICT DO NOTHING",
                (
                    reaction_action_id,
                    json.dumps(
                        {
                            "prepared_action_id": prepared_action_id,
                            "source_action_id": source_action_id,
                            "rule_event": rule_event.kind,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            completed = tx.execute(
                "UPDATE actions SET status = 'completed', completed_at = NOW(), result = %s "
                "WHERE action_id = %s AND status = 'armed'",
                (
                    json.dumps(
                        {
                            "kind": "prepared_action_triggered",
                            "reactionActionId": reaction_action_id,
                            "ruleEvent": rule_event.kind,
                        },
                        ensure_ascii=False,
                    ),
                    prepared_action_id,
                ),
            )
            if completed.rowcount != 1:
                raise RuntimeError("prepared_action_completion_conflict")
            tx.execute(
                "INSERT INTO action_status_events (action_id, status, metadata) "
                "VALUES (%s, 'completed', %s)",
                (
                    prepared_action_id,
                    json.dumps(
                        {
                            "reason": "prepared_rule_event_triggered",
                            "reaction_action_id": reaction_action_id,
                            "rule_event": rule_event.kind,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            from ..ai.decision_audit import finalize_terminal_decision_audit

            finalize_terminal_decision_audit(
                tx,
                prepared_action_id,
                action_status="completed",
                reason_code="prepared_rule_event_triggered",
            )
            triggered.append(
                {
                    "prepared_action_id": prepared_action_id,
                    "reaction_action_id": reaction_action_id,
                    "reaction_kind": reaction_kind,
                }
            )
    return triggered


def complete_triggered_prepared_reaction(
    conn,
    *,
    reaction_action_id: str,
    terminal_status: Literal["completed", "rejected", "timeout"],
    transaction=None,
) -> bool:
    """Close the source preparation after its internally queued reaction ends."""
    def execute(tx) -> bool:
        from ..campaign_archive import CampaignReadOnlyError, ensure_campaign_writable

        reaction = tx.execute(
            "SELECT room_id, params FROM actions WHERE action_id = %s FOR UPDATE",
            (reaction_action_id,),
        ).fetchone()
        if not reaction:
            return False
        try:
            ensure_campaign_writable(tx, reaction["room_id"])
        except CampaignReadOnlyError:
            return False
        params = _json_value(reaction.get("params"))
        prepared_action_id = params.get("preparedActionId") if isinstance(params, dict) else None
        if not isinstance(prepared_action_id, str) or not prepared_action_id:
            return False
        cursor = tx.execute(
            "UPDATE prepared_rule_actions SET status = %s, completed_at = NOW() "
            "WHERE action_id = %s AND room_id = %s AND status = 'triggered'",
            (terminal_status, prepared_action_id, reaction["room_id"]),
        )
        return cursor.rowcount == 1
    if transaction is not None:
        return execute(transaction)
    with conn.transaction() as tx:
        return execute(tx)


def _json_value(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}
