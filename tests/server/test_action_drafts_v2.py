from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.server.db_adapter import PgConnection
from src.server.player.action_service import confirm_action_draft
from tests.server.conftest import create_room, setup_auth_test_data


def _setup_player(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    return room_id, joined["character_id"], joined["player_token"]


def test_analyze_stateful_action_requires_confirmation_and_persists(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={"declared_intent": "我用手枪射击门后的怪物"},
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["draft_id"]
    assert draft["status"] == "awaiting_confirmation"
    assert draft["intent_type"] == "combat_action"
    assert draft["risk"] == "high"
    assert draft["requires_confirmation"] is True
    assert "attack" in draft["confirmation_requirements"]
    assert draft["analysis_source"] == "local_fallback"

    row = test_db.execute(
        "SELECT room_id, character_id, status, risk_level, current_revision "
        "FROM action_drafts WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert dict(row) == {
        "room_id": room_id,
        "character_id": character_id,
        "status": "awaiting_confirmation",
        "risk_level": "high",
        "current_revision": 1,
    }
    revision = test_db.execute(
        "SELECT revision_number, declared_intent FROM action_draft_revisions WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert dict(revision) == {
        "revision_number": 1,
        "declared_intent": "我用手枪射击门后的怪物",
    }


def test_ephemeral_idle_analysis_never_persists_text(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={
            "declared_intent": "我看看桌上的旧报纸",
            "ephemeral": True,
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["draft_id"] is None
    assert draft["ephemeral"] is True
    assert draft["risk"] == "low"
    assert draft["requires_confirmation"] is False
    assert draft["confirmation_requirements"] == []
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_draft_revisions").fetchone()["count"] == 0


def test_persisted_draft_and_first_revision_are_atomic(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    test_db.executescript(
        """
        CREATE OR REPLACE FUNCTION reject_action_draft_revision() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'revision rejected for atomicity test';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER reject_action_draft_revision_trigger
        BEFORE INSERT ON action_draft_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_action_draft_revision();
        """
    )

    try:
        with pytest.raises(Exception, match="revision rejected for atomicity test"):
            client.post(
                "/api/player/action-drafts/analyze",
                headers={"X-Room-Token": player_token},
                json={"declared_intent": "我看看桌上的旧报纸"},
            )
    finally:
        test_db.executescript(
            "DROP TRIGGER IF EXISTS reject_action_draft_revision_trigger ON action_draft_revisions; "
            "DROP FUNCTION IF EXISTS reject_action_draft_revision();"
        )

    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0


def test_action_analysis_requires_player_token(client):
    response = client.post(
        "/api/player/action-drafts/analyze",
        json={"declared_intent": "我向前走"},
    )

    assert response.status_code == 401


def test_patch_draft_reanalyzes_and_keeps_revision_history(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    created = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()

    response = client.patch(
        f"/api/player/action-drafts/{created['draft_id']}",
        headers=headers,
        json={"declared_intent": "我用手枪射击门后的怪物"},
    )

    assert response.status_code == 200
    revised = response.json()
    assert revised["revision"] == 2
    assert revised["risk"] == "high"
    rows = test_db.execute(
        "SELECT revision_number, declared_intent FROM action_draft_revisions "
        "WHERE draft_id = %s ORDER BY revision_number",
        (created["draft_id"],),
    ).fetchall()
    assert [row["revision_number"] for row in rows] == [1, 2]
    assert rows[0]["declared_intent"] == "我看看桌上的旧报纸"
    assert rows[1]["declared_intent"] == "我用手枪射击门后的怪物"


def test_confirm_draft_is_idempotent_and_records_timeline(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我用手枪射击门后的怪物"},
    ).json()
    confirm_headers = {**headers, "Idempotency-Key": "confirm-shot-1"}
    body = {"confirmations": ["attack", "state_change"]}

    first = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers=confirm_headers,
        json=body,
    )
    second = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers=confirm_headers,
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["action_id"] == second.json()["action_id"]
    assert first.json()["status"] == "queued"
    assert first.json()["can_cancel"] is True
    assert first.json()["timeline"][0]["status"] == "queued"
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 1


def test_confirm_draft_is_idempotent_under_concurrent_requests(client, test_db, monkeypatch):
    _, character_id, player_token = _setup_player(client, test_db)
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    character = dict(
        test_db.execute(
            "SELECT * FROM characters WHERE character_id = %s",
            (character_id,),
        ).fetchone()
    )
    initial_reads = Barrier(2)
    original_execute = PgConnection.execute

    def synchronized_execute(conn, sql, params=None):
        result = original_execute(conn, sql, params)
        if (
            "SELECT action_id, draft_id FROM actions WHERE character_id" in sql
            and not getattr(conn, "_idempotency_read_synchronized", False)
        ):
            conn._idempotency_read_synchronized = True
            initial_reads.wait(timeout=5)
        return result

    monkeypatch.setattr(PgConnection, "execute", synchronized_execute)

    def confirm_once():
        conn = PgConnection(test_db._pool)
        try:
            return confirm_action_draft(
                conn,
                character,
                draft["draft_id"],
                "concurrent-confirm",
                [],
            )
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(lambda _: confirm_once(), range(2)))

    assert receipts[0].action_id == receipts[1].action_id
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 1


def test_confirm_rejects_missing_required_confirmation(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我用手枪射击门后的怪物"},
    ).json()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "missing-confirmation"},
        json={"confirmations": ["attack"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "confirmation_required"
    assert response.json()["detail"]["missing"] == ["state_change"]


def test_luck_spend_and_pushed_roll_require_explicit_second_confirmation(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}

    luck = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我想花幸运把失败改成成功"},
    ).json()
    pushed = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我选择孤注一掷重新检定"},
    ).json()

    assert luck["risk"] == "high"
    assert "luck_spend" in luck["confirmation_requirements"]
    assert luck["resource_impacts"] == [
        {"kind": "luck", "direction": "decrease", "amount": "pending_roll"}
    ]
    assert pushed["risk"] == "high"
    assert pushed["confirmation_requirements"] == [
        "pushed_roll",
        "irreversible_consequence",
    ]


def test_ambiguous_local_fallback_routes_to_host_exception_without_state_change(
    client,
    test_db,
):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    before_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"]
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我尝试用一种无法确定规则的方式改变现实"},
    ).json()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "ambiguous-action"},
        json={"confirmations": ["stateful_action"]},
    )

    assert draft["resolution_route"] == "host_exception"
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["status"] == "awaiting_host_exception"
    assert [event["status"] for event in receipt["timeline"]] == [
        "queued",
        "resolving",
        "awaiting_host_exception",
    ]
    after_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"]
    assert after_version == before_version


