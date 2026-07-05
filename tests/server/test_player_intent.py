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
