import json

import pytest

from src.server.combat_round_planner import build_combat_round_plan
from src.server.engine.skill_check import _determine_success
from src.server.engine.rule_executor import RuleExecutor
from src.server.engine.solo_combat_reactions import _wins_opposed_check
from src.server.models import MechanicCompileResult, PlayerIntent
from src.server.rules.base import GameState
from src.server.rules.coc_handlers import (
    CocCombatHandler,
    CocHealingHandler,
    CocLuckCheckHandler,
    CocOpposedCheckHandler,
    CocSanityAdvanceHandler,
    CocSanityCheckHandler,
    CocSkillCheckHandler,
    CocStatusHandler,
)
from src.server.rules.encounter_handlers import (
    ChaseEscapeHandler,
    ChasePursueHandler,
    CombatAttackHandler,
)


def _skill_rolls(monkeypatch, values):
    values = iter(values)
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(values),
    )


def _san_rolls(monkeypatch, values):
    values = iter(values)
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.secure_randint",
        lambda _low, _high, **_kwargs: next(values),
    )


def _sanity_state(result):
    return next(
        mutation["value"]
        for mutation in result.mutations
        if mutation["path"] == "/character/temp_modifier/coc7_sanity"
    )


def test_fumble_threshold_uses_required_target_not_unmodified_skill():
    assert _determine_success(96, 27, 55) == "fumble"


@pytest.mark.asyncio
async def test_failed_pushed_roll_is_resolved_by_engine_without_human_host(monkeypatch):
    _skill_rolls(monkeypatch, [8, 0, 9, 0])

    result = await CocSkillCheckHandler().execute(
        GameState(character={"luck": 0}),
        {
            "skillName": "侦查",
            "skillValue": 60,
            "pushed": True,
            "pushedFailureConsequence": {
                "code": "glass_alarm_escalates",
                "publicText": "警报升级，倒计时缩短。",
            },
        },
    )

    assert result.is_success is False
    assert result.metadata["pending_consequence"] is None
    assert result.metadata["pushed_consequence"] == {
        "status": "resolved_by_engine",
        "reason": "pushed_check_failed",
        "code": "glass_alarm_escalates",
        "public_text": "警报升级，倒计时缩短。",
    }


@pytest.mark.asyncio
async def test_opposed_check_rerolls_exact_tie_until_there_is_a_winner(monkeypatch):
    _skill_rolls(monkeypatch, [2, 0, 2, 0, 3, 0, 7, 0])
    state = GameState(
        character={"skills": {"侦查": 60}},
        scene={"opponent": {"name": "守卫", "skills": {"潜行": 60}}},
    )

    result = await CocOpposedCheckHandler().execute(
        state,
        {"skillName": "侦查", "opponentSkillName": "潜行"},
    )

    assert result.is_success is True
    assert result.metadata["winner"] == "actor"
    assert result.metadata["reroll_count"] == 1
    assert len(result.metadata["rounds"]) == 2


@pytest.mark.asyncio
async def test_opposed_check_uses_higher_skill_when_both_rolls_fail(monkeypatch):
    _skill_rolls(monkeypatch, [8, 0, 9, 0])
    state = GameState(
        character={"skills": {"侦查": 60}},
        scene={"opponent": {"skills": {"潜行": 50}}},
    )

    result = await CocOpposedCheckHandler().execute(
        state,
        {"skillName": "侦查", "opponentSkillName": "潜行"},
    )

    assert result.is_success is True
    assert result.metadata["winner"] == "actor"


@pytest.mark.asyncio
async def test_opposed_check_without_authoritative_opponent_is_rejected_not_sent_to_host():
    result = await CocOpposedCheckHandler().execute(
        GameState(character={"skills": {"侦查": 60}}),
        {"skillName": "侦查", "opponentSkillName": "潜行"},
    )

    assert result.is_success is False
    assert result.metadata["status"] == "rejected"
    assert result.metadata["reason_code"] == "authoritative_opponent_required"


@pytest.mark.asyncio
async def test_sanity_fumble_applies_maximum_failure_loss(monkeypatch):
    _san_rolls(monkeypatch, [100, 80])

    result = await CocSanityCheckHandler().execute(
        GameState(character={"san": 50, "attributes": {"int": 40}}),
        {
            "success_loss": "0",
            "failure_loss": "1d6+1",
            "sourceId": "glass-collapse",
            "inGameDay": "1926-11-03",
        },
    )

    assert result.metadata["sanity_fumble"] is True
    assert result.metadata["san_loss"] == 7
    assert result.metadata["new_san"] == 43


