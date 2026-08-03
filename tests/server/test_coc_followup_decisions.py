import json

import pytest

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.action_lifecycle import transition_action
from src.server.engine.roll_receipt import verify_roll_receipt
from src.server.engine.rule_executor import RuleExecutor
from src.server.engine.state_service import StateService
from src.server.models import MechanicCompileResult, PlayerIntent
from src.server.main import app
from src.server.player.action_service import (
    ActionDraftError,
    submit_coc_followup_decision,
)


class _SkillCheckCompiler:
    def __init__(self, consequence=None):
        self.consequence = consequence or {}

    async def compile(self, _intent, _scenario, _character):
        return MechanicCompileResult(
            triggeredMechanic="skill_check",
            skillName="侦查",
            difficulty="regular",
            consequence=self.consequence,
        )


class _Dispatcher:
    def __init__(self):
        self.events = []

    async def emit(self, room_id, event_type, audience, payload, character_id=None):
        self.events.append((room_id, event_type, audience, payload, character_id))


def _action_params(**extra):
    params = {
        "director_plan": {
            "context_version": 0,
            "preconditions": [],
            "permissions": [],
            "state_patch": [],
            "state_patch_authority": "advisory_only",
        }
    }
    params.update(extra)
    return params


def _insert_action(test_db, *, luck=10, params=None):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, player_experience_version) "
        "VALUES ('room-followup', 'owner-token', 'v1')"
    )
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('char-followup', 'room-followup', '玩家一', 'token-owner', %s)",
        (json.dumps({"skills": {"侦查": 60}, "luck": luck}, ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('char-other', 'room-followup', '玩家二', 'token-other', %s)",
        (json.dumps({"skills": {"侦查": 60}, "luck": luck}, ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, draft_id, idempotency_key, intent_type, "
        "declared_intent, params, status, rule_set_version_id) "
        "VALUES ('action-followup', 'room-followup', 'char-followup', 'draft-followup', "
        "'confirm-action-followup', 'skill_check', '我仔细侦查房间', %s, 'queued', 'coc7-v2')",
        (json.dumps(params or _action_params(pushed=True), ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('action-followup', 'queued', '{}')"
    )


def _sequence_rng(monkeypatch, values):
    calls = []
    values = iter(values)

    def randint(_low, _high):
        value = next(values)
        calls.append(value)
        return value

    monkeypatch.setenv("AIKEEPER_DEV_MODE", "1")
    monkeypatch.setattr("src.server.engine.skill_check.random.randint", randint)
    return calls


@pytest.mark.asyncio
async def test_initial_failure_is_persisted_with_locked_follow_up_and_v2_receipt(
    test_db,
    monkeypatch,
):
    monkeypatch.setenv("JWT_SECRET", "followup-receipt-secret")
    consequence = {
        "pushedConsequenceEnvelope": {
            "riskLevel": "medium",
            "affectedScope": ["scene"],
            "supportingFactIds": ["fact-public-1"],
            "warning": "失败会让警报升级。",
            "allowedCodes": ["alarm_escalates"],
        },
    }
    _insert_action(
        test_db,
        params=_action_params(pushed=True),
    )
    calls = _sequence_rng(monkeypatch, [6, 5, 3, 0])
    dispatcher = _Dispatcher()

    outcome = await ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(consequence),
        dispatcher=dispatcher,
    ).resolve_action("action-followup")

    assert outcome["status"] == "awaiting_player_choice"
    assert calls == [6, 5]
    action = test_db.execute(
        "SELECT status, result, receipt FROM actions WHERE action_id = 'action-followup'"
    ).fetchone()
    assert action["status"] == "awaiting_player_choice"
    follow_up = action["result"]["metadata"]["follow_up"]
    assert follow_up["luck"]["required"] == 5
    assert follow_up["push"] == {
        "available": True,
        "risk_level": "medium",
        "affected_scope": ["scene"],
        "supporting_fact_ids": ["fact-public-1"],
        "warning": "失败会让警报升级。",
    }
    receipt = action["receipt"]["verification_receipt"]
    assert receipt["version"] == "v2"
    assert receipt["purpose"] == "skill_check.initial"
    assert receipt["room_id"] == "room-followup"
    assert receipt["state_version"] == 0
    assert receipt["idempotency_key"] == "confirm-action-followup"
    assert verify_roll_receipt(receipt, secret="followup-receipt-secret") is True
    bundle = test_db.execute(
        "SELECT canonical_result, rule_explanation, release_status "
        "FROM resolution_bundles WHERE action_id = 'action-followup'"
    ).fetchone()
    assert bundle["canonical_result"]["metadata"]["roll"] == 65
    assert bundle["rule_explanation"] == action["receipt"]
    assert bundle["release_status"] == "ready"
    assert any(event[1] == "s2c_action_choice_requested" for event in dispatcher.events)


@pytest.mark.asyncio
async def test_push_confirmation_is_owner_bound_and_retry_does_not_redraw(
    test_db,
    monkeypatch,
):
    monkeypatch.setenv("JWT_SECRET", "followup-receipt-secret")
    consequence = {
        "pushedConsequenceEnvelope": {
            "riskLevel": "medium",
            "affectedScope": ["scene"],
            "supportingFactIds": ["fact-public-1"],
            "warning": "失败会让警报升级。",
            "allowedCodes": ["alarm_escalates"],
            "allowedConsequences": [
                {
                    "code": "alarm_escalates",
                    "publicText": "警报升级，调查时间缩短。",
                }
            ],
        },
        "pushedFailureConsequence": {
            "code": "alarm_escalates",
            "publicText": "调查员立即死亡，幕后真相全部公开。",
            "riskLevel": "medium",
            "affectedScope": ["scene"],
            "supportingFactIds": ["fact-public-1"],
        },
        "pushedFailureConsequenceRetry": {
            "code": "alarm_escalates",
            "publicText": "仍然输出未获批准的具体后果。",
            "riskLevel": "medium",
            "affectedScope": ["scene"],
            "supportingFactIds": ["fact-public-1"],
        },
    }
    _insert_action(
        test_db,
        params=_action_params(),
    )
    calls = _sequence_rng(monkeypatch, [6, 5, 9, 0])
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(consequence),
        dispatcher=_Dispatcher(),
    )
    await pipeline.resolve_action("action-followup")

    with pytest.raises(ActionDraftError) as not_owner:
        submit_coc_followup_decision(
            test_db,
            "char-other",
            "action-followup",
            "push",
            "push-once",
        )
    assert not_owner.value.status_code == 404
    submit_coc_followup_decision(
        test_db,
        "char-followup",
        "action-followup",
        "push",
        "push-once",
    )
    assert calls == [6, 5]

    outcome = await pipeline.resolve_action("action-followup")

    assert outcome["status"] == "completed"
    assert calls == [6, 5, 9, 0]
    action = test_db.execute(
        "SELECT result, receipt FROM actions WHERE action_id = 'action-followup'"
    ).fetchone()
    consequence = action["result"]["metadata"]["pushed_consequence"]
    assert consequence["selection_source"] == "engine_fixed_fallback"
    assert consequence["retry_count"] == 1
    assert consequence["risk_level"] == "medium"
    assert consequence["affected_scope"] == ["scene"]
    assert action["receipt"]["verification_receipt"]["purpose"] == "skill_check.pushed"
    assert action["result"]["metadata"]["initial_verification_receipt"]["purpose"] == "skill_check.initial"

    replay = submit_coc_followup_decision(
        test_db,
        "char-followup",
        "action-followup",
        "push",
        "push-once",
    )
    assert replay.status == "completed"
    assert replay.rule_explanation["verification_receipt"] == action["receipt"][
        "verification_receipt"
    ]
    assert (await pipeline.resolve_action("action-followup"))["status"] == "completed"
    assert calls == [6, 5, 9, 0]


@pytest.mark.asyncio
async def test_luck_confirmation_spends_exact_amount_once(test_db, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "followup-receipt-secret")
    _insert_action(test_db, luck=10, params=_action_params(spendLuck=True))
    calls = _sequence_rng(monkeypatch, [6, 5])
    state_service = StateService(test_db)
    state_service.initialize_character_state("char-followup", "room-followup")
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=_Dispatcher(),
        state_service=state_service,
    )
    await pipeline.resolve_action("action-followup")

    submit_coc_followup_decision(
        test_db,
        "char-followup",
        "action-followup",
        "spend_luck",
        "luck-once",
    )
    assert (await pipeline.resolve_action("action-followup"))["status"] == "completed"
    assert calls == [6, 5]
    runtime = state_service.get_runtime_state("char-followup", "room-followup")
    assert runtime["luck"] == 5
    action = test_db.execute(
        "SELECT result, receipt FROM actions WHERE action_id = 'action-followup'"
    ).fetchone()
    assert action["result"]["metadata"]["luck_spent"] == 5
    assert action["receipt"]["verification_receipt"]["purpose"] == "skill_check.spend_luck"

    replay = submit_coc_followup_decision(
        test_db,
        "char-followup",
        "action-followup",
        "spend_luck",
        "luck-once",
    )
    assert replay.status == "completed"
    assert replay.rule_explanation["verification_receipt"] == action["receipt"][
        "verification_receipt"
    ]
    assert state_service.get_runtime_state("char-followup", "room-followup")["luck"] == 5


@pytest.mark.asyncio
async def test_decline_completes_original_failure_without_another_draw(test_db, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "followup-receipt-secret")
    _insert_action(test_db, luck=10)
    calls = _sequence_rng(monkeypatch, [6, 5])
    state_service = StateService(test_db)
    state_service.initialize_character_state("char-followup", "room-followup")
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=_Dispatcher(),
        state_service=state_service,
    )
    await pipeline.resolve_action("action-followup")
    submit_coc_followup_decision(
        test_db,
        "char-followup",
        "action-followup",
        "decline",
        "decline-once",
    )

    outcome = await pipeline.resolve_action("action-followup")

    assert outcome["status"] == "completed"
    assert calls == [6, 5]
    action = test_db.execute(
        "SELECT result, receipt FROM actions WHERE action_id = 'action-followup'"
    ).fetchone()
    assert action["result"]["isSuccess"] is False
    assert action["result"]["metadata"]["follow_up"] == {
        "status": "resolved",
        "decision": "decline",
    }
    assert action["receipt"]["verification_receipt"]["purpose"] == "skill_check.decline"
    assert state_service.get_runtime_state("char-followup", "room-followup")["luck"] == 10


@pytest.mark.asyncio
async def test_requeued_follow_up_reuses_initial_draw_instead_of_rolling_it_again(
    test_db,
    monkeypatch,
):
    monkeypatch.setenv("JWT_SECRET", "followup-receipt-secret")
    _insert_action(test_db)
    calls = _sequence_rng(monkeypatch, [6, 5, 3, 0])
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=_Dispatcher(),
    )
    await pipeline.resolve_action("action-followup")
    submit_coc_followup_decision(
        test_db,
        "char-followup",
        "action-followup",
        "push",
        "push-after-sync",
    )
    assert transition_action(
        test_db,
        "action-followup",
        from_statuses=("awaiting_player_choice",),
        to_status="sync_required",
    ) is True
    assert transition_action(
        test_db,
        "action-followup",
        from_statuses=("sync_required",),
        to_status="queued",
    ) is True

    outcome = await pipeline.resolve_action("action-followup")

    assert outcome["status"] == "completed"
    assert calls == [6, 5, 3, 0]
    action = test_db.execute(
        "SELECT result FROM actions WHERE action_id = 'action-followup'"
    ).fetchone()
    assert action["result"]["metadata"]["initial_roll"] == 65
    assert action["result"]["metadata"]["roll"] == 30


