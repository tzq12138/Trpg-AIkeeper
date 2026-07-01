"""Encounter rule handlers — combat and chase v1 (minimal viable state machine).

All handlers follow the existing BaseRuleHandler pattern.
Encounter context (participant HP, distance bands, etc.) is passed via params.encounter_context
from the resolution pipeline, avoiding DB reads in handlers.
"""

import random
from .base import BaseRuleHandler, GameState, RuleResult


def _d100() -> int:
    return random.randint(1, 100)


def _parse_dice(notation: str) -> int:
    """Roll dice notation like 1d3, 2d6. Simple XdY only."""
    import re
    match = re.match(r"(\d+)d(\d+)", notation)
    if not match:
        return 0
    count, sides = int(match.group(1)), int(match.group(2))
    return sum(random.randint(1, sides) for _ in range(count))


# ══════════════════════════════════════════════
#  Combat Handlers
# ══════════════════════════════════════════════

class CombatAttackHandler(BaseRuleHandler):
    """Skill check → damage roll → HP mutation on target."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        target_id = params.get("targetId", "")
        skill_name = params.get("skillName", "斗殴")
        skill_value = params.get("skillValue", state.character.get("skills", {}).get(skill_name, 0))
        damage_expr = params.get("damage", params.get("damageExpression", "1d3"))
        difficulty = params.get("difficulty", "regular")

        roll = _d100()
        is_success = roll <= skill_value

        success_level = "failure"
        if roll == 1:
            success_level = "critical"
        elif roll <= skill_value // 5:
            success_level = "extreme"
        elif roll <= skill_value // 2:
            success_level = "hard"
        elif is_success:
            success_level = "regular"
        elif roll == 100 or (skill_value < 50 and roll >= 96):
            success_level = "fumble"

        damage = _parse_dice(damage_expr) if is_success and success_level != "fumble" else 0
        if success_level == "critical":
            damage = max(damage, _parse_dice(damage_expr))  # crit = max of double roll (v1 simple)

        return RuleResult(
            is_success=is_success,
            metadata={
                "roll": roll, "skill_name": skill_name, "skill_value": skill_value,
                "success_level": success_level, "damage": damage,
                "target_id": target_id, "difficulty": difficulty,
            },
            mutations=[
                {"op": "replace", "path": f"/encounter/{params.get('encounterId', '')}/participants/{target_id}/hp_delta", "value": -damage}
            ] if damage > 0 else [],
            reveal_steps=[
                {"kind": "roll", "dice": "d100", "result": roll, "target": skill_value,
                 "skillName": skill_name, "successLevel": success_level},
                {"kind": "damage", "dice": damage_expr, "result": damage, "targetId": target_id},
            ],
            cascading_state_changes=(
                [f"{skill_name}攻击成功，造成 {damage} 点伤害"] if damage > 0
                else [f"{skill_name}攻击失败"] if is_success is False
                else ["攻击大失败！"]
            ),
        )


class CombatDodgeHandler(BaseRuleHandler):
    """Dodge check — d100 vs dodge skill. Success negates incoming damage (handled by pipeline)."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        skill_value = state.character.get("skills", {}).get("闪避", params.get("skillValue", 20))
        roll = _d100()
        is_success = roll <= skill_value

        success_level = "failure"
        if roll == 1:
            success_level = "critical"
        elif roll <= skill_value // 5:
            success_level = "extreme"
        elif roll <= skill_value // 2:
            success_level = "hard"
        elif is_success:
            success_level = "regular"

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": "闪避", "skill_value": skill_value,
                       "success_level": success_level},
            reveal_steps=[
                {"kind": "roll", "dice": "d100", "result": roll, "target": skill_value,
                 "skillName": "闪避", "successLevel": success_level},
            ],
            cascading_state_changes=(
                ["闪避成功！"] if is_success else ["闪避失败"]
            ),
        )


