import pytest

from src.server.engine.rule_executor import RuleExecutor
from src.server.engine.skill_check import roll_skill_check
from src.server.models import MechanicCompileResult, PlayerIntent
from src.server.rules.base import GameState
from src.server.rules.coc_handlers import (
    CocHealingHandler,
    CocMoveHandler,
    CocOpposedCheckHandler,
    CocSkillCheckHandler,
    CocStatusHandler,
)
from src.server.rules.encounter_handlers import CombatAttackHandler, ChasePursueHandler
from src.server.rules.registry import register_rule, rule_registry


def _sequence_randint(monkeypatch, values):
    values = iter(values)
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(values),
    )


def test_bonus_die_compares_full_percentile_values_and_records_roll_trace(monkeypatch):
    _sequence_randint(monkeypatch, [0, 0, 5])

    result = roll_skill_check(60, bonus_dice=1)

    assert result["roll"] == 50
    assert result["roll_trace"] == {
        "ones": 0,
        "tens": [0, 5],
        "candidates": [100, 50],
        "selected_index": 1,
    }


def test_bonus_and_penalty_dice_are_clamped_to_two(monkeypatch):
    _sequence_randint(monkeypatch, [5, 5, 4, 3])

    result = roll_skill_check(60, bonus_dice=99)

    assert result["bonus_dice"] == 2
    assert len(result["roll_trace"]["candidates"]) == 3


@pytest.mark.asyncio
async def test_skill_check_can_spend_only_required_luck_after_server_roll(monkeypatch):
    _sequence_randint(monkeypatch, [6, 5])
    state = GameState(character={"luck": 10})

    result = await CocSkillCheckHandler().execute(
        state,
        {
            "skillName": "侦查",
            "skillValue": 60,
            "difficulty": "regular",
            "spendLuck": True,
        },
    )

    assert result.is_success is True
    assert result.metadata["roll"] == 65
    assert result.metadata["luck_spent"] == 5
    assert result.metadata["success_level"] == "regular"
    assert result.mutations == [
        {"op": "replace", "path": "/character/luck", "value": 5}
    ]


@pytest.mark.asyncio
async def test_pushed_check_rerolls_a_failure_and_keeps_both_rolls(monkeypatch):
    _sequence_randint(monkeypatch, [8, 0, 3, 0])

    result = await CocSkillCheckHandler().execute(
        GameState(character={"luck": 0}),
        {"skillName": "侦查", "skillValue": 60, "pushed": True},
    )

    assert result.is_success is True
    assert result.metadata["pushed"] is True
    assert result.metadata["initial_roll"] == 80
    assert result.metadata["roll"] == 30
    assert [step["result"] for step in result.reveal_steps] == [80, 30]


@pytest.mark.asyncio
async def test_failed_pushed_check_only_creates_evidence_backed_pending_consequence(monkeypatch):
    _sequence_randint(monkeypatch, [8, 0, 9, 0])

    result = await CocSkillCheckHandler().execute(
        GameState(character={"luck": 0}),
        {
            "skillName": "侦查",
            "skillValue": 60,
            "pushed": True,
            "ruleCitation": {"source_ref": "coc7#p84"},
        },
    )

    assert result.is_success is False
    assert result.mutations == []
    assert result.metadata["pending_consequence"]["status"] == "pending_host_confirmation"
    assert result.metadata["pending_consequence"]["citation"]["source_ref"] == "coc7#p84"


@pytest.mark.asyncio
async def test_opposed_check_uses_server_state_values_and_success_levels(monkeypatch):
    _sequence_randint(monkeypatch, [2, 0, 4, 0])
    state = GameState(
        character={"skills": {"侦查": 60}},
        scene={"opponent": {"name": "守卫", "skills": {"潜行": 50}}},
    )

    result = await CocOpposedCheckHandler().execute(
        state,
        {
            "skillName": "侦查",
            "opponentSkillName": "潜行",
            "skillValue": 1,
            "opponentSkillValue": 99,
        },
    )

    assert result.is_success is True
    assert result.metadata["actor"]["skill_value"] == 60
    assert result.metadata["opponent"]["skill_value"] == 50
    assert result.metadata["winner"] == "actor"
    assert result.mutations == []


@pytest.mark.asyncio
async def test_opposed_check_without_authoritative_opponent_requires_host_confirmation():
    result = await CocOpposedCheckHandler().execute(
        GameState(character={"skills": {"侦查": 60}}),
        {"skillName": "侦查", "opponentSkillName": "潜行"},
    )

    assert result.is_success is False
    assert result.mutations == []
    assert result.metadata["status"] == "pending_host_confirmation"


