import random
import pytest

from src.server.rules.base import GameState, RuleResult
from src.server.rules.coc_handlers import (
    CocCombatHandler,
    CocLuckCheckHandler,
    CocSanityCheckHandler,
    CocSkillCheckHandler,
    parse_dice,
)
from src.server.rules.registry import get_handler, register_rule
from src.server.rules.triggers import evaluate_triggers


def make_state(san=50, hp=10, luck=50):
    return GameState(character={"san": san, "hp": hp, "luck": luck})


# --- parse_dice ---

def test_parse_dice_1d3():
    random.seed(42)
    result = parse_dice("1d3")
    assert 1 <= result <= 3


def test_parse_dice_2d6():
    random.seed(42)
    result = parse_dice("2d6")
    assert 2 <= result <= 12


def test_parse_dice_1d10():
    random.seed(42)
    result = parse_dice("1d10")
    assert 1 <= result <= 10


def test_parse_dice_invalid():
    with pytest.raises(ValueError):
        parse_dice("invalid")


# --- CocSkillCheckHandler ---

@pytest.mark.asyncio
async def test_skill_check_critical_success():
    handler = CocSkillCheckHandler()
    random.seed(139)  # roll=1
    result = await handler.execute(make_state(), {"skillName": "侦查", "skillValue": 60})
    assert result.is_success is True
    assert result.metadata["success_level"] == "critical_success"
    assert result.metadata["roll"] == 1


@pytest.mark.asyncio
async def test_skill_check_fumble():
    handler = CocSkillCheckHandler()
    random.seed(23)  # roll=100
    result = await handler.execute(make_state(), {"skillName": "侦查", "skillValue": 60})
    assert result.is_success is False
    assert result.metadata["success_level"] == "fumble"


@pytest.mark.asyncio
async def test_skill_check_success():
    handler = CocSkillCheckHandler()
    random.seed(0)  # roll=50, under 60
    result = await handler.execute(make_state(), {"skillName": "侦查", "skillValue": 60})
    assert result.is_success is True
    assert result.metadata["success_level"] == "success"


@pytest.mark.asyncio
async def test_skill_check_failure():
    handler = CocSkillCheckHandler()
    random.seed(5)  # roll=80, over 60
    result = await handler.execute(make_state(), {"skillName": "侦查", "skillValue": 60})
    assert result.is_success is False
    assert result.metadata["success_level"] == "failure"


@pytest.mark.asyncio
async def test_skill_check_hard_difficulty():
    handler = CocSkillCheckHandler()
    random.seed(1)  # roll=18, skill=60 hard target=30 -> success
    result = await handler.execute(
        make_state(), {"skillName": "侦查", "skillValue": 60, "difficulty": "hard"}
    )
    assert result.metadata["difficulty"] == "hard"
    assert result.metadata["target"] == 30


@pytest.mark.asyncio
async def test_skill_check_fumble_low_skill():
    handler = CocSkillCheckHandler()
    random.seed(26)  # roll=96, skill=40 (<50) -> fumble
    result = await handler.execute(make_state(), {"skillName": "闪避", "skillValue": 40})
    assert result.is_success is False
    assert result.metadata["success_level"] == "fumble"


@pytest.mark.asyncio
async def test_skill_check_reveal_steps():
    handler = CocSkillCheckHandler()
    random.seed(1)
    result = await handler.execute(make_state(), {"skillName": "侦查", "skillValue": 60})
    assert len(result.reveal_steps) == 1
    assert result.reveal_steps[0]["kind"] == "roll"


# --- CocSanityCheckHandler ---

@pytest.mark.asyncio
async def test_sanity_check_success_loss():
    handler = CocSanityCheckHandler()
    random.seed(0)  # roll=50, san=50 -> success
    result = await handler.execute(
        make_state(san=50), {"success_loss": "1d3", "failure_loss": "1d10"}
    )
    assert result.is_success is True
    assert result.metadata["san_loss"] >= 1
    assert result.metadata["new_san"] < 50


@pytest.mark.asyncio
async def test_sanity_check_failure_loss():
    handler = CocSanityCheckHandler()
    random.seed(5)  # roll=80, san=50 -> failure
    result = await handler.execute(
        make_state(san=50), {"success_loss": "1d3", "failure_loss": "1d10"}
    )
    assert result.is_success is False
    assert result.metadata["san_loss"] >= 1