class CombatDefendHandler(BaseRuleHandler):
    """Defend/cover action — adds 'defending' status tag."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        return RuleResult(
            is_success=True,
            metadata={"action": "defend"},
            mutations=[
                {"op": "add", "path": f"/encounter/{params.get('encounterId', '')}/participants/{params.get('characterId', '')}/status_tag", "value": "defending"}
            ],
            reveal_steps=[{"kind": "status_delta", "payload": {"statusTag": "defending"}}],
            cascading_state_changes=["采取防御姿态"],
        )


class CombatAssistHandler(BaseRuleHandler):
    """Assist ally — adds 'assisted' status tag to target."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        target_id = params.get("targetId", "")
        return RuleResult(
            is_success=True,
            metadata={"action": "assist", "target_id": target_id},
            mutations=[
                {"op": "add", "path": f"/encounter/{params.get('encounterId', '')}/participants/{target_id}/status_tag", "value": "assisted"}
            ],
            reveal_steps=[{"kind": "status_delta", "payload": {"statusTag": "assisted", "targetId": target_id}}],
            cascading_state_changes=[f"协助 {target_id}"],
        )


class CombatFleeHandler(BaseRuleHandler):
    """Flee from combat — DEX or MOV check to escape."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        skill_value = state.character.get("dex", 50)
        roll = _d100()
        is_success = roll <= skill_value

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": "DEX", "skill_value": skill_value},
            mutations=(
                [{"op": "add", "path": f"/encounter/{params.get('encounterId', '')}/participants/{params.get('characterId', '')}/status_tag", "value": "fled"}]
                if is_success else
                [{"op": "add", "path": f"/encounter/{params.get('encounterId', '')}/participants/{params.get('characterId', '')}/status_tag", "value": "pinned"}]
            ),
            reveal_steps=[{"kind": "roll", "dice": "d100", "result": roll, "target": skill_value,
                           "skillName": "DEX"}],
            cascading_state_changes=(["成功逃脱！"] if is_success else ["逃脱失败，被牵制"]),
        )


class CombatWaitHandler(BaseRuleHandler):
    """Wait/pass action — just marks acted_this_round."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        return RuleResult(
            is_success=True,
            metadata={"action": "wait"},
            cascading_state_changes=["等待时机"],
        )


# ══════════════════════════════════════════════
#  Chase Handlers
# ══════════════════════════════════════════════

class ChasePursueHandler(BaseRuleHandler):
    """Pursue target — MOV + skill check, success reduces distance band."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        mov = state.character.get("mov", 7)
        skill_name = params.get("skillName", "运动")
        skill_value = params.get("skillValue", state.character.get("skills", {}).get(skill_name, 20))
        roll = _d100()
        is_success = roll <= skill_value

        success_level = "failure"
        if roll == 1:
            success_level = "critical"
        elif roll <= skill_value // 5:
            success_level = "extreme"
        elif roll <= skill_value // 2:
            success_level = "hard"
        elif is_success:
            success_level = "regular"

        from ..encounter_persistence import compute_distance_change
        delta = compute_distance_change(mov, skill_value, is_success, success_level)

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": skill_name, "skill_value": skill_value,
                       "success_level": success_level, "mov": mov, "distance_delta": -delta},
            mutations=[
                {"op": "replace", "path": f"/encounter/{params.get('encounterId', '')}/participants/{params.get('characterId', '')}/distance_band_delta", "value": -delta}
            ] if delta > 0 else [],
            reveal_steps=[{"kind": "roll", "dice": "d100", "result": roll, "target": skill_value,
                           "skillName": skill_name, "successLevel": success_level}],
            cascading_state_changes=(
                [f"追击成功，距离缩短 {delta} 级"] if delta > 0 else ["追击失败"]
            ),
        )


class ChaseEscapeHandler(BaseRuleHandler):
    """Escape from pursuer — MOV + skill, success increases distance band."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        mov = state.character.get("mov", 7)
        skill_name = params.get("skillName", "运动")
        skill_value = params.get("skillValue", state.character.get("skills", {}).get(skill_name, 20))
        roll = _d100()
        is_success = roll <= skill_value

        success_level = "failure"
        if roll == 1:
            success_level = "critical"
        elif roll <= skill_value // 5:
            success_level = "extreme"
        elif roll <= skill_value // 2:
            success_level = "hard"
        elif is_success:
            success_level = "regular"

        from ..encounter_persistence import compute_distance_change
        delta = compute_distance_change(mov, skill_value, is_success, success_level)

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": skill_name, "skill_value": skill_value,
                       "success_level": success_level, "mov": mov, "distance_delta": delta},
            mutations=[
                {"op": "replace", "path": f"/encounter/{params.get('encounterId', '')}/participants/{params.get('characterId', '')}/distance_band_delta", "value": delta}
            ] if delta > 0 else [],
            reveal_steps=[{"kind": "roll", "dice": "d100", "result": roll, "target": skill_value,
                           "skillName": skill_name, "successLevel": success_level}],
            cascading_state_changes=(
                [f"逃脱成功，距离拉远 {delta} 级"] if delta > 0 else ["逃脱失败"]
            ),
        )


