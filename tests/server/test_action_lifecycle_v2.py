import json

import pytest
from pydantic import ValidationError

from src.server.engine.action_lifecycle import transition_action
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.roll_receipt import verify_roll_receipt
from src.server.engine.state_service import StateService
from src.server.models import (
    ActionDraftStepDTO,
    DirectorActionStepDTO,
    MechanicCompileResult,
    PlayerIntent,
    ResolutionResult,
)
from src.server.player.action_service import ActionDraftError, choose_composite_action_continuation


def _verified_params(**extra):
    payload = {
        "director_plan": {
            "context_version": 0,
            "preconditions": [],
            "permissions": [],
            "state_patch": [],
            "state_patch_authority": "advisory_only",
        }
    }
    payload.update(extra)
    return payload


@pytest.mark.parametrize("step_type", (ActionDraftStepDTO, DirectorActionStepDTO))
def test_composite_step_contract_rejects_mid_round_choice_policy(step_type):
    with pytest.raises(ValidationError):
        step_type(
            step_id="step-2",
            summary="进入房间",
            declared_intent="进入房间",
            intent_type="move",
            on_previous_failure="ask",
        )


def _insert_action(test_db, *, action_id="action-v2", status="queued"):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) VALUES ('room-v2', 'owner-token')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-v2', 'room-v2', '玩家', 'player-token')"
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, draft_id, intent_type, "
        "declared_intent, params, status) VALUES (%s, 'room-v2', 'char-v2', 'draft-v2', "
        "'dialogue', '观察房间', %s, %s)",
        (action_id, json.dumps(_verified_params(), ensure_ascii=False), status),
    )


def test_director_plan_accepts_the_same_resolving_turn_snapshot(test_db):
    _insert_action(test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active', state_version = 1 WHERE room_id = 'room-v2'"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, base_state_version) "
        "VALUES ('turn-v2', 'room-v2', 1, 'resolving', 0)"
    )
    test_db.execute(
        "UPDATE actions SET turn_id = 'turn-v2' WHERE action_id = 'action-v2'"
    )

    action = dict(
        test_db.execute("SELECT * FROM actions WHERE action_id = 'action-v2'").fetchone()
    )
    room = dict(test_db.execute("SELECT * FROM rooms WHERE room_id = 'room-v2'").fetchone())
    intent = PlayerIntent(
        action_id="action-v2",
        intent_type="dialogue",
        declared_intent="观察房间",
        params=_verified_params(),
    )
    pipeline = ResolutionPipeline(test_db, _DialogueCompiler())

    assert pipeline._validate_director_plan(action, intent, room) is None


def test_shared_turn_scene_arrival_is_not_rejected_as_stale(test_db):
    _insert_action(test_db)
    citation = {"source_ref": "module#edge", "page_number": 1}
    analysis = {
        "semantic_progression": {
            "validated": True,
            "fromNodeId": "gallery",
            "targetNodeId": "orchid-hall",
            "ruleCitation": citation,
        },
        "director_plan": {
            "context_version": 0,
            "preconditions": [],
            "permissions": [],
            "state_patch": [],
            "state_patch_authority": "advisory_only",
        },
    }
    params = {
        "fromNodeId": "gallery",
        "targetNodeId": "orchid-hall",
        "analysis": analysis,
        "director_plan": analysis["director_plan"],
    }
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title) VALUES ('scenario-shared-turn', 'Shared turn')"
    )
    test_db.execute(
        "INSERT INTO scenario_versions (scenario_version_id, scenario_id, version_number, created_by) "
        "VALUES ('version-shared-turn', 'scenario-shared-turn', 1, 'test')"
    )
    test_db.execute(
        "UPDATE rooms SET status = 'active', state_version = 1, scenario_id = 'scenario-shared-turn', "
        "scenario_version_id = 'version-shared-turn' WHERE room_id = 'room-v2'"
    )
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, "
        "input_checksum, runtime_package, created_by) VALUES "
        "('package-shared-turn', 'version-shared-turn', 1, 'ready', 'shared-turn', %s, 'test')",
        (
            json.dumps(
                {
                    "semantic_progression_rules": {
                        "edges": [{
                            "from_scene_id": "gallery",
                            "to_scene_id": "orchid-hall",
                            "relation_type": "transitions_to",
                            "conditions": [],
                            "citation": citation,
                        }],
                    },
                }
            ),
        ),
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, version) "
        "VALUES ('room-v2', 'orchid-hall', '[\"gallery\", \"orchid-hall\"]', 2)"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, base_state_version) "
        "VALUES ('turn-shared', 'room-v2', 1, 'resolving', 0)"
    )
    test_db.execute(
        "UPDATE actions SET turn_id = 'turn-shared', params = %s WHERE action_id = 'action-v2'",
        (json.dumps(params),),
    )

    action = dict(
        test_db.execute("SELECT * FROM actions WHERE action_id = 'action-v2'").fetchone()
    )
    intent = PlayerIntent(
        action_id="action-v2",
        intent_type="move",
        declared_intent="与队友一起前往兰花展厅",
        params=params,
    )
    transition, error = ResolutionPipeline(
        test_db, _DialogueCompiler()
    )._validated_generic_scene_transition(action, intent)

    assert error is None
    assert transition["already_applied"] is True


