import json

from src.server.turn_manager import TurnManager
from tests.server.conftest import create_room, login, setup_auth_test_data


def _setup_owned_character(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    old_token = "player-session-before-removal"
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, account_id, status, xlsx_data) "
        "VALUES ('protected-char', %s, 'Investigator', %s, 'acc-player', 'ready', %s)",
        (
            room["room_id"],
            old_token,
            json.dumps({"name": "保留的调查员", "hp": 8, "privateHistory": "不应交给房主"}),
        ),
    )
    test_db.execute(
        "INSERT INTO player_notes "
        "(note_id, room_id, character_id, title_ciphertext, body_ciphertext) "
        "VALUES ('private-note-preserved', %s, 'protected-char', 'encrypted-title', 'encrypted-body')",
        (room["room_id"],),
    )
    test_db.commit()
    return room, old_token


def test_host_removal_terminates_access_without_taking_over_character_or_private_data(client, test_db):
    room, old_token = _setup_owned_character(client, test_db)
    response = client.post(
        f"/api/host/{room['room_id']}/players/protected-char/remove",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"reason": "玩家暂时离线"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "characterId": "protected-char",
        "status": "protected_inactive",
    }
    char = test_db.execute(
        "SELECT account_id, status, player_token, xlsx_data FROM characters WHERE character_id = 'protected-char'"
    ).fetchone()
    assert char["account_id"] == "acc-player"
    assert char["status"] == "protected_inactive"
    assert char["player_token"] != old_token
    assert char["xlsx_data"]["privateHistory"] == "不应交给房主"
    assert test_db.execute(
        "SELECT body_ciphertext FROM player_notes WHERE note_id = 'private-note-preserved'"
    ).fetchone()["body_ciphertext"] == "encrypted-body"
    assert client.get(
        "/api/player/action-drafts/current",
        headers={"X-Room-Token": old_token},
    ).status_code == 403
    audit = test_db.execute(
        "SELECT audience, payload FROM events "
        "WHERE room_id = %s AND event_type = 'character_access_terminated'",
        (room["room_id"],),
    ).fetchone()
    assert audit["audience"] == "system"
    assert audit["payload"] == {
        "actor": "host",
        "characterId": "protected-char",
        "reason": "玩家暂时离线",
        "result": "protected_inactive",
    }


def test_owning_account_can_recover_control_with_a_rotated_token(client, test_db):
    room, old_token = _setup_owned_character(client, test_db)
    client.post(
        f"/api/host/{room['room_id']}/players/protected-char/remove",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"reason": "网络中断"},
    )
    host_attempt = client.post(
        "/api/player/characters/protected-char/restore-session",
        headers={"X-Owner-Token": room["owner_token"]},
    )
    player_account_token = login(client, "testplayer")
    restored = client.post(
        "/api/player/characters/protected-char/restore-session",
        headers={"Authorization": f"Bearer {player_account_token}"},
    )

    assert host_attempt.status_code == 401
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["character_id"] == "protected-char"
    assert body["room_id"] == room["room_id"]
    assert body["player_token"] != old_token
    assert test_db.execute(
        "SELECT status, player_token FROM characters WHERE character_id = 'protected-char'"
    ).fetchone() == {"status": "joined", "player_token": body["player_token"]}
    recovery = test_db.execute(
        "SELECT payload FROM events WHERE room_id = %s AND event_type = 'character_control_recovered'",
        (room["room_id"],),
    ).fetchone()
    assert recovery["payload"]["characterId"] == "protected-char"
    assert "playerToken" not in recovery["payload"]


def test_offline_placeholder_cannot_spend_resources_make_irreversible_choices_or_reveal_secrets(
    client,
    test_db,
):
    room, _ = _setup_owned_character(client, test_db)
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('offline-turn', %s, 1, 'collecting', 'combat')",
        (room["room_id"],),
    )
    test_db.commit()

    result = TurnManager(test_db).skip_character(
        room["room_id"],
        "offline-turn",
        "protected-char",
        "maintain_existing",
    )

    assert result["status"] == "skipped"
    action = test_db.execute(
        "SELECT intent_type, params, result FROM actions WHERE action_id = %s",
        (result["action_id"],),
    ).fetchone()
    assert action["intent_type"] == "system_skip"
    assert action["params"] == {
        "allowedEffects": ["defend", "follow", "safe_withdraw"],
        "irreversible": False,
        "resourceCost": 0,
        "revealsSecrets": False,
    }
    assert action["result"] == {"outcome": "safe_hold"}
