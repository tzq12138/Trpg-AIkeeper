import random
import re
from copy import deepcopy
from math import ceil
from typing import Any

from .base import BaseRuleHandler, GameState, RuleResult
from ..engine.secure_random import secure_randint


_DICE_PATTERN = re.compile(r"^(\d{1,2})d(\d{1,4})([+-]\d{1,4})?$")
_KNOWN_STATUSES = {
    "unconscious", "dying", "major_wound", "temporary_insanity",
    "indefinite_insanity", "permanent_insanity", "dying_stabilized",
    "dead", "restrained", "poisoned", "burning", "fled", "pinned",
    "defending", "assisted",
}
_SANITY_STATE_PATH = "/character/temp_modifier/coc7_sanity"
_IMMEDIATE_SANITY_SYMPTOMS = {
    1: "amnesia",
    2: "psychosomatic_disability",
    3: "violence",
    4: "paranoia",
    5: "significant_person_dependency",
    6: "fainting",
    7: "fleeing",
    8: "hysterics",
    9: "phobia",
    10: "mania",
}
_SUMMARY_SANITY_SYMPTOMS = {
    1: "amnesia",
    2: "robbed",
    3: "battered",
    4: "violence",
    5: "extreme_belief",
    6: "significant_person",
    7: "institutionalized",
    8: "fleeing",
    9: "phobia",
    10: "mania",
}
_HIGH_RISK_SANITY_SYMPTOMS = {
    "immediate": {3, 7},
    "summary": {2, 3, 4, 7, 8},
}
_SAFE_SANITY_FALLBACK = {"immediate": 8, "summary": 1}


def roll_dice(notation: str) -> tuple[int, list[int], int]:
    normalized = str(notation).strip()
    if normalized.isdigit():
        value = int(normalized)
        if value > 10000:
            raise ValueError(f"Dice notation out of range: {notation}")
        return value, [], value
    match = _DICE_PATTERN.fullmatch(normalized)
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