def test_transition_action_updates_status_and_timeline_atomically(test_db):
    _insert_action(test_db)

    transitioned = transition_action(
        test_db,
        "action-v2",
        from_statuses=("queued",),
        to_status="resolving",
        metadata={"worker": "test"},
    )

    assert transitioned is True
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'action-v2'"
    ).fetchone()
    assert action["status"] == "resolving"
    event = test_db.execute(
        "SELECT status, metadata FROM action_status_events WHERE action_id = 'action-v2'"
    ).fetchone()
    assert event["status"] == "resolving"
    assert event["metadata"] == {"worker": "test"}


def test_transition_action_does_not_duplicate_event_after_lost_claim(test_db):
    _insert_action(test_db, status="resolving")

    transitioned = transition_action(
        test_db,
        "action-v2",
        from_statuses=("queued",),
        to_status="resolving",
    )

    assert transitioned is False
    count = test_db.execute(
        "SELECT COUNT(*) AS count FROM action_status_events WHERE action_id = 'action-v2'"
    ).fetchone()["count"]
    assert count == 0


def test_transition_action_rejects_illegal_state_jump(test_db):
    _insert_action(test_db)

    with pytest.raises(ValueError, match="Illegal action transition"):
        transition_action(
            test_db,
            "action-v2",
            from_statuses=("queued",),
            to_status="completed",
        )

    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'action-v2'"
    ).fetchone()["status"] == "queued"


class _SkillCheckCompiler:
    async def compile(self, _intent, _scenario, _character):
        return MechanicCompileResult(
            triggeredMechanic="skill_check",
            skillName="侦查",
            difficulty="regular",
        )


class _DialogueCompiler:
    async def compile(self, _intent, _scenario, _character):
        return MechanicCompileResult(triggeredMechanic="dialogue")


class _HiddenModifierCompiler:
    async def compile(self, _intent, _scenario, _character):
        return MechanicCompileResult(
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


class _Dispatcher:
    def __init__(self):
        self.events = []

    async def emit(self, room_id, event_type, audience, payload, character_id=None):
        self.events.append((room_id, event_type, audience, payload, character_id))


class _MutationRuleExecutor:
    async def execute(self, intent, compiled, character, inventory, scenario_assets):
        return ResolutionResult(
            actionId=intent.action_id,
            roomId=character["room_id"],
            characterId=character["character_id"],
            mechanic="use_item",
            isSuccess=True,
            mutations=[
                {"op": "replace", "path": "/character/luck", "value": 20}
            ],
        )


class _FailingStateService:
    def apply_change(self, *args, **kwargs):
        raise RuntimeError("state persistence unavailable")


class _PendingSuggestionRuleExecutor:
    async def execute(self, intent, compiled, character, inventory, scenario_assets):
        return ResolutionResult(
            actionId=intent.action_id,
            roomId=character["room_id"],
            characterId=character["character_id"],
            mechanic="unsupported_rule",
            isSuccess=False,
            metadata={
                "pending_rule_suggestions": [
                    {
                        "mechanic": "unsupported_rule",
                        "status": "pending_host_confirmation",
                        "reason_code": "rule_handler_not_found",
                        "citation": {"source_ref": "module#p12"},
                    }
                ]
            },
        )


class _CompositeChoiceRuleExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, intent, _compiled, character, _inventory, _scenario_assets):
        self.calls.append(intent.declared_intent)
        return ResolutionResult(
            actionId=intent.action_id,
            roomId=character["room_id"],
            characterId=character["character_id"],
            mechanic=intent.intent_type,
            isSuccess=False,
        )


