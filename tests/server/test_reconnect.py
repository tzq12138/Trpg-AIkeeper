import json
import pytest


def _setup_player(client):
    resp = client.post("/api/rooms", json={})
    room_id = resp.json()["room_id"]
    owner_token = resp.json()["owner_token"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    data = resp.json()
    return room_id, owner_token, data["character_id"], data["player_token"]


def _insert_event(conn, room_id, seq, event_type, audience, payload):
    conn.execute(
        "INSERT INTO events (sequence, room_id, event_type, audience, payload) VALUES (?, ?, ?, ?, ?)",
        (seq, room_id, event_type, audience, json.dumps(payload)),
    )
    conn.commit()


def test_reconnect_returns_missed_events(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "event1"})
    _insert_event(test_db, room_id, 2, "s2c_public_observation", "party", {"text": "event2"})
    _insert_event(test_db, room_id, 3, "s2c_public_observation", "party", {"text": "event3"})

    test_db.execute(
        "INSERT INTO player_sequences (character_id, room_id, last_delivered_sequence) VALUES (?, ?, 1)",
        (char_id, room_id),
    )
    test_db.commit()

    resp = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["recent_events"]) == 2
    assert data["recent_events"][0]["sequence"] == 2
    assert data["recent_events"][1]["sequence"] == 3
    assert data["last_sequence"] == 3


def test_reconnect_long_disconnect_returns_snapshot(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    for i in range(1, 105):
        _insert_event(test_db, room_id, i, "s2c_public_observation", "party", {"text": f"event{i}"})

    test_db.execute(
        "INSERT INTO player_sequences (character_id, room_id, last_delivered_sequence) VALUES (?, ?, 1)",
        (char_id, room_id),
    )
    test_db.commit()

    resp = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_sequence"] == 104
    assert len(data["recent_events"]) == 104


def test_reconnect_invalid_token(client):
    resp = client.get("/api/player/reconnect", headers={"X-Room-Token": "bad-token"})
    assert resp.status_code == 403


def test_reconnect_missing_token(client):
    resp = client.get("/api/player/reconnect")
    assert resp.status_code == 401


def test_reconnect_idempotent(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "event1"})
    _insert_event(test_db, room_id, 2, "s2c_public_observation", "party", {"text": "event2"})

    resp1 = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    data1 = resp1.json()

    resp2 = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    data2 = resp2.json()

    assert data1["recent_events"] == data2["recent_events"]
    assert data1["last_sequence"] == data2["last_sequence"]


def test_reconnect_first_time_returns_snapshot(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "event1"})
    _insert_event(test_db, room_id, 2, "s2c_private_notice", "player", {"text": "secret", "characterId": char_id})

    resp = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_sequence"] == 2
    assert len(data["recent_events"]) == 2


def test_reconnect_with_pending_actions(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-pending', ?, ?, 'dialogue', 'test action', 'queued')",
        (room_id, char_id),
    )
    test_db.commit()

    resp = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["pending_actions"]) == 1
    assert data["pending_actions"][0]["action_id"] == "act-pending"


def test_action_status_endpoint(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status, result) "
        "VALUES ('act-1', ?, ?, 'dialogue', 'test', 'resolved', 'done')",
        (room_id, char_id),
    )
    test_db.commit()

    resp = client.get("/api/player/actions/act-1", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["action_id"] == "act-1"
    assert data["status"] == "resolved"
    assert data["result"] == "done"


def test_action_status_not_found(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    resp = client.get("/api/player/actions/nonexistent", headers={"X-Room-Token": token})
    assert resp.status_code == 404


def test_action_status_wrong_owner(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    resp2 = client.post(f"/api/player/rooms/{room_id}/join")
    other_token = resp2.json()["player_token"]

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-owner', ?, ?, 'dialogue', 'test', 'queued')",
        (room_id, char_id),
    )
    test_db.commit()

    resp = client.get("/api/player/actions/act-owner", headers={"X-Room-Token": other_token})
    assert resp.status_code == 404