def test_confirming_stale_draft_requires_sync_and_creates_no_action(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    assert draft["base_state_version"] == 0
    test_db.execute(
        "UPDATE rooms SET state_version = 1 WHERE room_id = %s",
        (room_id,),
    )

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "stale-draft"},
        json={"confirmations": []},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "sync_required",
        "base_state_version": 0,
        "current_state_version": 1,
    }
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0


def test_host_exception_queue_is_owner_only_and_can_request_player_choice(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    room = test_db.execute(
        "SELECT owner_token FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我用无法确定规则的方式改变现实"},
    ).json()
    action = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "host-exception"},
        json={"confirmations": ["stateful_action"]},
    ).json()

    denied = client.get(
        f"/api/host/{room_id}/action-exceptions",
        headers={"X-Owner-Token": "wrong"},
    )
    listed = client.get(
        f"/api/host/{room_id}/action-exceptions",
        headers={"X-Owner-Token": room["owner_token"]},
    )
    resolved = client.post(
        f"/api/host/{room_id}/action-exceptions/{action['action_id']}/resolve",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"decision": "request_player_choice", "reason": "请说明具体实现方式"},
    )

    assert denied.status_code == 403
    assert listed.status_code == 200
    assert [item["action_id"] for item in listed.json()["items"]] == [action["action_id"]]
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "awaiting_player_choice"
    receipt = client.get(
        f"/api/player/actions/{action['action_id']}",
        headers=headers,
    ).json()
    assert receipt["timeline"][-1]["status"] == "awaiting_player_choice"


def test_configured_ai_analysis_is_structured_and_cannot_change_player_text(
    client,
    test_db,
):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            assert context["declared_intent"] == "我悄悄前往图书馆"
            return {
                "understanding_summary": "玩家想秘密移动到图书馆",
                "risk": "high",
                "intent_type": "move",
                "suggested_skill": "潜行",
                "difficulty": "hard",
                "resource_impacts": [],
                "visibility": "private",
                "movement_target": "图书馆",
                "confirmation_requirements": [
                    "movement",
                    "secret_action",
                    "state_change",
                ],
                "confidence": 0.94,
                "citations": [{"source_ref": "scenario#library"}],
                "declared_intent": "AI 不得覆盖原文",
                "mutations": [{"op": "replace", "path": "/character/luck", "value": 0}],
            }

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我悄悄前往图书馆"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["analysis_source"] == "configured_provider"
    assert draft["resolution_route"] == "ai"
    assert draft["declared_intent"] == "我悄悄前往图书馆"
    assert draft["movement_target"] == "图书馆"
    assert draft["citations"] == [{"source_ref": "scenario#library"}]
    assert "mutations" not in draft