@pytest.mark.asyncio
async def test_v2_composite_action_cancels_legacy_choice_policy_without_a_mid_round_prompt(test_db):
    _insert_action(test_db)
    params = _verified_params(
        composite_steps=[
            {
                "step_id": "step_1",
                "summary": "先撬门",
                "declared_intent": "先撬门",
                "intent_type": "skill_check",
                "params": {},
                "on_previous_failure": "cancel",
            },
            {
                "step_id": "step_2",
                "summary": "改从窗户进入",
                "declared_intent": "改从窗户进入",
                "intent_type": "move",
                "params": {},
                "on_previous_failure": "ask",
            },
        ],
    )
    test_db.execute(
        "UPDATE actions SET params = %s WHERE action_id = 'action-v2'",
        (json.dumps(params, ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-v2', 'queued', '{}')"
    )
    executor = _CompositeChoiceRuleExecutor()
    dispatcher = _Dispatcher()
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_DialogueCompiler(),
        dispatcher=dispatcher,
        rule_executor=executor,
    )

    result = await pipeline.resolve_action("action-v2")

    assert result["status"] == "completed"
    assert executor.calls == ["先撬门"]
    phases = result["result"]["metadata"]["composite_action"]["phases"]
    assert [phase["status"] for phase in phases] == ["failed", "canceled"]
    assert all(event[1] != "s2c_action_choice_requested" for event in dispatcher.events)


@pytest.mark.asyncio
async def test_v2_composite_choice_rejects_after_legacy_policy_is_auto_canceled(test_db):
    _insert_action(test_db)
    params = _verified_params(
        composite_steps=[
            {
                "step_id": "step_1",
                "summary": "先撬门",
                "declared_intent": "先撬门",
                "intent_type": "skill_check",
                "params": {},
                "on_previous_failure": "cancel",
            },
            {
                "step_id": "step_2",
                "summary": "改从窗户进入",
                "declared_intent": "改从窗户进入",
                "intent_type": "move",
                "params": {},
                "on_previous_failure": "ask",
            },
        ],
    )
    test_db.execute(
        "UPDATE actions SET params = %s WHERE action_id = 'action-v2'",
        (json.dumps(params, ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-v2', 'queued', '{}')"
    )
    executor = _CompositeChoiceRuleExecutor()
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        rule_executor=executor,
    )

    await pipeline.resolve_action("action-v2")

    with pytest.raises(ActionDraftError) as error:
        choose_composite_action_continuation(
            test_db,
            "char-v2",
            "action-v2",
            proceed=True,
        )

    assert error.value.detail == {"code": "composite_choice_not_pending"}


@pytest.mark.asyncio
async def test_v2_pipeline_records_completed_timeline_and_verifiable_rule_receipt(
    client,
    test_db,
    monkeypatch,
):
    monkeypatch.setenv("JWT_SECRET", "receipt-secret")
    _insert_action(test_db)
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = 'char-v2'",
        (json.dumps({"skills": {"侦查": 60}, "luck": 40}),),
    )
    test_db.execute(
        "UPDATE actions SET intent_type = 'skill_check', declared_intent = '我仔细侦查房间', "
        "rule_set_version_id = 'coc7-v1', params = %s WHERE action_id = 'action-v2'",
        (json.dumps(_verified_params(skillName="侦查"), ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-v2', 'queued', '{}')"
    )
    rolls = iter([4, 2])
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(rolls),
    )
    dispatcher = _Dispatcher()
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=dispatcher,
    )

    result = await pipeline.resolve_action("action-v2")

    assert result["status"] == "completed"
    action = test_db.execute(
        "SELECT status, receipt FROM actions WHERE action_id = 'action-v2'"
    ).fetchone()
    assert action["status"] == "completed"
    explanation = action["receipt"]
    assert explanation["rule_set_version"] == "coc7-v1"
    assert explanation["authoritative_inputs"]["skill_value"] == 60
    assert explanation["authoritative_inputs"]["success_level"] == "regular"
    assert explanation["formula"] == "d100 <= 60"
    assert verify_roll_receipt(
        explanation["verification_receipt"],
        secret="receipt-secret",
    ) is True

    bundle = test_db.execute(
        "SELECT canonical_result, rule_explanation, actor_projection, stage_projection, "
        "host_console, release_status, released_at FROM resolution_bundles "
        "WHERE action_id = 'action-v2'"
    ).fetchone()
    assert bundle["canonical_result"]["actionId"] == "action-v2"
    assert bundle["rule_explanation"] == explanation
    assert bundle["actor_projection"]["action_completed"]["actionId"] == "action-v2"
    assert bundle["stage_projection"]["actionId"] == "action-v2"
    assert bundle["host_console"]["actionId"] == "action-v2"
    assert isinstance(bundle["canonical_result"]["stateVersion"], int)
    assert bundle["release_status"] == "released"
    assert bundle["released_at"] is not None

    test_db.execute(
        "UPDATE actions SET result = %s, receipt = %s WHERE action_id = 'action-v2'",
        (
            json.dumps({"tampered": "mutable result"}, ensure_ascii=False),
            json.dumps({"tampered": "mutable receipt"}, ensure_ascii=False),
        ),
    )
    test_db.commit()

    statuses = test_db.execute(
        "SELECT status FROM action_status_events WHERE action_id = 'action-v2' "
        "ORDER BY status_event_id"
    ).fetchall()
    assert [row["status"] for row in statuses] == ["queued", "resolving", "completed"]

    response = client.get(
        "/api/player/actions/action-v2",
        headers={"X-Room-Token": "player-token"},
    )
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["status"] == "completed"
    assert receipt["can_review"] is True
    assert receipt["result"]["actionId"] == "action-v2"
    assert "tampered" not in receipt["result"]
    assert receipt["transaction_id"] == bundle["host_console"]["transactionId"]
    assert receipt["state_version"] == bundle["canonical_result"]["stateVersion"]
    assert receipt["rule_explanation"]["verification_receipt"]["action_id"] == "action-v2"


@pytest.mark.asyncio
async def test_v2_background_item_claim_adds_inventory_exactly_once(test_db):
    _insert_action(test_db)
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = 'char-v2'",
        (json.dumps({"background": "宝贵之物：父亲留下的黄铜打火机"}),),
    )
    test_db.execute(
        "UPDATE actions SET intent_type = 'retroactive_item_claim', declared_intent = %s, "
        "params = %s WHERE action_id = 'action-v2'",
        (
            "我拿出黄铜打火机",
            json.dumps(
                _verified_params(
                    **{
                        "claimedItemName": "黄铜打火机",
                        "justificationText": "这是父亲留下的遗物",
                    }
                ),
                ensure_ascii=False,
            ),
        ),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-v2', 'queued', '{}')"
    )
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        state_service=StateService(test_db),
    )

    first_result = await pipeline.resolve_action("action-v2")
    second_result = await pipeline.resolve_action("action-v2")

    assert first_result["status"] == "completed"
    assert second_result["status"] == "completed"
    items = test_db.execute(
        "SELECT name, quantity, source FROM inventory WHERE character_id = 'char-v2'"
    ).fetchall()
    assert [dict(item) for item in items] == [
        {"name": "黄铜打火机", "quantity": 1, "source": "backstory"}
    ]


