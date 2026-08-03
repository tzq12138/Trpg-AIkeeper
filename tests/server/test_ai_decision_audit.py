import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, BrokenBarrierError, local

import pytest

from src.server.ai.gateway import AiGateway
from src.server.engine.ending_conditions import EndingDecision
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.models import MechanicCompileResult, ResolutionResult
from tests.server.conftest import create_room, setup_auth_test_data


class _DecisionProvider:
    name = "configured:audit-provider-12345678901234567890"
    model = "audit-model-v1"

    def supports(self, _required=None):
        return True

    async def call(self, _task_type, _context):
        return {
            "interpreted_intent": "inspect the visible label",
            "intent_type": "dialogue",
            "confidence": 0.9,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
            "citations": [{
                "content_item_id": "visible-label",
                "version": "content-v1",
                "page_number": 1,
            }],
        }


class _UnavailableProvider(_DecisionProvider):
    name = "unavailable-provider"

    async def call(self, _task_type, _context):
        raise RuntimeError("private-boundary-text-must-not-be-logged")


class _NarratorDecisionProvider:
    name = "configured:narrator-audit"
    model = "narrator-model-v1"

    def supports(self, _required=None):
        return True

    async def call(self, _task_type, _context):
        refs = ["fact:scene-brief"]
        return {
            "narrative_text": "The visible door remains closed.",
            "environment_changes": ["The room remains quiet."],
            "interactable_objects": ["visible door"],
            "open_question": "How do you inspect the visible door?",
            "fact_refs": {
                "narrative_text": refs,
                "environment_changes": refs,
                "interactable_objects": refs,
                "open_question": refs,
            },
            "redacted_citations": [{
                "label": "Scene evidence",
                "page": 7,
                "scene": "waiting-room",
                "verified": True,
            }],
            "style_pack_version": "style-v1",
            "status": "completed",
        }


class _InvalidDecisionProvider(_DecisionProvider):
    name = "invalid-decision-provider"

    async def call(self, _task_type, _context):
        return {
            "interpreted_intent": "inspect",
            "intent_type": "dialogue",
            "confidence": {"input": "audit-validation-secret-sentinel"},
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
        }


class _AutoSuccessCompiler:
    async def compile(self, *_args, **_kwargs):
        return MechanicCompileResult(triggeredMechanic="auto_success")


class _NoMutationRuleExecutor:
    async def execute(self, intent, *_args, **_kwargs):
        return ResolutionResult(
            actionId=intent.action_id,
            roomId="",
            characterId="",
            isSuccess=True,
            narrative="ok",
            mutations=[],
            metadata={},
        )


@pytest.mark.asyncio
async def test_spoiler_retry_never_uses_untracked_narrative_provider(test_db):
    class UntrackedGateway:
        called = 0

        async def generate_narrative(self, *_args, **_kwargs):
            self.called += 1
            return {"public": "untracked replacement"}

    gateway = UntrackedGateway()
    pipeline = ResolutionPipeline(test_db, gateway=gateway)
    result = await pipeline._retry_with_constraint(
        {
            "action_id": "spoiler-retry-action",
            "room_id": "spoiler-retry-room",
            "character_id": "spoiler-retry-character",
            "declared_intent": "inspect",
            "intent_type": "dialogue",
        },
        ResolutionResult(
            actionId="spoiler-retry-action",
            roomId="spoiler-retry-room",
            characterId="spoiler-retry-character",
            narrative="unsafe narrative",
        ),
        "avoid the unrevealed fact",
    )

    assert result is None
    assert gateway.called == 0


def _confirmed_decision_action(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    player = client.post(f"/api/player/rooms/{room_id}/join").json()
    gateway = AiGateway(db_conn=test_db)
    gateway._get_ordered_providers = lambda _room_id=None: [_DecisionProvider()]
    previous_gateway = client.app.state.gateway
    client.app.state.gateway = gateway
    try:
        analyzed = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player["player_token"]},
            json={"declared_intent": "I inspect the visible label."},
        )
    finally:
        client.app.state.gateway = previous_gateway
    assert analyzed.status_code == 200
    draft = analyzed.json()
    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={
            "X-Room-Token": player["player_token"],
            "Idempotency-Key": f"decision-audit-{draft['draft_id']}",
        },
        json={"confirmations": draft["confirmation_requirements"]},
    )
    assert confirmed.status_code == 200
    return room_id, confirmed.json()["action_id"]


