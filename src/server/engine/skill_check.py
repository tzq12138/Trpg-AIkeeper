import random
from typing import Literal

SuccessLevel = Literal["critical", "extreme", "hard", "regular", "failure", "fumble"]

SUCCESS_LEVEL_RANK = {
    "fumble": 0,
    "failure": 0,
    "regular": 1,
    "hard": 2,
    "extreme": 3,
    "critical": 4,
}
DIFFICULTY_RANK = {"regular": 1, "hard": 2, "extreme": 3}


def roll_skill_check(
    skill_value: int,
    difficulty: Literal["regular", "hard", "extreme"] = "regular",
    bonus_dice: int = 0,
    policy: dict | None = None,
) -> dict:
    policy = policy or {}
    try:
        normalized_bonus_dice = int(bonus_dice)
    except (TypeError, ValueError):
        normalized_bonus_dice = 0
    try:
        max_bonus_dice = max(0, min(2, int(policy.get("max_bonus_dice", 2))))
    except (TypeError, ValueError):
        max_bonus_dice = 2
    bonus_dice = max(-max_bonus_dice, min(max_bonus_dice, normalized_bonus_dice))
    difficulty = difficulty if difficulty in DIFFICULTY_RANK else "regular"
    skill_value = max(0, int(skill_value or 0))

    tens_digit = random.randint(0, 9)
    ones_digit = random.randint(0, 9)
    tens_digits = [tens_digit]
    if bonus_dice:
        tens_digits.extend(random.randint(0, 9) for _ in range(abs(bonus_dice)))
    candidates = [digit * 10 + ones_digit or 100 for digit in tens_digits]
    if bonus_dice > 0:
        selected_index = min(range(len(candidates)), key=candidates.__getitem__)
    elif bonus_dice < 0:
        selected_index = max(range(len(candidates)), key=candidates.__getitem__)
    else:
        selected_index = 0
    roll = candidates[selected_index]

    threshold = _compute_threshold(skill_value, difficulty)
    success_level = _determine_success(roll, threshold, skill_value, policy)
    is_success = is_success_for_difficulty(success_level, difficulty)

    return {
        "skill_name": "",
        "skill_value": skill_value,
        "roll": roll,
        "difficulty": difficulty,
        "success_level": success_level,
        "is_success": is_success,
        "target": threshold,
        "bonus_dice": bonus_dice,
        "roll_trace": {
            "ones": ones_digit,
            "tens": tens_digits,
            "candidates": candidates,
            "selected_index": selected_index,
        },
        "detail": _format_detail(roll, threshold, success_level, bonus_dice),
    }


def _compute_threshold(skill_value: int, difficulty: str) -> int:
    if difficulty == "extreme":
        return skill_value // 5
    if difficulty == "hard":
        return skill_value // 2
    return skill_value


def _determine_success(
    roll: int,
    threshold: int,
    skill_value: int,
    policy: dict | None = None,
) -> SuccessLevel:
    policy = policy or {}
    if roll == 1:
        return "critical"
    if roll == 100:
        return "fumble"
    # CoC 7e: low-skill characters fumble on 96-100
    try:
        low_skill_fumble_min = max(
            96, min(100, int(policy.get("low_skill_fumble_min", 96)))
        )
    except (TypeError, ValueError):
        low_skill_fumble_min = 96
    if skill_value < 50 and roll >= low_skill_fumble_min:
        return "fumble"
    if roll <= skill_value // 5:
        return "extreme"
    if roll <= skill_value // 2:
        return "hard"
    if roll <= skill_value:
        return "regular"
    return "failure"


def is_success_for_difficulty(success_level: str, difficulty: str) -> bool:
    return SUCCESS_LEVEL_RANK.get(success_level, 0) >= DIFFICULTY_RANK.get(difficulty, 1)


def _format_detail(roll: int, threshold: int, level: str, bonus_dice: int) -> str:
    parts = [f"roll={roll}", f"threshold={threshold}", f"level={level}"]
    if bonus_dice != 0:
        parts.append(f"bonus_dice={bonus_dice}")
    return ", ".join(parts)
