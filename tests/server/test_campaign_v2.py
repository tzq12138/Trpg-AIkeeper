import json

from tests.server.conftest import create_room, login, setup_auth_test_data


def test_campaign_v2_dtos_and_emergency_notice_are_registered():
    from src.server.events.events_registry import ALL_EVENTS
    from src.server.models import CampaignHomeDTO, CampaignQuestionDTO, EvidenceCardDTO, PlayerDeviceSessionDTO

    device = PlayerDeviceSessionDTO(device_id="phone-a", status="active", controller=True)
    card = EvidenceCardDTO(
        evidence_card_id="card-1",
        title="问题",
        body="待确认",
        card_type="question",
        fact_status="hypothesis",
        visibility="party",
        source="player",
    )
    question = CampaignQuestionDTO(
        evidence_card_id=card.evidence_card_id,
        title=card.title,
        fact_status=card.fact_status,
    )
    home = CampaignHomeDTO(room_id="room-1", unresolved_questions=[question])

    assert device.device_id == "phone-a"
    assert home.unresolved_questions[0].evidence_card_id == "card-1"
    assert ALL_EVENTS["s2c_private_note_emergency_access"].audience == "player"


def _setup_player(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    return room_id, joined["character_id"], joined["player_token"]


def test_device_lease_requires_explicit_takeover(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}

    first = client.post(
        "/api/player/device-sessions/claim",
        headers=headers,
        json={"device_id": "phone-a"},
    )
    assert first.status_code == 200
    assert first.json()["controller"] is True
    assert first.json()["device_id"] == "phone-a"

    blocked = client.post(
        "/api/player/device-sessions/claim",
        headers=headers,
        json={"device_id": "laptop-b"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "controller_held"

    taken = client.post(
        "/api/player/device-sessions/claim",
        headers=headers,
        json={"device_id": "laptop-b", "takeover": True},
    )
    assert taken.status_code == 200
    assert taken.json()["controller"] is True
    assert taken.json()["device_id"] == "laptop-b"

    rows = test_db.execute(
        "SELECT device_id, status, is_controller FROM player_device_sessions "
        "WHERE room_id = %s AND character_id = %s ORDER BY device_id",
        (room_id, character_id),
    ).fetchall()
    assert [dict(row) for row in rows] == [
        {"device_id": "laptop-b", "status": "active", "is_controller": True},
        {"device_id": "phone-a", "status": "revoked", "is_controller": False},
    ]


def test_only_controller_device_can_confirm_action(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我用手枪射击门后的怪物"},
    ).json()
    claimed = client.post(
        "/api/player/device-sessions/claim",
        headers=headers,
        json={"device_id": "phone-a"},
    )
    assert claimed.status_code == 200

    blocked = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "X-Device-Id": "laptop-b", "Idempotency-Key": "blocked-device"},
        json={"confirmations": ["attack", "state_change"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "controller_held"

    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "X-Device-Id": "phone-a", "Idempotency-Key": "phone-device"},
        json={"confirmations": ["attack", "state_change"]},
    )
    assert confirmed.status_code == 200


def test_confirmed_action_starts_player_scoped_campaign_home(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token, "X-Device-Id": "phone-a"}
    test_db.execute(
        "INSERT INTO objectives (objective_id, room_id, text, type) VALUES (%s, %s, %s, 'team')",
        ("team-goal", room_id, "查明失踪者去向"),
    )
    test_db.execute(
        "INSERT INTO objectives (objective_id, room_id, character_id, text, type) "
        "VALUES (%s, %s, %s, %s, 'personal')",
        ("my-goal", room_id, character_id, "保护姐姐"),
    )
    test_db.execute(
        "INSERT INTO objectives (objective_id, room_id, character_id, text, type) "
        "VALUES (%s, %s, %s, %s, 'personal')",
        ("other-goal", room_id, "other-character", "不应泄露"),
    )
    test_db.commit()
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我观察门上的血迹"},
    ).json()
    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "start-session"},
        json={"confirmations": []},
    )
    assert confirmed.status_code == 200

    home = client.get("/api/player/campaign-home", headers=headers)
    assert home.status_code == 200
    payload = home.json()
    assert payload["room_id"] == room_id
    assert payload["session"]["status"] == "active"
    assert payload["session"]["started_by_character_id"] == character_id
    assert [item["objective_id"] for item in payload["team_objectives"]] == ["team-goal"]
    assert [item["objective_id"] for item in payload["personal_objectives"]] == ["my-goal"]
    assert "other-goal" not in str(payload)


