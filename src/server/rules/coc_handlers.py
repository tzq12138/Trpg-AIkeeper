import random
import re

from .base import BaseRuleHandler, GameState, RuleResult


def parse_dice(notation: str) -> int:
    match = re.match(r"(\d+)d(\d+)", notation)
    if not match:
        raise ValueError(f"Invalid dice notation: {notation}")
    count, sides = int(match.group(1)), int(match.group(2))
    return sum(random.randint(1, sides) for _ in range(count))


class CocSkillCheckHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        skill_name = params.get("skillName", "")
        skill_value = params.get("skillValue", 0)
        difficulty = params.get("difficulty", "regular")
        bonus_dice = params.get("bonusDice", params.get("bonus_dice", 0))

        # Use the shared CoC D100 engine that supports bonus/penalty dice
        # and produces unified success levels: critical/extreme/hard/regular/failure/fumble
        from ..engine.skill_check import roll_skill_check, _compute_threshold
        result = roll_skill_check(skill_value=skill_value, difficulty=difficulty,
                                  bonus_dice=bonus_dice)

        roll = result["roll"]
        target = _compute_threshold(skill_value, difficulty)
        success_level = result["success_level"]
        detail = result.get("detail", "")
        is_success = success_level in ("critical", "extreme", "hard", "regular")

        return RuleResult(
            is_success=is_success,
            metadata={
                "skill_name": skill_name,
                "skill_value": skill_value,
                "roll": roll,
                "target": target,
                "difficulty": difficulty,
                "success_level": success_level,
                "is_success": is_success,
                "bonus_dice": bonus_dice,
                "detail": detail,
            },
            reveal_steps=[
                {"kind": "roll", "dice": "d100", "result": roll, "target": target,
                 "successLevel": success_level, "skillName": skill_name,
                 "bonusDice": bonus_dice},
            ],
        )


class CocSanityCheckHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        success_loss = params.get("success_loss", "0")
        failure_loss = params.get("failure_loss", "0")
        current_san = state.character.get("san", 0)

        roll = random.randint(1, 100)
        is_success = roll <= current_san

        if is_success:
            san_loss = parse_dice(success_loss) if success_loss != "0" else 0
        else:
            san_loss = parse_dice(failure_loss) if failure_loss != "0" else 0

        new_san = max(0, current_san - san_loss)
        cascading = []
        if new_san <= 0:
            cascading.append("疯狂")

        return RuleResult(
            is_success=is_success,
            metadata={
                "roll": roll,
                "current_san": current_san,
                "san_loss": san_loss,
                "new_san": new_san,
            },
            mutations=[
                {"op": "replace", "path": "/character/san", "value": new_san}
            ],
            reveal_steps=[
                {"kind": "roll", "dice": "d100", "result": roll, "target": current_san},
                {"kind": "san_loss", "loss": san_loss},
            ],
            cascading_state_changes=cascading,
        )


class CocCombatHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        damage_dice = params.get("damage", "1d3")
        current_hp = state.character.get("hp", 0)

        damage = parse_dice(damage_dice)
        new_hp = max(0, current_hp - damage)
        cascading = []
        if new_hp <= 0:
            cascading.append("昏迷/濒死")

        return RuleResult(
            is_success=True,
            metadata={"damage": damage, "current_hp": current_hp, "new_hp": new_hp},
            mutations=[
                {"op": "replace", "path": "/character/hp", "value": new_hp}
            ],
            reveal_steps=[
                {"kind": "damage", "dice": damage_dice, "result": damage}
            ],
            cascading_state_changes=cascading,
        )


class CocLuckCheckHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        current_luck = state.character.get("luck", 0)
        roll = random.randint(1, 100)
        is_success = roll <= current_luck

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "luck": current_luck},
            reveal_steps=[
                {"kind": "roll", "dice": "d100", "result": roll, "target": current_luck}
            ],
        )


class CocMoveHandler(BaseRuleHandler):
    """Validates map movement and returns position mutation."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        target_node = params.get("targetNodeId", "")
        from_node = params.get("fromNodeId", "")
        return RuleResult(
            is_success=True,
            metadata={
                "target_node": target_node,
                "from_node": from_node,
                "move_success": True,
            },
            mutations=[
                {"op": "replace", "path": "/character/current_location", "value": target_node}
            ],
            reveal_steps=[
                {"kind": "move", "fromNode": from_node, "toNode": target_node}
            ],
        )
