import json

import pytest

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.host_autonomy import decide_host_autonomy


class _Dispatcher:
    def __init__(self):
        self.events = []

    async def emit(self, room_id, event_type, audience, payload, **kwargs):
        self.events.append((room_id, event_type, audience, payload, kwargs))


def test_delegated_host_absence_allows_only_safe_verifiable_actions():
    decision = decide_host_autonomy(
        policy="delegated",
        host_connected=False,
        intent_type="move",
        params={
            "targetNodeId": "hall",
            "fromNodeId": "foyer",
            "analysis": {"risk": "medium", "visibility": "public"},
        },
    )

    assert decision.route == "offline_autonomy"
    assert decision.reason_code is None


def test_host_absence_defers_sensitive_or_undelegated_actions():
    combat = decide_host_autonomy(
        policy="delegated",
        host_connected=False,
        intent_type="combat_action",
        params={"analysis": {"risk": "high", "visibility": "public"}},
    )
    secret = decide_host_autonomy(
        policy="delegated",
        host_connected=False,
        intent_type="move",
        params={
            "targetNodeId": "hidden-room",
            "analysis": {"risk": "high", "visibility": "private"},
        },
    )
    unplanned = decide_host_autonomy(
        policy="host_required",
        host_connected=False,
        intent_type="skill_check",
        params={"analysis": {"risk": "medium", "visibility": "public"}},
    )

    assert combat.route == "deferred_host_review"
    assert secret.route == "deferred_host_review"
    assert unplanned.route == "deferred_host_review"
    assert combat.reason_code == "host_offline_policy"


def test_ai_only_host_absence_never_routes_to_human_review():
    public_move = decide_host_autonomy(
        policy="host_required",
        session_mode="ai_only",
        host_connected=False,
        intent_type="move",
        params={
            "targetNodeId": "hall",
            "analysis": {"risk": "medium", "visibility": "public"},
        },
    )
    sensitive_attack = decide_host_autonomy(
        policy="host_required",
        session_mode="ai_only",
        host_connected=False,
        intent_type="combat_action",
        params={"analysis": {"risk": "high", "visibility": "public"}},
    )

    assert public_move.route == "offline_autonomy"
    assert sensitive_attack.route == "engine_policy"
    assert sensitive_attack.reason_code == "ai_only_policy_required"


@pytest.mark.asyncio
async def test_offline_policy_pauses_sensitive_action_before_any_state_or_projection(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, host_autonomy_policy) "
        "VALUES ('offline-room', 'owner', 'delegated')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('offline-character', 'offline-room', '玩家', 'token')"
    )
    params = {
        "analysis": {
            "risk": "high",
            "visibility": "public",
            "confirmation_requirements": ["attack", "state_change"],
        },
        "director_plan": {
            "context_version": 0,
            "preconditions": [],
            "permissions": [],
            "state_patch": [],
            "state_patch_authority": "advisory_only",
        },
    }
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, draft_id, intent_type, "
        "declared_intent, params, status) VALUES "
        "('offline-action', 'offline-room', 'offline-character', 'draft', 'combat_action', "
        "'我向人影开枪', %s, 'queued')",
        (json.dumps(params, ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('offline-action', 'queued', '{}')"
    )
    dispatcher = _Dispatcher()
    pipeline = ResolutionPipeline(
        test_db,
        dispatcher=dispatcher,
        host_connection_checker=lambda _room_id: False,
    )

    result = await pipeline.resolve_action("offline-action")

    assert result == {
        "status": "awaiting_host_exception",
        "action_id": "offline-action",
        "reason": "host_offline_policy",
    }
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'offline-action'"
    ).fetchone()["status"] == "awaiting_host_exception"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM resolution_bundles WHERE action_id = 'offline-action'"
    ).fetchone()["count"] == 0
    statuses = test_db.execute(
        "SELECT status FROM action_status_events WHERE action_id = 'offline-action' "
        "ORDER BY status_event_id"
    ).fetchall()
    assert [row["status"] for row in statuses] == [
        "queued",
        "resolving",
        "awaiting_host_exception",
    ]
    assert any(event[1] == "s2c_action_exception_requested" for event in dispatcher.events)
    assert (
        "offline-room",
        "s2c_action_deferred",
        "player",
        {
            "actionId": "offline-action",
            "status": "awaiting_host_exception",
            "reasonCode": "host_offline_policy",
        },
        {"character_id": "offline-character"},
    ) in dispatcher.events