class ChaseBlockHandler(BaseRuleHandler):
    """Block a path — marks current band as 'blocked'."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        return RuleResult(
            is_success=True,
            metadata={"action": "block"},
            mutations=[
                {"op": "add", "path": f"/encounter/{params.get('encounterId', '')}/metadata/blocked_band", "value": params.get("currentBand", "medium")}
            ],
            cascading_state_changes=["设置路障"],
        )


class ChaseCreateObstacleHandler(BaseRuleHandler):
    """Create obstacle — skill check, on fail lose distance."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        skill_name = params.get("skillName", "妙手")
        skill_value = params.get("skillValue", state.character.get("skills", {}).get(skill_name, 20))
        roll = _d100()
        is_success = roll <= skill_value

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": skill_name, "skill_value": skill_value},
            mutations=(
                [] if is_success else
                [{"op": "replace", "path": f"/encounter/{params.get('encounterId', '')}/participants/{params.get('characterId', '')}/distance_band_delta", "value": 1}]
            ),
            reveal_steps=[{"kind": "roll", "dice": "d100", "result": roll, "target": skill_value,
                           "skillName": skill_name}],
            cascading_state_changes=(
                ["障碍设置成功"] if is_success else ["设置失败，失去距离"]
            ),
        )


class ChaseDetourHandler(BaseRuleHandler):
    """Detour around obstacle — navigation/athletics check, costs MOV distance."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        skill_name = params.get("skillName", "导航")
        skill_value = params.get("skillValue", state.character.get("skills", {}).get(skill_name, 20))
        roll = _d100()
        is_success = roll <= skill_value

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "skill_name": skill_name, "skill_value": skill_value},
            mutations=(
                [{"op": "replace", "path": f"/encounter/{params.get('encounterId', '')}/participants/{params.get('characterId', '')}/distance_band_delta", "value": 1}]
            ),
            reveal_steps=[{"kind": "roll", "dice": "d100", "result": roll, "target": skill_value,
                           "skillName": skill_name}],
            cascading_state_changes=(
                ["绕过障碍成功"] if is_success else ["绕路失败"]
            ),
        )


class ChaseAssistHandler(BaseRuleHandler):
    """Assist ally in chase — adds 'assisted' tag to target."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        target_id = params.get("targetId", "")
        return RuleResult(
            is_success=True,
            metadata={"action": "assist", "target_id": target_id},
            mutations=[
                {"op": "add", "path": f"/encounter/{params.get('encounterId', '')}/participants/{target_id}/status_tag", "value": "assisted"}
            ],
            reveal_steps=[{"kind": "status_delta", "payload": {"statusTag": "assisted", "targetId": target_id}}],
            cascading_state_changes=[f"协助 {target_id}"],
        )


class ChaseWaitHandler(BaseRuleHandler):
    """Wait in chase — marks acted_this_round."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        return RuleResult(
            is_success=True,
            metadata={"action": "wait"},
            cascading_state_changes=["等待时机"],
        )
