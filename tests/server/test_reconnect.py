import json
import time
import pytest
from tests.server.conftest import setup_auth_test_data, create_room, login


def _setup_player(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    room_id = room["room_id"]
    owner_token = room["owner_token"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    data = resp.json()
    return room_id, owner_token, data["character_id"], data["player_token"]


def _insert_event(conn, room_id, seq, event_type, audience, payload):
    conn.execute(
        "INSERT INTO events (sequence, room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s, %s)",
        (seq, room_id, event_type, audience, json.dumps(payload)),
    )
    conn.commit()


def test_reconnect_returns_missed_events(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

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
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

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


def test_reconnect_replays_one_thousand_visible_events_within_three_seconds(client, test_db):
    room_id, _, _, token = _setup_player(client, test_db)
    for sequence in range(1, 1001):
        _insert_event(
            test_db,
            room_id,
            sequence,
            "s2c_public_observation",
            "party",
            {"text": f"event-{sequence}"},
        )
    test_db.commit()

    started_at = time.monotonic()
    response = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    elapsed_seconds = time.monotonic() - started_at

    assert response.status_code == 200
    payload = response.json()
    assert payload["last_sequence"] == 1000
    assert len(payload["recent_events"]) == 1000
    assert elapsed_seconds <= 3


def test_reconnect_invalid_token(client):
    resp = client.get("/api/player/reconnect", headers={"X-Room-Token": "bad-token"})
    assert resp.status_code == 403


def test_reconnect_missing_token(client):
    resp = client.get("/api/player/reconnect")
    assert resp.status_code == 401


def test_reconnect_idempotent(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "event1"})
    _insert_event(test_db, room_id, 2, "s2c_public_observation", "party", {"text": "event2"})

    resp1 = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    data1 = resp1.json()

    resp2 = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    data2 = resp2.json()

    assert data1["recent_events"] == data2["recent_events"]
    assert data1["last_sequence"] == data2["last_sequence"]


def test_reconnect_first_time_returns_snapshot(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "event1"})
    _insert_event(test_db, room_id, 2, "s2c_private_notice", "player", {"text": "secret", "characterId": char_id})

    resp = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_sequence"] == 2
    assert len(data["recent_events"]) == 2


def test_reconnect_snapshot_excludes_host_and_other_player_private_events(client, test_db):
    room_id, _, char_id, token = _setup_player(client, test_db)
    other = client.post(f"/api/player/rooms/{room_id}/join").json()

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "队伍可见"})
    _insert_event(test_db, room_id, 2, "s2c_private_notice", "player", {"characterId": char_id, "text": "本人私密"})
    _insert_event(test_db, room_id, 3, "s2c_private_notice", "player", {"characterId": other["character_id"], "text": "他人私密"})
    _insert_event(test_db, room_id, 4, "s2c_host_snapshot", "host", {"director": "仅房主"})

    response = client.get("/api/player/reconnect", headers={"X-Room-Token": token})

    assert response.status_code == 200
    events = response.json()["recent_events"]
    assert [event["sequence"] for event in events] == [1, 2]
    assert "他人私密" not in json.dumps(events, ensure_ascii=False)
    assert "仅房主" not in json.dumps(events, ensure_ascii=False)


def test_reconnect_incremental_excludes_host_and_other_player_private_events(client, test_db):
    room_id, _, char_id, token = _setup_player(client, test_db)
    other = client.post(f"/api/player/rooms/{room_id}/join").json()

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "已读公开事件"})
    _insert_event(test_db, room_id, 2, "s2c_private_notice", "player", {"characterId": char_id, "text": "本人新私密"})
    _insert_event(test_db, room_id, 3, "s2c_private_notice", "player", {"characterId": other["character_id"], "text": "他人新私密"})
    _insert_event(test_db, room_id, 4, "s2c_host_snapshot", "host", {"director": "仅房主"})
    test_db.execute(
        "INSERT INTO player_sequences (character_id, room_id, last_delivered_sequence) VALUES (%s, %s, %s)",
        (char_id, room_id, 1),
    )
    test_db.commit()

    response = client.get("/api/player/reconnect", headers={"X-Room-Token": token})

    assert response.status_code == 200
    events = response.json()["recent_events"]
    assert [event["sequence"] for event in events] == [2]
    assert "他人新私密" not in json.dumps(events, ensure_ascii=False)
    assert "仅房主" not in json.dumps(events, ensure_ascii=False)


