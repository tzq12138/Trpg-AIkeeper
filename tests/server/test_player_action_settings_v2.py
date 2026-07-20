import logging

import pytest

from tests.server.conftest import create_room, login, setup_auth_test_data


PRESET_TIMINGS = {
    "fast": {
        "input_hint_seconds": 30,
        "receipt_seconds": 3,
        "preview_seconds": 15,
        "resolution_seconds": 90,
    },
    "standard": {
        "input_hint_seconds": 60,
        "receipt_seconds": 5,
        "preview_seconds": 30,
        "resolution_seconds": 180,
    },
    "slow": {
        "input_hint_seconds": 120,
        "receipt_seconds": 10,
        "preview_seconds": 60,
        "resolution_seconds": 300,
    },
}


def _setup_room(client, test_db):
    setup_auth_test_data(test_db)
    return create_room(client)


def _join_room(client, room_id):
    response = client.post(f"/api/player/rooms/{room_id}/join")
    assert response.status_code == 200, response.text
    return response.json()


def test_player_settings_require_token_and_fall_back_to_room(client, test_db):
    room = _setup_room(client, test_db)
    player = _join_room(client, room["room_id"])
    test_db.execute(
        "UPDATE rooms SET draft_analysis_enabled = false WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    missing = client.get("/api/player/settings")
    invalid = client.get(
        "/api/player/settings",
        headers={"X-Room-Token": "invalid-room-token"},
    )
    response = client.get(
        "/api/player/settings",
        headers={"X-Room-Token": player["player_token"]},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 403
    assert response.status_code == 200
    assert response.json() == {
        "room_id": room["room_id"],
        "character_id": player["character_id"],
        "draft_analysis_enabled": False,
        "absent_policy": "idle",
        "speech_routing": "party_message",
    }


def test_patch_player_settings_upserts_boolean_override(client, test_db):
    room = _setup_room(client, test_db)
    player = _join_room(client, room["room_id"])
    headers = {"X-Room-Token": player["player_token"]}

    enabled = client.patch(
        "/api/player/settings",
        headers=headers,
        json={"draft_analysis_enabled": True},
    )
    disabled = client.patch(
        "/api/player/settings",
        headers=headers,
        json={"draft_analysis_enabled": False},
    )

    assert enabled.status_code == 200
    assert enabled.json()["draft_analysis_enabled"] is True
    assert disabled.status_code == 200
    assert disabled.json() == {
        "room_id": room["room_id"],
        "character_id": player["character_id"],
        "draft_analysis_enabled": False,
        "absent_policy": "idle",
        "speech_routing": "party_message",
    }
    row = test_db.execute(
        "SELECT room_id, character_id, draft_analysis_enabled "
        "FROM room_player_settings WHERE room_id = %s AND character_id = %s",
        (room["room_id"], player["character_id"]),
    ).fetchone()
    assert dict(row) == {
        "room_id": room["room_id"],
        "character_id": player["character_id"],
        "draft_analysis_enabled": False,
    }


def test_player_can_save_a_documented_absence_preset(client, test_db):
    room = _setup_room(client, test_db)
    player = _join_room(client, room["room_id"])

    response = client.patch(
        "/api/player/settings",
        headers={"X-Room-Token": player["player_token"]},
        json={"absent_policy": "maintain_existing"},
    )

    assert response.status_code == 200
    assert response.json()["absent_policy"] == "maintain_existing"
    row = test_db.execute(
        "SELECT absent_policy FROM room_player_settings "
        "WHERE room_id = %s AND character_id = %s",
        (room["room_id"], player["character_id"]),
    ).fetchone()
    assert row["absent_policy"] == "maintain_existing"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"draft_analysis_enabled": "false"},
        {"draft_analysis_enabled": 1},
        {"draft_analysis_enabled": None},
        {"draft_analysis_enabled": True, "room_id": "other-room"},
    ],
)
def test_patch_player_settings_rejects_non_boolean_or_extra_fields(
    client, test_db, payload
):
    room = _setup_room(client, test_db)
    player = _join_room(client, room["room_id"])

    response = client.patch(
        "/api/player/settings",
        headers={"X-Room-Token": player["player_token"]},
        json=payload,
    )

    assert response.status_code == 422
    count = test_db.execute(
        "SELECT COUNT(*) AS count FROM room_player_settings"
    ).fetchone()["count"]
    assert count == 0


