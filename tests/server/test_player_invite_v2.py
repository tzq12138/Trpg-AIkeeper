import json

from tests.server.conftest import create_room, login, setup_auth_test_data


def _new_v2_room(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    stored = test_db.execute(
        "SELECT player_experience_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert stored["player_experience_version"] == "v2"
    return room


def test_v2_invite_requires_login_and_binds_joined_character_to_account(
    client,
    test_db,
    monkeypatch,
):
    room = _new_v2_room(client, test_db)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")

    anonymous = client.post(f"/api/player/rooms/{room['room_id']}/join")
    player_token = login(client, "testplayer")
    joined = client.post(
        f"/api/player/rooms/{room['room_id']}/join",
        headers={"Authorization": f"Bearer {player_token}"},
    )

    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["code"] == "login_required"
    assert joined.status_code == 200
    character = test_db.execute(
        "SELECT account_id FROM characters WHERE character_id = %s",
        (joined.json()["character_id"],),
    ).fetchone()
    assert character["account_id"] == "acc-player"


def test_v2_join_with_character_cannot_bypass_login(client, test_db, monkeypatch):
    room = _new_v2_room(client, test_db)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")

    response = client.post(
        f"/api/player/rooms/{room['room_id']}/join-with-character",
        data={
            "player_name": "访客",
            "character_data": json.dumps(
                {
                    "name": "调查员",
                    "occupation": "记者",
                    "attributes": {"str": 50, "con": 50, "pow": 50},
                    "skills": {"侦查": 50},
                },
                ensure_ascii=False,
            ),
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "login_required"


def test_invite_preflight_reports_login_room_mode_and_account_recovery(
    client,
    test_db,
    monkeypatch,
):
    room = _new_v2_room(client, test_db)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")

    guest = client.get(f"/api/player/rooms/{room['room_id']}/preflight")
    player_token = login(client, "testplayer")
    joined = client.post(
        f"/api/player/rooms/{room['room_id']}/join",
        headers={"Authorization": f"Bearer {player_token}"},
    ).json()
    authenticated = client.get(
        f"/api/player/rooms/{room['room_id']}/preflight",
        headers={"Authorization": f"Bearer {player_token}"},
    )

    assert guest.status_code == 200
    assert guest.json() == {
        "room_id": room["room_id"],
        "rest_ok": True,
        "websocket_path": "/ws",
        "room_status": "lobby",
        "join_mode": "direct",
        "requires_login": True,
        "authenticated": False,
        "recovery_available": False,
        "recovery_character_id": None,
    }
    assert authenticated.status_code == 200
    assert authenticated.json()["authenticated"] is True
    assert authenticated.json()["recovery_available"] is True
    assert authenticated.json()["recovery_character_id"] == joined["character_id"]


def test_active_room_preflight_uses_host_approval_waiting_mode(client, test_db):
    room = _new_v2_room(client, test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    response = client.get(f"/api/player/rooms/{room['room_id']}/preflight")

    assert response.status_code == 200
    assert response.json()["join_mode"] == "host_approval"


def test_v2_room_rejects_legacy_stateful_intent_in_production(
    client,
    test_db,
    monkeypatch,
):
    room = _new_v2_room(client, test_db)
    player_account_token = login(client, "testplayer")
    joined = client.post(
        f"/api/player/rooms/{room['room_id']}/join",
        headers={"Authorization": f"Bearer {player_account_token}"},
    ).json()
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")

    response = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": joined["player_token"]},
        json={
            "action_id": "legacy-bypass",
            "intent_type": "move",
            "declared_intent": "绕过预览直接移动",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "v2_action_draft_required"
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0
