"""Persistent player reactions for the scripted black-bear solo encounter."""

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from ..models import CharacterMutationItem, StateChangeSet
from ..rules.coc_handlers import roll_dice
from ..scenario.solo_runtime import SoloAdventureRuntime
from .roll_receipt import create_roll_receipt
from .skill_check import SUCCESS_LEVEL_RANK, roll_skill_check
from .state_service import StateService


class SoloCombatReactionError(ValueError):
    """Raised when a player tries to resolve an unavailable combat reaction."""


_BEAR_ATTACKS = {
    1: (
        {"name": "爪击", "skill": 35, "damage_expression": "2d6"},
        {"name": "爪击", "skill": 35, "damage_expression": "2d6"},
    ),
    2: (
        {"name": "爪击", "skill": 35, "damage_expression": "2d6"},
        {"name": "啃咬", "skill": 25, "damage_expression": "1d8"},
    ),
    3: (
        {"name": "爪击", "skill": 35, "damage_expression": "2d6"},
        {"name": "爪击", "skill": 35, "damage_expression": "2d6"},
    ),
}


def _json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value or {}


def _row(value: Any) -> dict[str, Any] | None:
    return dict(value) if value else None


def _is_black_bear(encounter: dict[str, Any] | None, enemy: dict[str, Any] | None) -> bool:
    return bool(
        encounter
        and encounter.get("type") == "combat"
        and enemy
        and enemy.get("display_name") == "黑熊"
    )


def get_pending_reaction(
    conn,
    character_id: str,
    *,
    room_id: str | None = None,
    encounter_id: str | None = None,
) -> dict[str, Any] | None:
    clauses = ["character_id = %s", "status = 'pending'"]
    params: list[str] = [character_id]
    if room_id:
        clauses.append("room_id = %s")
        params.append(room_id)
    if encounter_id:
        clauses.append("encounter_id = %s")
        params.append(encounter_id)
    return _row(conn.execute(
        "SELECT * FROM encounter_pending_reactions WHERE "
        + " AND ".join(clauses)
        + " ORDER BY created_at ASC LIMIT 1",
        tuple(params),
    ).fetchone())


def reaction_projection(reaction: dict[str, Any]) -> dict[str, Any]:
    return {
        "reactionId": reaction["reaction_id"],
        "encounterId": reaction["encounter_id"],
        "roundNumber": reaction["round_number"],
        "attackIndex": reaction["attack_index"],
        "attackName": reaction["attack_name"],
        "choices": ["dodge", "counterattack"],
        "status": reaction["status"],
    }