def test_authoritative_decision_audit_is_structured_minimal_and_expiring(test_db):
    from src.server.ai.decision_audit import DecisionAuditRecorder, minimal_context_hash

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('audit-room', 'owner', 'active')"
    )
    test_db.commit()
    context = {
        "room_id": "audit-room",
        "state_version": 7,
        "current_scene": "gate",
        "intent_type": "move",
        "account_id": "account-secret",
        "player_token": "token-secret",
        "raw_safety_text": "private boundary text",
        "unrelated_secret": "keeper-only-secret",
    }
    recorder = DecisionAuditRecorder(test_db)
    audit_id = recorder.record(
        room_id="audit-room",
        action_id="audit-action",
        task_type="director",
        provider="configured:test",
        model="model-v1",
        template_version="director.v3",
        rule_version="coc7.v1",
        context=context,
        citations=[
            {"citation_id": "rule-citation", "version": "1", "raw_text": "forbidden"}
        ],
        structured_proposal={
            "targetNodeId": "cistern",
            "owner_token": "forbidden-owner-token",
            "accountId": "forbidden-camel-account",
            "rawSafetyText": "forbidden-camel-safety",
            "accessToken": "forbidden-access-token",
            "email": "forbidden-account-email@example.test",
        },
        engine_validation={"validated": True, "account_id": "forbidden-account"},
        final_delta={"scene": "cistern", "private_note": "forbidden-note"},
    )

    row = test_db.execute(
        "SELECT * FROM ai_call_logs WHERE decision_audit_id = %s",
        (audit_id,),
    ).fetchone()
    rendered = json.dumps(dict(row), ensure_ascii=False, default=str)
    assert row["provider"] == "configured:test"
    assert row["model"] == "model-v1"
    assert row["template_version"] == "director.v3"
    assert row["rule_version"] == "coc7.v1"
    assert row["context_hash"] == minimal_context_hash(context)
    assert row["citations"] == [{"citation_id": "rule-citation", "version": "1"}]
    assert row["structured_proposal"] == {"targetNodeId": "cistern"}
    assert row["engine_validation"] == {"validated": True}
    assert row["final_delta"] == {"scene": "cistern"}
    assert row["record_kind"] == "decision"
    assert row["expires_at"] > row["created_at"]
    for forbidden in (
        "account-secret",
        "token-secret",
        "private boundary text",
        "keeper-only-secret",
        "forbidden-owner-token",
        "forbidden-camel-account",
        "forbidden-camel-safety",
        "forbidden-access-token",
        "forbidden-account-email@example.test",
        "forbidden-account",
        "forbidden-note",
    ):
        assert forbidden not in rendered

    equivalent = {**context, "player_token": "another-token", "account_id": "another-account"}
    assert minimal_context_hash(equivalent) == row["context_hash"]
    assert minimal_context_hash({**context, "state_version": 8}) != row["context_hash"]


def test_decision_audit_can_finalize_engine_result_without_storing_raw_context(test_db):
    from src.server.ai.decision_audit import DecisionAuditRecorder

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('audit-final-room', 'owner', 'active')"
    )
    test_db.commit()
    recorder = DecisionAuditRecorder(test_db)
    recorder.record(
        room_id="audit-final-room",
        action_id="audit-final-action",
        task_type="director",
        provider="local",
        model="deterministic",
        context={"state_version": 1, "player_token": "never-store"},
        structured_proposal={"kind": "move"},
    )

    assert recorder.finalize(
        "audit-final-action",
        engine_validation={"validated": True, "reason": "compiled_edge"},
        final_delta={"stateVersion": 2},
    ) == 1
    row = test_db.execute(
        "SELECT engine_validation, final_delta FROM ai_call_logs "
        "WHERE action_id = 'audit-final-action'"
    ).fetchone()
    assert row["engine_validation"]["validated"] is True
    assert row["final_delta"] == {"stateVersion": 2}


def test_decision_audit_keeps_director_and_narrator_validation_separate(test_db):
    from src.server.ai.decision_audit import DecisionAuditRecorder

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('audit-stages-room', 'owner', 'active')"
    )
    recorder = DecisionAuditRecorder(test_db)
    for task_type in ("analyze_director_action", "narrate_action"):
        recorder.record(
            room_id="audit-stages-room",
            action_id="audit-stages-action",
            task_type=task_type,
            provider="local",
            model="deterministic",
        )

    assert recorder.finalize(
        "audit-stages-action",
        task_type="narrate_action",
        engine_validation={"validated": False, "reason": "fact_violation"},
        final_delta={},
    ) == 1
    validations = {
        row["task_type"]: row["engine_validation"]
        for row in test_db.execute(
            "SELECT task_type, engine_validation FROM ai_call_logs "
            "WHERE action_id = 'audit-stages-action'"
        ).fetchall()
    }
    assert validations["analyze_director_action"] == {}
    assert validations["narrate_action"] == {
        "validated": False,
        "reason": "fact_violation",
    }

    assert recorder.finalize(
        "audit-stages-action",
        engine_validation=None,
        final_delta={"action_status": "completed"},
    ) == 2
    rows = test_db.execute(
        "SELECT engine_validation, final_delta FROM ai_call_logs "
        "WHERE action_id = 'audit-stages-action' ORDER BY task_type"
    ).fetchall()
    assert all(row["final_delta"] == {"action_status": "completed"} for row in rows)
    assert any(row["engine_validation"].get("validated") is False for row in rows)


