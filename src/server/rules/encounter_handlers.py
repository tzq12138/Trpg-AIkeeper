"""Encounter rule handlers — combat and chase v1 (minimal viable state machine).

All handlers follow the existing BaseRuleHandler pattern.
Encounter context (participant HP, distance bands, etc.) is passed via params.encounter_context
from the resolution pipeline, avoiding DB reads in handlers.
"""

import random
import re
from .base import BaseRuleHandler, GameState, RuleResult
from ..engine.secure_random import secure_randint


def _d100() -> int:
    return secure_randint(1, 100, test_rng=random)


def _parse_dice(notation: str) -> int:
    from .coc_handlers import parse_dice

    return parse_dice(notation)


def _skill_check(skill_value: int, params: dict) -> dict:
    from ..engine.skill_check import roll_skill_check

    return roll_skill_check(
        skill_value=skill_value,
        difficulty=params.get("difficulty", "regular"),
        bonus_dice=params.get("bonusDice", params.get("bonus_dice", 0)),
        policy=params.get("_rule_policy") if isinstance(params.get("_rule_policy"), dict) else {},
    )


def _roll_step(result: dict, skill_name: str) -> dict:
    return {
        "kind": "roll",
        "dice": "d100",
        "result": result["roll"],
        "target": result["target"],
        "skillName": skill_name,
        "successLevel": result["success_level"],
        "bonusDice": result["bonus_dice"],
        "rollTrace": result["roll_trace"],
    }


def _encounter_context(params: dict) -> tuple[dict, list[dict], dict] | None:
    context = params.get("encounter_context")
    if not isinstance(context, dict):
        return None
    participant = context.get("participant")
    participants = context.get("allParticipants")
    encounter = context.get("encounter")
    if not isinstance(participant, dict) or not isinstance(participants, list) or not isinstance(encounter, dict):
        return None
    return participant, [item for item in participants if isinstance(item, dict)], encounter


def _encounter_id(encounter: dict) -> str:
    return str(encounter.get("encounter_id") or encounter.get("encounterId") or "")


def _find_participant(participants: list[dict], character_id: str) -> dict | None:
    return next(
        (item for item in participants if item.get("character_id") == character_id),
        None,
    )


def _invalid_context(reason_code: str) -> RuleResult:
    return RuleResult(is_success=False, metadata={"reason_code": reason_code})


# ══════════════════════════════════════════════
#  Combat Handlers
# ══════════════════════════════════════════════

class CombatAttackHandler(BaseRuleHandler):
    """Skill check → damage roll → HP mutation on target."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        participant, participants, encounter = context
        target_id = params.get("targetId", "")
        target = _find_participant(participants, target_id)
        if not target or target_id == participant.get("character_id"):
            return _invalid_context("invalid_encounter_target")
        participant_skill = str(participant.get("main_skill") or "斗殴")
        skills = state.character.get("skills", {}) or {}
        skill_name = participant_skill
        skill_value = int(skills.get(skill_name, 0) or 0)
        damage_expr = str(participant.get("damage_expression") or "1d3")
        difficulty = params.get("difficulty", "regular")
        encounter_id = _encounter_id(encounter)

        check = _skill_check(skill_value, params)
        roll = check["roll"]
        is_success = check["is_success"]
        success_level = check["success_level"]

        raw_damage = 0
        if is_success and success_level != "fumble":
            from .coc_handlers import max_dice

            impaling = bool(
                participant.get("impaling")
                or params.get("impaling")
            )
            if success_level in {"extreme", "critical"}:
                raw_damage = max_dice(damage_expr)
                if impaling:
                    raw_damage += _parse_dice(damage_expr)
            else:
                raw_damage = _parse_dice(damage_expr)
        armor_match = re.search(r"吸收前\s*(\d+)\s*点伤害", str(target.get("notes") or ""))
        armor = int(armor_match.group(1)) if armor_match else 0
        damage = max(0, raw_damage - armor)

        return RuleResult(
            is_success=is_success,
            metadata={
                "roll": roll, "skill_name": skill_name, "skill_value": skill_value,
                "success_level": success_level, "raw_damage": raw_damage,
                "armor": armor, "damage": damage,
                "target_id": target_id, "difficulty": difficulty,
                "damage_expression": damage_expr,
                "bonus_dice": check["bonus_dice"],
                "roll_trace": check["roll_trace"],
            },
            mutations=[
                {"op": "replace", "path": f"/encounter/{encounter_id}/participants/{target_id}/hp_delta", "value": -damage}
            ] if damage > 0 else [],
            reveal_steps=[
                _roll_step(check, skill_name),
                {"kind": "damage", "dice": damage_expr, "result": damage, "targetId": target_id},
            ],
            cascading_state_changes=(
                ["攻击大失败！"] if success_level == "fumble"
                else [f"{skill_name}攻击成功，造成 {damage} 点伤害"] if damage > 0
                else [f"{skill_name}攻击命中，但 {raw_damage} 点伤害被护甲吸收"] if raw_damage > 0
                else [f"{skill_name}攻击失败"]
            ),
        )


class CombatDodgeHandler(BaseRuleHandler):
    """Dodge check — d100 vs dodge skill. Success negates incoming damage (handled by pipeline)."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        skill_value = int((state.character.get("skills", {}) or {}).get("闪避", 0) or 0)
        check = _skill_check(skill_value, params)
        roll = check["roll"]
        is_success = check["is_success"]
        success_level = check["success_level"]

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": "闪避", "skill_value": skill_value,
                       "success_level": success_level,
                       "roll_trace": check["roll_trace"]},
            reveal_steps=[
                _roll_step(check, "闪避"),
            ],
            cascading_state_changes=(
                ["闪避成功！"] if is_success else ["闪避失败"]
            ),
        )


