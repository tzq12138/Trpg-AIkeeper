import pytest

from tests.server.conftest import setup_auth_test_data, create_room


def test_join_room(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    assert resp.status_code == 200
    data = resp.json()
    assert "character_id" in data
    assert "player_token" in data


def test_join_nonexistent_room(client):
    resp = client.post("/api/player/rooms/nonexistent/join")
    assert resp.status_code == 404


def test_submit_intent(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player_token = resp.json()["player_token"]

    resp = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": player_token},
        json={
            "action_id": "act-1",
            "intent_type": "dialogue",
            "declared_intent": "I look around",
        },
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


def test_submit_intent_missing_token(client):
    resp = client.post(
        "/api/player/intent",
        json={"action_id": "act-1", "intent_type": "dialogue", "declared_intent": "test"},
    )
    assert resp.status_code == 401


def test_submit_intent_idempotent(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player_token = resp.json()["player_token"]

    intent = {
        "action_id": "act-dup",
        "intent_type": "dialogue",
        "declared_intent": "test",
    }
    headers = {"X-Room-Token": player_token}

    resp1 = client.post("/api/player/intent", headers=headers, json=intent)
    resp2 = client.post("/api/player/intent", headers=headers, json=intent)
    assert resp1.status_code == 202
    assert resp2.status_code == 202


def test_completed_campaign_rejects_legacy_intent_and_ready_toggle(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    test_db.execute(
        "UPDATE rooms SET status = 'completed' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    for action_id, intent_type in (
        ("completed-dialogue", "dialogue"),
        ("completed-ready", "ready_toggle"),
    ):
        response = client.post(
            "/api/player/intent",
            headers={"X-Room-Token": joined["player_token"]},
            json={
                "action_id": action_id,
                "intent_type": intent_type,
                "declared_intent": "结局后不应写入",
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "campaign_completed_read_only"

    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM actions WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT is_ready FROM characters WHERE character_id = %s",
        (joined["character_id"],),
    ).fetchone()["is_ready"] is False


def test_engine_write_boundary_rejects_completed_campaign_intent(test_db):
    from src.server.campaign_archive import CampaignReadOnlyError
    from src.server.engine.engine import Engine
    from src.server.models import PlayerIntent

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('completed-engine-room', 'owner-engine', 'completed')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('completed-engine-char', 'completed-engine-room', 'Player', 'token', 'joined')"
    )
    test_db.commit()

    with pytest.raises(CampaignReadOnlyError, match="campaign_completed_read_only"):
        Engine(test_db).submit_intent(
            "completed-engine-room",
            "completed-engine-char",
            PlayerIntent(
                action_id="completed-engine-action",
                intent_type="dialogue",
                declared_intent="This write must be rejected at the engine boundary.",
            ),
        )

    assert test_db.execute(
        "SELECT 1 FROM actions WHERE action_id = 'completed-engine-action'"
    ).fetchone() is None
    assert test_db.execute(
        "SELECT 1 FROM events WHERE room_id = 'completed-engine-room'"
    ).fetchone() is None


def test_active_intent_does_not_create_turn_before_engine_write_boundary(
    client,
    test_db,
    monkeypatch,
):
    from src.server.campaign_archive import CampaignReadOnlyError

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    test_db.execute(
        "UPDATE rooms SET status = 'active' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    def complete_before_engine_write(*_args, **_kwargs):
        test_db.execute(
            "UPDATE rooms SET status = 'completed' WHERE room_id = %s",
            (room_id,),
        )
        test_db.commit()
        raise CampaignReadOnlyError("campaign_completed_read_only")

    monkeypatch.setattr(
        client.app.state.engine,
        "submit_intent",
        complete_before_engine_write,
    )

    response = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": joined["player_token"]},
        json={
            "action_id": "completed-before-active-write",
            "intent_type": "dialogue",
            "declared_intent": "This must not open a turn.",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "campaign_completed_read_only"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM room_turns WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == 0


def test_active_intent_creates_and_binds_turn_in_engine_transaction(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    client.post(f"/api/player/rooms/{room_id}/join")
    test_db.execute(
        "UPDATE rooms SET status = 'active' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()
    headers = {"X-Room-Token": joined["player_token"]}

    first = client.post(
        "/api/player/intent",
        headers=headers,
        json={
            "action_id": "active-atomic-action",
            "intent_type": "dialogue",
            "declared_intent": "I inspect the locked gate.",
        },
    )

    assert first.status_code == 202
    assert first.json()["turnId"]
    action = test_db.execute(
        "SELECT turn_id FROM actions WHERE action_id = 'active-atomic-action'"
    ).fetchone()
    assert action["turn_id"] == first.json()["turnId"]
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM room_turns WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == 1

    duplicate = client.post(
        "/api/player/intent",
        headers=headers,
        json={
            "action_id": "active-duplicate-action",
            "intent_type": "dialogue",
            "declared_intent": "I submit twice in one turn.",
        },
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["turn_id"] == first.json()["turnId"]
    assert test_db.execute(
        "SELECT 1 FROM actions WHERE action_id = 'active-duplicate-action'"
    ).fetchone() is None


def test_retroactive_claim_rechecks_campaign_under_write_lock(
    client,
    test_db,
    monkeypatch,
):
    import json
    from src.server.player import router_player

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = %s",
        (json.dumps({"background": "父亲留下的黄铜打火机"}), joined["character_id"]),
    )
    base_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"]
    test_db.commit()
    original_assets = router_player._scenario_assets_for_room

    def complete_before_claim_write(conn, target_room_id):
        conn.execute(
            "UPDATE rooms SET status = 'completed' WHERE room_id = %s",
            (target_room_id,),
        )
        conn.commit()
        return original_assets(conn, target_room_id)

    monkeypatch.setattr(
        router_player,
        "_scenario_assets_for_room",
        complete_before_claim_write,
    )

    response = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": joined["player_token"]},
        json={
            "action_id": "late-retroactive-claim",
            "intent_type": "retroactive_item_claim",
            "declared_intent": "我拿出黄铜打火机",
            "params": {
                "claimedItemName": "黄铜打火机",
                "justificationText": "这是父亲的遗物",
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "campaign_completed_read_only"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM inventory WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM actions WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"] == base_version


def test_retroactive_claim_commits_action_inventory_and_version_together(client, test_db):
    import json

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    test_db.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = %s",
        (json.dumps({"background": "父亲留下的黄铜打火机"}), joined["character_id"]),
    )
    base_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"]
    test_db.commit()

    response = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": joined["player_token"]},
        json={
            "action_id": "atomic-retroactive-claim",
            "intent_type": "retroactive_item_claim",
            "declared_intent": "我拿出黄铜打火机",
            "params": {
                "claimedItemName": "黄铜打火机",
                "justificationText": "这是父亲的遗物",
            },
        },
    )

    assert response.status_code == 202
    assert test_db.execute(
        "SELECT name FROM inventory WHERE room_id = %s AND character_id = %s",
        (room_id, joined["character_id"]),
    ).fetchone()["name"] == "黄铜打火机"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'atomic-retroactive-claim'"
    ).fetchone()["status"] == "resolved"
    assert test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"] == base_version + 1


def test_completed_campaign_rejects_basic_join(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    test_db.execute(
        "UPDATE rooms SET status = 'completed' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    response = client.post(f"/api/player/rooms/{room_id}/join")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "campaign_completed_read_only"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM characters WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == 0


def test_ready_toggle_flips_is_ready(client, test_db):
    """ready_toggle intent should flip is_ready in the database."""
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    data = resp.json()
    player_token = data["player_token"]
    character_id = data["character_id"]

    # Toggle to ready
    resp = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": player_token},
        json={
            "action_id": "act-ready-1",
            "intent_type": "ready_toggle",
            "declared_intent": "准备就绪",
        },
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"

    char = test_db.execute(
        "SELECT is_ready FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    assert char["is_ready"] is True

    # Toggle back to not ready
    resp = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": player_token},
        json={
            "action_id": "act-ready-2",
            "intent_type": "ready_toggle",
            "declared_intent": "取消准备",
        },
    )
    assert resp.status_code == 202
    char = test_db.execute(
        "SELECT is_ready FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    assert char["is_ready"] is False


def test_ready_toggle_requires_token(client):
    """ready_toggle without player_token should return 401."""
    resp = client.post(
        "/api/player/intent",
        json={
            "action_id": "act-no-tok",
            "intent_type": "ready_toggle",
            "declared_intent": "准备就绪",
        },
    )
    assert resp.status_code == 401
