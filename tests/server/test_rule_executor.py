import random

import pytest

from src.server.models import MechanicCompileResult, PlayerIntent
from src.server.rule_executor import RuleExecutor


@pytest.mark.asyncio
async def test_rule_executor_runs_compiled_skill_check_with_character_skill():
    random.seed(0)
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
    assert "疯狂" in result.cascading_state_changes
