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


def test_action_history(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-1', ?, ?, 'dialogue', 'look around', 'resolved')",
        (room_id, char_id),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-2', ?, ?, 'skill_check', 'spot hidden', 'queued')",
        (room_id, char_id),
    )
    test_db.commit()

    resp = client.get("/api/player/archive/actions", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["actions"]) == 2
    assert data["actions"][0]["action_id"] == "act-1"
    assert data["actions"][1]["action_id"] == "act-2"


def test_clue_history(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "public clue"})
    _insert_event(test_db, room_id, 2, "s2c_private_notice", "player", {"text": "private clue", "characterId": char_id})
    _insert_event(test_db, room_id, 3, "s2c_private_notice", "player", {"text": "other clue", "characterId": "other-char"})

    resp = client.get("/api/player/archive/clues", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clues"]) == 2
    assert data["clues"][0]["data"]["text"] == "public clue"
    assert data["clues"][1]["data"]["text"] == "private clue"


def test_skill_check_history(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status, result) "
        "VALUES ('sc-1', ?, ?, 'skill_check', 'spot hidden', 'resolved', '\"success\"')",
        (room_id, char_id),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('dlg-1', ?, ?, 'dialogue', 'talk', 'resolved')",
        (room_id, char_id),
    )
    test_db.commit()

    resp = client.get("/api/player/archive/skill-checks", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["skill_checks"]) == 1
    assert data["skill_checks"][0]["action_id"] == "sc-1"


def test_public_replay_for_host(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "public"})
    _insert_event(test_db, room_id, 2, "s2c_private_notice", "player", {"text": "private"})
    _insert_event(test_db, room_id, 3, "s2c_atmosphere", "system", {"text": "atmosphere"})

    resp = client.get(
        f"/api/rooms/{room_id}/replay",
        headers={"X-Owner-Token": owner_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["events"]) == 2
    assert data["events"][0]["audience"] == "party"
    assert data["events"][1]["audience"] == "system"


def test_replay_invalid_owner(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    resp = client.get(
        f"/api/rooms/{room_id}/replay",
        headers={"X-Owner-Token": "bad-token"},
    )
    assert resp.status_code == 403


def test_archive_filter_by_type(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "observation"})
    _insert_event(test_db, room_id, 2, "s2c_action_completed", "player", {"actionId": "a1", "status": "resolved"})
    _insert_event(test_db, room_id, 3, "s2c_state_patch", "party", {"patch": {}})

    resp = client.get("/api/player/archive?type=clues", headers={"X-Room-Token": token})
    data = resp.json()
    assert data["total"] == 1
    assert data["entries"][0]["type"] == "s2c_public_observation"

    resp = client.get("/api/player/archive?type=state_changes", headers={"X-Room-Token": token})
    data = resp.json()
    assert data["total"] == 1
    assert data["entries"][0]["type"] == "s2c_state_patch"


def test_archive_search_keyword(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "you see a door"})
    _insert_event(test_db, room_id, 2, "s2c_public_observation", "party", {"text": "you hear a noise"})

    resp = client.get("/api/player/archive?keyword=door", headers={"X-Room-Token": token})
    data = resp.json()
    assert data["total"] == 1
    assert "door" in data["entries"][0]["data"]["text"]


def test_archive_missing_token(client):
    resp = client.get("/api/player/archive")
    assert resp.status_code == 401


def test_archive_pagination(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    for i in range(10):
        _insert_event(test_db, room_id, i + 1, "s2c_public_observation", "party", {"text": f"event{i}"})

    resp = client.get("/api/player/archive?offset=0&limit=3", headers={"X-Room-Token": token})
    data = resp.json()
    assert len(data["entries"]) == 3
    assert data["total"] == 10

    resp = client.get("/api/player/archive?offset=8&limit=5", headers={"X-Room-Token": token})
    data = resp.json()
    assert len(data["entries"]) == 2


def test_replay_pagination(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client)

    for i in range(10):
        _insert_event(test_db, room_id, i + 1, "s2c_public_observation", "party", {"text": f"event{i}"})

    resp = client.get(
        f"/api/rooms/{room_id}/replay?offset=0&limit=3",
        headers={"X-Owner-Token": owner_token},
    )
    data = resp.json()
    assert len(data["events"]) == 3
    assert data["total"] == 10