def test_player_settings_are_isolated_between_rooms(client, test_db):
    setup_auth_test_data(test_db)
    first_room = create_room(client)
    second_room = create_room(client)
    first_player = _join_room(client, first_room["room_id"])
    second_player = _join_room(client, second_room["room_id"])
    test_db.execute(
        "UPDATE rooms SET draft_analysis_enabled = false WHERE room_id = %s",
        (first_room["room_id"],),
    )
    test_db.commit()

    first = client.patch(
        "/api/player/settings",
        headers={"X-Room-Token": first_player["player_token"]},
        json={"draft_analysis_enabled": True},
    )
    second = client.patch(
        "/api/player/settings",
        headers={"X-Room-Token": second_player["player_token"]},
        json={"draft_analysis_enabled": False},
    )

    assert first.status_code == 200
    assert first.json()["room_id"] == first_room["room_id"]
    assert first.json()["draft_analysis_enabled"] is True
    assert second.status_code == 200
    assert second.json()["room_id"] == second_room["room_id"]
    assert second.json()["draft_analysis_enabled"] is False
    rows = test_db.execute(
        "SELECT room_id, character_id FROM room_player_settings ORDER BY room_id"
    ).fetchall()
    assert {(row["room_id"], row["character_id"]) for row in rows} == {
        (first_room["room_id"], first_player["character_id"]),
        (second_room["room_id"], second_player["character_id"]),
    }


@pytest.mark.parametrize("preset", ["fast", "standard", "slow"])
def test_host_action_settings_apply_fixed_presets(client, test_db, preset):
    room = _setup_room(client, test_db)

    response = client.patch(
        f"/api/rooms/{room['room_id']}/action-settings",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"preset": preset},
    )

    assert response.status_code == 200
    assert response.json() == {
        "room_id": room["room_id"],
        "preset": preset,
        "timing": PRESET_TIMINGS[preset],
        "draft_analysis_enabled": True,
        "speech_routing": "party_message",
        "host_autonomy_policy": "host_required",
    }
    stored = test_db.execute(
        "SELECT action_pacing_preset, action_timing FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert stored["action_pacing_preset"] == preset
    assert stored["action_timing"] == PRESET_TIMINGS[preset]


def test_host_action_settings_apply_custom_timing_and_room_draft_toggle(
    client, test_db
):
    room = _setup_room(client, test_db)
    timing = {
        "input_hint_seconds": 45,
        "receipt_seconds": 4,
        "preview_seconds": 20,
        "resolution_seconds": 150,
    }

    response = client.patch(
        f"/api/rooms/{room['room_id']}/action-settings",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "preset": "custom",
            "timing": timing,
            "draft_analysis_enabled": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "room_id": room["room_id"],
        "preset": "custom",
        "timing": timing,
        "draft_analysis_enabled": False,
        "speech_routing": "party_message",
        "host_autonomy_policy": "host_required",
    }


def test_host_can_route_speech_to_npc_dialogue_and_players_can_read_it(client, test_db):
    room = _setup_room(client, test_db)
    player = _join_room(client, room["room_id"])

    response = client.patch(
        f"/api/rooms/{room['room_id']}/action-settings",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"speech_routing": "npc_dialogue"},
    )
    player_settings = client.get(
        "/api/player/settings",
        headers={"X-Room-Token": player["player_token"]},
    )

    assert response.status_code == 200
    assert response.json()["speech_routing"] == "npc_dialogue"
    assert player_settings.status_code == 200
    assert player_settings.json()["speech_routing"] == "npc_dialogue"
    stored = test_db.execute(
        "SELECT speech_routing FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert stored["speech_routing"] == "npc_dialogue"


def test_host_can_delegate_safe_actions_while_planned_offline(client, test_db):
    room = _setup_room(client, test_db)

    response = client.patch(
        f"/api/rooms/{room['room_id']}/action-settings",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"host_autonomy_policy": "delegated"},
    )

    assert response.status_code == 200
    assert response.json()["host_autonomy_policy"] == "delegated"
    stored = test_db.execute(
        "SELECT host_autonomy_policy FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert stored["host_autonomy_policy"] == "delegated"


@pytest.mark.parametrize(
    "timing",
    [
        None,
        {
            "input_hint_seconds": 0,
            "receipt_seconds": 4,
            "preview_seconds": 20,
            "resolution_seconds": 150,
        },
        {
            "input_hint_seconds": 45,
            "receipt_seconds": 3601,
            "preview_seconds": 20,
            "resolution_seconds": 150,
        },
        {
            "input_hint_seconds": 45.5,
            "receipt_seconds": 4,
            "preview_seconds": 20,
            "resolution_seconds": 150,
        },
        {
            "input_hint_seconds": True,
            "receipt_seconds": 4,
            "preview_seconds": 20,
            "resolution_seconds": 150,
        },
        {
            "input_hint_seconds": 45,
            "receipt_seconds": 4,
            "preview_seconds": 20,
        },
    ],
)
def test_custom_action_settings_require_four_bounded_integers(
    client, test_db, timing
):
    room = _setup_room(client, test_db)
    payload = {"preset": "custom"}
    if timing is not None:
        payload["timing"] = timing

    response = client.patch(
        f"/api/rooms/{room['room_id']}/action-settings",
        headers={"X-Owner-Token": room["owner_token"]},
        json=payload,
    )

    assert response.status_code == 422


def test_room_action_settings_require_owner_or_admin_and_isolate_rooms(
    client, test_db
):
    setup_auth_test_data(test_db)
    first_room = create_room(client)
    second_room = create_room(client)
    player_token = login(client, "testplayer")
    admin_token = login(client, "admin")

    wrong_room = client.patch(
        f"/api/rooms/{second_room['room_id']}/action-settings",
        headers={"X-Owner-Token": first_room["owner_token"]},
        json={"preset": "fast"},
    )
    player = client.patch(
        f"/api/rooms/{second_room['room_id']}/action-settings",
        headers={"Authorization": f"Bearer {player_token}"},
        json={"preset": "fast"},
    )
    admin = client.patch(
        f"/api/rooms/{second_room['room_id']}/action-settings",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"preset": "slow"},
    )

    assert wrong_room.status_code == 403
    assert player.status_code == 403
    assert admin.status_code == 200
    assert admin.json()["preset"] == "slow"
    first = test_db.execute(
        "SELECT action_pacing_preset FROM rooms WHERE room_id = %s",
        (first_room["room_id"],),
    ).fetchone()
    assert first["action_pacing_preset"] == "standard"