class CombatDefendHandler(BaseRuleHandler):
    """Defend/cover action — adds 'defending' status tag."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        participant, _participants, encounter = context
        return RuleResult(
            is_success=True,
            metadata={"action": "defend"},
            mutations=[
                {"op": "add", "path": f"/encounter/{_encounter_id(encounter)}/participants/{participant.get('character_id', '')}/status_tag", "value": "defending"}
            ],
            reveal_steps=[{"kind": "status_delta", "payload": {"statusTag": "defending"}}],
            cascading_state_changes=["采取防御姿态"],
        )


class CombatAssistHandler(BaseRuleHandler):
    """Assist ally — adds 'assisted' status tag to target."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        _participant, participants, encounter = context
        target_id = params.get("targetId", "")
        if not _find_participant(participants, target_id):
            return _invalid_context("invalid_encounter_target")
        return RuleResult(
            is_success=True,
            metadata={"action": "assist", "target_id": target_id},
            mutations=[
                {"op": "add", "path": f"/encounter/{_encounter_id(encounter)}/participants/{target_id}/status_tag", "value": "assisted"}
            ],
            reveal_steps=[{"kind": "status_delta", "payload": {"statusTag": "assisted", "targetId": target_id}}],
            cascading_state_changes=[f"协助 {target_id}"],
        )


class CombatFleeHandler(BaseRuleHandler):
    """Flee from combat — DEX or MOV check to escape."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        participant, _participants, encounter = context
        skill_value = int(participant.get("dex", 0) or 0)
        check = _skill_check(skill_value, params)
        roll = check["roll"]
        is_success = check["is_success"]

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": "DEX", "skill_value": skill_value,
                      "success_level": check["success_level"],
                      "roll_trace": check["roll_trace"]},
            mutations=(
                [{"op": "add", "path": f"/encounter/{_encounter_id(encounter)}/participants/{participant.get('character_id', '')}/status_tag", "value": "fled"}]
                if is_success else
                [{"op": "add", "path": f"/encounter/{_encounter_id(encounter)}/participants/{participant.get('character_id', '')}/status_tag", "value": "pinned"}]
            ),
            reveal_steps=[_roll_step(check, "DEX")],
            cascading_state_changes=(["成功逃脱！"] if is_success else ["逃脱失败，被牵制"]),
        )


class CombatWaitHandler(BaseRuleHandler):
    """Wait/pass action — just marks acted_this_round."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        if not _encounter_context(params):
            return _invalid_context("authoritative_encounter_context_required")
        return RuleResult(
            is_success=True,
            metadata={"action": "wait"},
            cascading_state_changes=["等待时机"],
        )


# ══════════════════════════════════════════════
#  Chase Handlers
# ══════════════════════════════════════════════

