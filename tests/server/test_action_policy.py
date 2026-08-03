from src.server.engine.action_policy import evaluate_action_policy
from src.server.models import ActionDraftAnalyzeRequest
from src.server.player.action_service import analyze_action_draft
from tests.server.conftest import create_room, setup_auth_test_data


def test_private_mechanical_move_is_rejected_with_public_reproposal():
    decision = evaluate_action_policy(
        {
            "intent_type": "move",
            "declared_intent": "我偷偷去地下室",
            "visibility": "private",
            "target": "地下室",
            "params": {"secretMove": True},
        },
        current_state={},
        risk_contract={},
    )

    assert decision.outcome == "reject"
    assert decision.reason_code == "private_mechanical_action_forbidden"
    assert decision.candidates == [
        {
            "label": "公开提出前往地下室",
            "interpreted_intent": "public_reproposal",
            "visibility": "public",
        },
        {
            "label": "取消行动，不产生任何效果",
            "interpreted_intent": "cancel_action",
            "visibility": "private",
        },
    ]


def test_private_inner_thought_is_non_mechanical_and_has_no_world_effect():
    draft = analyze_action_draft(
        ActionDraftAnalyzeRequest(declared_intent="我在心里害怕，但没有采取行动")
    )

    assert draft.intent_type == "dialogue"
    assert draft.visibility == "private"
    assert draft.risk == "low"
    assert draft.confirmation_requirements == []
    assert draft.resource_impacts == []
    assert draft.params["nonMechanical"] is True


def test_player_claim_of_existing_fact_requires_clarification_without_state_delta():
    draft = analyze_action_draft(
        ActionDraftAnalyzeRequest(declared_intent="我已经拿到地下室钥匙")
    )

    assert draft.status == "analyzing"
    assert draft.adjudication_stage == "player_clarification_required"
    assert draft.confirmation_requirements == []
    assert draft.resource_impacts == []
    assert 2 <= len(draft.candidate_interpretations) <= 3
    assert {item["interpreted_intent"] for item in draft.candidate_interpretations} == {
        "attempt_to_acquire",
        "ask_about_possession",
        "cancel_action",
    }


def test_material_ambiguity_returns_bounded_engine_filtered_candidates():
    decision = evaluate_action_policy(
        {
            "intent_type": "skill_check",
            "declared_intent": "我检查它",
            "visibility": "public",
            "ambiguities": ["target", "skill", "risk"],
            "candidate_interpretations": [
                {"label": "检查门锁并承担普通失败风险", "interpreted_intent": "inspect_lock"},
                {"label": "检查伤员并消耗急救包", "interpreted_intent": "treat_injury"},
                {"label": "我已经成功并获得秘密", "interpreted_intent": "assert_success"},
                {"label": "取消", "interpreted_intent": "cancel_action"},
            ],
        },
        current_state={},
        risk_contract={},
    )

    assert decision.outcome == "clarify"
    assert 2 <= len(decision.candidates) <= 3
    assert "assert_success" not in {
        item["interpreted_intent"] for item in decision.candidates
    }


def test_reversible_decorative_ambiguity_is_allowed_with_disclosure():
    decision = evaluate_action_policy(
        {
            "intent_type": "dialogue",
            "declared_intent": "我把外套挂在附近",
            "visibility": "public",
            "ambiguities": ["decorative_position"],
            "ambiguity_scope": "decorative",
        },
        current_state={},
        risk_contract={},
    )

    assert decision.outcome == "allow"
    assert decision.disclosures == ["按可逆装饰性解释处理；不会改变资源、线索或规则状态"]


def test_timeout_policy_never_draws_randomness_or_spends_resources():
    investigation = evaluate_action_policy(
        {"intent_type": "skill_check", "declared_intent": "调查门锁"},
        current_state={"phase": "investigation"},
        risk_contract={},
        timed_out=True,
    )
    combat = evaluate_action_policy(
        {
            "intent_type": "combat_action",
            "declared_intent": "攻击",
            "params": {"timeoutChoice": "withdraw"},
        },
        current_state={"phase": "combat"},
        risk_contract={},
        timed_out=True,
    )

    assert investigation.outcome == "timeout_safe_effect"
    assert investigation.safe_effect == {
        "effect": "cancel",
        "mechanical_delta": [],
        "rng_draws": [],
    }
    assert combat.safe_effect == {
        "effect": "withdraw",
        "mechanical_delta": [],
        "rng_draws": [],
    }