@pytest.mark.asyncio
async def test_sanity_below_fifty_fumbles_on_ninety_six_and_applies_maximum_loss(
    monkeypatch,
):
    _san_rolls(monkeypatch, [96, 100])

    result = await CocSanityCheckHandler().execute(
        GameState(character={"san": 40, "attributes": {"int": 0}}),
        {
            "success_loss": "0",
            "failure_loss": "1d6+1",
            "sourceId": "glass-collapse",
            "inGameDay": "1926-11-03",
        },
    )

    assert result.metadata["sanity_fumble"] is True
    assert result.metadata["san_loss"] == 7
    assert result.metadata["new_san"] == 33


@pytest.mark.asyncio
async def test_single_loss_of_five_with_successful_int_check_causes_temporary_insanity(
    monkeypatch,
):
    _san_rolls(monkeypatch, [80, 5, 20, 4, 7])

    result = await CocSanityCheckHandler().execute(
        GameState(character={"san": 60, "attributes": {"int": 70}}),
        {
            "success_loss": "0",
            "failure_loss": "1d5",
            "sourceId": "glass-collapse",
            "inGameDay": "1926-11-03",
            "companionsPresent": True,
            "manifestation": {"mode": "immediate", "symptomId": 8},
        },
    )

    state = _sanity_state(result)
    assert state["insanity_type"] == "temporary"
    assert state["phase"] == "bout"
    assert state["bout"]["mode"] == "immediate"
    assert state["bout"]["symptom_id"] == 8
    assert state["bout"]["duration"] == {"value": 4, "unit": "rounds"}
    assert state["underlying_duration"] == {"value": 7, "unit": "hours"}
    assert {
        "op": "add",
        "path": "/character/status_tag",
        "value": "temporary_insanity",
    } in result.mutations


@pytest.mark.asyncio
async def test_one_fifth_daily_sanity_loss_causes_indefinite_insanity(monkeypatch):
    _san_rolls(monkeypatch, [80, 4])
    first = await CocSanityCheckHandler().execute(
        GameState(character={"san": 50, "attributes": {"int": 20}}),
        {
            "success_loss": "0",
            "failure_loss": "1d4",
            "sourceId": "first-shock",
            "inGameDay": "1926-11-03",
        },
    )

    _san_rolls(monkeypatch, [80, 6, 3, 5])
    second = await CocSanityCheckHandler().execute(
        GameState(
            character={
                "san": 46,
                "attributes": {"int": 20},
                "temp_modifiers": {"coc7_sanity": _sanity_state(first)},
            }
        ),
        {
            "success_loss": "0",
            "failure_loss": "1d6",
            "sourceId": "second-shock",
            "inGameDay": "1926-11-03",
            "companionsPresent": True,
        },
    )

    state = _sanity_state(second)
    assert state["day_start_san"] == 50
    assert state["day_loss"] == 10
    assert state["insanity_type"] == "indefinite"
    assert state["phase"] == "bout"


@pytest.mark.asyncio
async def test_underlying_insanity_retriggers_a_bout_after_any_sanity_loss(monkeypatch):
    previous = {
        "schema_version": 1,
        "day_key": "1926-11-03",
        "day_start_san": 60,
        "day_loss": 5,
        "insanity_type": "temporary",
        "phase": "underlying",
        "underlying_duration": {"value": 6, "unit": "hours"},
    }
    _san_rolls(monkeypatch, [80, 1, 2])

    result = await CocSanityCheckHandler().execute(
        GameState(
            character={
                "san": 55,
                "attributes": {"int": 70},
                "temp_modifiers": {"coc7_sanity": previous},
            }
        ),
        {
            "success_loss": "0",
            "failure_loss": "1",
            "sourceId": "related-trigger",
            "inGameDay": "1926-11-03",
            "companionsPresent": True,
        },
    )

    state = _sanity_state(result)
    assert state["insanity_type"] == "temporary"
    assert state["phase"] == "bout"
    assert state["retriggered"] is True
    assert "int_check" not in result.metadata


@pytest.mark.asyncio
async def test_sanity_zero_transfers_control_to_ai_keeper_and_marks_archive(monkeypatch):
    _san_rolls(monkeypatch, [80, 1, 3])

    result = await CocSanityCheckHandler().execute(
        GameState(character={"san": 1, "attributes": {"int": 70}}),
        {
            "success_loss": "0",
            "failure_loss": "1",
            "sourceId": "glass-collapse",
            "inGameDay": "1926-11-03",
        },
    )

    state = _sanity_state(result)
    assert state["insanity_type"] == "permanent"
    assert state["phase"] == "permanent"
    assert state["control"] == "ai_keeper"
    assert state["archive_required"] is True
    assert {
        "op": "add",
        "path": "/character/status_tag",
        "value": "permanent_insanity",
    } in result.mutations


