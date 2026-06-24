import json
from datetime import datetime, timezone, timedelta
import pytest


def _setup_room_and_player(client):
    resp = client.post("/api/rooms", json={})
    room = resp.json()
    room_id = room["room_id"]
    owner_token = room["owner_token"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player = resp.json()
    return room_id, owner_token, player["character_id"], player["player_token"]


def _insert_action(test_db, room_id, char_id, action_id="action-1"):
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (action_id, room_id, char_id, "voice_command", "I search the room", "resolved"),
    )
    test_db.commit()


def test_submit_clarification_within_window(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)
    _insert_action(test_db, room_id, char_id)

    resp = client.post(
        "/api/player/clarification",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={"targetActionId": "action-1", "text": "I meant I search the desk, not the room"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert "clarification_id" in data


def test_reject_clarification_missing_target(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)

    resp = client.post(
        "/api/player/clarification",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={"text": "Something wrong"},
    )
    assert resp.status_code == 400


def test_reject_clarification_nonexistent_action(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)

    resp = client.post(
        "/api/player/clarification",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={"targetActionId": "nonexistent", "text": "Wrong action"},
    )
    assert resp.status_code == 404


def test_rate_limiting_on_spam(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)
    _insert_action(test_db, room_id, char_id, "action-1")
    _insert_action(test_db, room_id, char_id, "action-2")

    resp = client.post(
        "/api/player/clarification",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={"targetActionId": "action-1", "text": "First request"},
    )
    assert resp.status_code == 200

    resp = client.post(
        "/api/player/clarification",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={"targetActionId": "action-2", "text": "Second request too soon"},
    )
    assert resp.status_code == 429


def test_get_clarification_result(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)
    _insert_action(test_db, room_id, char_id)

    resp = client.post(
        "/api/player/clarification",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={"targetActionId": "action-1", "text": "Please explain"},
    )
    cl_id = resp.json()["clarification_id"]

    result_data = {"type": "explain", "content": "The roll was 15, success."}
    test_db.execute(
        "UPDATE clarifications SET status = 'resolved', resolved_at = ?, result = ? "
        "WHERE clarification_id = ?",
        (datetime.now(timezone.utc).isoformat(), json.dumps(result_data), cl_id),
    )
    test_db.commit()

    resp = client.get(f"/api/player/clarification/{cl_id}", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resolved"
    assert data["result"]["type"] == "explain"
    assert "15" in data["result"]["content"]


def test_different_result_types(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)
    _insert_action(test_db, room_id, char_id, "action-1")

    for rtype in ["explain", "followup", "recalc"]:
        cl_id = f"cl-{rtype}"
        result_data = {"type": rtype, "content": f"Result for {rtype}"}
        now = datetime.now(timezone.utc)
        test_db.execute(
            "INSERT INTO clarifications "
            "(clarification_id, room_id, character_id, target_action_id, text, status, result, created_at, resolved_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cl_id, room_id, char_id, "action-1", f"Test {rtype}", "resolved",
             json.dumps(result_data), now.isoformat(), now.isoformat()),
        )
        test_db.commit()

        resp = client.get(f"/api/player/clarification/{cl_id}", headers={"X-Room-Token": token})
        assert resp.status_code == 200
        assert resp.json()["result"]["type"] == rtype