@pytest.mark.asyncio
async def test_director_decision_audit_follows_draft_through_engine_completion(
    client,
    test_db,
):
    from src.server.engine.resolution_pipeline import ResolutionPipeline

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    player = client.post(f"/api/player/rooms/{room_id}/join").json()
    gateway = AiGateway(db_conn=test_db)
    gateway._get_ordered_providers = lambda _room_id=None: [_DecisionProvider()]
    previous_gateway = client.app.state.gateway
    client.app.state.gateway = gateway
    try:
        analyzed = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player["player_token"]},
            json={"declared_intent": "I inspect the visible label."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert analyzed.status_code == 200
    draft = analyzed.json()
    audit = test_db.execute(
        "SELECT * FROM ai_call_logs WHERE record_kind = 'decision'"
    ).fetchone()
    assert audit["action_id"] == draft["draft_id"]
    assert audit["provider"] == "configured:audit-provider-12345678901234567890"
    assert audit["model"] == "audit-model-v1"
    assert audit["template_version"] == "m0-runtime-v1"
    assert audit["rule_version"]
    assert audit["context_hash"]
    assert audit["citations"] == [{
        "content_item_id": "visible-label",
        "version": "content-v1",
        "page_number": 1,
    }]
    assert audit["structured_proposal"]["interpreted_intent"] == (
        "inspect the visible label"
    )
    assert "actor_display_name" not in audit["structured_proposal"]
    assert "declared_intent" not in audit["structured_proposal"]
    assert "I inspect the visible label." not in json.dumps(
        audit["structured_proposal"],
        ensure_ascii=False,
    )
    assert audit["engine_validation"] == {
        "validated": True,
        "stage": "draft_projection",
        "route": "ai",
    }
    assert audit["expires_at"] > audit["created_at"]

    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={
            "X-Room-Token": player["player_token"],
            "Idempotency-Key": "decision-audit-confirm",
        },
        json={"confirmations": draft["confirmation_requirements"]},
    )
    assert confirmed.status_code == 200
    action_id = confirmed.json()["action_id"]
    assert test_db.execute(
        "SELECT action_id FROM ai_call_logs WHERE decision_audit_id = %s",
        (audit["decision_audit_id"],),
    ).fetchone()["action_id"] == action_id

    result = await ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    ).resolve_action(action_id)

    assert result["status"] == "completed", result
    finalized = test_db.execute(
        "SELECT engine_validation, final_delta FROM ai_call_logs "
        "WHERE decision_audit_id = %s",
        (audit["decision_audit_id"],),
    ).fetchone()
    assert finalized["engine_validation"]["validated"] is True
    assert finalized["final_delta"]["action_status"] == "completed"
    assert isinstance(finalized["final_delta"]["state_version"], int)


def test_revised_draft_supersedes_provider_audit_instead_of_relinking_it(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    player = client.post(f"/api/player/rooms/{room_id}/join").json()
    headers = {"X-Room-Token": player["player_token"]}
    gateway = AiGateway(db_conn=test_db)
    gateway._get_ordered_providers = lambda _room_id=None: [_DecisionProvider()]
    previous_gateway = client.app.state.gateway
    client.app.state.gateway = gateway
    try:
        analyzed = client.post(
            "/api/player/action-drafts/analyze",
            headers=headers,
            json={"declared_intent": "I inspect the visible label."},
        )
    finally:
        client.app.state.gateway = previous_gateway
    assert analyzed.status_code == 200, analyzed.text
    draft = analyzed.json()

    revised = client.patch(
        f"/api/player/action-drafts/{draft['draft_id']}",
        headers=headers,
        json={"declared_intent": "I attack the visible figure."},
    )

    assert revised.status_code == 200, revised.text
    revised_draft = revised.json()
    assert revised_draft["revision"] == 2
    audit = test_db.execute(
        "SELECT action_id, draft_id, draft_revision, audit_state, final_delta "
        "FROM ai_call_logs WHERE room_id = %s AND record_kind = 'decision'",
        (room_id,),
    ).fetchone()
    assert audit == {
        "action_id": None,
        "draft_id": draft["draft_id"],
        "draft_revision": 1,
        "audit_state": "superseded",
        "final_delta": {
            "status": "superseded",
            "reasonCode": "draft_revised",
            "draftRevision": 1,
        },
    }

    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "revised-audit-confirm"},
        json={"confirmations": revised_draft["confirmation_requirements"]},
    )

    assert confirmed.status_code == 200, confirmed.text
    action = test_db.execute(
        "SELECT action_id, revision_number FROM actions WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert action["revision_number"] == 2
    assert test_db.execute(
        "SELECT action_id, audit_state FROM ai_call_logs WHERE room_id = %s",
        (room_id,),
    ).fetchone() == {"action_id": None, "audit_state": "superseded"}


@pytest.mark.asyncio
async def test_resolution_bundle_failure_rolls_back_terminal_action_and_audit(
    client,
    test_db,
    monkeypatch,
):
    _, action_id = _confirmed_decision_action(client, test_db)
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    )

    def fail_bundle(*_args, **_kwargs):
        raise RuntimeError("forced-post-completion-crash")

    monkeypatch.setattr(pipeline, "_persist_resolution_bundle", fail_bundle)

    with pytest.raises(RuntimeError, match="forced-post-completion-crash"):
        await pipeline.resolve_action(action_id)

    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["status"] == "resolving"
    delta = test_db.execute(
        "SELECT final_delta FROM ai_call_logs "
        "WHERE action_id = %s AND task_type = 'analyze_director_action'",
        (action_id,),
    ).fetchone()["final_delta"]
    assert "action_status" not in delta