@pytest.mark.asyncio
async def test_v2_pipeline_does_not_complete_or_project_when_state_persistence_fails(test_db):
    _insert_action(test_db)
    test_db.execute(
        "UPDATE actions SET intent_type = 'use_item', params = %s WHERE action_id = 'action-v2'",
        (json.dumps(_verified_params(), ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-v2', 'queued', '{}')"
    )
    dispatcher = _Dispatcher()
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=dispatcher,
        rule_executor=_MutationRuleExecutor(),
        state_service=_FailingStateService(),
    )

    result = await pipeline.resolve_action("action-v2")

    assert result["status"] == "awaiting_host_exception"
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'action-v2'"
    ).fetchone()
    assert action["status"] == "awaiting_host_exception"
    assert action["result"] is None
    statuses = test_db.execute(
        "SELECT status FROM action_status_events WHERE action_id = 'action-v2' "
        "ORDER BY status_event_id"
    ).fetchall()
    assert [row["status"] for row in statuses] == [
        "queued",
        "resolving",
        "awaiting_host_exception",
    ]
    assert "s2c_action_completed" not in [event[1] for event in dispatcher.events]


@pytest.mark.asyncio
async def test_failed_v2_pushed_roll_waits_for_host_consequence_without_state_change(
    test_db,
    monkeypatch,
):
    _insert_action(test_db)
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = 'char-v2'",
        (json.dumps({"skills": {"侦查": 60}, "luck": 0}),),
    )
    test_db.execute(
        "UPDATE actions SET intent_type = 'skill_check', params = %s "
        "WHERE action_id = 'action-v2'",
        (json.dumps(_verified_params(skillName="侦查", pushed=True), ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-v2', 'queued', '{}')"
    )
    rolls = iter([8, 0, 9, 0])
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(rolls),
    )
    dispatcher = _Dispatcher()
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=dispatcher,
    )

    result = await pipeline.resolve_action("action-v2")

    assert result["status"] == "awaiting_host_exception"
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'action-v2'"
    ).fetchone()
    assert action["status"] == "awaiting_host_exception"
    assert action["result"]["metadata"]["pending_consequence"]["reason"] == "pushed_check_failed"
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = 'room-v2'"
    ).fetchone()["state_version"] == 0