@pytest.mark.asyncio
async def test_opposed_check_has_no_winner_when_both_sides_fail(monkeypatch):
    _sequence_randint(monkeypatch, [8, 0, 9, 0])
    state = GameState(
        character={"skills": {"侦查": 60}},
        scene={"opponent": {"skills": {"潜行": 50}}},
    )

    result = await CocOpposedCheckHandler().execute(
        state, {"skillName": "侦查", "opponentSkillName": "潜行"}
    )

    assert result.is_success is False
    assert result.metadata["winner"] == "tie"


@pytest.mark.asyncio
async def test_healing_is_capped_by_max_hp(monkeypatch):
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.random.randint", lambda _low, _high: 6
    )

    result = await CocHealingHandler().execute(
        GameState(character={"hp": 7, "max_hp": 10}),
        {"amount": "1d6"},
    )

    assert result.metadata["healed"] == 3
    assert result.mutations == [
        {"op": "replace", "path": "/character/hp", "value": 10}
    ]


@pytest.mark.asyncio
async def test_status_handler_only_mutates_known_statuses():
    handler = CocStatusHandler()

    accepted = await handler.execute(
        GameState(character={}), {"status": "unconscious", "operation": "add"}
    )
    pending = await handler.execute(
        GameState(character={}),
        {
            "status": "invented_by_ai",
            "operation": "add",
            "ruleCitation": {"source_ref": "house-rule#1"},
        },
    )

    assert accepted.mutations == [
        {"op": "add", "path": "/character/status_tag", "value": "unconscious"}
    ]
    assert pending.mutations == []
    assert pending.metadata["status"] == "pending_host_confirmation"


@pytest.mark.asyncio
async def test_move_rejects_non_adjacent_nodes_when_server_map_is_available():
    state = GameState(
        character={},
        scene={"map": {"edges": [{"from": "hall", "to": "library"}]}},
    )

    result = await CocMoveHandler().execute(
        state, {"fromNodeId": "hall", "targetNodeId": "crypt"}
    )

    assert result.is_success is False
    assert result.mutations == []
    assert result.metadata["reason_code"] == "nodes_not_adjacent"


@pytest.mark.asyncio
async def test_rule_executor_ignores_client_or_ai_skill_value_and_roll(monkeypatch):
    _sequence_randint(monkeypatch, [5, 0])
    executor = RuleExecutor()
    intent = PlayerIntent(intent_type="skill_check", declared_intent="侦查")
    compiled = MechanicCompileResult(
        triggeredMechanic="skill_check",
        skillName="侦查",
        consequence={"skillValue": 99, "roll": 1, "successLevel": "critical"},
    )

    result = await executor.execute(
        intent,
        compiled,
        {"xlsx_data": {"skills": {"侦查": 20}, "luck": 0}},
        inventory=[],
        scenario_assets={},
    )

    assert result.metadata["skill_value"] == 20
    assert result.metadata["roll"] == 50
    assert result.is_success is False


@pytest.mark.asyncio
async def test_unimplemented_rule_never_applies_state_and_returns_pending_suggestion():
    executor = RuleExecutor()
    intent = PlayerIntent(intent_type="dialogue", declared_intent="进入密室")
    assets = {
        "triggers": [{
            "condition": {"$action": "dialogue"},
            "mechanics": [{
                "type": "teleport_through_dream",
                "params": {
                    "path": "/character/san",
                    "value": 0,
                    "ruleCitation": {"source_ref": "module#p12"},
                },
            }],
        }],
    }

    result = await executor.execute(
        intent,
        MechanicCompileResult(triggeredMechanic="auto_success"),
        {"xlsx_data": {"san": 50}},
        inventory=[],
        scenario_assets=assets,
    )

    assert result.is_success is False
    assert result.mutations == []
    pending = result.metadata["pending_rule_suggestions"][0]
    assert pending["mechanic"] == "teleport_through_dream"
    assert pending["status"] == "pending_host_confirmation"
    assert pending["citation"]["source_ref"] == "module#p12"


@pytest.mark.asyncio
async def test_apply_patch_rejects_non_allowlisted_state_path():
    executor = RuleExecutor()
    intent = PlayerIntent(intent_type="dialogue", declared_intent="进入密室")
    assets = {
        "triggers": [{
            "condition": {"$action": "dialogue"},
            "mechanics": [{
                "type": "apply_patch",
                "params": {
                    "op": "replace",
                    "path": "/character/name",
                    "value": "AI overwrite",
                    "ruleCitation": {"source_ref": "module#p13"},
                },
            }],
        }],
    }

    result = await executor.execute(
        intent,
        MechanicCompileResult(triggeredMechanic="auto_success"),
        {"xlsx_data": {"name": "Original"}},
        inventory=[],
        scenario_assets=assets,
    )

    assert result.is_success is False
    assert result.mutations == []
    assert result.metadata["pending_rule_suggestions"][0]["mechanic"] == "apply_patch"


