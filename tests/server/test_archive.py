import json
import pytest
from src.server.export import export_markdown
from tests.server.conftest import setup_auth_test_data, create_room


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


def test_action_history(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-1', %s, %s, 'dialogue', 'look around', 'resolved')",
        (room_id, char_id),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-2', %s, %s, 'skill_check', 'spot hidden', 'queued')",
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
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

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
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status, result) "
        "VALUES ('sc-1', %s, %s, 'skill_check', 'spot hidden', 'resolved', '\"success\"')",
        (room_id, char_id),
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('dlg-1', %s, %s, 'dialogue', 'talk', 'resolved')",
        (room_id, char_id),
    )
    test_db.commit()

    resp = client.get("/api/player/archive/skill-checks", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["skill_checks"]) == 1
    assert data["skill_checks"][0]["action_id"] == "sc-1"


def test_public_replay_for_host(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

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
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    resp = client.get(
        f"/api/rooms/{room_id}/replay",
        headers={"X-Owner-Token": "bad-token"},
    )
    assert resp.status_code == 403


def test_host_timeline_route_is_mounted(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)
    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "timeline event"})

    resp = client.get(
        f"/api/rooms/{room_id}/timeline",
        headers={"X-Owner-Token": owner_token},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["events"][0]["event_type"] == "s2c_public_observation"
    assert data["events"][0]["payload"]["text"] == "timeline event"


def test_campaign_summary_full_scope_for_host(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)
    _insert_event(test_db, room_id, 1, "s2c_public_observation", "party", {"text": "timeline event"})

    resp = client.get(
        f"/api/rooms/{room_id}/campaign?scope=full",
        headers={"X-Owner-Token": owner_token},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["room_id"] == room_id
    assert "total_actions" in data


def test_end_campaign_emits_campaign_ended_event(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    resp = client.post(
        f"/api/rooms/{room_id}/end",
        headers={"X-Owner-Token": owner_token},
        json={
            "ending_type": "victory",
            "ending_name": "成功逃脱",
            "text": "调查员们成功逃离烬头村。",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ending_type"] == "victory"

    room = test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    assert room["status"] == "completed"

    event = test_db.execute(
        "SELECT payload FROM events WHERE room_id = %s AND event_type = 's2c_campaign_ended' ORDER BY sequence DESC LIMIT 1",
        (room_id,),
    ).fetchone()
    assert event is not None
    payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
    assert payload["ending_type"] == "victory"
    assert payload["endingName"] == "成功逃脱"


def test_archive_filter_by_type(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

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


def test_narrative_archive_reads_released_bundles_without_exposing_other_players_results(
    client, test_db
):
    room_id, _, char_id, token = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('other-char', %s, 'Other', 'other-token')",
        (room_id,),
    )
    for action_id, owner, intent, narrative, result, state_version in [
        ("own-bundle", char_id, "检查书桌", "你在书桌夹层找到烧焦的车票。", {"roll": 23}, 4),
        ("other-bundle", "other-char", "私下翻找档案", "队友从档案室回来，神色凝重。", {"secret": "地下室入口"}, 5),
    ]:
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
            "VALUES (%s, %s, %s, 'dialogue', %s, 'completed')",
            (action_id, room_id, owner, intent),
        )
        test_db.execute(
            "INSERT INTO resolution_bundles "
            "(action_id, room_id, character_id, canonical_result, rule_explanation, "
            "actor_projection, stage_projection, host_console, release_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'released')",
            (
                action_id,
                room_id,
                owner,
                json.dumps({"stateVersion": state_version}),
                json.dumps({"citations": [{"label": "已校验依据", "page": 2}]}),
                json.dumps({"result": result}),
                json.dumps({"narrativeText": narrative, "spoilerStatus": "none"}),
                json.dumps({"transactionId": f"tx-{action_id}"}),
            ),
        )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('unreleased-bundle', %s, %s, 'dialogue', '未公布的发现', 'completed')",
        (room_id, char_id),
    )
    test_db.execute(
        "INSERT INTO resolution_bundles "
        "(action_id, room_id, character_id, canonical_result, rule_explanation, "
        "actor_projection, stage_projection, host_console, release_status) "
        "VALUES ('unreleased-bundle', %s, %s, '{}', '{}', '{}', %s, '{}', 'ready')",
        (room_id, char_id, json.dumps({"narrativeText": "不应出现"})),
    )
    test_db.commit()

    response = client.get("/api/player/archive?type=narrative", headers={"X-Room-Token": token})

    assert response.status_code == 200
    entries = response.json()["entries"]
    assert [entry["data"]["text"] for entry in entries] == [
        "你在书桌夹层找到烧焦的车票。",
        "队友从档案室回来，神色凝重。",
    ]
    own = next(entry for entry in entries if entry["data"]["actionId"] == "own-bundle")
    other = next(entry for entry in entries if entry["data"]["actionId"] == "other-bundle")
    assert own["data"]["result"] == {"roll": 23}
    assert own["data"]["citations"] == [{"label": "已校验依据", "page": 2}]
    assert own["data"]["stateVersion"] == 4
    assert own["data"]["transactionId"] == "tx-own-bundle"
    assert "result" not in other["data"]
    assert "citations" not in other["data"]
    assert "transactionId" not in other["data"]

    citations = client.get("/api/player/archive?type=citations", headers={"X-Room-Token": token})
    assert citations.status_code == 200
    assert [entry["data"]["actionId"] for entry in citations.json()["entries"]] == ["own-bundle"]


def test_archive_search_keyword(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

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
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    for i in range(10):
        _insert_event(test_db, room_id, i + 1, "s2c_public_observation", "party", {"text": f"event{i}"})

    resp = client.get("/api/player/archive?offset=0&limit=3", headers={"X-Room-Token": token})
    data = resp.json()
    assert len(data["entries"]) == 3
    assert data["total"] == 10

    resp = client.get("/api/player/archive?offset=8&limit=5", headers={"X-Room-Token": token})
    data = resp.json()
    assert len(data["entries"]) == 2


def test_export_omits_reveal_summary_when_public_projection_exists(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client)
    room_id = room["room_id"]
    action_id = "action-1"
    narrative = "调查员在书桌夹层里找到一张燃烧过的车票。"

    _insert_event(
        test_db,
        room_id,
        1,
        "s2c_reveal_transaction",
        "host",
        {"actionId": action_id, "summaryText": narrative},
    )
    _insert_event(
        test_db,
        room_id,
        2,
        "s2c_public_observation",
        "party",
        {"actionId": action_id, "text": narrative},
    )

    result = export_markdown(test_db, room_id)

    assert result["content"].count(narrative) == 1


def test_export_rejects_unknown_scope_instead_of_treating_it_as_full(client, test_db):
    room_id, _, _, token = _setup_player(client, test_db)

    response = client.get(
        f"/api/rooms/{room_id}/export?format=json&scope=anything",
        headers={"X-Room-Token": token},
    )

    assert response.status_code == 422


def test_export_rejects_unknown_format(client, test_db):
    room_id, _, _, token = _setup_player(client, test_db)

    response = client.get(
        f"/api/rooms/{room_id}/export?format=xml&scope=public",
        headers={"X-Room-Token": token},
    )

    assert response.status_code == 422


def test_replay_pagination(client, test_db):
    room_id, owner_token, char_id, token = _setup_player(client, test_db)

    for i in range(10):
        _insert_event(test_db, room_id, i + 1, "s2c_public_observation", "party", {"text": f"event{i}"})

    resp = client.get(
        f"/api/rooms/{room_id}/replay?offset=0&limit=3",
        headers={"X-Owner-Token": owner_token},
    )
    data = resp.json()
    assert len(data["events"]) == 3
    assert data["total"] == 10