@pytest.mark.asyncio
async def test_v2_rule_explanation_uses_authoritative_runtime_before_and_after_state(test_db):
    _insert_action(test_db)
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = 'char-v2'",
        (json.dumps({"skills": {}, "luck": 40}),),
    )
    test_db.execute(
        "UPDATE actions SET intent_type = 'use_item', params = %s WHERE action_id = 'action-v2'",
        (json.dumps(_verified_params(), ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-v2', 'queued', '{}')"
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("char-v2", "room-v2")
    test_db.execute(
        "UPDATE character_runtime_state SET luck = 35 "
        "WHERE character_id = 'char-v2' AND room_id = 'room-v2'"
    )
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=_Dispatcher(),
        rule_executor=_MutationRuleExecutor(),
        state_service=state_service,
    )

    result = await pipeline.resolve_action("action-v2")

    assert result["status"] == "completed"
    receipt = test_db.execute(
        "SELECT receipt FROM actions WHERE action_id = 'action-v2'"
    ).fetchone()["receipt"]
    assert receipt["state_before"]["luck"] == 35
    assert receipt["state_after"]["luck"] == 20


@pytest.mark.asyncio
async def test_unimplemented_v2_rule_waits_for_host_without_completing_action(test_db):
    _insert_action(test_db)
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-v2', 'queued', '{}')"
    )
    dispatcher = _Dispatcher()
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=dispatcher,
        rule_executor=_PendingSuggestionRuleExecutor(),
    )

    result = await pipeline.resolve_action("action-v2")

    assert result["status"] == "awaiting_host_exception"
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'action-v2'"
    ).fetchone()
    assert action["status"] == "awaiting_host_exception"
    assert action["result"]["metadata"]["pending_rule_suggestions"][0][
        "reason_code"
    ] == "rule_handler_not_found"
    assert "s2c_action_completed" not in [event[1] for event in dispatcher.events]


def test_rule_explanation_hides_modifier_source_but_keeps_mechanical_effect():
    pipeline = ResolutionPipeline(conn=None)
    explanation = pipeline._build_rule_explanation(
        {
            "action_id": "action-hidden",
            "intent_type": "skill_check",
            "declared_intent": "侦查走廊",
            "rule_set_version_id": "coc7-v1",
            "params": {},
        },
        {"xlsx_data": {"skills": {"侦查": 60}}},
        ResolutionResult(
            actionId="action-hidden",
            roomId="room-v2",
            characterId="char-v2",
            mechanic="skill_check",
            isSuccess=False,
            metadata={
                "target": 60,
                "hidden_modifiers": [
                    {"source": "走廊里的不可见生物", "effect": "1 penalty die"}
                ],
            },
        ),
    )

    assert explanation["hidden_sources"] == [
        {"source": "hidden", "effect": "1 penalty die"}
    ]
    assert "不可见生物" not in json.dumps(explanation, ensure_ascii=False)


@pytest.mark.asyncio
async def test_player_receipt_applies_hidden_modifier_and_never_exposes_source(
    client,
    test_db,
    monkeypatch,
):
    monkeypatch.setenv("JWT_SECRET", "hidden-receipt-secret")
    _insert_action(test_db)
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = 'char-v2'",
        (json.dumps({"skills": {"侦查": 60}, "luck": 0}),),
    )
    test_db.execute(
        "UPDATE actions SET intent_type = 'skill_check', params = %s "
        "WHERE action_id = 'action-v2'",
        (json.dumps(_verified_params(skillName="侦查"), ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-v2', 'queued', '{}')"
    )
    rolls = iter([5, 0, 9])
    monkeypatch.setattr(
        "src.server.engine.skill_check.random.randint",
        lambda _low, _high: next(rolls),
    )
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_HiddenModifierCompiler(),
        dispatcher=_Dispatcher(),
    )

    result = await pipeline.resolve_action("action-v2")
    response = client.get(
        "/api/player/actions/action-v2",
        headers={"X-Room-Token": "player-token"},
    )

    assert result["status"] == "completed"
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["metadata"]["bonus_dice"] == -1
    assert payload["result"]["metadata"]["hidden_modifiers"][0]["source"] == "hidden"
    assert payload["rule_explanation"]["hidden_sources"] == [
        {"source": "hidden", "effect": "1 penalty die"}
    ]
    assert "不可见生物" not in response.text
