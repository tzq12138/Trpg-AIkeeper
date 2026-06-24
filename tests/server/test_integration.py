def test_full_flow(client):
    # 1. Create room
    resp = client.post("/api/rooms", json={"scenario_id": "sc-1"})
    assert resp.status_code == 200
    room = resp.json()
    room_id = room["room_id"]
    owner_token = room["owner_token"]

    # 2. Player joins
    resp = client.post(f"/api/player/rooms/{room_id}/join")
    assert resp.status_code == 200
    player = resp.json()
    player_token = player["player_token"]

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

    # 5. Start room
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