@pytest.mark.asyncio
async def test_effect_event_is_durable_before_post_commit_publish(
    client,
    test_db,
    monkeypatch,
):
    _, action_id = _confirmed_decision_action(client, test_db)
    params = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["params"]
    params = dict(params) if isinstance(params, dict) else json.loads(params)
    params.update({"fromNodeId": "hall", "targetNodeId": "vault"})
    test_db.execute(
        "UPDATE actions SET intent_type = 'move', params = %s WHERE action_id = %s",
        (json.dumps(params), action_id),
    )
    test_db.commit()
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    )

    async def valid_move(*_args, **_kwargs):
        return None

    async def deferred_move_event(*_args, **_kwargs):
        return [{
            "event_type": "s2c_player_moved",
            "audience": "party",
            "payload": {
                "actionId": action_id,
                "characterId": "durable-character",
                "toNodeId": "vault",
            },
        }]

    original_emit = pipeline.dispatcher.emit

    async def fail_legacy_effect_emit(room_id, event_type, *args, **kwargs):
        if event_type == "s2c_player_moved":
            raise RuntimeError("forced-effect-publish-failure")
        return await original_emit(room_id, event_type, *args, **kwargs)

    async def fail_committed_publish(*_args, **_kwargs):
        raise RuntimeError("forced-effect-publish-failure")

    monkeypatch.setattr(pipeline, "_validate_director_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_validate_move", valid_move)
    monkeypatch.setattr(pipeline, "_apply_move_result", deferred_move_event)
    monkeypatch.setattr(pipeline.dispatcher, "emit", fail_legacy_effect_emit)
    monkeypatch.setattr(
        pipeline.dispatcher,
        "publish_committed_event",
        fail_committed_publish,
    )

    result = await pipeline.resolve_action(action_id)

    assert result["status"] == "completed"
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM resolution_bundles WHERE action_id = %s",
        (action_id,),
    ).fetchone()["c"] == 1
    event = test_db.execute(
        "SELECT event_type, payload FROM events "
        "WHERE action_id = %s AND event_type = 's2c_player_moved'",
        (action_id,),
    ).fetchone()
    assert event is not None
    assert event["payload"]["toNodeId"] == "vault"


def test_verified_ending_bundle_failure_rolls_back_campaign_terminal_state(
    client,
    test_db,
    monkeypatch,
):
    _, action_id = _confirmed_decision_action(client, test_db)
    action = dict(test_db.execute(
        "SELECT * FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone())
    test_db.execute(
        "UPDATE rooms SET status = 'active' WHERE room_id = %s",
        (action["room_id"],),
    )
    test_db.execute(
        "UPDATE actions SET status = 'resolving' WHERE action_id = %s",
        (action_id,),
    )
    test_db.commit()
    pipeline = ResolutionPipeline(test_db)
    ending = EndingDecision(
        ending_id="atomic-ending",
        ending_type="victory",
        citation={"source_ref": "page:1", "page_number": 1},
        room_status="active",
        priority=1,
        exclusive_group="campaign_ending",
    )
    resolution = ResolutionResult(
        actionId=action_id,
        roomId=action["room_id"],
        characterId=action["character_id"],
        isSuccess=True,
        narrative="verified ending",
    )

    def fail_bundle(*_args, **_kwargs):
        raise RuntimeError("forced-ending-bundle-failure")

    monkeypatch.setattr(pipeline, "_persist_resolution_bundle", fail_bundle)

    with pytest.raises(RuntimeError, match="forced-ending-bundle-failure"):
        pipeline._commit_verified_runtime_ending(
            action,
            ending,
            completion_status="completed",
            result=resolution.model_dump(by_alias=True),
            receipt={"verified": True},
            resolution=resolution,
            complete_current_action=True,
            revalidate=False,
        )

    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s",
        (action["room_id"],),
    ).fetchone()["status"] == "active"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["status"] == "resolving"
    assert test_db.execute(
        "SELECT 1 FROM campaign_archives WHERE room_id = %s",
        (action["room_id"],),
    ).fetchone() is None


@pytest.mark.asyncio
async def test_terminal_delta_is_written_once_at_action_commit(
    client,
    test_db,
    monkeypatch,
):
    from src.server.ai.decision_audit import DecisionAuditRecorder

    _, action_id = _confirmed_decision_action(client, test_db)
    original_finalize = DecisionAuditRecorder.finalize
    terminal_calls = 0

    def count_terminal_finalize(
        self,
        target_action_id,
        *,
        engine_validation,
        final_delta,
        task_type=None,
    ):
        nonlocal terminal_calls
        if isinstance(final_delta, dict) and "action_status" in final_delta:
            terminal_calls += 1
        return original_finalize(
            self,
            target_action_id,
            engine_validation=engine_validation,
            final_delta=final_delta,
            task_type=task_type,
        )

    monkeypatch.setattr(DecisionAuditRecorder, "finalize", count_terminal_finalize)

    result = await ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    ).resolve_action(action_id)

    assert result["status"] == "completed"
    assert terminal_calls == 1


@pytest.mark.asyncio
async def test_terminal_action_rolls_back_when_atomic_audit_finalize_fails(
    client,
    test_db,
    monkeypatch,
):
    from src.server.ai.decision_audit import DecisionAuditRecorder

    _, action_id = _confirmed_decision_action(client, test_db)
    original_finalize = DecisionAuditRecorder.finalize

    def fail_terminal_finalize(
        self,
        target_action_id,
        *,
        engine_validation,
        final_delta,
        task_type=None,
    ):
        if isinstance(final_delta, dict) and "action_status" in final_delta:
            raise RuntimeError("forced-terminal-audit-failure")
        return original_finalize(
            self,
            target_action_id,
            engine_validation=engine_validation,
            final_delta=final_delta,
            task_type=task_type,
        )

    monkeypatch.setattr(DecisionAuditRecorder, "finalize", fail_terminal_finalize)
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    )

    with pytest.raises(RuntimeError, match="decision_audit_finalize_failed"):
        await pipeline.resolve_action(action_id)

    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["status"] == "resolving"


