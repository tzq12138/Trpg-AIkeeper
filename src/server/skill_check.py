import random
from typing import Literal

SuccessLevel = Literal["critical", "extreme", "hard", "regular", "failure", "fumble"]


def roll_skill_check(
    skill_value: int,
    difficulty: Literal["regular", "hard", "extreme"] = "regular",
    bonus_dice: int = 0,
) -> dict:
    tens_digit = random.randint(0, 9)
    ones_digit = random.randint(0, 9)
    raw_tens = tens_digit * 10

    if bonus_dice != 0:
        extra_tens = [random.randint(0, 9) * 10 for _ in range(abs(bonus_dice))]
        candidates = [raw_tens] + extra_tens
        if bonus_dice > 0:
            raw_tens = min(candidates)
        else:
            raw_tens = max(candidates)

    roll = raw_tens + ones_digit
    if roll == 0:
        roll = 100

    threshold = _compute_threshold(skill_value, difficulty)
    success_level = _determine_success(roll, threshold, skill_value)

    return {
        "skill_name": "",
        "skill_value": skill_value,
        "roll": roll,
        "difficulty": difficulty,
        "success_level": success_level,
        "detail": _format_detail(roll, threshold, success_level, bonus_dice),
    }


def _compute_threshold(skill_value: int, difficulty: str) -> int:
    if difficulty == "extreme":
        return skill_value // 5
    if difficulty == "hard":
        return skill_value // 2
    return skill_value


def _determine_success(roll: int, threshold: int, skill_value: int) -> SuccessLevel:
    if roll == 1:
        return "critical"
    if roll == 100:
        return "fumble"
    if roll <= threshold // 5:
        return "extreme"
    if roll <= threshold // 2:
        return "hard"
    if roll <= threshold:
        return "regular"
    return "failure"


def _format_detail(roll: int, threshold: int, level: str, bonus_dice: int) -> str:
    parts = [f"roll={roll}", f"threshold={threshold}", f"level={level}"]
    if bonus_dice != 0:
        parts.append(f"bonus_dice={bonus_dice}")
    return ", ".join(parts)
