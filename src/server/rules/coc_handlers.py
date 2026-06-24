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

        roll = random.randint(1, 100)

        if difficulty == "hard":
            target = skill_value // 2
        elif difficulty == "extreme":
            target = skill_value // 5
        else:
            target = skill_value

        if roll == 1:
            success_level = "critical_success"
            is_success = True
        elif roll == 100:
            success_level = "fumble"
            is_success = False
        elif roll >= 96 and skill_value < 50:
            success_level = "fumble"
            is_success = False
        elif roll <= target:
            success_level = "success"
            is_success = True
        else:
            success_level = "failure"
            is_success = False

        return RuleResult(
            is_success=is_success,
            metadata={
                "skill_name": skill_name,
                "skill_value": skill_value,
                "roll": roll,
                "target": target,
                "difficulty": difficulty,
                "success_level": success_level,
            },
            reveal_steps=[
                {"kind": "roll", "dice": "d100", "result": roll, "target": target}
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
