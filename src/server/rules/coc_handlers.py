import random
import re

from .base import BaseRuleHandler, GameState, RuleResult
from ..engine.secure_random import secure_randint


_DICE_PATTERN = re.compile(r"^(\d{1,2})d(\d{1,4})([+-]\d{1,4})?$")
_KNOWN_STATUSES = {
    "unconscious", "dying", "major_wound", "temporary_insanity",
    "indefinite_insanity", "restrained", "poisoned", "burning",
    "fled", "pinned", "defending", "assisted",
}


def roll_dice(notation: str) -> tuple[int, list[int], int]:
    match = _DICE_PATTERN.fullmatch(str(notation).strip())
    if not match:
        raise ValueError(f"Invalid dice notation: {notation}")
    count, sides = int(match.group(1)), int(match.group(2))
    if count < 1 or count > 20 or sides < 2 or sides > 1000:
        raise ValueError(f"Dice notation out of range: {notation}")
    modifier = int(match.group(3) or 0)
    draws = [secure_randint(1, sides, test_rng=random) for _ in range(count)]
    return max(0, sum(draws) + modifier), draws, modifier


def parse_dice(notation: str) -> int:
    return roll_dice(notation)[0]


def _rule_citation(params: dict) -> dict:
    raw = params.get("ruleCitation") or params.get("rule_citation") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if not key.lower().endswith("_path") and key.lower() not in {"absolute_path", "storage_path"}
    }


def _roll_step(result: dict, skill_name: str, *, pushed: bool = False) -> dict:
    return {
        "kind": "roll",
        "dice": "d100",
        "result": result["roll"],
        "target": result["target"],
        "successLevel": result["success_level"],
        "skillName": skill_name,
        "bonusDice": result["bonus_dice"],
        "rollTrace": result["roll_trace"],
        "pushed": pushed,
    }


class CocSkillCheckHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        skill_name = params.get("skillName", "")
        skill_value = params.get("skillValue", 0)
        difficulty = params.get("difficulty", "regular")
        bonus_dice = params.get("bonusDice", params.get("bonus_dice", 0))
        rule_policy = params.get("_rule_policy") if isinstance(params.get("_rule_policy"), dict) else {}

        # Use the shared CoC D100 engine that supports bonus/penalty dice
        # and produces unified success levels: critical/extreme/hard/regular/failure/fumble
        from ..engine.skill_check import roll_skill_check, _compute_threshold
        result = roll_skill_check(skill_value=skill_value, difficulty=difficulty,
                                  bonus_dice=bonus_dice, policy=rule_policy)

        initial_result = result
        bonus_dice = initial_result["bonus_dice"]
        pushed = bool(params.get("pushed", params.get("push", False)))
        if rule_policy.get("allow_pushed_roll") is False:
            pushed = False
        reveal_steps = [_roll_step(initial_result, skill_name)]
        if pushed and not initial_result["is_success"] and initial_result["success_level"] != "fumble":
            result = roll_skill_check(
                skill_value=skill_value,
                difficulty=difficulty,
                bonus_dice=bonus_dice,
                policy=rule_policy,
            )
            reveal_steps.append(_roll_step(result, skill_name, pushed=True))

        roll = result["roll"]
        target = _compute_threshold(skill_value, difficulty)
        success_level = result["success_level"]
        detail = result.get("detail", "")
        is_success = result["is_success"]
        mutations = []
        luck_spent = 0
        spend_luck = params.get("spendLuck", params.get("spend_luck", False))
        if rule_policy.get("allow_luck_spend") is False:
            spend_luck = False
        current_luck = max(0, int(state.character.get("luck", 0) or 0))
        if spend_luck and not pushed and not is_success and success_level != "fumble":
            required_luck = max(0, roll - target)
            if spend_luck is True:
                budget = current_luck
            else:
                try:
                    budget = max(0, int(spend_luck))
                except (TypeError, ValueError):
                    budget = 0
            if 0 < required_luck <= min(current_luck, budget):
                luck_spent = required_luck
                is_success = True
                success_level = difficulty
                mutations.append({
                    "op": "replace",
                    "path": "/character/luck",
                    "value": current_luck - required_luck,
                })

        pending_consequence = None
        if pushed and not is_success:
            pending_consequence = {
                "status": "pending_host_confirmation",
                "reason": "pushed_check_failed",
                "citation": _rule_citation(params),
            }

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
                "roll_trace": result["roll_trace"],
                "pushed": pushed and len(reveal_steps) == 2,
                "initial_roll": initial_result["roll"],
                "initial_roll_trace": initial_result["roll_trace"],
                "luck_spent": luck_spent,
                "pending_consequence": pending_consequence,
                "detail": detail,
            },
            mutations=mutations,
            reveal_steps=reveal_steps,
        )


class CocSanityCheckHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        success_loss = params.get("success_loss", "0")
        failure_loss = params.get("failure_loss", "0")
        current_san = state.character.get("san", 0)

        roll = secure_randint(1, 100, test_rng=random)
        is_success = roll <= current_san
        success_level = "regular" if is_success else "failure"

        if is_success:
            san_loss, loss_draws, modifier = roll_dice(success_loss) if success_loss != "0" else (0, [], 0)
        else:
            san_loss, loss_draws, modifier = roll_dice(failure_loss) if failure_loss != "0" else (0, [], 0)

        new_san = max(0, current_san - san_loss)
        cascading = []
        if new_san <= 0:
            cascading.append("疯狂")

        return RuleResult(
            is_success=is_success,
            metadata={
                "roll": roll,
                "current_san": current_san,
                "skill_name": "理智",
                "skill_value": current_san,
                "target": current_san,
                "difficulty": "regular",
                "success_level": success_level,
                "san_loss": san_loss,
                "new_san": new_san,
                "roll_trace": {"d100": [roll], "loss_draws": loss_draws, "modifier": modifier},
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

        damage, damage_draws, modifier = roll_dice(damage_dice)
        new_hp = max(0, current_hp - damage)
        cascading = []
        if new_hp <= 0:
            cascading.append("昏迷/濒死")

        return RuleResult(
            is_success=True,
            metadata={
                "damage": damage,
                "current_hp": current_hp,
                "new_hp": new_hp,
                "roll_trace": {"draws": damage_draws, "modifier": modifier},
            },
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
        roll = secure_randint(1, 100, test_rng=random)
        is_success = roll <= current_luck

        return RuleResult(
            is_success=is_success,
            metadata={"roll": roll, "luck": current_luck, "roll_trace": {"d100": [roll]}},
            reveal_steps=[
                {"kind": "roll", "dice": "d100", "result": roll, "target": current_luck}
            ],
        )


class CocMoveHandler(BaseRuleHandler):
    """Validates map movement and returns position mutation."""

    async def execute(self, state: GameState, params: dict) -> RuleResult:
        target_node = params.get("targetNodeId", "")
        from_node = params.get("fromNodeId", "")
        if params.get("solo_adventure_damage"):
            return RuleResult(
                is_success=True,
                metadata={"solo_damage_transition": True},
            )
        if not target_node:
            return RuleResult(
                is_success=False,
                metadata={"reason_code": "target_node_required"},
            )
        edges = ((state.scene.get("map") or {}).get("edges") or []) if state.scene else []
        if edges and from_node:
            is_adjacent = any(
                (
                    edge.get("from", edge.get("source")) == from_node
                    and edge.get("to", edge.get("target")) == target_node
                )
                or (
                    not edge.get("directed", False)
                    and edge.get("from", edge.get("source")) == target_node
                    and edge.get("to", edge.get("target")) == from_node
                )
                for edge in edges
                if isinstance(edge, dict)
            )
            if not is_adjacent:
                return RuleResult(
                    is_success=False,
                    metadata={
                        "target_node": target_node,
                        "from_node": from_node,
                        "move_success": False,
                        "reason_code": "nodes_not_adjacent",
                    },
                )
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


class CocOpposedCheckHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        opponent = state.scene.get("opponent") if state.scene else None
        if not isinstance(opponent, dict):
            context = params.get("encounter_context")
            target_id = params.get("targetId")
            if isinstance(context, dict) and target_id:
                participants = context.get("allParticipants") or []
                opponent = next(
                    (
                        item for item in participants
                        if isinstance(item, dict)
                        and item.get("character_id") == target_id
                        and isinstance(item.get("skills"), dict)
                    ),
                    None,
                )
        if not isinstance(opponent, dict):
            return RuleResult(
                is_success=False,
                metadata={
                    "status": "pending_host_confirmation",
                    "reason_code": "authoritative_opponent_required",
                    "citation": _rule_citation(params),
                },
            )

        from ..engine.skill_check import SUCCESS_LEVEL_RANK, roll_skill_check

        actor_skill_name = params.get("skillName", "")
        opponent_skill_name = params.get("opponentSkillName", actor_skill_name)
        actor_value = int((state.character.get("skills") or {}).get(actor_skill_name, 0) or 0)
        opponent_value = int((opponent.get("skills") or {}).get(opponent_skill_name, 0) or 0)
        actor_roll = roll_skill_check(actor_value)
        opponent_roll = roll_skill_check(opponent_value)
        actor_rank = SUCCESS_LEVEL_RANK[actor_roll["success_level"]]
        opponent_rank = SUCCESS_LEVEL_RANK[opponent_roll["success_level"]]
        if actor_rank == 0 and opponent_rank == 0:
            winner = "tie"
        elif actor_rank > opponent_rank:
            winner = "actor"
        elif opponent_rank > actor_rank:
            winner = "opponent"
        elif actor_value > opponent_value:
            winner = "actor"
        elif opponent_value > actor_value:
            winner = "opponent"
        else:
            winner = "tie"
        return RuleResult(
            is_success=winner == "actor",
            metadata={
                "winner": winner,
                "actor": {
                    **actor_roll,
                    "skill_name": actor_skill_name,
                    "skill_value": actor_value,
                },
                "opponent": {
                    **opponent_roll,
                    "name": opponent.get("name", "opponent"),
                    "skill_name": opponent_skill_name,
                    "skill_value": opponent_value,
                },
            },
            reveal_steps=[
                _roll_step(actor_roll, actor_skill_name),
                _roll_step(opponent_roll, opponent_skill_name),
            ],
        )


class CocHealingHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        current_hp = max(0, int(state.character.get("hp", 0) or 0))
        max_hp = max(
            current_hp,
            int(state.character.get("max_hp", state.character.get("hp_max", current_hp)) or current_hp),
        )
        amount = params.get("amount", "1")
        if isinstance(amount, int):
            rolled = max(0, amount)
            draws, modifier = [], amount
        elif str(amount).isdigit():
            rolled = int(amount)
            draws, modifier = [], rolled
        else:
            rolled, draws, modifier = roll_dice(str(amount))
        new_hp = min(max_hp, current_hp + rolled)
        healed = new_hp - current_hp
        return RuleResult(
            is_success=healed > 0,
            metadata={
                "current_hp": current_hp,
                "max_hp": max_hp,
                "new_hp": new_hp,
                "healed": healed,
                "roll_trace": {"draws": draws, "modifier": modifier},
            },
            mutations=(
                [{"op": "replace", "path": "/character/hp", "value": new_hp}]
                if healed > 0 else []
            ),
            reveal_steps=[{"kind": "healing", "result": healed, "newHp": new_hp}],
        )


class CocStatusHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        status = str(params.get("status") or "").strip()
        operation = str(params.get("operation") or "add").strip().lower()
        if status not in _KNOWN_STATUSES or operation not in {"add", "remove"}:
            return RuleResult(
                is_success=False,
                metadata={
                    "status": "pending_host_confirmation",
                    "reason_code": "unsupported_status_change",
                    "requested_status": status,
                    "citation": _rule_citation(params),
                },
            )
        return RuleResult(
            is_success=True,
            metadata={"status": status, "operation": operation},
            mutations=[{
                "op": operation,
                "path": "/character/status_tag",
                "value": status,
            }],
            reveal_steps=[{
                "kind": "status_delta",
                "payload": {"statusTag": status, "operation": operation},
            }],
        )