def max_dice(notation: str) -> int:
    normalized = str(notation).strip()
    if normalized.isdigit():
        return min(10000, int(normalized))
    match = _DICE_PATTERN.fullmatch(normalized)
    if not match:
        raise ValueError(f"Invalid dice notation: {notation}")
    count, sides = int(match.group(1)), int(match.group(2))
    if count < 1 or count > 20 or sides < 2 or sides > 1000:
        raise ValueError(f"Dice notation out of range: {notation}")
    modifier = int(match.group(3) or 0)
    return max(0, count * sides + modifier)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _character_attribute(character: dict, *names: str) -> int:
    attributes = character.get("attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {}
    candidates = {
        str(key).strip().lower(): value
        for key, value in {**character, **attributes}.items()
    }
    for name in names:
        normalized = name.strip().lower()
        if normalized in candidates:
            return max(0, _as_int(candidates[normalized]))
    return 0


def _status_tags(character: dict) -> list[str]:
    raw = character.get("status_tags") or []
    if isinstance(raw, str):
        try:
            import json

            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    return [str(value) for value in raw] if isinstance(raw, list) else []


def _temp_modifiers(character: dict) -> dict:
    raw = character.get("temp_modifiers") or {}
    if isinstance(raw, str):
        try:
            import json

            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = {}
    return dict(raw) if isinstance(raw, dict) else {}


def _normalized_consequence(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {
            "code": "pushed_check_complication",
            "public_text": "孤注一掷失败，局势出现了更严重但不越权改写状态的后果。",
        }
    code = re.sub(r"[^a-z0-9_-]", "", str(value.get("code") or "").lower())[:80]
    text = re.sub(r"\s+", " ", str(value.get("publicText") or value.get("public_text") or "")).strip()
    return {
        "code": code or "pushed_check_complication",
        "public_text": text[:500] or "孤注一掷失败，局势出现了更严重但不越权改写状态的后果。",
    }


def _sanity_day_key(state: GameState, params: dict) -> str:
    value = (
        params.get("inGameDay")
        or params.get("in_game_day")
        or (state.scene or {}).get("in_game_day")
        or (state.scene or {}).get("public_time")
        or "session-day-1"
    )
    return str(value).strip()[:120] or "session-day-1"


def _sanity_manifestation(
    *,
    mode: str,
    proposal: Any,
    safe_replacement: Any,
) -> dict[str, Any]:
    table = (
        _IMMEDIATE_SANITY_SYMPTOMS
        if mode == "immediate"
        else _SUMMARY_SANITY_SYMPTOMS
    )

    def candidate(value: Any) -> int | None:
        if not isinstance(value, dict) or str(value.get("mode") or mode) != mode:
            return None
        symptom_id = _as_int(value.get("symptomId", value.get("symptom_id")))
        return symptom_id if symptom_id in table else None

    proposed_id = candidate(proposal)
    selected_id = proposed_id
    selection_source = "ai_validated"
    retry_count = 0
    if selected_id is None or selected_id in _HIGH_RISK_SANITY_SYMPTOMS[mode]:
        retry_count = 1
        replacement_id = candidate(safe_replacement)
        if (
            replacement_id is not None
            and replacement_id not in _HIGH_RISK_SANITY_SYMPTOMS[mode]
        ):
            selected_id = replacement_id
            selection_source = "ai_safe_replacement"
        else:
            selected_id = _SAFE_SANITY_FALLBACK[mode]
            selection_source = "engine_safe_fallback"
    return {
        "mode": mode,
        "symptom_id": selected_id,
        "symptom": table[selected_id],
        "selection_source": selection_source,
        "retry_count": retry_count,
        "boundary_tags": ["distress", "non_graphic", "no_forced_harm"],
    }


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
        pushed_consequence = None
        if pushed and not is_success:
            consequence = _normalized_consequence(
                params.get("pushedFailureConsequence")
                or params.get("pushed_failure_consequence")
            )
            pushed_consequence = {
                "status": "resolved_by_engine",
                "reason": "pushed_check_failed",
                **consequence,
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
                "pushed_consequence": pushed_consequence,
                "detail": detail,
            },
            mutations=mutations,
            reveal_steps=reveal_steps,
            cascading_state_changes=(
                [pushed_consequence["public_text"]]
                if pushed_consequence else []
            ),
        )


class CocSanityCheckHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        success_loss = params.get("success_loss", "0")
        failure_loss = params.get("failure_loss", "0")
        current_san = max(0, _as_int(state.character.get("san", 0)))
        prior_state = _temp_modifiers(state.character).get("coc7_sanity")
        prior_state = deepcopy(prior_state) if isinstance(prior_state, dict) else {}

        if (
            prior_state.get("insanity_type") == "permanent"
            or prior_state.get("phase") == "permanent"
            or current_san == 0
        ):
            return RuleResult(
                is_success=False,
                metadata={
                    "reason_code": "permanent_insanity",
                    "current_san": current_san,
                    "new_san": current_san,
                    "san_loss": 0,
                    "sanity_state": prior_state,
                },
            )
        if prior_state.get("phase") == "bout":
            return RuleResult(
                is_success=True,
                metadata={
                    "reason_code": "san_loss_suspended_during_bout",
                    "current_san": current_san,
                    "new_san": current_san,
                    "san_loss": 0,
                    "sanity_state": prior_state,
                },
            )

        roll = secure_randint(1, 100, test_rng=random)
        is_success = roll <= current_san
        sanity_fumble = roll == 100 or (current_san < 50 and roll >= 96)
        success_level = (
            "fumble" if sanity_fumble
            else "regular" if is_success
            else "failure"
        )

        if is_success:
            san_loss, loss_draws, modifier = roll_dice(success_loss) if success_loss != "0" else (0, [], 0)
        elif sanity_fumble:
            san_loss = max_dice(failure_loss)
            loss_draws, modifier = [], 0
        else:
            san_loss, loss_draws, modifier = roll_dice(failure_loss) if failure_loss != "0" else (0, [], 0)

        new_san = max(0, current_san - san_loss)
        day_key = _sanity_day_key(state, params)
        if prior_state.get("day_key") == day_key:
            day_start_san = max(
                current_san,
                _as_int(prior_state.get("day_start_san"), current_san),
            )
            day_loss = max(0, _as_int(prior_state.get("day_loss"))) + san_loss
        else:
            day_start_san = current_san
            day_loss = san_loss
        daily_threshold = max(1, ceil(day_start_san / 5))

        sanity_state = {
            **prior_state,
            "schema_version": 1,
            "day_key": day_key,
            "day_start_san": day_start_san,
            "day_loss": day_loss,
            "last_source_id": str(
                params.get("sourceId")
                or params.get("source_id")
                or "unspecified"
            )[:120],
            "last_san_before": current_san,
            "last_san_after": new_san,
            "last_san_loss": san_loss,
            "retriggered": False,
        }
        existing_type = str(prior_state.get("insanity_type") or "none")
        existing_phase = str(prior_state.get("phase") or "stable")
        insanity_type = "none"
        int_check = None
        retriggered = (
            existing_type in {"temporary", "indefinite"}
            and existing_phase == "underlying"
            and san_loss > 0
        )

        if new_san == 0:
            insanity_type = "permanent"
        elif day_loss >= daily_threshold:
            insanity_type = "indefinite"
        elif retriggered:
            insanity_type = existing_type
        elif san_loss >= 5:
            int_value = _character_attribute(state.character, "int", "智力")
            int_roll = secure_randint(1, 100, test_rng=random)
            int_success = int_roll <= int_value
            int_check = {
                "roll": int_roll,
                "target": int_value,
                "is_success": int_success,
            }
            if int_success:
                insanity_type = "temporary"

        mutations = [
            {"op": "replace", "path": "/character/san", "value": new_san}
        ]
        cascading = []
        if insanity_type == "permanent":
            sanity_state.update({
                "insanity_type": "permanent",
                "phase": "permanent",
                "control": "ai_keeper",
                "archive_required": True,
                "reserve_investigator_at_safe_scene": True,
                "background_change_pending_player_confirmation": True,
            })
            mutations.extend([
                {
                    "op": "add",
                    "path": "/character/status_tag",
                    "value": "permanent_insanity",
                },
                {
                    "op": "replace",
                    "path": _SANITY_STATE_PATH,
                    "value": sanity_state,
                },
            ])
            cascading.append("永久性疯狂：调查员退出玩家控制并转由 AI-Keeper 作为 NPC 管理")
        elif insanity_type in {"temporary", "indefinite"}:
            mode = (
                "immediate"
                if bool(
                    params.get(
                        "companionsPresent",
                        params.get("companions_present", True),
                    )
                )
                else "summary"
            )
            bout = _sanity_manifestation(
                mode=mode,
                proposal=params.get("manifestation"),
                safe_replacement=(
                    params.get("safeReplacement")
                    or params.get("safe_replacement")
                ),
            )
            bout_duration = secure_randint(1, 10, test_rng=random)
            bout["duration"] = {
                "value": bout_duration,
                "unit": "rounds" if mode == "immediate" else "hours",
            }
            sanity_state.update({
                "insanity_type": insanity_type,
                "phase": "bout",
                "bout": bout,
                "control": "ai_keeper",
                "retriggered": retriggered,
                "background_change_pending_player_confirmation": False,
            })
            if insanity_type == "temporary":
                if existing_type == "temporary" and prior_state.get("underlying_duration"):
                    underlying_duration = deepcopy(prior_state["underlying_duration"])
                else:
                    underlying_duration = {
                        "value": secure_randint(1, 10, test_rng=random),
                        "unit": "hours",
                    }
                sanity_state["underlying_duration"] = underlying_duration
            else:
                sanity_state["underlying_duration"] = {
                    "value": None,
                    "unit": "until_recovery",
                }
            status = f"{insanity_type}_insanity"
            if existing_type in {"temporary", "indefinite"} and existing_type != insanity_type:
                mutations.append({
                    "op": "remove",
                    "path": "/character/status_tag",
                    "value": f"{existing_type}_insanity",
                })
            mutations.extend([
                {
                    "op": "add",
                    "path": "/character/status_tag",
                    "value": status,
                },
                {
                    "op": "replace",
                    "path": _SANITY_STATE_PATH,
                    "value": sanity_state,
                },
            ])
            cascading.append(
                "不定性疯狂发作" if insanity_type == "indefinite"
                else "临时性疯狂发作"
            )
        else:
            if existing_type in {"temporary", "indefinite"}:
                sanity_state["insanity_type"] = existing_type
                sanity_state["phase"] = existing_phase
            else:
                sanity_state["insanity_type"] = "none"
                sanity_state["phase"] = "stable"
                sanity_state["control"] = "player"
            mutations.append({
                "op": "replace",
                "path": _SANITY_STATE_PATH,
                "value": sanity_state,
            })

        metadata = {
            "roll": roll,
            "current_san": current_san,
            "skill_name": "理智",
            "skill_value": current_san,
            "target": current_san,
            "difficulty": "regular",
            "success_level": success_level,
            "san_loss": san_loss,
            "new_san": new_san,
            "sanity_fumble": sanity_fumble,
            "daily_san_loss": day_loss,
            "daily_san_threshold": daily_threshold,
            "insanity_type": sanity_state.get("insanity_type", "none"),
            "sanity_phase": sanity_state.get("phase", "stable"),
            "roll_trace": {
                "d100": [roll],
                "loss_draws": loss_draws,
                "modifier": modifier,
            },
        }
        if int_check is not None:
            metadata["int_check"] = int_check

        return RuleResult(
            is_success=is_success,
            metadata=metadata,
            mutations=mutations,
            reveal_steps=[
                {"kind": "roll", "dice": "d100", "result": roll, "target": current_san},
                {"kind": "san_loss", "loss": san_loss},
            ],
            cascading_state_changes=cascading,
        )


class CocSanityAdvanceHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        current = _temp_modifiers(state.character).get("coc7_sanity")
        if not isinstance(current, dict):
            return RuleResult(
                is_success=False,
                metadata={"status": "rejected", "reason_code": "sanity_state_required"},
            )
        event = str(params.get("event") or "").strip()
        updated = deepcopy(current)
        mutations = []
        if event == "bout_elapsed" and current.get("phase") == "bout":
            updated["phase"] = "underlying"
            updated["control"] = "player"
            updated["background_change_pending_player_confirmation"] = True
            mutations.append({
                "op": "replace",
                "path": _SANITY_STATE_PATH,
                "value": updated,
            })
        elif event == "background_confirmed" and current.get(
            "background_change_pending_player_confirmation"
        ):
            updated["background_change_pending_player_confirmation"] = False
            updated["background_change_confirmed"] = True
            mutations.append({
                "op": "replace",
                "path": _SANITY_STATE_PATH,
                "value": updated,
            })
        elif (
            event == "recovered"
            and current.get("insanity_type") in {"temporary", "indefinite"}
            and current.get("phase") == "underlying"
        ):
            insanity_type = str(current["insanity_type"])
            updated.update({
                "insanity_type": "none",
                "phase": "stable",
                "control": "player",
                "bout": None,
                "underlying_duration": None,
            })
            mutations.extend([
                {
                    "op": "remove",
                    "path": "/character/status_tag",
                    "value": f"{insanity_type}_insanity",
                },
                {
                    "op": "replace",
                    "path": _SANITY_STATE_PATH,
                    "value": updated,
                },
            ])
        else:
            return RuleResult(
                is_success=False,
                metadata={
                    "status": "rejected",
                    "reason_code": "invalid_sanity_transition",
                    "event": event,
                },
            )
        return RuleResult(
            is_success=True,
            metadata={
                "event": event,
                "insanity_type": updated.get("insanity_type"),
                "sanity_phase": updated.get("phase"),
                "background_change_pending_player_confirmation": updated.get(
                    "background_change_pending_player_confirmation",
                    False,
                ),
            },
            mutations=mutations,
            reveal_steps=[{
                "kind": "sanity_state",
                "event": event,
                "phase": updated.get("phase"),
            }],
        )


class CocCombatHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        damage_dice = params.get("damage", "1d3")
        current_hp = max(0, _as_int(state.character.get("hp", 0)))
        max_hp = max(
            current_hp,
            _as_int(
                state.character.get(
                    "max_hp",
                    state.character.get("hp_max", current_hp),
                ),
                current_hp,
            ),
        )

        damage, damage_draws, modifier = roll_dice(damage_dice)
        new_hp = max(0, current_hp - damage)
        existing_statuses = set(_status_tags(state.character))
        major_wound = max_hp > 0 and damage >= ceil(max_hp / 2)
        instantly_dead = max_hp > 0 and damage > max_hp
        mutations = [
            {"op": "replace", "path": "/character/hp", "value": new_hp}
        ]
        cascading = []
        con_check = None
        statuses_to_add = []
        if instantly_dead:
            statuses_to_add.extend(["dead", "unconscious"])
            cascading.append("单次伤害超过最大生命值：死亡")
        else:
            if major_wound:
                statuses_to_add.append("major_wound")
                cascading.append("重伤")
            if new_hp == 0:
                statuses_to_add.append("unconscious")
                if major_wound or "major_wound" in existing_statuses:
                    statuses_to_add.append("dying")
                    cascading.append("濒死")
                else:
                    cascading.append("昏迷")
            elif major_wound:
                from ..engine.skill_check import roll_skill_check

                con_value = _character_attribute(state.character, "con", "体质")
                con_check = roll_skill_check(con_value)
                if not con_check["is_success"]:
                    statuses_to_add.append("unconscious")
                    cascading.append("重伤体质检定失败：昏迷")
        for status in statuses_to_add:
            if status not in existing_statuses:
                mutations.append({
                    "op": "add",
                    "path": "/character/status_tag",
                    "value": status,
                })
                existing_statuses.add(status)

        return RuleResult(
            is_success=True,
            metadata={
                "damage": damage,
                "current_hp": current_hp,
                "max_hp": max_hp,
                "new_hp": new_hp,
                "major_wound": major_wound,
                "instantly_dead": instantly_dead,
                "con_check": con_check,
                "roll_trace": {"draws": damage_draws, "modifier": modifier},
            },
            mutations=mutations,
            reveal_steps=[
                {"kind": "damage", "dice": damage_dice, "result": damage}
            ],
            cascading_state_changes=cascading,
        )


class CocLuckCheckHandler(BaseRuleHandler):
    async def execute(self, state: GameState, params: dict) -> RuleResult:
        group_luck = bool(
            params.get("groupLuck", params.get("group_luck", False))
        )
        luck_values = (state.scene or {}).get("_party_luck_values")
        if group_luck and isinstance(luck_values, list):
            normalized = [
                max(0, _as_int(value))
                for value in luck_values
                if value is not None
            ]
            current_luck = min(normalized) if normalized else max(
                0, _as_int(state.character.get("luck", 0))
            )
        else:
            current_luck = max(0, _as_int(state.character.get("luck", 0)))
        roll = secure_randint(1, 100, test_rng=random)
        is_success = roll <= current_luck

        return RuleResult(
            is_success=is_success,
            metadata={
                "roll": roll,
                "luck": current_luck,
                "group_luck": group_luck,
                "roll_trace": {"d100": [roll]},
            },
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
                    "status": "rejected",
                    "reason_code": "authoritative_opponent_required",
                    "citation": _rule_citation(params),
                },
            )

        from ..engine.skill_check import SUCCESS_LEVEL_RANK, roll_skill_check

        actor_skill_name = params.get("skillName", "")
        opponent_skill_name = params.get("opponentSkillName", actor_skill_name)
        actor_value = int((state.character.get("skills") or {}).get(actor_skill_name, 0) or 0)
        opponent_value = int((opponent.get("skills") or {}).get(opponent_skill_name, 0) or 0)
        rounds = []
        winner = "stalemate"
        actor_roll = opponent_roll = None
        for _round in range(1, 101):
            actor_roll = roll_skill_check(actor_value)
            opponent_roll = roll_skill_check(opponent_value)
            actor_rank = SUCCESS_LEVEL_RANK[actor_roll["success_level"]]
            opponent_rank = SUCCESS_LEVEL_RANK[opponent_roll["success_level"]]
            rounds.append({
                "round": _round,
                "actor": actor_roll,
                "opponent": opponent_roll,
            })
            if actor_rank > opponent_rank:
                winner = "actor"
                break
            if opponent_rank > actor_rank:
                winner = "opponent"
                break
            if actor_value > opponent_value:
                winner = "actor"
                break
            if opponent_value > actor_value:
                winner = "opponent"
                break
            # Exact success-level and skill tie: reroll. A hard cap preserves
            # deterministic termination if the random source is pathological.
        return RuleResult(
            is_success=winner == "actor",
            metadata={
                "winner": winner,
                "reroll_count": len(rounds) - 1,
                "rounds": rounds,
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
        method = str(params.get("method") or "first_aid").strip().lower()
        statuses = set(_status_tags(state.character))
        if method == "first_aid":
            within_hour = bool(
                params.get("withinHour", params.get("within_hour", True))
            )
            already_attempted = bool(
                params.get("alreadyAttempted", params.get("already_attempted", False))
            )
            pushed = bool(params.get("pushed", False))
            if not within_hour:
                return RuleResult(
                    is_success=False,
                    metadata={
                        "status": "rejected",
                        "reason_code": "first_aid_window_elapsed",
                    },
                )
            if already_attempted and not pushed:
                return RuleResult(
                    is_success=False,
                    metadata={
                        "status": "rejected",
                        "reason_code": "first_aid_push_required",
                    },
                )
            rolled, draws, modifier = 1, [], 1
            healing_dice = "1"
        elif method == "medicine":
            if "dying" in statuses and "dying_stabilized" not in statuses:
                return RuleResult(
                    is_success=False,
                    metadata={
                        "status": "rejected",
                        "reason_code": "dying_requires_first_aid_stabilization",
                    },
                )
            rolled, draws, modifier = roll_dice("1d3")
            healing_dice = "1d3"
        elif method == "regular_recovery":
            if "major_wound" in statuses:
                return RuleResult(
                    is_success=False,
                    metadata={
                        "status": "rejected",
                        "reason_code": "major_wound_requires_weekly_recovery",
                    },
                )
            rolled, draws, modifier = 1, [], 1
            healing_dice = "1/day"
        elif method == "major_wound_recovery":
            success_level = str(params.get("successLevel") or params.get("success_level") or "failure")
            if success_level not in {"regular", "hard", "extreme", "critical"}:
                rolled, draws, modifier = 0, [], 0
                healing_dice = "0"
            else:
                healing_dice = "2d3" if success_level in {"extreme", "critical"} else "1d3"
                rolled, draws, modifier = roll_dice(healing_dice)
        else:
            return RuleResult(
                is_success=False,
                metadata={
                    "status": "rejected",
                    "reason_code": "unsupported_healing_method",
                },
            )
        new_hp = min(max_hp, current_hp + rolled)
        healed = new_hp - current_hp
        mutations = (
            [{"op": "replace", "path": "/character/hp", "value": new_hp}]
            if healed > 0 else []
        )
        if method == "first_aid" and "dying" in statuses:
            mutations.append({
                "op": "add",
                "path": "/character/status_tag",
                "value": "dying_stabilized",
            })
        if method == "medicine" and "dying" in statuses:
            mutations.extend([
                {
                    "op": "remove",
                    "path": "/character/status_tag",
                    "value": "dying",
                },
                {
                    "op": "remove",
                    "path": "/character/status_tag",
                    "value": "dying_stabilized",
                },
            ])
        if (
            method == "major_wound_recovery"
            and "major_wound" in statuses
            and (
                str(params.get("successLevel") or params.get("success_level") or "")
                in {"extreme", "critical"}
                or new_hp >= ceil(max_hp / 2)
            )
        ):
            mutations.append({
                "op": "remove",
                "path": "/character/status_tag",
                "value": "major_wound",
            })
        return RuleResult(
            is_success=healed > 0,
            metadata={
                "method": method,
                "current_hp": current_hp,
                "max_hp": max_hp,
                "new_hp": new_hp,
                "healed": healed,
                "healing_dice": healing_dice,
                "roll_trace": {"draws": draws, "modifier": modifier},
            },
            mutations=mutations,
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
                    "status": "rejected",
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
