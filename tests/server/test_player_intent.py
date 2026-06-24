def test_join_room(client):
    resp = client.post("/api/rooms", json={})
    room_id = resp.json()["room_id"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    assert resp.status_code == 200
    data = resp.json()
    assert "character_id" in data
    assert "player_token" in data


def test_join_nonexistent_room(client):
    resp = client.post("/api/player/rooms/nonexistent/join")
    assert resp.status_code == 404


def test_submit_intent(client):
    resp = client.post("/api/rooms", json={})
    room_id = resp.json()["room_id"]

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


def test_submit_intent_idempotent(client):
    resp = client.post("/api/rooms", json={})
    room_id = resp.json()["room_id"]

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