@pytest.mark.asyncio
async def test_authoritative_post_effect_failure_does_not_complete_action_or_audit(
    client,
    test_db,
    monkeypatch,
):
    _, action_id = _confirmed_decision_action(client, test_db)
    params = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["params"]
    params = dict(params) if isinstance(params, dict) else json.loads(params)
    params.update({"fromNodeId": "hall", "targetNodeId": "vault"})
    test_db.execute(
        "UPDATE actions SET intent_type = 'move', params = %s WHERE action_id = %s",
        (json.dumps(params), action_id),
    )
    test_db.commit()
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    )

    async def valid_move(*_args, **_kwargs):
        return None

    async def fail_authoritative_effect(*_args, **_kwargs):
        raise RuntimeError("forced-authoritative-effect-failure")

    monkeypatch.setattr(pipeline, "_validate_director_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_validate_move", valid_move)
    monkeypatch.setattr(pipeline, "_apply_move_result", fail_authoritative_effect)

    with pytest.raises(RuntimeError, match="forced-authoritative-effect-failure"):
        await pipeline.resolve_action(action_id)

    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["status"] == "resolving"
    delta = test_db.execute(
        "SELECT final_delta FROM ai_call_logs "
        "WHERE action_id = %s AND task_type = 'analyze_director_action'",
        (action_id,),
    ).fetchone()["final_delta"]
    assert "action_status" not in delta


@pytest.mark.asyncio
async def test_terminal_delta_reads_map_position_after_authoritative_effects(
    client,
    test_db,
    monkeypatch,
):
    _, action_id = _confirmed_decision_action(client, test_db)
    action = test_db.execute(
        "SELECT character_id, params FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    params = dict(action["params"]) if isinstance(action["params"], dict) else json.loads(action["params"])
    params.update({"fromNodeId": "hall", "targetNodeId": "vault"})
    test_db.execute(
        "UPDATE actions SET intent_type = 'move', params = %s WHERE action_id = %s",
        (json.dumps(params), action_id),
    )
    test_db.commit()
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    )

    async def valid_move(*_args, **_kwargs):
        return None

    async def persist_map_position(*_args, **_kwargs):
        test_db.execute(
            "INSERT INTO character_map_positions "
            "(character_id, room_id, node_id, updated_at) "
            "SELECT character_id, room_id, 'vault', NOW() FROM actions "
            "WHERE action_id = %s "
            "ON CONFLICT (character_id, room_id) DO UPDATE "
            "SET node_id = EXCLUDED.node_id, updated_at = NOW()",
            (action_id,),
        )
        test_db.commit()

    monkeypatch.setattr(pipeline, "_validate_director_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_validate_move", valid_move)
    monkeypatch.setattr(pipeline, "_apply_move_result", persist_map_position)

    result = await pipeline.resolve_action(action_id)

    assert result["status"] == "completed"
    delta = test_db.execute(
        "SELECT final_delta FROM ai_call_logs "
        "WHERE action_id = %s AND task_type = 'analyze_director_action'",
        (action_id,),
    ).fetchone()["final_delta"]
    assert delta["authoritative_effects"]["map"] == {
        "character_id": action["character_id"],
        "position_node_id": "vault",
    }