@pytest.mark.asyncio
async def test_high_risk_ai_manifestation_is_replaced_by_engine_safe_fallback(monkeypatch):
    _san_rolls(monkeypatch, [80, 5, 20, 4, 7])

    result = await CocSanityCheckHandler().execute(
        GameState(character={"san": 60, "attributes": {"int": 70}}),
        {
            "success_loss": "0",
            "failure_loss": "1d5",
            "sourceId": "glass-collapse",
            "inGameDay": "1926-11-03",
            "companionsPresent": True,
            "manifestation": {
                "mode": "immediate",
                "symptomId": 3,
                "rawText": "attack another investigator",
            },
        },
    )

    bout = _sanity_state(result)["bout"]
    assert bout["symptom_id"] == 8
    assert bout["selection_source"] == "engine_safe_fallback"
    assert bout["retry_count"] == 1
    assert "rawText" not in str(result.metadata)
    assert "attack another investigator" not in str(result.metadata)


@pytest.mark.asyncio
async def test_bout_completion_enters_underlying_insanity_and_background_change_waits_for_player():
    current = {
        "schema_version": 1,
        "day_key": "1926-11-03",
        "day_start_san": 60,
        "day_loss": 5,
        "insanity_type": "temporary",
        "phase": "bout",
        "bout": {
            "mode": "immediate",
            "symptom_id": 8,
            "duration": {"value": 4, "unit": "rounds"},
        },
        "underlying_duration": {"value": 7, "unit": "hours"},
    }

    result = await CocSanityAdvanceHandler().execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {"event": "bout_elapsed"},
    )

    state = _sanity_state(result)
    assert state["phase"] == "underlying"
    assert state["background_change_pending_player_confirmation"] is True


@pytest.mark.asyncio
async def test_damage_marks_major_wound_and_dying_from_single_hit(monkeypatch):
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.roll_dice",
        lambda _notation: (7, [7], 0),
    )

    result = await CocCombatHandler().execute(
        GameState(character={"hp": 6, "max_hp": 12, "status_tags": []}),
        {"damage": "1d8"},
    )

    assert result.metadata["major_wound"] is True
    assert result.metadata["new_hp"] == 0
    assert {
        "op": "add",
        "path": "/character/status_tag",
        "value": "major_wound",
    } in result.mutations
    assert {
        "op": "add",
        "path": "/character/status_tag",
        "value": "dying",
    } in result.mutations


@pytest.mark.asyncio
async def test_first_aid_heals_exactly_one_and_medicine_heals_one_d3(monkeypatch):
    handler = CocHealingHandler()
    first_aid = await handler.execute(
        GameState(character={"hp": 4, "max_hp": 10, "status_tags": []}),
        {"method": "first_aid", "withinHour": True, "amount": "9d100"},
    )
    monkeypatch.setattr(
        "src.server.rules.coc_handlers.roll_dice",
        lambda _notation: (3, [3], 0),
    )
    medicine = await handler.execute(
        GameState(character={"hp": 4, "max_hp": 10, "status_tags": []}),
        {"method": "medicine", "amount": "9d100"},
    )

    assert first_aid.metadata["healed"] == 1
    assert medicine.metadata["healed"] == 3
    assert medicine.metadata["healing_dice"] == "1d3"


@pytest.mark.asyncio
async def test_group_luck_uses_lowest_luck_present(monkeypatch):
    _san_rolls(monkeypatch, [35])
    result = await CocLuckCheckHandler().execute(
        GameState(
            character={"luck": 80},
            scene={"_party_luck_values": [80, 40, 30]},
        ),
        {"groupLuck": True},
    )

    assert result.metadata["luck"] == 30
    assert result.metadata["group_luck"] is True
    assert result.is_success is False


@pytest.mark.asyncio
async def test_unknown_status_is_rejected_without_human_host():
    result = await CocStatusHandler().execute(
        GameState(character={}),
        {"status": "invented_by_ai", "operation": "add"},
    )

    assert result.is_success is False
    assert result.metadata["status"] == "rejected"