def test_ai_analysis_failure_keeps_local_host_exception_fallback(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            raise RuntimeError("provider unavailable")

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我用无法确定规则的方式改变现实"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    assert response.json()["analysis_source"] == "local_fallback"
    assert response.json()["resolution_route"] == "host_exception"


def test_ai_analysis_cannot_lower_local_risk_or_remove_confirmations(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            return {
                "understanding_summary": "普通交流",
                "risk": "low",
                "intent_type": "dialogue",
                "confirmation_requirements": [],
                "confidence": 0.99,
            }

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我用手枪射击门后的怪物"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["risk"] == "high"
    assert draft["intent_type"] == "combat_action"
    assert set(draft["confirmation_requirements"]) >= {"attack", "state_change"}
    assert draft["requires_confirmation"] is True


def test_low_confidence_ai_analysis_routes_to_host_exception(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            return {
                "understanding_summary": "无法可靠理解该行动",
                "risk": "medium",
                "intent_type": "dialogue",
                "confirmation_requirements": ["stateful_action"],
                "confidence": 0.3,
            }

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我尝试用一种无法确定规则的方式改变现实"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    assert response.json()["resolution_route"] == "host_exception"


def test_v2_legacy_retroactive_claim_cannot_bypass_draft_chain(
    client,
    test_db,
    monkeypatch,
):
    _, _, player_token = _setup_player(client, test_db)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")

    response = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": player_token},
        json={
            "action_id": "legacy-retro",
            "intent_type": "retroactive_item_claim",
            "declared_intent": "我刚才其实带了撬棍",
            "params": {},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "v2_action_draft_required"


def test_v2_legacy_skill_check_cannot_bypass_draft_chain(
    client,
    test_db,
    monkeypatch,
):
    _, _, player_token = _setup_player(client, test_db)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")

    response = client.post(
        "/api/player/skill-check",
        headers={"X-Room-Token": player_token},
        json={
            "skill_name": "侦查",
            "skill_value": 60,
            "difficulty": "regular",
            "bonus_dice": 0,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "v2_action_draft_required"


def test_confirmed_local_action_is_scheduled_for_background_resolution(
    client,
    test_db,
    monkeypatch,
):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    scheduled = []
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_action_resolution",
        lambda app, conn, action_id: scheduled.append(action_id),
        raising=False,
    )

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "schedule-local"},
        json={"confirmations": []},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert scheduled == [response.json()["action_id"]]


def test_tactical_draft_preserves_server_validated_intent_params(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "我攻击敌人",
            "intent_type": "combat_action",
            "params": {"actionKind": "attack", "skillName": "斗殴", "clientRoll": 1},
        },
    ).json()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "tactical-params"},
        json={"confirmations": ["attack", "state_change"]},
    )

    assert response.status_code == 200
    action = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (response.json()["action_id"],),
    ).fetchone()
    assert action["params"]["actionKind"] == "attack"
    assert action["params"]["skillName"] == "斗殴"
    assert "clientRoll" not in action["params"]


def test_retroactive_item_claim_uses_v2_preview_and_preserves_claim_fields(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={
            "declared_intent": "我主张角色背景中应有撬棍",
            "intent_type": "retroactive_item_claim",
            "params": {
                "claimedItemName": "撬棍",
                "justificationText": "角色曾长期从事锁匠工作",
                "clientRoll": 1,
            },
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["intent_type"] == "retroactive_item_claim"
    assert draft["params"] == {
        "claimedItemName": "撬棍",
        "justificationText": "角色曾长期从事锁匠工作",
    }
    assert draft["resolution_route"] == "host_exception"


def test_one_effective_action_per_player_per_turn(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.commit()
    headers = {"X-Room-Token": player_token}

    first_draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    first = client.post(
        f"/api/player/action-drafts/{first_draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "turn-action-1"},
        json={"confirmations": []},
    )
    second_draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我询问门卫昨晚发生了什么"},
    ).json()
    second = client.post(
        f"/api/player/action-drafts/{second_draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "turn-action-2"},
        json={"confirmations": []},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "action_already_submitted"


def test_cancel_action_is_atomic_before_resolving(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    receipt = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "cancel-me"},
        json={"confirmations": []},
    ).json()

    response = client.post(
        f"/api/player/actions/{receipt['action_id']}/cancel",
        headers=headers,
    )

    assert response.status_code == 200
    canceled = response.json()
    assert canceled["status"] == "canceled"
    assert canceled["can_cancel"] is False
    assert [event["status"] for event in canceled["timeline"]] == ["queued", "canceled"]

    second = client.post(
        f"/api/player/actions/{receipt['action_id']}/cancel",
        headers=headers,
    )
    assert second.status_code == 409


def test_delete_draft_preserves_a_canceled_audit_record(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()

    response = client.delete(
        f"/api/player/action-drafts/{draft['draft_id']}",
        headers=headers,
    )

    assert response.status_code == 204
    row = test_db.execute(
        "SELECT status FROM action_drafts WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert row["status"] == "canceled"