def test_concurrent_moves_preserve_both_map_updates(client, test_db, monkeypatch):
    from src.server.db_adapter import PgConnection
    from src.server import map_persistence

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    players = [
        client.post(f"/api/player/rooms/{room_id}/join").json()
        for _ in range(2)
    ]
    test_db.execute(
        "INSERT INTO room_map_state (room_id, map_id) VALUES (%s, 'map-race')",
        (room_id,),
    )
    test_db.commit()

    first_reads = Barrier(2)
    thread_state = local()
    original_get_state = map_persistence.get_room_map_state

    def synchronize_first_state_read(conn, target_room_id):
        state = original_get_state(conn, target_room_id)
        if not getattr(thread_state, "read_once", False):
            thread_state.read_once = True
            try:
                first_reads.wait(timeout=0.3)
            except BrokenBarrierError:
                pass
        return state

    monkeypatch.setattr(
        map_persistence,
        "get_room_map_state",
        synchronize_first_state_read,
    )

    def move(character_id: str, node_id: str):
        conn = PgConnection(test_db._pool)
        try:
            pipeline = ResolutionPipeline(conn)
            with conn.transaction() as tx:
                asyncio.run(pipeline._apply_move_result(
                    {
                        "action_id": f"move-{character_id}",
                        "room_id": room_id,
                        "character_id": character_id,
                        "params": {
                            "fromNodeId": "start",
                            "targetNodeId": node_id,
                        },
                    },
                    None,
                    transaction=tx,
                    publish=False,
                ))
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(move, players[0]["character_id"], "library"),
            pool.submit(move, players[1]["character_id"], "vault"),
        ]
        for future in futures:
            future.result(timeout=5)

    state = test_db.execute(
        "SELECT explored_nodes, token_visibility FROM room_map_state "
        "WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert set(state["explored_nodes"]) == {"library", "vault"}
    assert state["token_visibility"] == {
        players[0]["character_id"]: "party",
        players[1]["character_id"]: "party",
    }


@pytest.mark.asyncio
async def test_no_mutation_combat_audit_captures_actor_and_queued_reaction(
    client,
    test_db,
    monkeypatch,
):
    room_id, action_id = _confirmed_decision_action(client, test_db)
    action = test_db.execute(
        "SELECT character_id FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    encounter_id = "audit-no-mutation-encounter"
    enemy_id = "npc:audit-no-mutation-enemy"
    test_db.execute(
        "UPDATE rooms SET status = 'active' WHERE room_id = %s",
        (room_id,),
    )
    test_db.execute(
        "UPDATE actions SET intent_type = 'combat_action', params = %s "
        "WHERE action_id = %s",
        (
            json.dumps({
                "encounterId": encounter_id,
                "actionKind": "wait",
                "visibility": "public",
            }),
            action_id,
        ),
    )
    test_db.execute(
        "INSERT INTO encounters "
        "(encounter_id, room_id, type, status, current_round) "
        "VALUES (%s, %s, 'combat', 'active', 1)",
        (encounter_id, room_id),
    )
    for character_id, side, label in (
        (action["character_id"], "player", "Investigator"),
        (enemy_id, "enemy", "Visible attacker"),
    ):
        test_db.execute(
            "INSERT INTO encounter_participants "
            "(encounter_id, character_id, side, hp, hp_max, acted_this_round, "
            "public_visibility, public_label) "
            "VALUES (%s, %s, %s, 10, 10, FALSE, 'visible', %s)",
            (encounter_id, character_id, side, label),
        )
    test_db.commit()

    pipeline = ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_director_plan",
        lambda *_args, **_kwargs: None,
    )

    result = await pipeline.resolve_action(action_id)

    assert result["status"] == "completed"
    delta = test_db.execute(
        "SELECT final_delta FROM ai_call_logs "
        "WHERE action_id = %s AND task_type = 'analyze_director_action'",
        (action_id,),
    ).fetchone()["final_delta"]
    encounter = delta["authoritative_effects"]["encounter"]
    assert encounter["participants"] == [{
        "character_id": action["character_id"],
        "hp": 10,
        "distance_band": "medium",
        "status_tags": [],
        "acted_this_round": True,
    }]
    pending = test_db.execute(
        "SELECT reaction_id FROM encounter_pending_reactions "
        "WHERE source_action_id = %s",
        (action_id,),
    ).fetchone()
    assert encounter["pending_reaction_ids"] == [pending["reaction_id"]]
    assert encounter["prepared_action_ids"] == []
    assert encounter["prepared_reaction_action_ids"] == []


@pytest.mark.asyncio
async def test_local_fallback_action_completes_without_decision_audit(
    client,
    test_db,
    monkeypatch,
):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    player = client.post(f"/api/player/rooms/{room_id}/join").json()
    previous_gateway = client.app.state.gateway
    client.app.state.gateway = None
    try:
        analyzed = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player["player_token"]},
            json={"declared_intent": "I inspect the visible label."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert analyzed.status_code == 200, analyzed.text
    draft = analyzed.json()
    assert draft["analysis_source"] == "local_fallback"
    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={
            "X-Room-Token": player["player_token"],
            "Idempotency-Key": f"local-audit-{draft['draft_id']}",
        },
        json={"confirmations": draft["confirmation_requirements"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    action_id = confirmed.json()["action_id"]
    test_db.execute(
        "UPDATE actions SET status = 'queued' WHERE action_id = %s",
        (action_id,),
    )
    test_db.commit()
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM ai_call_logs WHERE action_id = %s",
        (action_id,),
    ).fetchone()["c"] == 0

    pipeline = ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    )
    monkeypatch.setattr(pipeline, "_validate_director_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_is_host_connected", lambda *_args, **_kwargs: True)

    result = await pipeline.resolve_action(action_id)

    assert result["status"] == "completed", result


@pytest.mark.asyncio
async def test_ai_action_terminal_fails_closed_if_decision_audit_disappears(
    client,
    test_db,
    monkeypatch,
):
    from src.server.ai.decision_audit import DecisionAuditPersistenceError

    _, action_id = _confirmed_decision_action(client, test_db)
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    )
    original_finalize = pipeline._finalize_decision_audit
    director_validated = False

    def remove_audit_after_director_validation(
        target_action_id,
        *,
        engine_validation,
        final_delta,
        task_type=None,
        transaction=None,
    ):
        nonlocal director_validated
        result = original_finalize(
            target_action_id,
            engine_validation=engine_validation,
            final_delta=final_delta,
            task_type=task_type,
            transaction=transaction,
        )
        if task_type == "analyze_director_action" and not director_validated:
            director_validated = True
            test_db.execute(
                "DELETE FROM ai_call_logs WHERE action_id = %s",
                (target_action_id,),
            )
            test_db.commit()
        return result

    monkeypatch.setattr(
        pipeline,
        "_finalize_decision_audit",
        remove_audit_after_director_validation,
    )

    with pytest.raises(DecisionAuditPersistenceError):
        await pipeline.resolve_action(action_id)

    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["status"] == "resolving"


