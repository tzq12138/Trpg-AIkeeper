import json
import pytest
from tests.server.conftest import setup_auth_test_data, create_room


def _setup_room_and_player(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
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
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (clue_id, room_id, character_id, text, "test", int(is_private)),
    )
    conn.commit()
    return clue_id


def test_private_clue_discovery(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client, test_db)
    _insert_clue(test_db, room_id, char_id, "A secret message")

    resp = client.get("/api/player/clues", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clues"]) == 1
    assert data["clues"][0]["text"] == "A secret message"
    assert data["clues"][0]["is_private"] is True
    assert data["clues"][0]["is_owner"] is True


def test_clue_sharing_creates_public_version(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client, test_db)
    clue_id = _insert_clue(test_db, room_id, char_id, "Secret clue text")

    # Share with explicit public_version
    resp = client.post(
        f"/api/player/clues/{clue_id}/share",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={"public_version": "这条线索指向书房的保险箱", "note": "Important detail"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "share_id" in data
    assert "书房的保险箱" in data["public_version"]
    assert "Important detail" in data["public_version"]

    # Safe default: share without public_version gives safe fallback
    room_id2, _, char_id2, token2 = _setup_room_and_player(client, test_db)
    clue_id2 = _insert_clue(test_db, room_id2, char_id2, "Another secret")
    resp2 = client.post(
        f"/api/player/clues/{clue_id2}/share",
        headers={"X-Room-Token": token2, "Content-Type": "application/json"},
        json={},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert "未公开完整内容" in data2["public_version"]


def test_unshared_clues_stay_private(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client, test_db)

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player2 = resp.json()
    token2 = player2["player_token"]

    _insert_clue(test_db, room_id, char_id, "Private info")

    resp = client.get("/api/player/clues", headers={"X-Room-Token": token2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clues"]) == 0


def test_clue_list_includes_private_and_shared(client, test_db):
    room_id, _, char_id, token = _setup_room_and_player(client, test_db)

    resp = client.post(f"/api/player/rooms/{room_id}/join")
    player2 = resp.json()
    char_id2 = player2["character_id"]
    token2 = player2["player_token"]

    clue_id = _insert_clue(test_db, room_id, char_id, "Shared clue")

    # Share with explicit public_version so teammates see the summary
    client.post(
        f"/api/player/clues/{clue_id}/share",
        headers={"X-Room-Token": token, "Content-Type": "application/json"},
        json={"public_version": "Shared clue summary"},
    )

    _insert_clue(test_db, room_id, char_id2, "Player 2 private")

    # Player 1 sees their own original text and their shared summary
    resp = client.get("/api/player/clues", headers={"X-Room-Token": token})
    data = resp.json()
    texts = [c["text"] for c in data["clues"]]
    assert "Shared clue" in texts  # owner sees original
    assert "Player 2 private" not in texts

    # Player 2 sees public_version of shared clue, not original
    resp = client.get("/api/player/clues", headers={"X-Room-Token": token2})
    data = resp.json()
    texts = [c["text"] for c in data["clues"]]
    assert "Shared clue summary" in texts  # teammate sees public_version
    assert "Shared clue" not in texts       # teammate does NOT see original
    assert "Player 2 private" in texts      # own private clue visible
