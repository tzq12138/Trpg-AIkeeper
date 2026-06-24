import json
import pytest


def _setup_room_and_player(client):
    resp = client.post("/api/rooms", json={})
    room = resp.json()
    room_id = room["room_id"]
    owner_token = room["owner_token"]

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player = resp.json()
    return room_id, owner_token, player["character_id"], player["player_token"]


_clue_counter = 0

def _insert_clue(conn, room_id, character_id, text, is_private=True):
    global _clue_counter
    _clue_counter += 1
    clue_id = f"clue-{_clue_counter}"
    conn.execute(
        "INSERT INTO clues (clue_id, room_id, character_id, text, source, is_private) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (clue_id, room_id, character_id, text, "test", int(is_private)),
    )
    conn.commit()
    return clue_id


def test_private_clue_discovery(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)
    _insert_clue(test_db, room_id, char_id, "A secret message")

    resp = client.get("/api/player/clues", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clues"]) == 1
    assert data["clues"][0]["text"] == "A secret message"
    assert data["clues"][0]["is_private"] is True
    assert data["clues"][0]["is_owner"] is True


def test_clue_sharing_creates_public_version(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)
    clue_id = _insert_clue(test_db, room_id, char_id, "Secret clue text")

    resp = client.post(
        f"/api/player/clues/{clue_id}/share",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={"note": "Important detail"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "share_id" in data
    assert "Secret clue text" in data["public_version"]
    assert "Important detail" in data["public_version"]


def test_unshared_clues_stay_private(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player2 = resp.json()
    token2 = player2["player_token"]

    _insert_clue(test_db, room_id, char_id, "Private info")

    resp = client.get("/api/player/clues", headers={"X-Room-Token": token2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clues"]) == 0


def test_clue_list_includes_private_and_shared(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client)

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player2 = resp.json()
    char_id2 = player2["character_id"]
    token2 = player2["player_token"]

    clue_id = _insert_clue(test_db, room_id, char_id, "Shared clue")

    client.post(
        f"/api/player/clues/{clue_id}/share",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={},
    )

    _insert_clue(test_db, room_id, char_id2, "Player 2 private")

    resp = client.get("/api/player/clues", headers={"X-Room-Token": token})
    data = resp.json()
    texts = [c["text"] for c in data["clues"]]
    assert "Shared clue" in texts
    assert "Player 2 private" not in texts

    resp = client.get("/api/player/clues", headers={"X-Room-Token": token2})
    data = resp.json()
    texts = [c["text"] for c in data["clues"]]
    assert "Shared clue" in texts
    assert "Player 2 private" in texts
