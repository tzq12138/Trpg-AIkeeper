from tests.server.conftest import setup_auth_test_data, create_room


def test_full_flow(client, test_db):
    setup_auth_test_data(test_db)

    # 1. Create room (authenticated)
    room = create_room(client)
    room_id = room["room_id"]
    owner_token = room["owner_token"]

    # 2. Player joins
    resp = client.post(f"/api/player/rooms/{room_id}/join")
    assert resp.status_code == 200
    player = resp.json()
    player_token = player["player_token"]
    character_id = player["character_id"]

    # 3. Submit intent
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

    # 4. Idempotent re-submit
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

    # 5. Mark character ready (direct DB — admin endpoint requires auth)
    db = client.app.state.db
    db.execute("UPDATE characters SET is_ready = TRUE WHERE character_id = %s", (character_id,))
    db.commit()

    # 6. Start room
    resp = client.post(
        f"/api/rooms/{room_id}/start",
        headers={"X-Owner-Token": owner_token},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    # 6. Health check
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