def queue_black_bear_reaction(
    conn,
    *,
    room_id: str,
    encounter_id: str,
    character_id: str,
    source_action_id: str,
) -> dict[str, Any] | None:
    """Create exactly one outstanding enemy attack for the current solo round."""
    from ..encounter_persistence import get_encounter, get_participants

    existing = get_pending_reaction(
        conn, character_id, room_id=room_id, encounter_id=encounter_id,
    )
    if existing:
        return existing

    encounter = get_encounter(conn, encounter_id)
    participants = get_participants(conn, encounter_id)
    enemy = next((item for item in participants if item.get("side") == "enemy"), None)
    if not _is_black_bear(encounter, enemy) or encounter.get("status") != "active":
        return None
    if int(enemy.get("hp", 0) or 0) <= 0:
        return None

    round_number = int(encounter.get("current_round", 0) or 1)
    attacks = _BEAR_ATTACKS.get(round_number)
    if not attacks:
        return None
    count_row = conn.execute(
        "SELECT COUNT(*) AS count FROM encounter_pending_reactions "
        "WHERE encounter_id = %s AND character_id = %s AND round_number = %s",
        (encounter_id, character_id, round_number),
    ).fetchone()
    attack_index = int(count_row["count"] if count_row else 0) + 1
    if attack_index > len(attacks):
        return None

    reaction_id = f"reaction:{uuid.uuid4()}"
    conn.execute(
        """
        INSERT INTO encounter_pending_reactions (
            reaction_id, room_id, encounter_id, source_action_id, character_id,
            attacker_id, round_number, attack_index, attack_name, damage_expression
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            reaction_id, room_id, encounter_id, source_action_id, character_id,
            enemy["character_id"], round_number, attack_index,
            attacks[attack_index - 1]["name"],
            attacks[attack_index - 1]["damage_expression"],
        ),
    )
    return _row(conn.execute(
        "SELECT * FROM encounter_pending_reactions WHERE reaction_id = %s",
        (reaction_id,),
    ).fetchone())


def _player_fighting_skill(conn, character_id: str) -> tuple[str, int]:
    row = conn.execute(
        "SELECT xlsx_data FROM characters WHERE character_id = %s", (character_id,),
    ).fetchone()
    sheet = _json_value(row.get("xlsx_data") if row else {})
    skills = sheet.get("skills") if isinstance(sheet, dict) else {}
    skills = skills if isinstance(skills, dict) else {}
    name = next(
        (value for value in ("格斗（斗殴）", "格斗(斗殴)", "斗殴", "格斗") if value in skills),
        "格斗（斗殴）",
    )
    return name, int(skills.get(name, 0) or 0)


def _player_dodge_skill(conn, character_id: str) -> int:
    row = conn.execute(
        "SELECT xlsx_data FROM characters WHERE character_id = %s", (character_id,),
    ).fetchone()
    sheet = _json_value(row.get("xlsx_data") if row else {})
    skills = sheet.get("skills") if isinstance(sheet, dict) else {}
    return int((skills or {}).get("闪避", 0) or 0)


def _character_attribute(conn, character_id: str, *names: str) -> int:
    row = conn.execute(
        "SELECT xlsx_data FROM characters WHERE character_id = %s", (character_id,),
    ).fetchone()
    sheet = _json_value(row.get("xlsx_data") if row else {})
    attributes = sheet.get("attributes") if isinstance(sheet, dict) else {}
    attributes = attributes if isinstance(attributes, dict) else {}
    for name in names:
        if name in attributes:
            return int(attributes.get(name, 0) or 0)
    return 0


def _attack_definition(reaction: dict[str, Any]) -> dict[str, Any]:
    attacks = _BEAR_ATTACKS.get(int(reaction["round_number"])) or ()
    index = int(reaction["attack_index"]) - 1
    if 0 <= index < len(attacks):
        return attacks[index]
    return {
        "name": reaction["attack_name"],
        "skill": 35,
        "damage_expression": reaction["damage_expression"],
    }


def _scripted_outcome_target(
    conn,
    reaction: dict[str, Any],
    *,
    player_hp: int,
    player_hp_max: int,
    bear_hp: int,
) -> tuple[str | None, dict[str, Any] | None]:
    scene = SoloAdventureRuntime(conn).current(reaction["room_id"])
    targets = {str(item) for item in (scene or {}).get("target_node_ids") or []}
    if not {"193", "201"}.issubset(targets):
        return None, None
    if player_hp <= 0:
        return "193", None
    if bear_hp <= 0:
        return "201", None
    if (
        int(reaction["round_number"]) < 3
        or int(reaction["attack_index"]) < len(_BEAR_ATTACKS[3])
    ):
        return None, None
    if player_hp > max(1, player_hp_max) // 2:
        return "201", None
    con = _character_attribute(conn, reaction["character_id"], "con", "CON", "体质")
    check = roll_skill_check(con)
    return ("201" if check["is_success"] else "193"), check


def _wins_opposed_check(defender: dict[str, Any], attacker: dict[str, Any]) -> bool:
    if not defender["is_success"]:
        return False
    if not attacker["is_success"]:
        return True
    return SUCCESS_LEVEL_RANK[defender["success_level"]] >= SUCCESS_LEVEL_RANK[
        attacker["success_level"]
    ]


def _armor(notes: str) -> int:
    match = re.search(r"吸收前\s*(\d+)\s*点伤害", notes or "")
    return int(match.group(1)) if match else 0


def resolve_pending_reaction(
    conn,
    *,
    reaction_id: str,
    character_id: str,
    choice: str,
) -> dict[str, Any]:
    """Resolve one defensive choice and atomically apply its authoritative changes."""
    if choice not in {"dodge", "counterattack"}:
        raise SoloCombatReactionError("invalid_reaction_choice")

    with conn.transaction() as tx:
        reaction = _row(tx.execute(
            "SELECT * FROM encounter_pending_reactions "
            "WHERE reaction_id = %s AND character_id = %s FOR UPDATE",
            (reaction_id, character_id),
        ).fetchone())
        if not reaction:
            raise SoloCombatReactionError("reaction_not_found")
        if reaction["status"] == "resolved":
            return {
                "reaction": reaction,
                "result": _json_value(reaction.get("result")),
                "next_reaction": None,
                "idempotent": True,
            }
        if reaction["status"] != "pending":
            raise SoloCombatReactionError("reaction_not_pending")

        encounter = _row(tx.execute(
            "SELECT * FROM encounters WHERE encounter_id = %s FOR UPDATE",
            (reaction["encounter_id"],),
        ).fetchone())
        player = _row(tx.execute(
            "SELECT * FROM encounter_participants WHERE encounter_id = %s AND character_id = %s FOR UPDATE",
            (reaction["encounter_id"], character_id),
        ).fetchone())
        enemy = _row(tx.execute(
            "SELECT * FROM encounter_participants WHERE encounter_id = %s AND character_id = %s FOR UPDATE",
            (reaction["encounter_id"], reaction["attacker_id"]),
        ).fetchone())
        if not _is_black_bear(encounter, enemy) or not player or encounter.get("status") != "active":
            raise SoloCombatReactionError("reaction_encounter_unavailable")

        attack = _attack_definition(reaction)
        bear_check = roll_skill_check(int(attack["skill"]))
        if choice == "dodge":
            player_skill_name = "闪避"
            player_check = roll_skill_check(_player_dodge_skill(conn, character_id))
        else:
            player_skill_name, player_skill = _player_fighting_skill(conn, character_id)
            player_check = roll_skill_check(player_skill)

        player_wins = _wins_opposed_check(player_check, bear_check)
        player_damage = 0
        bear_damage = 0
        raw_rolls: list[dict[str, Any]] = [
            {
                "actor": "黑熊",
                "kind": "skill",
                "result": bear_check["roll"],
                "target": int(attack["skill"]),
            },
            {
                "actor": character_id,
                "kind": "skill",
                "result": player_check["roll"],
                "target": player_check["skill_value"],
            },
        ]
        if choice == "counterattack" and player_wins:
            raw_player_damage, draws, modifier = roll_dice(
                str(player.get("damage_expression") or "1d3")
            )
            player_damage = max(0, raw_player_damage - _armor(str(enemy.get("notes") or "")))
            raw_rolls.append({
                "actor": character_id,
                "kind": "damage",
                "draws": draws,
                "modifier": modifier,
                "result": raw_player_damage,
            })
        elif bear_check["is_success"] and not player_wins:
            bear_damage, draws, modifier = roll_dice(attack["damage_expression"])
            raw_rolls.append({
                "actor": "黑熊",
                "kind": "damage",
                "draws": draws,
                "modifier": modifier,
                "result": bear_damage,
            })

        next_player_hp = max(0, int(player.get("hp", 0) or 0) - bear_damage)
        next_bear_hp = max(0, int(enemy.get("hp", 0) or 0) - player_damage)
        if bear_damage:
            mutations = [{"op": "replace", "path": "/character/hp", "value": next_player_hp}]
            if next_player_hp == 0:
                mutations.append({"op": "add", "path": "/character/status_tag", "value": "unconscious"})
            StateService(conn).apply_change(
                reaction["room_id"],
                {"type": "system", "id": "solo_black_bear"},
                StateChangeSet(characterMutations=[CharacterMutationItem(
                    characterId=character_id,
                    mutations=mutations,
                )]),
                reason="黑熊攻击结算",
                transaction=tx,
            )
            tx.execute(
                "UPDATE encounter_participants SET hp = %s WHERE encounter_id = %s AND character_id = %s",
                (next_player_hp, reaction["encounter_id"], character_id),
            )
        if player_damage:
            tx.execute(
                "UPDATE encounter_participants SET hp = %s WHERE encounter_id = %s AND character_id = %s",
                (next_bear_hp, reaction["encounter_id"], reaction["attacker_id"]),
            )

        outcome_target, con_check = _scripted_outcome_target(
            tx,
            reaction,
            player_hp=next_player_hp,
            player_hp_max=int(player.get("hp_max", 0) or 0),
            bear_hp=next_bear_hp,
        )
        if con_check:
            raw_rolls.append({
                "actor": character_id,
                "kind": "con_check",
                "result": con_check["roll"],
                "target": con_check["skill_value"],
            })
        receipt = create_roll_receipt(
            action_id=reaction_id,
            rule_set_version="coc7-core-v1",
            rolled_at=datetime.now(timezone.utc).isoformat(),
            raw_rolls=raw_rolls,
        )
        solo_transition = None
        result = {
            "choice": choice,
            "playerSkill": player_skill_name,
            "playerCheck": player_check,
            "bearCheck": bear_check,
            "playerWins": player_wins,
            "damageToPlayer": bear_damage,
            "damageToBear": player_damage,
            "verificationReceipt": receipt,
        }

        next_reaction: dict[str, Any] | None = None
        if outcome_target:
            tx.execute(
                "UPDATE encounters SET status = 'resolved', summary = %s, resolved_at = NOW() WHERE encounter_id = %s",
                (
                    "调查员失去意识" if outcome_target == "193" else "黑熊战斗结束",
                    reaction["encounter_id"],
                ),
            )
            current_scene = SoloAdventureRuntime(tx).current(reaction["room_id"])
            solo_transition = SoloAdventureRuntime(tx).transition(
                reaction["room_id"],
                from_node_id=str((current_scene or {}).get("node_id") or ""),
                target_node_id=outcome_target,
                transaction=tx,
            )
            result["soloTransition"] = solo_transition
            if con_check:
                result["majorWoundCheck"] = con_check
        elif reaction["attack_index"] < len(_BEAR_ATTACKS[reaction["round_number"]]):
            next_index = reaction["attack_index"] + 1
            next_attack = _BEAR_ATTACKS[reaction["round_number"]][next_index - 1]
            next_id = f"reaction:{uuid.uuid4()}"
            tx.execute(
                """
                INSERT INTO encounter_pending_reactions (
                    reaction_id, room_id, encounter_id, source_action_id, character_id,
                    attacker_id, round_number, attack_index, attack_name, damage_expression
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    next_id, reaction["room_id"], reaction["encounter_id"],
                    reaction["source_action_id"], character_id, reaction["attacker_id"],
                    reaction["round_number"], next_index,
                    next_attack["name"], next_attack["damage_expression"],
                ),
            )
            next_reaction = _row(tx.execute(
                "SELECT * FROM encounter_pending_reactions WHERE reaction_id = %s", (next_id,),
            ).fetchone())
        elif reaction["round_number"] >= 3:
            tx.execute(
                "UPDATE encounters SET status = 'resolved', summary = %s, resolved_at = NOW() WHERE encounter_id = %s",
                ("三轮黑熊战斗结束", reaction["encounter_id"]),
            )
        else:
            tx.execute(
                "UPDATE encounter_participants SET acted_this_round = FALSE WHERE encounter_id = %s",
                (reaction["encounter_id"],),
            )
            tx.execute(
                "UPDATE encounters SET current_round = current_round + 1 WHERE encounter_id = %s",
                (reaction["encounter_id"],),
            )

        tx.execute(
            """
            UPDATE encounter_pending_reactions
            SET status = 'resolved', choice = %s, result = %s, resolved_at = NOW()
            WHERE reaction_id = %s
            """,
            (choice, json.dumps(result, ensure_ascii=False), reaction_id),
        )

    resolved = _row(conn.execute(
        "SELECT * FROM encounter_pending_reactions WHERE reaction_id = %s", (reaction_id,),
    ).fetchone())
    return {
        "reaction": resolved,
        "result": _json_value(resolved.get("result") if resolved else {}),
        "next_reaction": next_reaction,
        "solo_transition": solo_transition,
        "idempotent": False,
    }