def test_combat_round_keeps_dex_order_even_when_action_declares_dependency():
    plan = build_combat_round_plan(
        turn_id="turn",
        encounter_id="encounter",
        round_number=1,
        actions=[
            {
                "action_id": "fast",
                "character_id": "fast",
                "intent_type": "combat_action",
                "declared_intent": "I wait for the door and fire.",
                "params": {"depends_on_action_ids": ["slow"]},
                "dex": 80,
            },
            {
                "action_id": "slow",
                "character_id": "slow",
                "intent_type": "combat_action",
                "declared_intent": "I open the door.",
                "dex": 40,
            },
        ],
    )

    assert [step["action_id"] for step in plan["steps"]] == ["fast", "slow"]


def test_ready_firearm_adds_fifty_to_effective_dex():
    plan = build_combat_round_plan(
        turn_id="turn",
        encounter_id="encounter",
        round_number=1,
        actions=[
            {
                "action_id": "ready-shot",
                "character_id": "shooter",
                "intent_type": "combat_action",
                "declared_intent": "I fire the pistol I already have trained on the door.",
                "params": {
                    "actionKind": "attack",
                    "weaponType": "firearm",
                    "readyFirearm": True,
                },
                "dex": 40,
            },
            {
                "action_id": "quick-punch",
                "character_id": "brawler",
                "intent_type": "combat_action",
                "declared_intent": "I punch.",
                "dex": 80,
            },
        ],
    )

    assert [step["action_id"] for step in plan["steps"]] == [
        "ready-shot",
        "quick-punch",
    ]
    assert plan["steps"][0]["effective_dex"] == 90


def test_combat_round_keeps_one_significant_declared_action():
    plan = build_combat_round_plan(
        turn_id="turn",
        encounter_id="encounter",
        round_number=1,
        actions=[
            {
                "action_id": "combo",
                "character_id": "investigator",
                "intent_type": "combat_action",
                "declared_intent": "我开枪、掩护安娜撤退、再冲去开门",
                "dex": 60,
            },
        ],
    )

    assert plan["steps"][0]["segments"] == ["我开枪"]


def test_melee_tie_favors_dodge_but_not_fight_back():
    equal = {"is_success": True, "success_level": "regular"}

    assert _wins_opposed_check(equal, equal, reaction="dodge") is True
    assert _wins_opposed_check(equal, equal, reaction="counterattack") is False


def test_generic_enemy_melee_attack_waits_for_player_reaction_and_resolves_fight_back(
    test_db,
    monkeypatch,
):
    from src.server.encounter_persistence import (
        add_participant,
        create_encounter,
        get_participant,
        update_encounter_round,
    )
    from src.server.engine import solo_combat_reactions
    from src.server.engine.state_service import StateService

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('generic-reaction-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('generic-defender', 'generic-reaction-room', 'Player', 'token', %s)",
        (
            json.dumps(
                {
                    "hp": 10,
                    "max_hp": 10,
                    "skills": {"格斗（斗殴）": 60, "闪避": 40},
                },
                ensure_ascii=False,
            ),
        ),
    )
    StateService(test_db).initialize_character_state(
        "generic-defender",
        "generic-reaction-room",
    )
    create_encounter(
        test_db,
        "generic-reaction-encounter",
        "generic-reaction-room",
        status="active",
    )
    update_encounter_round(test_db, "generic-reaction-encounter", 1)
    add_participant(
        test_db,
        "generic-reaction-encounter",
        "generic-defender",
        side="player",
        hp=10,
        hp_max=10,
        main_skill="格斗（斗殴）",
        damage_expression="1d4",
    )
    add_participant(
        test_db,
        "generic-reaction-encounter",
        "npc:cultist",
        side="enemy",
        hp=8,
        hp_max=8,
        main_skill="格斗",
        weapon_name="短棍",
        damage_expression="1d6",
        notes="格斗 45%",
        display_name="蒙面袭击者",
        public_visibility="visible",
    )

    queued = solo_combat_reactions.queue_enemy_reaction(
        test_db,
        room_id="generic-reaction-room",
        encounter_id="generic-reaction-encounter",
        character_id="generic-defender",
        source_action_id="generic-source-action",
    )

    assert queued is not None
    assert solo_combat_reactions.reaction_projection(queued)["attackerName"] == "蒙面袭击者"
    checks = iter(
        [
            {
                "roll": 80,
                "skill_value": 45,
                "is_success": False,
                "success_level": "failure",
            },
            {
                "roll": 20,
                "skill_value": 60,
                "is_success": True,
                "success_level": "regular",
            },
        ]
    )
    monkeypatch.setattr(
        solo_combat_reactions,
        "roll_skill_check",
        lambda _skill: next(checks),
    )
    monkeypatch.setattr(
        solo_combat_reactions,
        "roll_dice",
        lambda _dice: (3, [3], 0),
    )

    resolved = solo_combat_reactions.resolve_pending_reaction(
        test_db,
        reaction_id=queued["reaction_id"],
        character_id="generic-defender",
        choice="counterattack",
    )

    assert resolved["result"]["damageToPlayer"] == 0
    assert resolved["result"]["damageToAttacker"] == 3
    assert resolved["next_reaction"] is None
    assert get_participant(
        test_db,
        "generic-reaction-encounter",
        "npc:cultist",
    )["hp"] == 5


