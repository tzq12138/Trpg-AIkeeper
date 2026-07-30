import random

import pytest

from src.server.models import MechanicCompileResult, PlayerIntent
from src.server.engine.rule_executor import RuleExecutor


@pytest.mark.asyncio
async def test_rule_executor_runs_compiled_skill_check_with_character_skill():
    random.seed(36)  # roll=50, success against skill 60
    executor = RuleExecutor()
    intent = PlayerIntent(intent_type="dialogue", declared_intent="我侦查书桌")
    compiled = MechanicCompileResult(
        triggeredMechanic="skill_check",
        skillName="侦查",
        difficulty="regular",
    )
    character = {"xlsx_data": {"skills": {"侦查": 60}, "hp": 10, "san": 50, "luck": 40}}

    result = await executor.execute(intent, compiled, character, inventory=[], scenario_assets={})

    assert result.mechanic == "skill_check"
    assert result.is_success is True
    assert result.metadata["skill_value"] == 60
    assert result.metadata["roll"] == 50
    assert result.reveal_steps[0]["kind"] == "roll"


@pytest.mark.asyncio
async def test_rule_executor_preserves_confirmed_luck_spend_params(monkeypatch):
    rolls = iter([6, 5])
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(rolls),
    )
    executor = RuleExecutor()
    intent = PlayerIntent(
        intent_type="skill_check",
        declared_intent="我确认花费幸运",
        params={"skillName": "侦查", "spendLuck": True},
    )
    compiled = MechanicCompileResult(
        triggeredMechanic="skill_check",
        skillName="侦查",
        difficulty="regular",
    )
    character = {"xlsx_data": {"skills": {"侦查": 60}, "luck": 10}}

    result = await executor.execute(intent, compiled, character, inventory=[], scenario_assets={})

    assert result.is_success is True
    assert result.metadata["luck_spent"] == 5
    assert result.mutations == [
        {"op": "replace", "path": "/character/luck", "value": 5}
    ]


@pytest.mark.asyncio
async def test_rule_executor_keeps_solo_move_out_of_character_mutations():
    executor = RuleExecutor()
    intent = PlayerIntent(
        intent_type="move",
        declared_intent="我转到条目 2",
        params={"fromNodeId": "1", "targetNodeId": "2", "solo_adventure": True},
    )
    compiled = MechanicCompileResult(triggeredMechanic="auto_success")

    result = await executor.execute(intent, compiled, {"xlsx_data": {}}, [], {})

    assert result.is_success is True
    assert result.metadata["solo_adventure"] is True
    assert result.mutations == []


@pytest.mark.asyncio
async def test_rule_executor_preserves_solo_move_target_when_compiler_returns_move():
    executor = RuleExecutor()
    intent = PlayerIntent(
        intent_type="move",
        declared_intent="我转到条目 2",
        params={"fromNodeId": "1", "targetNodeId": "2", "solo_adventure": True},
    )
    compiled = MechanicCompileResult(triggeredMechanic="move")

    result = await executor.execute(intent, compiled, {"xlsx_data": {}}, [], {})

    assert result.is_success is True
    assert result.metadata["solo_adventure"] is True
    assert result.mutations == []


@pytest.mark.asyncio
async def test_rule_executor_preserves_confirmed_pushed_roll_and_bonus_dice(monkeypatch):
    rolls = iter([8, 0, 9, 3, 0, 2])
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(rolls),
    )
    executor = RuleExecutor()
    intent = PlayerIntent(
        intent_type="skill_check",
        declared_intent="我确认孤注一掷",
        params={"skillName": "侦查", "pushed": True, "bonusDice": 1},
    )
    compiled = MechanicCompileResult(
        triggeredMechanic="skill_check",
        skillName="侦查",
        difficulty="regular",
    )
    character = {"xlsx_data": {"skills": {"侦查": 60}, "luck": 0}}

    result = await executor.execute(intent, compiled, character, inventory=[], scenario_assets={})

    assert result.metadata["pushed"] is True
    assert result.metadata["bonus_dice"] == 1
    assert len(result.reveal_steps) == 2


@pytest.mark.asyncio
async def test_rule_executor_applies_hidden_modifier_without_exposing_it_as_player_input(
    monkeypatch,
):
    rolls = iter([5, 0, 9])
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(rolls),
    )
    executor = RuleExecutor()
    intent = PlayerIntent(
        intent_type="skill_check",
        declared_intent="我侦查走廊",
        params={"skillName": "侦查"},
    )
    compiled = MechanicCompileResult(
        triggeredMechanic="skill_check",
        skillName="侦查",
        difficulty="regular",
        consequence={
            "hiddenModifiers": [
                {
                    "source": "走廊里的不可见生物",
                    "effect": "1 penalty die",
                    "bonusDice": -1,
                }
            ]
        },
    )
    character = {"xlsx_data": {"skills": {"侦查": 60}, "luck": 0}}

    result = await executor.execute(intent, compiled, character, inventory=[], scenario_assets={})

    assert result.is_success is False
    assert result.metadata["bonus_dice"] == -1
    assert result.metadata["hidden_modifiers"] == [
        {
            "source": "走廊里的不可见生物",
            "effect": "1 penalty die",
            "bonus_dice": -1,
        }
    ]


@pytest.mark.asyncio
async def test_non_blocking_sanity_trigger_does_not_cancel_the_parent_move():
    executor = RuleExecutor()
    intent = PlayerIntent(
        intent_type="move",
        declared_intent="enter the cistern",
        params={
            "fromNodeId": "control-room",
            "targetNodeId": "cistern",
            "generic_scene_progression": {
                "from_scene_id": "control-room",
                "target_scene_id": "cistern",
            },
        },
    )
    compiled = MechanicCompileResult(triggeredMechanic="move")
    character = {
        "room_id": "room-glass",
        "character_id": "char-glass",
        "xlsx_data": {"skills": {}, "hp": 10, "san": 0, "luck": 40},
    }
    assets = {
        "triggers": [
            {
                "condition": {"$action": "move", "targetNodeId": "cistern"},
                "mechanics": [
                    {
                        "type": "sanity_check",
                        "blocking": False,
                        "params": {"success_loss": 0, "failure_loss": "1d4"},
                    }
                ],
            }
        ]
    }

    result = await executor.execute(
        intent,
        compiled,
        character,
        inventory=[],
        scenario_assets=assets,
    )

    assert result.is_success is True
    assert result.mechanic == "move"
    assert result.metadata["reason_code"] == "permanent_insanity"


@pytest.mark.asyncio
async def test_rule_executor_runs_matching_scene_triggers_and_cascading_changes():
    random.seed(5)
    executor = RuleExecutor()
    intent = PlayerIntent(
        intent_type="use_item",
        declared_intent="阅读邪书",
        params={"itemId": "book_necronomicon"},
    )
    compiled = MechanicCompileResult(triggeredMechanic="auto_success")
    character = {"xlsx_data": {"skills": {}, "hp": 10, "san": 1, "luck": 40}}
    assets = {
        "scenes": [
            {
                "nodeId": "library",
                "triggers": [
                    {
                        "condition": {"$action": "use_item", "itemId": "book_necronomicon"},
                        "mechanics": [
                            {
                                "type": "sanity_check",
                                "params": {"success_loss": "0", "failure_loss": "1d3"},
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result = await executor.execute(intent, compiled, character, inventory=[], scenario_assets=assets)

    assert result.mechanic == "sanity_check"
    assert result.metadata["new_san"] == 0
    assert {"op": "replace", "path": "/character/san", "value": 0} in result.mutations
    assert any("疯狂" in change for change in result.cascading_state_changes)