@pytest.mark.asyncio
async def test_expired_follow_up_times_out_without_luck_spend_or_push(test_db, monkeypatch):
    from src.server.ai.decision_audit import DecisionAuditRecorder

    monkeypatch.setenv("JWT_SECRET", "followup-receipt-secret")
    _insert_action(test_db, luck=10)
    calls = _sequence_rng(monkeypatch, [6, 5, 3, 0])
    state_service = StateService(test_db)
    state_service.initialize_character_state("char-followup", "room-followup")
    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=_Dispatcher(),
        state_service=state_service,
    )
    await pipeline.resolve_action("action-followup")
    audit_id = DecisionAuditRecorder(test_db).record(
        room_id="room-followup",
        action_id="action-followup",
        task_type="analyze_director_action",
        provider="terminal-audit-test",
        model="deterministic",
    )
    test_db.commit()
    row = test_db.execute(
        "SELECT params FROM actions WHERE action_id = 'action-followup'"
    ).fetchone()
    params = row["params"]
    params["coc_followup_progress"]["expires_at"] = "2000-01-01T00:00:00+00:00"
    test_db.execute(
        "UPDATE actions SET params = %s WHERE action_id = 'action-followup'",
        (json.dumps(params, ensure_ascii=False),),
    )

    with pytest.raises(ActionDraftError) as expired:
        submit_coc_followup_decision(
            test_db,
            "char-followup",
            "action-followup",
            "push",
            "push-too-late",
        )

    assert expired.value.detail == {"code": "coc_followup_timed_out"}
    timed_out = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'action-followup'"
    ).fetchone()
    assert timed_out["status"] == "timeout"
    assert timed_out["result"]["metadata"]["follow_up"]["status"] == "timed_out"
    final_delta = test_db.execute(
        "SELECT final_delta FROM ai_call_logs WHERE decision_audit_id = %s",
        (audit_id,),
    ).fetchone()["final_delta"]
    assert final_delta["action_status"] == "timeout"
    assert final_delta["reason_code"] == "coc_followup_timed_out"
    assert isinstance(final_delta["state_version"], int)
    assert state_service.get_runtime_state("char-followup", "room-followup")["luck"] == 10
    assert calls == [6, 5]