@pytest.mark.asyncio
async def test_combat_roll_100_is_fumble_even_at_skill_100(monkeypatch):
    def fixed_randint(_low, high):
        if high == 100:
            return 100
        return 0 if high == 9 else 1

    monkeypatch.setattr("src.server.rules.encounter_handlers.random.randint", fixed_randint)
    result = await CombatAttackHandler().execute(
        GameState(character={"skills": {"斗殴": 100}}),
        {
            "skillName": "斗殴",
            "damage": "99d999",
            "targetId": "enemy",
            "encounterId": "enc-1",
            "encounter_context": _encounter_context(),
        },
    )

    assert result.is_success is False
    assert result.metadata["success_level"] == "fumble"
    assert result.metadata["damage"] == 0
    assert result.mutations == []


@pytest.mark.asyncio
async def test_chase_respects_required_difficulty_and_emits_roll_trace(monkeypatch):
    digits = iter([4, 0])

    def fixed_randint(_low, high):
        if high == 100:
            return 40
        return next(digits)

    monkeypatch.setattr("src.server.rules.encounter_handlers.random.randint", fixed_randint)
    result = await ChasePursueHandler().execute(
        GameState(character={"mov": 8, "skills": {"运动": 60}}),
        {
            "skillName": "运动",
            "difficulty": "hard",
            "encounter_context": _encounter_context("运动"),
        },
    )

    assert result.metadata["roll"] == 40
    assert result.metadata["success_level"] == "regular"
    assert result.is_success is False
    assert result.metadata["roll_trace"]["candidates"] == [40]


@pytest.mark.asyncio
async def test_combat_ignores_forged_skill_damage_and_unknown_target(monkeypatch):
    digits = iter([5, 0])

    def fixed_randint(_low, high):
        if high == 9:
            return next(digits)
        return 1

    monkeypatch.setattr("src.server.rules.encounter_handlers.random.randint", fixed_randint)
    handler = CombatAttackHandler()
    state = GameState(character={"skills": {"斗殴": 10}})
    params = {
        "skillName": "斗殴",
        "skillValue": 99,
        "damage": "99d999",
        "targetId": "enemy",
        "encounterId": "enc-1",
        "encounter_context": _encounter_context(),
    }

    result = await handler.execute(state, params)

    assert result.metadata["skill_value"] == 10
    assert result.metadata["damage_expression"] == "1d3"
    assert result.is_success is False
    assert result.mutations == []

    forged_target = await handler.execute(
        state,
        {**params, "targetId": "not-in-encounter"},
    )
    assert forged_target.is_success is False
    assert forged_target.mutations == []
    assert forged_target.metadata["reason_code"] == "invalid_encounter_target"


@pytest.mark.asyncio
async def test_registered_handler_cannot_emit_non_allowlisted_mutation():
    from src.server.rules.base import BaseRuleHandler, RuleResult

    class UnsafeHandler(BaseRuleHandler):
        async def execute(self, state, params):
            return RuleResult(
                is_success=True,
                mutations=[{
                    "op": "replace",
                    "path": "/character/name",
                    "value": "overwritten",
                }],
            )

    register_rule("unsafe_test_handler", UnsafeHandler())
    try:
        result = await RuleExecutor().execute(
            PlayerIntent(intent_type="dialogue", declared_intent="触发测试"),
            MechanicCompileResult(triggeredMechanic="auto_success"),
            {"xlsx_data": {"name": "Original"}},
            inventory=[],
            scenario_assets={
                "triggers": [{
                    "condition": {"$action": "dialogue"},
                    "mechanics": [{"type": "unsafe_test_handler", "params": {}}],
                }]
            },
        )
    finally:
        rule_registry.pop("unsafe_test_handler", None)

    assert result.is_success is False
    assert result.mutations == []
    assert result.metadata["pending_rule_suggestions"][0]["reason_code"] == "unsafe_mutation_rejected"


def _encounter_context(main_skill="斗殴"):
    return {
        "participant": {
            "character_id": "actor",
            "mov": 8,
            "damage_expression": "1d3",
            "main_skill": main_skill,
            "side": "player",
        },
        "allParticipants": [
            {"character_id": "actor", "side": "player", "hp": 10},
            {"character_id": "enemy", "side": "enemy", "hp": 10},
        ],
        "encounter": {"encounter_id": "enc-1", "type": "combat", "status": "active"},
    }