@pytest.mark.asyncio
async def test_chase_movement_spends_one_action_without_unrelated_skill_roll():
    context = {
        "participant": {
            "character_id": "actor",
            "mov": 8,
            "distance_band": "medium",
        },
        "allParticipants": [{"character_id": "actor"}],
        "encounter": {"encounter_id": "chase-1", "type": "chase", "status": "active"},
    }
    state = GameState(character={"skills": {"运动": 0}})

    pursue = await ChasePursueHandler().execute(
        state,
        {"encounter_context": context},
    )
    escape = await ChaseEscapeHandler().execute(
        state,
        {"encounter_context": context},
    )

    assert pursue.is_success is True
    assert pursue.metadata["movement_action_cost"] == 1
    assert pursue.mutations[0]["value"] == -1
    assert escape.is_success is True
    assert escape.mutations[0]["value"] == 1


@pytest.mark.asyncio
async def test_non_impaling_extreme_attack_deals_maximum_damage(monkeypatch):
    _skill_rolls(monkeypatch, [1, 0])
    monkeypatch.setattr(
        "src.server.rules.encounter_handlers._parse_dice",
        lambda _notation: 2,
    )
    context = {
        "participant": {
            "character_id": "actor",
            "main_skill": "斗殴",
            "damage_expression": "1d6",
        },
        "allParticipants": [
            {"character_id": "actor"},
            {"character_id": "target", "notes": ""},
        ],
        "encounter": {"encounter_id": "combat-1", "type": "combat", "status": "active"},
    }

    result = await CombatAttackHandler().execute(
        GameState(character={"skills": {"斗殴": 60}}),
        {"targetId": "target", "encounter_context": context},
    )

    assert result.metadata["success_level"] == "extreme"
    assert result.metadata["raw_damage"] == 6


@pytest.mark.asyncio
async def test_engine_sanity_handler_can_write_room_scoped_state_but_ai_patch_cannot():
    executor = RuleExecutor()
    current = {
        "schema_version": 1,
        "insanity_type": "temporary",
        "phase": "bout",
        "bout": {"duration": {"value": 1, "unit": "rounds"}},
        "underlying_duration": {"value": 4, "unit": "hours"},
    }
    result = await executor.execute(
        PlayerIntent(
            action_id="advance-sanity",
            intent_type="dialogue",
            declared_intent="疯狂发作时长结束",
        ),
        MechanicCompileResult(triggeredMechanic="dialogue"),
        {
            "character_id": "investigator",
            "room_id": "room",
            "xlsx_data": {"temp_modifiers": {"coc7_sanity": current}},
        },
        [],
        {
            "triggers": [
                {
                    "condition": {"$action": "dialogue"},
                    "mechanics": [
                        {"type": "sanity_advance", "params": {"event": "bout_elapsed"}}
                    ],
                }
            ]
        },
    )

    assert result.is_success is True
    assert result.metadata["sanity_phase"] == "underlying"
    assert result.metadata.get("pending_rule_suggestions") is None
    assert executor._is_safe_patch(
        {
            "op": "replace",
            "path": "/character/temp_modifier/coc7_sanity",
            "value": {},
        }
    ) is False


@pytest.mark.asyncio
async def test_unknown_rule_is_rejected_without_human_host_confirmation():
    result = await RuleExecutor().execute(
        PlayerIntent(
            action_id="unknown-rule",
            intent_type="dialogue",
            declared_intent="进入房间",
        ),
        MechanicCompileResult(triggeredMechanic="dialogue"),
        {"character_id": "investigator", "room_id": "room", "xlsx_data": {}},
        [],
        {
            "triggers": [
                {
                    "condition": {"$action": "dialogue"},
                    "mechanics": [{"type": "not_a_coc7_rule"}],
                }
            ]
        },
    )

    assert result.is_success is False
    assert result.metadata["pending_rule_suggestions"][0]["status"] == "rejected"