class ChasePursueHandler(BaseRuleHandler):
    """Spend one chase movement action to reduce the distance by one location."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        participant, _participants, encounter = context
        return RuleResult(
            is_success=True,
            metadata={
                "action": "pursue",
                "movement_action_cost": 1,
                "distance_delta": -1,
            },
            mutations=[
                {
                    "op": "replace",
                    "path": f"/encounter/{_encounter_id(encounter)}/participants/{participant.get('character_id', '')}/distance_band_delta",
                    "value": -1,
                }
            ],
            cascading_state_changes=["消耗 1 个移动行动，距离缩短 1 个位置"],
        )


class ChaseEscapeHandler(BaseRuleHandler):
    """Spend one chase movement action to increase the distance by one location."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        participant, _participants, encounter = context
        return RuleResult(
            is_success=True,
            metadata={
                "action": "escape",
                "movement_action_cost": 1,
                "distance_delta": 1,
            },
            mutations=[
                {
                    "op": "replace",
                    "path": f"/encounter/{_encounter_id(encounter)}/participants/{participant.get('character_id', '')}/distance_band_delta",
                    "value": 1,
                }
            ],
            cascading_state_changes=["消耗 1 个移动行动，距离拉远 1 个位置"],
        )


class ChaseBlockHandler(BaseRuleHandler):
    """Block a path — marks current band as 'blocked'."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        participant, _participants, encounter = context
        return RuleResult(
            is_success=True,
            metadata={"action": "block"},
            mutations=[
                {"op": "add", "path": f"/encounter/{_encounter_id(encounter)}/metadata/blocked_band", "value": participant.get("distance_band", "medium")}
            ],
            cascading_state_changes=["设置路障"],
        )


class ChaseCreateObstacleHandler(BaseRuleHandler):
    """Create obstacle — skill check, on fail lose distance."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        participant, _participants, encounter = context
        skill_name = str(participant.get("main_skill") or "妙手")
        skill_value = int((state.character.get("skills", {}) or {}).get(skill_name, 0) or 0)
        check = _skill_check(skill_value, params)
        roll = check["roll"]
        is_success = check["is_success"]

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": skill_name, "skill_value": skill_value,
                      "success_level": check["success_level"],
                      "roll_trace": check["roll_trace"]},
            mutations=(
                [] if is_success else
                [{"op": "replace", "path": f"/encounter/{_encounter_id(encounter)}/participants/{participant.get('character_id', '')}/distance_band_delta", "value": 1}]
            ),
            reveal_steps=[_roll_step(check, skill_name)],
            cascading_state_changes=(
                ["障碍设置成功"] if is_success else ["设置失败，失去距离"]
            ),
        )


class ChaseDetourHandler(BaseRuleHandler):
    """Detour around obstacle — navigation/athletics check, costs MOV distance."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        participant, _participants, encounter = context
        skill_name = str(participant.get("main_skill") or "导航")
        skill_value = int((state.character.get("skills", {}) or {}).get(skill_name, 0) or 0)
        check = _skill_check(skill_value, params)
        roll = check["roll"]
        is_success = check["is_success"]

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": skill_name, "skill_value": skill_value,
                      "success_level": check["success_level"],
                      "roll_trace": check["roll_trace"]},
            mutations=(
                [{"op": "replace", "path": f"/encounter/{_encounter_id(encounter)}/participants/{participant.get('character_id', '')}/distance_band_delta", "value": 1}]
            ),
            reveal_steps=[_roll_step(check, skill_name)],
            cascading_state_changes=(
                ["绕过障碍成功"] if is_success else ["绕路失败"]
            ),
        )


class ChaseAssistHandler(BaseRuleHandler):
    """Assist ally in chase — adds 'assisted' tag to target."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        context = _encounter_context(params)
        if not context:
            return _invalid_context("authoritative_encounter_context_required")
        _participant, participants, encounter = context
        target_id = params.get("targetId", "")
        if not _find_participant(participants, target_id):
            return _invalid_context("invalid_encounter_target")
        return RuleResult(
            is_success=True,
            metadata={"action": "assist", "target_id": target_id},
            mutations=[
                {"op": "add", "path": f"/encounter/{_encounter_id(encounter)}/participants/{target_id}/status_tag", "value": "assisted"}
            ],
            reveal_steps=[{"kind": "status_delta", "payload": {"statusTag": "assisted", "targetId": target_id}}],
            cascading_state_changes=[f"协助 {target_id}"],
        )


class ChaseWaitHandler(BaseRuleHandler):
    """Wait in chase — marks acted_this_round."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        if not _encounter_context(params):
            return _invalid_context("authoritative_encounter_context_required")
        return RuleResult(
            is_success=True,
            metadata={"action": "wait"},
            cascading_state_changes=["等待时机"],
        )