def test_ephemeral_analysis_uses_effective_player_setting(client, test_db):
    room = _setup_room(client, test_db)
    player = _join_room(client, room["room_id"])
    headers = {"X-Room-Token": player["player_token"]}
    test_db.execute(
        "UPDATE rooms SET draft_analysis_enabled = false WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    disabled = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我查看桌上的报纸", "ephemeral": True},
    )
    explicit = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我明确分析桌上的报纸"},
    )
    override = client.patch(
        "/api/player/settings",
        headers=headers,
        json={"draft_analysis_enabled": True},
    )
    enabled = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我查看桌上的报纸", "ephemeral": True},
    )

    assert disabled.status_code == 403
    assert disabled.json()["detail"]["code"] == "draft_analysis_disabled"
    assert explicit.status_code == 200
    assert override.status_code == 200
    assert enabled.status_code == 200
    assert enabled.json()["ephemeral"] is True


def test_personal_disable_overrides_enabled_room_for_ephemeral_analysis(
    client, test_db
):
    room = _setup_room(client, test_db)
    player = _join_room(client, room["room_id"])
    headers = {"X-Room-Token": player["player_token"]}
    patched = client.patch(
        "/api/player/settings",
        headers=headers,
        json={"draft_analysis_enabled": False},
    )

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看四周", "ephemeral": True},
    )

    assert patched.status_code == 200
    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "draft_analysis_disabled"}


def test_settings_and_analysis_do_not_log_tokens_or_action_text(
    client, test_db, caplog
):
    room = _setup_room(client, test_db)
    player = _join_room(client, room["room_id"])
    secret_text = "绝不能进入日志的行动正文-9f04"
    caplog.set_level(logging.DEBUG)
    caplog.clear()

    settings = client.patch(
        "/api/player/settings",
        headers={"X-Room-Token": player["player_token"]},
        json={"draft_analysis_enabled": True},
    )
    analysis = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player["player_token"]},
        json={"declared_intent": secret_text, "ephemeral": True},
    )

    assert settings.status_code == 200
    assert analysis.status_code == 200
    assert player["player_token"] not in caplog.text
    assert room["owner_token"] not in caplog.text
    assert secret_text not in caplog.text