def test_private_move_stops_before_ai_and_cannot_be_confirmed(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    player = client.post(f"/api/player/rooms/{room['room_id']}/join").json()

    class _Gateway:
        called = False

        async def analyze_director_action(self, *_args, **_kwargs):
            self.called = True
            return {}

    gateway = _Gateway()
    previous = client.app.state.gateway
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player["player_token"]},
            json={"declared_intent": "我偷偷前往地下室"},
        )
    finally:
        client.app.state.gateway = previous

    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["status"] == "analyzing"
    assert draft["adjudication_stage"] == "player_clarification_required"
    assert draft["candidate_interpretations"][0]["visibility"] == "public"
    assert gateway.called is False

    confirmation = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={
            "X-Room-Token": player["player_token"],
            "Idempotency-Key": "private-move-must-not-run",
        },
        json={"confirmations": []},
    )
    assert confirmation.status_code == 409
    assert confirmation.json()["detail"]["code"] == "draft_not_confirmable"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM actions WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["count"] == 0

    test_db.execute(
        "UPDATE action_drafts SET status = 'awaiting_confirmation' WHERE draft_id = %s",
        (draft["draft_id"],),
    )
    test_db.commit()
    bypass = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={
            "X-Room-Token": player["player_token"],
            "Idempotency-Key": "private-move-policy-recheck",
        },
        json={"confirmations": []},
    )
    assert bypass.status_code == 409
    assert bypass.json()["detail"] == {
        "code": "action_policy_rejected",
        "reason": "private_mechanical_action_forbidden",
    }


def test_expired_investigation_draft_is_atomically_canceled_without_action(client, test_db):
    from src.server.ai.decision_audit import DecisionAuditRecorder

    setup_auth_test_data(test_db)
    room = create_room(client)
    player = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    headers = {"X-Room-Token": player["player_token"]}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我检查门锁"},
    ).json()
    audit_id = DecisionAuditRecorder(test_db).record(
        room_id=room["room_id"],
        action_id=draft["draft_id"],
        draft_id=draft["draft_id"],
        draft_revision=draft["revision"],
        task_type="analyze_director_action",
        provider="draft-terminal-test",
        model="deterministic",
    )
    test_db.execute(
        "UPDATE action_drafts SET expires_at = NOW() - INTERVAL '1 second' "
        "WHERE draft_id = %s",
        (draft["draft_id"],),
    )
    test_db.commit()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "expired-investigation"},
        json={"confirmations": draft["confirmation_requirements"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "draft_timed_out",
        "safe_effect": {
            "effect": "cancel",
            "mechanical_delta": [],
            "rng_draws": [],
        },
    }
    stored = test_db.execute(
        "SELECT status, analysis FROM action_drafts WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert stored["status"] == "timeout"
    assert stored["analysis"]["timeout_safe_effect"]["effect"] == "cancel"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM actions WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["count"] == 0
    audit = test_db.execute(
        "SELECT action_id, audit_state, final_delta FROM ai_call_logs "
        "WHERE decision_audit_id = %s",
        (audit_id,),
    ).fetchone()
    assert audit["action_id"] is None
    assert audit["audit_state"] == "expired"
    assert audit["final_delta"] == {
        "draft_status": "timeout",
        "reason_code": "draft_timed_out",
        "draft_revision": draft["revision"],
        "safe_effect": {
            "effect": "cancel",
            "mechanical_delta": [],
            "rng_draws": [],
        },
    }


def test_expired_combat_draft_uses_declared_safe_withdraw_without_rng(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    player = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    headers = {"X-Room-Token": player["player_token"]}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "我攻击逼近的人影",
            "params": {"timeoutChoice": "withdraw"},
        },
    ).json()
    test_db.execute(
        "UPDATE action_drafts SET expires_at = NOW() - INTERVAL '1 second' "
        "WHERE draft_id = %s",
        (draft["draft_id"],),
    )
    test_db.commit()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "expired-combat"},
        json={"confirmations": draft["confirmation_requirements"]},
    )

    assert response.status_code == 409
    safe_effect = response.json()["detail"]["safe_effect"]
    assert safe_effect == {
        "effect": "withdraw",
        "mechanical_delta": [],
        "rng_draws": [],
    }
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM actions WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["count"] == 0


def test_one_players_clarification_does_not_block_another_safe_action(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    first = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    second = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    first_draft = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": first["player_token"]},
        json={"declared_intent": "我已经找到那把钥匙"},
    ).json()
    second_draft = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": second["player_token"]},
        json={"declared_intent": "我检查公开的告示牌"},
    ).json()

    accepted = client.post(
        f"/api/player/action-drafts/{second_draft['draft_id']}/confirm",
        headers={
            "X-Room-Token": second["player_token"],
            "Idempotency-Key": "second-safe-action",
        },
        json={"confirmations": second_draft["confirmation_requirements"]},
    )

    assert first_draft["status"] == "analyzing"
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["action_id"]
    assert test_db.execute(
        "SELECT status FROM action_drafts WHERE draft_id = %s",
        (first_draft["draft_id"],),
    ).fetchone()["status"] == "analyzing"
