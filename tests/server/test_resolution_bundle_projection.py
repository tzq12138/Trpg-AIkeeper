import json

from tests.server.conftest import create_room, setup_auth_test_data


def test_stage_and_host_console_receive_separate_resolution_projections(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    room_id = room["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    action_id = "bundle-projection-action"
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, status) "
        "VALUES (%s, %s, %s, %s, %s)",
        (action_id, room_id, joined["character_id"], "skill_check", "completed"),
    )
    test_db.execute(
        "INSERT INTO resolution_bundles "
        "(action_id, room_id, character_id, canonical_result, rule_explanation, actor_projection, "
        "stage_projection, host_console, release_status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'released')",
        (
            action_id,
            room_id,
            joined["character_id"],
            json.dumps({"mutations": [{"path": "/character/hp", "value": 2}], "truth": "幕后真相"}),
            json.dumps({"formula": "d100 <= 60"}),
            json.dumps({"statePatch": {"patches": [{"path": "/character/hp", "value": 2}]}}),
            json.dumps({"actionId": action_id, "text": "你听见走廊深处传来脚步声。"}),
            json.dumps({"actionId": action_id, "steps": [{"kind": "roll", "payload": {"roll": 42}}]}),
        ),
    )
    test_db.commit()

    stage = client.get(
        f"/api/player/rooms/{room_id}/stage",
        headers={"X-Room-Token": joined["player_token"]},
    )
    console = client.get(
        f"/api/host/{room_id}/resolution-console",
        headers={"X-Owner-Token": room["owner_token"]},
    )

    assert stage.status_code == 200
    assert stage.json()["items"] == [{"actionId": action_id, "text": "你听见走廊深处传来脚步声。"}]
    assert "mutations" not in stage.text
    assert "幕后真相" not in stage.text
    assert console.status_code == 200
    assert console.json()["items"] == [{
        "actionId": action_id,
        "hostConsole": {"actionId": action_id, "steps": [{"kind": "roll", "payload": {"roll": 42}}]},
        "ruleExplanation": {"formula": "d100 <= 60"},
    }]
    assert "canonicalResult" not in console.text


def test_host_can_release_pending_resolution_bundles(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    released_rooms = []

    class Pipeline:
        async def release_pending_bundles(self, room_id):
            released_rooms.append(room_id)
            return {"room_id": room_id, "released": 2, "failed": 0}

    previous_pipeline = getattr(client.app.state, "pipeline", None)
    client.app.state.pipeline = Pipeline()
    try:
        response = client.post(
            f"/api/host/{room['room_id']}/resolution-console/release-pending",
            headers={"X-Owner-Token": room["owner_token"]},
        )
    finally:
        client.app.state.pipeline = previous_pipeline

    assert response.status_code == 200
    assert response.json() == {"room_id": room["room_id"], "released": 2, "failed": 0}
    assert released_rooms == [room["room_id"]]
