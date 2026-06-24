import pytest


def _setup_room_and_player(client):
    resp = client.post("/api/rooms", json={})
    room = resp.json()
    room_id = room["room_id"]
    owner_token = room["owner_token"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player = resp.json()
    return room_id, owner_token, player["character_id"], player["player_token"]


def test_team_objectives_visible_to_all(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player2 = resp.json()
    token2 = player2["player_token"]

    test_db.execute(
        "INSERT INTO objectives (objective_id, room_id, character_id, text, type) "
        "VALUES (?, ?, ?, ?, ?)",
        ("obj-1", room_id, None, "Investigate the mansion", "team"),
    )
    test_db.commit()

    resp = client.get("/api/player/objectives", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["objectives"]) == 1
    assert data["objectives"][0]["text"] == "Investigate the mansion"
    assert data["objectives"][0]["type"] == "team"

    resp = client.get("/api/player/objectives", headers={"X-Room-Token": token2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["objectives"]) == 1


def test_personal_objectives_only_to_owner(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player2 = resp.json()
    char_id2 = player2["character_id"]
    token2 = player2["player_token"]

    test_db.execute(
        "INSERT INTO objectives (objective_id, room_id, character_id, text, type) "
        "VALUES (?, ?, ?, ?, ?)",
        ("obj-p1", room_id, char_id, "Find your lost sibling", "personal"),
    )
    test_db.commit()

    resp = client.get("/api/player/objectives", headers={"X-Room-Token": token})
    data = resp.json()
    assert len(data["objectives"]) == 1
    assert data["objectives"][0]["type"] == "personal"

    resp = client.get("/api/player/objectives", headers={"X-Room-Token": token2})
    data = resp.json()
    assert len(data["objectives"]) == 0


def test_objective_status_changes(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)

    test_db.execute(
        "INSERT INTO objectives (objective_id, room_id, character_id, text, type, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("obj-2", room_id, None, "Find the key", "team", "active"),
    )
    test_db.commit()

    resp = client.get("/api/player/objectives", headers={"X-Room-Token": token})
    assert resp.json()["objectives"][0]["status"] == "active"

    test_db.execute(
        "UPDATE objectives SET status = 'completed' WHERE objective_id = ?", ("obj-2",)
    )
    test_db.commit()

    resp = client.get("/api/player/objectives", headers={"X-Room-Token": token})
    assert resp.json()["objectives"][0]["status"] == "completed"