@pytest.mark.asyncio
async def test_authoritative_effect_rolls_back_with_terminal_audit_failure(
    client,
    test_db,
    monkeypatch,
):
    from src.server.ai.decision_audit import DecisionAuditRecorder

    _, action_id = _confirmed_decision_action(client, test_db)
    params = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["params"]
    params = dict(params) if isinstance(params, dict) else json.loads(params)
    params.update({"fromNodeId": "hall", "targetNodeId": "vault"})
    test_db.execute(
        "UPDATE actions SET intent_type = 'move', params = %s WHERE action_id = %s",
        (json.dumps(params), action_id),
    )
    test_db.commit()
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    )

    async def valid_move(*_args, **_kwargs):
        return None

    async def persist_position(
        *_args,
        transaction=None,
        publish=True,
        **_kwargs,
    ):
        executor = transaction or test_db
        executor.execute(
            "INSERT INTO character_map_positions "
            "(character_id, room_id, node_id, updated_at) "
            "SELECT character_id, room_id, 'vault', NOW() FROM actions "
            "WHERE action_id = %s",
            (action_id,),
        )
        if transaction is None:
            test_db.commit()
        return []

    original_finalize = DecisionAuditRecorder.finalize

    def fail_terminal_finalize(
        self,
        target_action_id,
        *,
        engine_validation,
        final_delta,
        task_type=None,
    ):
        if isinstance(final_delta, dict) and "action_status" in final_delta:
            raise RuntimeError("forced-terminal-audit-failure")
        return original_finalize(
            self,
            target_action_id,
            engine_validation=engine_validation,
            final_delta=final_delta,
            task_type=task_type,
        )

    monkeypatch.setattr(pipeline, "_validate_director_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_validate_move", valid_move)
    monkeypatch.setattr(pipeline, "_apply_move_result", persist_position)
    monkeypatch.setattr(DecisionAuditRecorder, "finalize", fail_terminal_finalize)

    with pytest.raises(RuntimeError, match="decision_audit_finalize_failed"):
        await pipeline.resolve_action(action_id)

    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["status"] == "resolving"
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM character_map_positions "
        "WHERE room_id = (SELECT room_id FROM actions WHERE action_id = %s) "
        "AND character_id = (SELECT character_id FROM actions WHERE action_id = %s)",
        (action_id, action_id),
    ).fetchone()["c"] == 0


def test_director_draft_finalize_failure_is_fail_closed(
    client,
    test_db,
    monkeypatch,
):
    from src.server.ai.decision_audit import (
        DecisionAuditPersistenceError,
        DecisionAuditRecorder,
    )

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    player = client.post(f"/api/player/rooms/{room_id}/join").json()
    gateway = AiGateway(db_conn=test_db)
    gateway._get_ordered_providers = lambda _room_id=None: [_DecisionProvider()]
    previous_gateway = client.app.state.gateway
    client.app.state.gateway = gateway
    monkeypatch.setattr(DecisionAuditRecorder, "finalize", lambda *_args, **_kwargs: 0)

    try:
        with pytest.raises(
            DecisionAuditPersistenceError,
            match="decision_audit_finalize_failed",
        ):
            client.post(
                "/api/player/action-drafts/analyze",
                headers={"X-Room-Token": player["player_token"]},
                json={"declared_intent": "I inspect the visible label."},
            )
    finally:
        client.app.state.gateway = previous_gateway

    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM action_drafts WHERE room_id = %s",
        (room_id,),
    ).fetchone()["c"] == 0


def test_director_timeout_falls_back_without_requiring_missing_audit(
    client,
    test_db,
    monkeypatch,
):
    import asyncio

    class SlowAuditedGateway:
        authoritative_audit_required = True

        async def analyze_director_action(self, *_args, **_kwargs):
            await asyncio.sleep(0.05)
            return None

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    player = client.post(f"/api/player/rooms/{room_id}/join").json()
    previous_gateway = client.app.state.gateway
    client.app.state.gateway = SlowAuditedGateway()
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._DIRECTOR_ANALYSIS_TIMEOUT_SECONDS",
        0.001,
    )

    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player["player_token"]},
            json={"declared_intent": "I inspect the visible door."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200, response.text
    assert response.json()["analysis_source"] == "local_fallback"
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM ai_call_logs WHERE room_id = %s",
        (room_id,),
    ).fetchone()["c"] == 0


def test_ai_draft_confirmation_fails_closed_when_audit_is_missing(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    player = client.post(f"/api/player/rooms/{room_id}/join").json()
    gateway = AiGateway(db_conn=test_db)
    gateway._get_ordered_providers = lambda _room_id=None: [_DecisionProvider()]
    previous_gateway = client.app.state.gateway
    client.app.state.gateway = gateway
    try:
        analyzed = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player["player_token"]},
            json={"declared_intent": "I inspect the visible label."},
        )
    finally:
        client.app.state.gateway = previous_gateway
    assert analyzed.status_code == 200
    draft = analyzed.json()
    test_db.execute(
        "DELETE FROM ai_call_logs WHERE action_id = %s",
        (draft["draft_id"],),
    )
    test_db.commit()

    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={
            "X-Room-Token": player["player_token"],
            "Idempotency-Key": "missing-decision-audit",
        },
        json={"confirmations": draft["confirmation_requirements"]},
    )

    assert confirmed.status_code == 409
    assert confirmed.json()["detail"]["code"] == "decision_audit_missing"
    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM actions WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()["c"] == 0