def test_reconnect_with_pending_actions(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-pending', %s, %s,'dialogue', 'test action', 'queued')",
        (room_id, char_id),
    )
    test_db.commit()

    resp = client.get("/api/player/reconnect", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["pending_actions"]) == 1
    assert data["pending_actions"][0]["action_id"] == "act-pending"


def test_reconnect_restores_all_nonterminal_v2_action_states(client, test_db):
    room_id, _, char_id, token = _setup_player(client, test_db)
    for index, status in enumerate(
        (
            "armed",
            "awaiting_player_consent",
            "awaiting_player_choice",
            "awaiting_host_exception",
            "sync_required",
        ),
        start=1,
    ):
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, draft_id, intent_type, "
            "declared_intent, status) VALUES (%s, %s, %s, %s, 'dialogue', %s, %s)",
            (
                f"act-v2-{index}",
                room_id,
                char_id,
                f"draft-v2-{index}",
                f"action {index}",
                status,
            ),
        )

    response = client.get("/api/player/reconnect", headers={"X-Room-Token": token})

    assert response.status_code == 200
    assert {action["status"] for action in response.json()["pending_actions"]} == {
        "armed",
        "awaiting_player_consent",
        "awaiting_player_choice",
        "awaiting_host_exception",
        "sync_required",
    }


def test_reconnect_restores_own_unfinished_action_submission(client, test_db):
    room_id, _, _, token = _setup_player(client, test_db)
    other_player = client.post(f"/api/player/rooms/{room_id}/join").json()
    headers = {"X-Room-Token": token}

    client.post(
        "/api/player/action-submissions",
        headers=headers,
        json={
            "actionId": "resume-own-action",
            "rawText": "我想重新检查那扇门。",
            "inputMode": "action",
            "clientSequence": 9,
            "baseStateVersion": 4,
        },
    )
    client.post(
        "/api/player/action-submissions",
        headers=headers,
        json={
            "actionId": "recorded-private-note",
            "rawText": "这条私人笔记不能作为行动恢复。",
            "inputMode": "private_note",
        },
    )
    client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": other_player["player_token"]},
        json={
            "actionId": "resume-other-action",
            "rawText": "其他调查员的行动不能泄露。",
            "inputMode": "action",
        },
    )

    response = client.get("/api/player/reconnect", headers=headers)

    assert response.status_code == 200
    pending = response.json()["pending_submissions"]
    assert len(pending) == 1
    assert pending[0] == {
        "action_id": "resume-own-action",
        "input_mode": "action",
        "raw_text": "我想重新检查那扇门。",
        "requested_visibility": "public",
        "client_sequence": 9,
        "base_state_version": 4,
        "status": "received",
    }


def test_action_status_endpoint(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status, result) "
        "VALUES ('act-1', %s, %s,'dialogue', 'test', 'resolved', 'done')",
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
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    resp = client.get("/api/player/actions/nonexistent", headers={"X-Room-Token": token})
    assert resp.status_code == 404


def test_action_status_wrong_owner(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    resp2 = client.post(f"/api/player/rooms/{room_id}/join")
    other_token = resp2.json()["player_token"]

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-owner', %s, %s,'dialogue', 'test', 'queued')",
        (room_id, char_id),
    )
    test_db.commit()

    resp = client.get("/api/player/actions/act-owner", headers={"X-Room-Token": other_token})
    assert resp.status_code == 404