def test_campaign_home_projects_only_the_current_solo_entry(client, test_db):
    from src.server.scenario.content_projection import ContentProjectionService

    room_id, _, player_token = _setup_player(client, test_db)
    version = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    graph = {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": "太阳高悬，你正在奥斯本药店门口等车。",
                    "target_node_ids": ["263"],
                    "citation": {"source_ref": "向火独行.pdf#page=4"},
                },
                {
                    "node_id": "263",
                    "title": "条目 263",
                    "text": "下一条隐藏正文不应提前泄露。",
                    "target_node_ids": [],
                    "citation": {"source_ref": "向火独行.pdf#page=58"},
                },
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), version["scenario_version_id"]),
    )
    ContentProjectionService(test_db).rebuild(
        version["scenario_version_id"], graph, requested_by="test"
    )
    test_db.execute(
        "INSERT INTO scenario_assets "
        "(asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "SELECT 'opening-image', scenario_id, 'opening.png', '长途车.png', 'image/png', 10, "
        "'data/scenario_assets/opening.png', 'host_only' FROM scenario_versions "
        "WHERE scenario_version_id = %s",
        (version["scenario_version_id"],),
    )
    test_db.execute(
        "INSERT INTO scenario_asset_bindings "
        "(binding_id, scenario_version_id, asset_id, target_type, target_key, confidence, status) "
        "VALUES ('opening-binding', %s, 'opening-image', 'branch_node', '1', 0.95, 'confirmed')",
        (version["scenario_version_id"],),
    )
    test_db.commit()

    response = client.get(
        "/api/player/campaign-home",
        headers={"X-Room-Token": player_token},
    )

    assert response.status_code == 200
    scene = response.json()["current_scene"]
    assert scene == {
        "node_id": "1",
        "title": "条目 1",
        "text_preview": "太阳高悬，你正在奥斯本药店门口等车。",
        "citation": {
            "label": "已校验依据",
            "page": None,
            "scene": None,
            "verified": True,
        },
        "choice_count": 1,
        "image_asset_id": "opening-image",
    }
    assert "source_ref" not in response.text
    assert "向火独行.pdf" not in response.text
    assert "下一条隐藏正文" not in response.text