def test_verified_ending_rolls_back_when_atomic_audit_finalize_fails(
    client,
    test_db,
    monkeypatch,
):
    from src.server.ai.decision_audit import (
        DecisionAuditPersistenceError,
        DecisionAuditRecorder,
    )

    room_id, action_id = _confirmed_decision_action(client, test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active' WHERE room_id = %s",
        (room_id,),
    )
    test_db.execute(
        "UPDATE actions SET status = 'resolving' WHERE action_id = %s",
        (action_id,),
    )
    test_db.commit()
    action = dict(test_db.execute(
        "SELECT * FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone())
    ending = EndingDecision(
        ending_id="atomic-audit-ending",
        ending_type="success",
        citation={"source": "compiled-test-ending"},
        room_status="active",
        priority=100,
        exclusive_group="campaign_ending",
    )
    original_finalize = DecisionAuditRecorder.finalize

    def fail_ending_finalize(
        self,
        target_action_id,
        *,
        engine_validation,
        final_delta,
        task_type=None,
    ):
        if isinstance(final_delta, dict) and final_delta.get("ending_id"):
            raise RuntimeError("forced-ending-audit-failure")
        return original_finalize(
            self,
            target_action_id,
            engine_validation=engine_validation,
            final_delta=final_delta,
            task_type=task_type,
        )

    monkeypatch.setattr(DecisionAuditRecorder, "finalize", fail_ending_finalize)

    with pytest.raises(
        DecisionAuditPersistenceError,
        match="decision_audit_finalize_failed",
    ):
        ResolutionPipeline(test_db)._commit_verified_runtime_ending(
            action,
            ending,
            completion_status="completed",
            result={"status": "completed"},
            receipt={"verified": True},
            resolution=ResolutionResult(
                actionId=action_id,
                roomId=room_id,
                characterId=action["character_id"],
                isSuccess=True,
                narrative="verified ending",
            ),
            complete_current_action=True,
            revalidate=False,
        )

    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["status"] == "resolving"
    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["status"] == "active"
    assert test_db.execute(
        "SELECT archive_id FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone() is None


@pytest.mark.asyncio
async def test_failed_authoritative_provider_call_is_short_lived_diagnostic(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('diagnostic-room', 'owner', 'active')"
    )
    test_db.commit()
    gateway = AiGateway(db_conn=test_db)
    gateway._get_ordered_providers = lambda _room_id=None: [_UnavailableProvider()]

    result = await gateway.analyze_director_action(
        {
            "context_version": 1,
            "declared_intent": "inspect",
            "actor_display_name": "Ada",
            "local_analysis": {"draft_id": "diagnostic-draft"},
        },
        room_id="diagnostic-room",
    )

    assert result is None
    row = test_db.execute(
        "SELECT record_kind, decision_audit_id, error_message FROM ai_call_logs "
        "WHERE room_id = 'diagnostic-room'"
    ).fetchone()
    assert row == {
        "record_kind": "diagnostic",
        "decision_audit_id": None,
        "error_message": "",
    }


@pytest.mark.asyncio
async def test_narrator_decision_audit_keeps_redacted_citation_and_rule_version(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('narrator-audit-room', 'owner', 'active')"
    )
    test_db.commit()
    gateway = AiGateway(db_conn=test_db)
    gateway._get_ordered_providers = lambda _room_id=None: [_NarratorDecisionProvider()]

    result = await gateway.narrate_action(
        {
            "context_version": 4,
            "director_plan_digest": "digest-v1",
            "rule_version": "coc7.rules.v7",
            "allowed_facts": [{
                "fact_ref": "fact:scene-brief",
                "text": "The visible door remains closed.",
            }],
            "visible_state_changes": ["The room remains quiet."],
            "interactable_objects": ["visible door"],
        },
        room_id="narrator-audit-room",
        action_id="narrator-audit-action",
    )

    assert result is not None
    audit = test_db.execute(
        "SELECT citations, rule_version, structured_proposal FROM ai_call_logs "
        "WHERE action_id = 'narrator-audit-action'"
    ).fetchone()
    assert audit["rule_version"] == "coc7.rules.v7"
    assert audit["citations"] == [{
        "label": "Scene evidence",
        "page": 7,
        "scene": "waiting-room",
        "verified": True,
    }]
    assert set(audit["structured_proposal"]) == {
        "context_version",
        "director_plan_digest",
        "fact_refs",
        "redacted_citations",
        "style_pack_version",
        "provider_source",
        "status",
    }
    assert "The visible door remains closed." not in json.dumps(
        audit["structured_proposal"],
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_authoritative_audit_failure_is_fail_closed_and_rolls_back(
    test_db,
    monkeypatch,
):
    from src.server.ai.decision_audit import DecisionAuditRecorder

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('audit-fail-room', 'owner', 'active')"
    )
    test_db.commit()
    gateway = AiGateway(db_conn=test_db)
    gateway._get_ordered_providers = lambda _room_id=None: [_DecisionProvider()]
    original_record = DecisionAuditRecorder.record

    def record_then_fail(self, **kwargs):
        original_record(self, **kwargs)
        raise RuntimeError("forced-audit-write-failure")

    monkeypatch.setattr(DecisionAuditRecorder, "record", record_then_fail)

    with pytest.raises(RuntimeError, match="authoritative_decision_audit_failed"):
        await gateway.analyze_director_action(
            {
                "context_version": 1,
                "declared_intent": "inspect",
                "actor_display_name": "Ada",
                "local_analysis": {"draft_id": "audit-fail-draft"},
            },
            room_id="audit-fail-room",
        )

    assert test_db.execute(
        "SELECT COUNT(*) AS c FROM ai_call_logs WHERE room_id = 'audit-fail-room'"
    ).fetchone()["c"] == 0


@pytest.mark.asyncio
async def test_authoritative_schema_error_does_not_log_provider_values(
    test_db,
    caplog,
):
    gateway = AiGateway(db_conn=test_db)
    gateway._get_ordered_providers = lambda _room_id=None: [_InvalidDecisionProvider()]

    result = await gateway.analyze_director_action(
        {
            "context_version": 1,
            "declared_intent": "inspect",
            "actor_display_name": "Ada",
            "local_analysis": {"draft_id": "invalid-audit-draft"},
        },
        room_id=None,
    )

    assert result is None
    assert "audit-validation-secret-sentinel" not in caplog.text
