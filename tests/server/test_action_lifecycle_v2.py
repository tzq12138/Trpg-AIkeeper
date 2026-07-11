import json

import pytest

from src.server.engine.action_lifecycle import transition_action
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.roll_receipt import verify_roll_receipt
from src.server.engine.state_service import StateService
from src.server.models import MechanicCompileResult, ResolutionResult


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
        "declared_intent, status) VALUES (%s, 'room-v2', 'char-v2', 'draft-v2', "
        "'dialogue', '观察房间', %s)",
        (action_id, status),
    )


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
        (json.dumps({"skillName": "侦查"}),),
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
    assert explanation["formula"] == "d100 <= 60"
    assert verify_roll_receipt(
        explanation["verification_receipt"],
        secret="receipt-secret",
    ) is True

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
    assert receipt["rule_explanation"]["verification_receipt"]["action_id"] == "action-v2"


@pytest.mark.asyncio
async def test_v2_pipeline_does_not_complete_or_project_when_state_persistence_fails(test_db):
    _insert_action(test_db)
    test_db.execute(
        "UPDATE actions SET intent_type = 'use_item', params = '{}' WHERE action_id = 'action-v2'"
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
        (json.dumps({"skillName": "侦查", "pushed": True}),),
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
        "UPDATE actions SET intent_type = 'use_item', params = '{}' WHERE action_id = 'action-v2'"
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
        (json.dumps({"skillName": "侦查"}),),
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