def test_campaign_home_ends_session_after_offline_quiet_window(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token, "X-Device-Id": "phone-a"}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我观察门上的血迹"},
    ).json()
    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "old-session"},
        json={"confirmations": []},
    )
    assert confirmed.status_code == 200
    test_db.execute(
        "UPDATE campaign_sessions SET started_at = NOW() - INTERVAL '3 hours', "
        "last_activity_at = NOW() - INTERVAL '100 minutes' WHERE room_id = %s",
        (room_id,),
    )
    test_db.execute(
        "UPDATE player_device_sessions SET status = 'expired', is_controller = FALSE, "
        "last_seen_at = NOW() - INTERVAL '31 minutes' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    home = client.get("/api/player/campaign-home", headers=headers)
    assert home.status_code == 200
    assert home.json()["session"]["status"] == "ended"


def test_automatic_session_summary_keeps_player_visible_event_citations(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token, "X-Device-Id": "phone-a"}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我观察门上的血迹"},
    ).json()
    assert client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "citation-session"},
        json={"confirmations": []},
    ).status_code == 200
    event = test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload, issued_at) "
        "VALUES (%s, 's2c_public_observation', 'party', %s, NOW() - INTERVAL '100 minutes') "
        "RETURNING sequence",
        (room_id, '{"text":"可见线索"}'),
    ).fetchone()
    test_db.execute(
        "UPDATE campaign_sessions SET started_at = NOW() - INTERVAL '3 hours', "
        "last_activity_at = NOW() - INTERVAL '100 minutes' WHERE room_id = %s",
        (room_id,),
    )
    test_db.execute(
        "UPDATE player_device_sessions SET status = 'expired', is_controller = FALSE, "
        "last_seen_at = NOW() - INTERVAL '31 minutes' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    home = client.get("/api/player/campaign-home", headers=headers)
    assert home.status_code == 200
    assert home.json()["last_summary"]["citations"] == [
        {"event_sequence": event["sequence"], "citation_label": "s2c_public_observation"}
    ]
    citation = test_db.execute(
        "SELECT c.event_sequence FROM session_summary_citations c "
        "JOIN session_summaries s ON s.session_summary_id = c.session_summary_id "
        "WHERE s.room_id = %s",
        (room_id,),
    ).fetchone()
    assert citation["event_sequence"] == event["sequence"]


def test_private_note_is_encrypted_and_only_visible_to_its_owner(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    owner_headers = {"X-Room-Token": player_token}
    created = client.post(
        "/api/player/notes",
        headers=owner_headers,
        json={"title": "私密推测", "body": "馆长其实害怕地下室。"},
    )
    assert created.status_code == 201
    note_id = created.json()["note_id"]
    row = test_db.execute(
        "SELECT title_ciphertext, body_ciphertext FROM player_notes WHERE note_id = %s",
        (note_id,),
    ).fetchone()
    assert "馆长其实害怕地下室" not in row["body_ciphertext"]
    assert "私密推测" not in row["title_ciphertext"]

    owner_notes = client.get("/api/player/notes", headers=owner_headers)
    assert owner_notes.status_code == 200
    assert owner_notes.json()["notes"][0]["body"] == "馆长其实害怕地下室。"

    another = client.post(f"/api/player/rooms/{room_id}/join").json()
    another_notes = client.get(
        "/api/player/notes", headers={"X-Room-Token": another["player_token"]}
    )
    assert another_notes.status_code == 200
    assert another_notes.json()["notes"] == []


def test_host_emergency_note_access_requires_reauthentication_and_audits(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    created = client.post(
        "/api/player/notes",
        headers={"X-Room-Token": player_token},
        json={"title": "只给自己", "body": "不要把这个真相告诉其他玩家。"},
    )
    assert created.status_code == 201
    note_id = created.json()["note_id"]
    host_token = login(client)

    denied = client.post(
        f"/api/host/{room_id}/player-notes/{note_id}/emergency-decrypt",
        headers={"Authorization": f"Bearer {host_token}"},
        json={"reason": "处理玩家申诉", "password": "wrong"},
    )
    assert denied.status_code == 401

    accessed = client.post(
        f"/api/host/{room_id}/player-notes/{note_id}/emergency-decrypt",
        headers={"Authorization": f"Bearer {host_token}"},
        json={"reason": "处理玩家申诉", "password": "test123"},
    )
    assert accessed.status_code == 200
    assert accessed.json()["body"] == "不要把这个真相告诉其他玩家。"
    audit = test_db.execute(
        "SELECT owner_character_id, reason FROM private_data_access_audits WHERE note_id = %s",
        (note_id,),
    ).fetchone()
    assert dict(audit) == {"owner_character_id": character_id, "reason": "处理玩家申诉"}
    notification = test_db.execute(
        "SELECT audience, payload FROM events WHERE room_id = %s "
        "AND event_type = 's2c_private_note_emergency_access'",
        (room_id,),
    ).fetchone()
    assert notification["audience"] == "player"
    assert character_id in str(notification["payload"])


def test_player_evidence_stays_hypothesis_until_host_confirms(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    created = client.post(
        f"/api/rooms/{room_id}/evidence",
        headers={"X-Room-Token": player_token},
        json={
            "title": "馆长与地下室有关",
            "body": "这只是根据他的反应作出的推测。",
            "card_type": "person",
        },
    )
    assert created.status_code == 201
    card = created.json()
    assert card["fact_status"] == "hypothesis"
    assert card["created_by_character_id"] == character_id

    host_token = login(client)
    confirmed = client.patch(
        f"/api/host/{room_id}/evidence/{card['evidence_card_id']}/fact-status",
        headers={"Authorization": f"Bearer {host_token}"},
        json={"fact_status": "confirmed"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["fact_status"] == "confirmed"
    assert confirmed.json()["confirmed_by"] == "host"

    listed = client.get(
        f"/api/rooms/{room_id}/evidence", headers={"X-Room-Token": player_token}
    )
    assert listed.status_code == 200
    assert listed.json()["cards"][0]["fact_status"] == "confirmed"


def test_campaign_home_includes_party_unresolved_questions(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    question = client.post(
        f"/api/rooms/{room_id}/evidence",
        headers=headers,
        json={
            "title": "谁拿走了钥匙？",
            "body": "需要继续调查。",
            "card_type": "question",
        },
    )
    assert question.status_code == 201

    home = client.get("/api/player/campaign-home", headers=headers)
    assert home.status_code == 200
    assert home.json()["unresolved_questions"] == [
        {
            "evidence_card_id": question.json()["evidence_card_id"],
            "title": "谁拿走了钥匙？",
            "fact_status": "hypothesis",
        }
    ]


def test_host_schedule_and_player_attendance_appear_in_campaign_home(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    host_token = login(client)
    scheduled = client.post(
        f"/api/host/{room_id}/campaign-sessions/schedule",
        headers={"Authorization": f"Bearer {host_token}"},
        json={"scheduled_for": "2030-01-02T12:30:00+00:00"},
    )
    assert scheduled.status_code == 201
    session_id = scheduled.json()["campaign_session_id"]

    attendance = client.post(
        f"/api/player/campaign-sessions/{session_id}/attendance",
        headers={"X-Room-Token": player_token},
        json={"attendance_status": "tentative"},
    )
    assert attendance.status_code == 200
    assert attendance.json()["attendance_status"] == "tentative"

    home = client.get("/api/player/campaign-home", headers={"X-Room-Token": player_token})
    assert home.status_code == 200
    assert home.json()["next_session"]["campaign_session_id"] == session_id
    assert home.json()["next_session"]["attendance_status"] == "tentative"


def test_player_can_manage_private_personal_objectives(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    created = client.post(
        "/api/player/objectives",
        headers={"X-Room-Token": player_token},
        json={"text": "查清父亲留下的信"},
    )
    assert created.status_code == 201
    objective_id = created.json()["objective_id"]

    own_home = client.get("/api/player/campaign-home", headers={"X-Room-Token": player_token})
    assert [item["objective_id"] for item in own_home.json()["personal_objectives"]] == [objective_id]

    another = client.post(f"/api/player/rooms/{room_id}/join").json()
    other_home = client.get(
        "/api/player/campaign-home", headers={"X-Room-Token": another["player_token"]}
    )
    assert other_home.status_code == 200
    assert other_home.json()["personal_objectives"] == []


def test_host_can_maintain_team_objectives(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    host_token = login(client)
    created = client.post(
        f"/api/host/{room_id}/objectives",
        headers={"Authorization": f"Bearer {host_token}"},
        json={"text": "查清宅邸地下室的秘密"},
    )
    assert created.status_code == 201

    home = client.get("/api/player/campaign-home", headers={"X-Room-Token": player_token})
    assert home.status_code == 200
    assert home.json()["team_objectives"][0]["text"] == "查清宅邸地下室的秘密"


def test_image_map_returns_visible_regions_and_safe_token_projection(client, test_db):
    from src.server.map_persistence import init_room_map_state, mark_node_explored, set_character_position

    room_id, character_id, player_token = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO scenario_maps "
        "(map_id, scenario_id, status, map_type, base_asset, regions, nodes, edges) "
        "VALUES (%s, %s, 'confirmed', 'image', %s, %s, %s, %s)",
        (
            "image-map-1",
            "sc-test",
            '{"assetId":"handdrawn-map"}',
            '[{"regionId":"library","nodeId":"library","polygon":[[0.1,0.2],[0.3,0.2],[0.3,0.4]]},'
            '{"regionId":"cellar","nodeId":"cellar","polygon":[[0.6,0.7],[0.8,0.7],[0.8,0.9]]}]',
            '[{"nodeId":"library","name":"图书馆","position":{"x":20,"y":30},"isStart":true},'
            '{"nodeId":"cellar","name":"地下室","position":{"x":70,"y":80}}]',
            '[{"fromNode":"library","toNode":"cellar"}]',
        ),
    )
    test_db.commit()
    init_room_map_state(test_db, room_id, "image-map-1")
    set_character_position(test_db, character_id, room_id, "library")
    mark_node_explored(test_db, room_id, "library")

    response = client.get(f"/api/maps/{room_id}", headers={"X-Room-Token": player_token})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mapType"] == "image"
    assert payload["baseAsset"] == {"assetId": "handdrawn-map"}
    assert [location["nodeId"] for location in payload["knownLocations"]] == ["library", "cellar"]
    assert payload["partyPosition"] == {"nodeId": "library", "label": "图书馆"}
    assert payload["fogOfWar"] == []
    assert "regions" not in payload
    assert "tokens" not in payload


def test_host_can_fog_a_map_region_with_a_versioned_party_event(client, test_db):
    from src.server.map_persistence import init_room_map_state, mark_node_explored, set_character_position

    room_id, character_id, player_token = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO scenario_maps (map_id, scenario_id, status, map_type, regions, nodes, edges) "
        "VALUES (%s, %s, 'confirmed', 'image', %s, %s, %s)",
        (
            "fog-control-map",
            "sc-test",
            '[{"regionId":"library","nodeId":"library","polygon":[[0.1,0.2]]},'
            '{"regionId":"cellar","nodeId":"cellar","polygon":[[0.6,0.7]]}]',
            '[{"nodeId":"library","name":"图书馆","isStart":true},'
            '{"nodeId":"cellar","name":"地下室"}]',
            '[{"fromNode":"library","toNode":"cellar"}]',
        ),
    )
    test_db.commit()
    init_room_map_state(test_db, room_id, "fog-control-map")
    set_character_position(test_db, character_id, room_id, "library")
    mark_node_explored(test_db, room_id, "library")

    host_token = login(client)
    changed = client.post(
        f"/api/host/{room_id}/map/regions/cellar/visibility",
        headers={"Authorization": f"Bearer {host_token}"},
        json={"visible": False},
    )

    assert changed.status_code == 200
    assert changed.json() == {
        "roomId": room_id,
        "regionId": "cellar",
        "visible": False,
        "mapVersion": 2,
    }
    player_view = client.get(
        f"/api/maps/{room_id}", headers={"X-Room-Token": player_token}
    ).json()
    assert "regions" not in player_view
    assert "fogRegions" not in player_view
    assert [region["regionId"] for region in player_view["fogOfWar"]] == ["cellar"]
    event = test_db.execute(
        "SELECT event_type, audience, payload FROM events WHERE room_id = %s "
        "ORDER BY sequence DESC LIMIT 1",
        (room_id,),
    ).fetchone()
    assert dict(event) == {
        "event_type": "s2c_map_revealed",
        "audience": "party",
        "payload": {
            "regionId": "cellar",
            "visible": False,
            "mapVersion": 2,
            "roomId": room_id,
        },
    }


def test_confirmed_move_reveals_its_fogged_region_once(client, test_db):
    import asyncio

    from src.server.engine.resolution_pipeline import ResolutionPipeline
    from src.server.map_persistence import init_room_map_state, mark_node_explored, set_character_position
    from src.server.models import ResolutionResult

    class Dispatcher:
        def __init__(self):
            self.events = []

        async def emit(self, room_id, event_type, audience, payload, character_id=None):
            self.events.append((event_type, audience, payload, character_id))

    room_id, character_id, _ = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO scenario_maps (map_id, scenario_id, status, map_type, regions, nodes, edges) "
        "VALUES (%s, %s, 'confirmed', 'image', %s, %s, %s)",
        (
            "move-reveal-map",
            "sc-test",
            '[{"regionId":"library","nodeId":"library","polygon":[[0.1,0.2]]},'
            '{"regionId":"cellar","nodeId":"cellar","polygon":[[0.6,0.7]]}]',
            '[{"nodeId":"library","name":"图书馆","isStart":true},'
            '{"nodeId":"cellar","name":"地下室"}]',
            '[{"fromNode":"library","toNode":"cellar"}]',
        ),
    )
    test_db.commit()
    init_room_map_state(test_db, room_id, "move-reveal-map")
    test_db.execute(
        "UPDATE room_map_state SET fog_regions = %s WHERE room_id = %s",
        ('["cellar"]', room_id),
    )
    test_db.commit()
    set_character_position(test_db, character_id, room_id, "library")
    mark_node_explored(test_db, room_id, "library")
    dispatcher = Dispatcher()
    pipeline = ResolutionPipeline(test_db, dispatcher=dispatcher)

    asyncio.run(pipeline._apply_move_result(
        {
            "room_id": room_id,
            "character_id": character_id,
            "params": {
                "targetNodeId": "cellar",
                "fromNodeId": "library",
                "analysis": {"visibility": "party"},
            },
        },
        ResolutionResult(actionId="reveal-move", roomId=room_id, characterId=character_id),
    ))

    state = test_db.execute(
        "SELECT fog_regions, state_version FROM room_map_state WHERE room_id = %s", (room_id,)
    ).fetchone()
    assert state["fog_regions"] == []
    map_events = [event for event in dispatcher.events if event[0] == "s2c_map_updated"]
    assert map_events == [
        (
            "s2c_map_updated",
            "party",
            {
                "exploredNodes": ["library", "cellar"],
                "currentPositions": {character_id: "cellar"},
                "private": False,
                "revealedRegionIds": ["cellar"],
                "mapVersion": state["state_version"],
            },
            None,
        )
    ]


def test_host_map_operations_keep_authoritative_versions_and_reveal_destination_fog(client, test_db):
    from src.server.map_persistence import init_room_map_state, mark_node_explored, set_character_position

    room_id, character_id, _ = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO scenario_maps (map_id, scenario_id, status, map_type, regions, nodes, edges) "
        "VALUES (%s, %s, 'confirmed', 'image', %s, %s, %s)",
        (
            "host-map-versioned",
            "sc-test",
            '[{"regionId":"library","nodeId":"library","polygon":[[0.1,0.2]]},'
            '{"regionId":"cellar","nodeId":"cellar","polygon":[[0.6,0.7]]}]',
            '[{"nodeId":"library","name":"图书馆","isStart":true},'
            '{"nodeId":"cellar","name":"地下室"}]',
            '[{"fromNode":"library","toNode":"cellar"}]',
        ),
    )
    test_db.commit()
    init_room_map_state(test_db, room_id, "host-map-versioned")
    set_character_position(test_db, character_id, room_id, "library")
    mark_node_explored(test_db, room_id, "library")
    test_db.execute(
        "UPDATE room_map_state SET fog_regions = %s WHERE room_id = %s",
        ('["cellar"]', room_id),
    )
    test_db.commit()
    host_token = login(client)
    headers = {"Authorization": f"Bearer {host_token}"}

    hidden = client.post(
        f"/api/host/{room_id}/map/reveal",
        headers=headers,
        json={"node_id": "cellar", "visible": False},
    )
    state_after_hide = test_db.execute(
        "SELECT state_version FROM room_map_state WHERE room_id = %s", (room_id,)
    ).fetchone()
    assert hidden.status_code == 200
    assert hidden.json()["mapVersion"] == state_after_hide["state_version"]

    moved = client.post(
        f"/api/host/{room_id}/map/move-character",
        headers=headers,
        json={
            "character_id": character_id,
            "node_id": "cellar",
            "reason": "玩家断线后经同意修正位置",
        },
    )

    state_after_move = test_db.execute(
        "SELECT fog_regions, state_version FROM room_map_state WHERE room_id = %s", (room_id,)
    ).fetchone()
    assert moved.status_code == 200
    assert state_after_move["fog_regions"] == []
    assert moved.json()["revealedRegionIds"] == ["cellar"]
    assert moved.json()["mapVersion"] == state_after_move["state_version"]


def test_player_map_falls_back_to_a_safe_text_scene_when_no_map_exists(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    test_db.execute(
        "UPDATE scenarios SET knowledge_graph = %s WHERE scenario_id = 'sc-test'",
        (
            '{"scenes":['
            '{"sceneId":"hall","name":"入口大厅","public_description":"雨水顺着玻璃窗流下。"},'
            '{"sceneId":"cellar","name":"邪教地窖","description":"不应公开的真相。","is_hidden":true}]}'
            ,
        ),
    )
    test_db.commit()

    response = client.get(f"/api/maps/{room_id}", headers={"X-Room-Token": player_token})

    assert response.status_code == 200
    payload = response.json()
    assert payload["roomId"] == room_id
    assert payload["mapStatus"] == "text_mode"
    assert payload["knownLocations"] == []
    assert payload["knownConnections"] == []
    assert payload["partyPosition"] is None
    assert payload["fogOfWar"] == []
    assert payload["textScene"] == {
        "name": "入口大厅",
        "description": "雨水顺着玻璃窗流下。",
        "visibleExits": [],
    }
    assert "nodes" not in payload
    assert "currentNodeId" not in payload
    assert "邪教地窖" not in response.text
    assert "不应公开的真相" not in response.text


def test_player_session_zero_tracks_five_required_confirmations(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    before = client.get("/api/player/session-zero", headers=headers)
    assert before.status_code == 200
    assert [item["step"] for item in before.json()["steps"]] == [
        "character_rules", "safety", "ai_host", "private_data", "connection",
    ]
    assert all(item["confirmed"] is False for item in before.json()["steps"])

    for step in ["character_rules", "safety", "ai_host", "private_data", "connection"]:
        response = client.post(
            f"/api/player/session-zero/{step}", headers=headers, json={"confirmed": True}
        )
        assert response.status_code == 200

    after = client.get("/api/player/session-zero", headers=headers)
    assert all(item["confirmed"] is True for item in after.json()["steps"])
    assert after.json()["complete"] is True


def test_hidden_map_token_is_visible_only_to_its_owner(client, test_db):
    from src.server.map_persistence import (
        init_room_map_state,
        mark_node_explored,
        set_character_position,
        set_token_visibility,
    )

    room_id, first_character_id, first_token = _setup_player(client, test_db)
    second = client.post(f"/api/player/rooms/{room_id}/join").json()
    test_db.execute(
        "INSERT INTO scenario_maps (map_id, scenario_id, status, nodes, edges) VALUES (%s, %s, 'confirmed', %s, %s)",
        (
            "secret-token-map",
            "sc-test",
            '[{"nodeId":"hall","name":"大厅","isStart":true}]',
            '[]',
        ),
    )
    test_db.commit()
    init_room_map_state(test_db, room_id, "secret-token-map")
    set_character_position(test_db, first_character_id, room_id, "hall")
    set_character_position(test_db, second["character_id"], room_id, "hall")
    mark_node_explored(test_db, room_id, "hall")
    set_token_visibility(test_db, room_id, second["character_id"], "hidden")

    first_view = client.get(f"/api/maps/{room_id}", headers={"X-Room-Token": first_token}).json()
    second_view = client.get(
        f"/api/maps/{room_id}", headers={"X-Room-Token": second["player_token"]}
    ).json()
    assert "tokens" not in first_view
    assert "tokens" not in second_view
    assert first_view["partyPosition"] == {"nodeId": "hall", "label": "大厅"}
    assert second_view["partyPosition"] == {"nodeId": "hall", "label": "大厅"}


def test_secret_move_is_compiled_as_private_confirmed_movement(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={"declared_intent": "我偷偷前往地下室"},
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["intent_type"] == "move"
    assert draft["visibility"] == "private"
    assert draft["movement_target"] == "地下室"
    assert draft["confirmation_requirements"] == ["movement", "secret_action", "state_change"]


def test_private_move_hides_token_and_emits_only_to_its_owner(client, test_db):
    import asyncio

    from src.server.engine.resolution_pipeline import ResolutionPipeline
    from src.server.map_persistence import init_room_map_state, mark_node_explored, set_character_position
    from src.server.models import ResolutionResult

    class Dispatcher:
        def __init__(self):
            self.events = []

        async def emit(self, room_id, event_type, audience, payload, character_id=None):
            self.events.append((event_type, audience, payload, character_id))

    room_id, character_id, _ = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO scenario_maps (map_id, scenario_id, status, nodes, edges) VALUES (%s, %s, 'confirmed', %s, %s)",
        (
            "private-move-map",
            "sc-test",
            '[{"nodeId":"hall","name":"大厅","isStart":true},{"nodeId":"cellar","name":"地下室"}]',
            '[{"fromNode":"hall","toNode":"cellar"}]',
        ),
    )
    test_db.commit()
    init_room_map_state(test_db, room_id, "private-move-map")
    set_character_position(test_db, character_id, room_id, "hall")
    mark_node_explored(test_db, room_id, "hall")
    dispatcher = Dispatcher()
    pipeline = ResolutionPipeline(test_db, dispatcher=dispatcher)

    asyncio.run(pipeline._apply_move_result(
        {
            "room_id": room_id,
            "character_id": character_id,
            "params": {
                "targetNodeId": "cellar",
                "fromNodeId": "hall",
                "analysis": {"visibility": "private"},
            },
        },
        ResolutionResult(actionId="private-move", roomId=room_id, characterId=character_id),
    ))

    state = test_db.execute("SELECT token_visibility FROM room_map_state WHERE room_id = %s", (room_id,)).fetchone()
    assert state["token_visibility"][character_id] == "hidden"
    assert [(event_type, audience, target) for event_type, audience, _, target in dispatcher.events] == [
        ("s2c_player_moved", "player", character_id),
        ("s2c_map_updated", "player", character_id),
    ]


def test_library_only_returns_ready_to_play_published_scenarios(client, test_db):
    setup_auth_test_data(test_db)
    test_db.execute(
        "UPDATE scenarios SET knowledge_graph = %s, quality_report = %s WHERE scenario_id = 'sc-test'",
        ('{"scenes":[{"id":"scene-1"}],"npcs":[{"id":"npc-1"}],"clues":[{"id":"clue-1"}]}', '{"level":"pass"}'),
    )
    test_db.execute(
        "INSERT INTO rule_sets (rule_set_id, name, slug, system, license_type, created_by, status) "
        "VALUES ('coc7', 'CoC7', 'coc7', 'coc7', 'open', 'test', 'published')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions (rule_set_version_id, rule_set_id, version_number, status, created_by) "
        "VALUES ('coc7-v1', 'coc7', 1, 'published', 'test')"
    )
    test_db.execute(
        "INSERT INTO scenario_rule_bindings (scenario_version_id, rule_set_version_id) "
        "VALUES ('sv-sc-test', 'coc7-v1')"
    )
    test_db.execute(
        "INSERT INTO character_templates (template_id, scenario_id, name) VALUES ('tpl-1', 'sc-test', '调查员')"
    )
    test_db.commit()

    response = client.get("/api/library")
    assert response.status_code == 200
    assert response.json()["items"] == [{
        "scenario_id": "sc-test",
        "scenario_version_id": "sv-sc-test",
        "title": "Test Scenario",
        "ready_to_play": True,
    }]


def test_private_note_allows_one_encrypted_image_attachment(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    note = client.post(
        "/api/player/notes",
        headers=headers,
        json={"title": "照片", "body": "我拍下了墙上的符号。"},
    ).json()
    image = b"\x89PNG\r\n\x1a\nexample-image"
    uploaded = client.post(
        f"/api/player/notes/{note['note_id']}/attachment",
        headers=headers,
        files={"file": ("symbol.png", image, "image/png")},
    )
    assert uploaded.status_code == 201
    row = test_db.execute(
        "SELECT filename_ciphertext, content_ciphertext FROM note_attachments WHERE note_id = %s",
        (note["note_id"],),
    ).fetchone()
    assert "symbol.png" not in row["filename_ciphertext"]
    assert "example-image" not in row["content_ciphertext"]

    downloaded = client.get(f"/api/player/notes/{note['note_id']}/attachment", headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("image/png")
    assert downloaded.content == image

    second = client.post(
        f"/api/player/notes/{note['note_id']}/attachment",
        headers=headers,
        files={"file": ("second.png", image, "image/png")},
    )
    assert second.status_code == 409


def test_evidence_links_only_connect_visible_cards_in_same_room(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    first = client.post(
        f"/api/rooms/{room_id}/evidence",
        headers=headers,
        json={"title": "钥匙", "body": "在书房发现。", "card_type": "item"},
    ).json()
    second = client.post(
        f"/api/rooms/{room_id}/evidence",
        headers=headers,
        json={"title": "书房", "body": "门锁被撬过。", "card_type": "location"},
    ).json()

    linked = client.post(
        f"/api/rooms/{room_id}/evidence/links",
        headers=headers,
        json={
            "from_evidence_card_id": first["evidence_card_id"],
            "to_evidence_card_id": second["evidence_card_id"],
            "relation_type": "found_at",
        },
    )
    assert linked.status_code == 201

    listed = client.get(f"/api/rooms/{room_id}/evidence", headers=headers).json()
    assert listed["links"] == [
        {
            "evidence_link_id": linked.json()["evidence_link_id"],
            "from_evidence_card_id": first["evidence_card_id"],
            "to_evidence_card_id": second["evidence_card_id"],
            "relation_type": "found_at",
        }
    ]