@pytest.mark.asyncio
async def test_sanity_check_go_insane():
    handler = CocSanityCheckHandler()
    random.seed(5)  # roll=80, san=1 -> failure, loss >=1 -> san=0
    result = await handler.execute(
        make_state(san=1), {"success_loss": "0", "failure_loss": "1d3"}
    )
    assert result.metadata["new_san"] == 0
    assert "疯狂" in result.cascading_state_changes


@pytest.mark.asyncio
async def test_sanity_check_mutation():
    handler = CocSanityCheckHandler()
    random.seed(0)
    result = await handler.execute(
        make_state(san=50), {"success_loss": "1d3", "failure_loss": "1d10"}
    )
    assert any(m["path"] == "/character/san" for m in result.mutations)


# --- CocCombatHandler ---

@pytest.mark.asyncio
async def test_combat_damage():
    handler = CocCombatHandler()
    random.seed(5)
    result = await handler.execute(make_state(hp=10), {"damage": "1d6"})
    assert result.is_success is True
    assert result.metadata["new_hp"] < 10


@pytest.mark.asyncio
async def test_combat_hp_zero():
    handler = CocCombatHandler()
    random.seed(5)
    result = await handler.execute(make_state(hp=1), {"damage": "1d6"})
    assert result.metadata["new_hp"] == 0
    assert "昏迷/濒死" in result.cascading_state_changes


@pytest.mark.asyncio
async def test_combat_mutation():
    handler = CocCombatHandler()
    random.seed(5)
    result = await handler.execute(make_state(hp=10), {"damage": "1d6"})
    assert any(m["path"] == "/character/hp" for m in result.mutations)


# --- CocLuckCheckHandler ---

@pytest.mark.asyncio
async def test_luck_check_pass():
    handler = CocLuckCheckHandler()
    random.seed(0)  # roll=50, luck=50 -> pass
    result = await handler.execute(make_state(luck=50), {})
    assert result.is_success is True


@pytest.mark.asyncio
async def test_luck_check_fail():
    handler = CocLuckCheckHandler()
    random.seed(5)  # roll=80, luck=50 -> fail
    result = await handler.execute(make_state(luck=50), {})
    assert result.is_success is False


# --- Registry ---

def test_registry_get_handler():
    handler = get_handler("skill_check")
    assert handler is not None
    assert isinstance(handler, CocSkillCheckHandler)


def test_registry_get_unknown():
    handler = get_handler("unknown_rule")
    assert handler is None


def test_register_rule():
    from src.server.rules.base import BaseRuleHandler

    class DummyHandler(BaseRuleHandler):
        pass

    register_rule("dummy", DummyHandler())
    assert get_handler("dummy") is not None


# --- Triggers ---

def test_triggers_match_action():
    triggers = [
        {
            "condition": {"$action": "investigate"},
            "mechanics": [{"type": "skill_check", "skillName": "侦查"}],
        }
    ]
    result = evaluate_triggers(triggers, "investigate", {})
    assert len(result) == 1
    assert result[0]["type"] == "skill_check"


def test_triggers_no_match():
    triggers = [
        {
            "condition": {"$action": "investigate"},
            "mechanics": [{"type": "skill_check"}],
        }
    ]
    result = evaluate_triggers(triggers, "combat", {})
    assert len(result) == 0


def test_triggers_match_item():
    triggers = [
        {
            "condition": {"$action": "use", "itemId": "key_01"},
            "mechanics": [{"type": "unlock_door"}],
        }
    ]
    result = evaluate_triggers(triggers, "use", {"itemId": "key_01"})
    assert len(result) == 1


def test_triggers_no_match_item():
    triggers = [
        {
            "condition": {"$action": "use", "itemId": "key_01"},
            "mechanics": [{"type": "unlock_door"}],
        }
    ]
    result = evaluate_triggers(triggers, "use", {"itemId": "key_02"})
    assert len(result) == 0


def test_triggers_multiple_mechanics():
    triggers = [
        {
            "condition": {"$action": "enter"},
            "mechanics": [
                {"type": "sanity_check", "success_loss": "1d3", "failure_loss": "1d6"},
                {"type": "spawn_entity", "entityId": "cultist_01"},
            ],
        }
    ]
    result = evaluate_triggers(triggers, "enter", {})
    assert len(result) == 2