@pytest.mark.asyncio
async def test_follow_up_http_endpoint_accepts_only_the_action_owner(
    client,
    test_db,
    monkeypatch,
):
    monkeypatch.setenv("JWT_SECRET", "followup-receipt-secret")
    monkeypatch.setattr(app.state, "pg_db", None, raising=False)
    monkeypatch.setattr(app.state, "pipeline", None, raising=False)
    _insert_action(test_db)
    _sequence_rng(monkeypatch, [6, 5])
    await ResolutionPipeline(
        conn=test_db,
        compiler=_SkillCheckCompiler(),
        dispatcher=_Dispatcher(),
    ).resolve_action("action-followup")

    not_owner = client.post(
        "/api/player/actions/action-followup/follow-up",
        headers={"X-Room-Token": "token-other", "Idempotency-Key": "push-http"},
        json={"decision": "push"},
    )
    invalid = client.post(
        "/api/player/actions/action-followup/follow-up",
        headers={"X-Room-Token": "token-owner", "Idempotency-Key": "bad-http"},
        json={"decision": "reroll"},
    )
    accepted = client.post(
        "/api/player/actions/action-followup/follow-up",
        headers={"X-Room-Token": "token-owner", "Idempotency-Key": "push-http"},
        json={"decision": "push"},
    )

    assert not_owner.status_code == 404
    assert not_owner.json()["detail"]["code"] == "action_not_found"
    assert invalid.status_code == 422
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "awaiting_player_choice"
    progress = test_db.execute(
        "SELECT params FROM actions WHERE action_id = 'action-followup'"
    ).fetchone()["params"]["coc_followup_progress"]
    assert progress["decision"] == "push"
    assert progress["decision_idempotency_key"] == "push-http"


@pytest.mark.asyncio
async def test_hidden_check_requires_explicit_compiled_rule_declaration(monkeypatch):
    calls = _sequence_rng(monkeypatch, [4, 2])
    executor = RuleExecutor()
    intent = PlayerIntent(
        action_id="hidden-action",
        intent_type="skill_check",
        params={"hiddenCheck": True},
    )
    character = {
        "character_id": "char-hidden",
        "room_id": "room-hidden",
        "xlsx_data": {"skills": {"侦查": 60}, "luck": 10},
    }

    rejected = await executor.execute(
        intent,
        MechanicCompileResult(triggeredMechanic="skill_check", skillName="侦查"),
        character,
        [],
        {},
    )

    assert rejected.is_success is False
    assert rejected.metadata["reason_code"] == "hidden_check_not_declared"
    assert calls == []

    allowed = await executor.execute(
        intent,
        MechanicCompileResult(
            triggeredMechanic="skill_check",
            skillName="侦查",
            consequence={"hiddenCheck": True},
        ),
        character,
        [],
        {},
    )
    assert allowed.metadata["hidden_check"] is True
    assert calls == [4, 2]
