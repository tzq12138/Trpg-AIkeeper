from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json

import pytest

from src.server.db_adapter import PgConnection
from src.server.models import ActionDraftAnalyzeRequest
from src.server.player.action_service import analyze_action_draft, confirm_action_draft
from tests.server.conftest import create_room, setup_auth_test_data


def _setup_player(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    return room_id, joined["character_id"], joined["player_token"]


def test_action_submission_is_received_before_ai_analysis_and_is_idempotent(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    payload = {
        "actionId": "client-action-1",
        "rawText": "我先检查车厢门锁。",
        "inputMode": "action",
        "clientSequence": 7,
        "baseStateVersion": 0,
    }

    created = client.post("/api/player/action-submissions", headers={"X-Room-Token": player_token}, json=payload)
    replayed = client.post("/api/player/action-submissions", headers={"X-Room-Token": player_token}, json=payload)

    assert created.status_code == 201
    assert replayed.status_code == 201
    assert created.json() == replayed.json()
    assert created.json()["actionId"] == "client-action-1"
    assert created.json()["status"] == "received"
    assert created.json()["requiresAnalysis"] is True
    row = test_db.execute(
        "SELECT room_id, character_id, input_mode, raw_text_ciphertext, client_sequence, status "
        "FROM player_action_submissions WHERE action_id = %s",
        ("client-action-1",),
    ).fetchone()
    assert {
        key: value for key, value in dict(row).items() if key != "raw_text_ciphertext"
    } == {
        "room_id": room_id,
        "character_id": character_id,
        "input_mode": "action",
        "client_sequence": 7,
        "status": "received",
    }
    assert "我先检查车厢门锁。" not in row["raw_text_ciphertext"]
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0


def test_non_stateful_submission_is_recorded_without_creating_world_action(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    before = test_db.execute("SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)).fetchone()

    response = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "client-speech-1",
            "rawText": "我对队友说：先别碰那扇门。",
            "inputMode": "speech",
            "requestedVisibility": "party",
        },
    )

    after = test_db.execute("SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    assert response.status_code == 201
    assert response.json()["requiresAnalysis"] is False
    assert response.json()["status"] == "recorded"
    assert after["state_version"] == before["state_version"]
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0


def test_private_note_submission_keeps_its_text_encrypted_and_out_of_world_actions(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    response = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "private-note-1",
            "rawText": "不要告诉任何人我看见了地下室的钥匙。",
            "inputMode": "private_note",
        },
    )

    row = test_db.execute(
        "SELECT requested_visibility, raw_text_ciphertext FROM player_action_submissions WHERE action_id = %s",
        ("private-note-1",),
    ).fetchone()
    assert response.status_code == 201
    assert response.json()["status"] == "recorded"
    assert row["requested_visibility"] == "private"
    assert "不要告诉任何人" not in row["raw_text_ciphertext"]
    note = test_db.execute(
        "SELECT character_id, title_ciphertext, body_ciphertext FROM player_notes WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert note["character_id"] == character_id
    assert "不要告诉任何人" not in note["body_ciphertext"]
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s", (room_id,)
    ).fetchone()["count"] == 0


def test_party_chat_submission_delivers_a_party_event_without_creating_an_action(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "party-chat-1",
            "rawText": "我们先查护士的办公室。",
            "inputMode": "party_chat",
        },
    )

    assert response.status_code == 201
    event = test_db.execute(
        "SELECT event_type, audience, payload FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert event["event_type"] == "s2c_team_message"
    assert event["audience"] == "party"
    assert event["payload"]["messageId"] == "party-chat-1"
    assert event["payload"]["text"] == "我们先查护士的办公室。"
    assert event["payload"]["channel"] == "party_chat"
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0


def test_speech_submission_is_visible_to_the_party_without_creating_an_action(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "speech-1",
            "rawText": "教授，你昨晚在哪里？",
            "inputMode": "speech",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "recorded"
    event = test_db.execute(
        "SELECT event_type, audience, payload FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert event["event_type"] == "s2c_team_message"
    assert event["audience"] == "party"
    assert event["payload"]["channel"] == "speech"
    assert event["payload"]["text"] == "教授，你昨晚在哪里？"
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0


def test_room_can_route_speech_through_dialogue_draft_without_party_leak(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    test_db.execute(
        "UPDATE rooms SET speech_routing = 'npc_dialogue' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    response = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "speech-dialogue-1",
            "rawText": "教授，你昨晚在哪里？",
            "inputMode": "speech",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "received"
    assert response.json()["requiresAnalysis"] is True
    submission = test_db.execute(
        "SELECT requested_visibility, status FROM player_action_submissions WHERE action_id = %s",
        ("speech-dialogue-1",),
    ).fetchone()
    assert dict(submission) == {"requested_visibility": "public", "status": "received"}
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s", (room_id,)
    ).fetchone()["count"] == 0
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0


def test_dialogue_speech_is_rejected_before_recording_after_combat_lock(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active', speech_routing = 'npc_dialogue' WHERE room_id = %s",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('locked-dialogue-turn', %s, 1, 'resolving', 'combat')",
        (room_id,),
    )
    test_db.commit()

    response = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "speech-after-lock-1",
            "rawText": "教授，快趴下！",
            "inputMode": "speech",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "speech_round_locked"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM player_action_submissions WHERE action_id = %s",
        ("speech-after-lock-1",),
    ).fetchone()["count"] == 0
    assert test_db.execute("SELECT COUNT(*) AS count FROM events WHERE room_id = %s", (room_id,)).fetchone()["count"] == 0


def test_locked_dialogue_speech_replay_returns_the_pre_lock_receipt(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active', speech_routing = 'npc_dialogue' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()
    payload = {
        "actionId": "speech-before-lock-1",
        "rawText": "教授，快趴下！",
        "inputMode": "speech",
    }

    created = client.post("/api/player/action-submissions", headers={"X-Room-Token": player_token}, json=payload)
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('replay-dialogue-turn', %s, 1, 'resolving', 'combat')",
        (room_id,),
    )
    test_db.commit()
    replayed = client.post("/api/player/action-submissions", headers={"X-Room-Token": player_token}, json=payload)

    assert created.status_code == 201
    assert replayed.status_code == 201
    assert replayed.json() == created.json()
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM player_action_submissions WHERE action_id = %s",
        ("speech-before-lock-1",),
    ).fetchone()["count"] == 1


def test_party_chat_remains_available_after_combat_lock(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('party-chat-lock-turn', %s, 1, 'resolving', 'combat')",
        (room_id,),
    )
    test_db.commit()

    response = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "party-chat-after-lock-1",
            "rawText": "我们先守住铁门。",
            "inputMode": "party_chat",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "recorded"
    event = test_db.execute(
        "SELECT audience, payload FROM events WHERE room_id = %s AND event_type = 's2c_team_message'",
        (room_id,),
    ).fetchone()
    assert event["audience"] == "party"
    assert event["payload"]["channel"] == "party_chat"


def test_ooc_submission_stays_out_of_actions_and_uses_its_own_team_channel(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "ooc-1",
            "rawText": "我去拿杯水，三分钟回来。",
            "inputMode": "ooc",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "recorded"
    event = test_db.execute(
        "SELECT event_type, audience, payload FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert event["event_type"] == "s2c_team_message"
    assert event["audience"] == "party"
    assert event["payload"]["channel"] == "ooc"
    assert event["payload"]["text"] == "我去拿杯水，三分钟回来。"
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0


def test_generic_clue_share_submission_requires_a_selected_clue_transaction(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "clue-share-1",
            "rawText": "我把信件内容告诉大家。",
            "inputMode": "clue_share",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "clue_share_requires_selected_clue"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM player_action_submissions"
    ).fetchone()["count"] == 0


def test_safety_submission_anonymously_pauses_engine_until_triggering_player_resumes(
    client,
    test_db,
):
    room_id, character_id, player_token = _setup_player(client, test_db)
    other = client.post(f"/api/player/rooms/{room_id}/join").json()
    owner = test_db.execute(
        "SELECT owner_token FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    message = "请淡出描述中的针头和身体伤害。"
    payload = {
        "actionId": "safety-1",
        "rawText": message,
        "inputMode": "safety",
    }

    created = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json=payload,
    )
    replayed = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json=payload,
    )
    marker = test_db.execute(
        "SELECT event_type, audience, payload FROM events WHERE room_id = %s "
        "AND event_type = 's2c_safety_request'",
        (room_id,),
    ).fetchone()
    host_view = client.get(
        f"/api/host/{room_id}/safety-requests",
        headers={"X-Owner-Token": owner["owner_token"]},
    )
    trigger_state = client.get(
        "/api/player/safety-state",
        headers={"X-Room-Token": player_token},
    )
    other_state = client.get(
        "/api/player/safety-state",
        headers={"X-Room-Token": other["player_token"]},
    )
    blocked_action = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": other["player_token"]},
        json={
            "actionId": "blocked-by-safety",
            "rawText": "我继续调查。",
            "inputMode": "action",
        },
    )
    forbidden_resume = client.post(
        "/api/player/safety-pauses/safety-1/resume",
        headers={"X-Room-Token": other["player_token"]},
    )
    resumed = client.post(
        "/api/player/safety-pauses/safety-1/resume",
        headers={"X-Room-Token": player_token},
    )
    accepted_after_resume = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": other["player_token"]},
        json={
            "actionId": "accepted-after-safety",
            "rawText": "我继续调查。",
            "inputMode": "action",
        },
    )

    assert created.status_code == 201
    assert replayed.status_code == 201
    assert created.json()["status"] == "safety_paused"
    assert marker["audience"] == "host"
    assert marker["payload"] == {"requestId": "safety-1"}
    assert message not in json.dumps(marker["payload"], ensure_ascii=False)
    assert host_view.status_code == 200
    assert host_view.json()["items"] == [{
        "actionId": "safety-1",
        "createdAt": host_view.json()["items"][0]["createdAt"],
    }]
    assert trigger_state.json() == {
        "status": "safety_paused",
        "activePauseCount": 1,
        "canResume": True,
        "ownRequestIds": ["safety-1"],
    }
    assert other_state.json() == {
        "status": "safety_paused",
        "activePauseCount": 1,
        "canResume": False,
        "ownRequestIds": [],
    }
    assert blocked_action.status_code == 409
    assert blocked_action.json()["detail"]["code"] == "safety_paused"
    assert forbidden_resume.status_code == 403
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"
    assert accepted_after_resume.status_code == 201
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s "
        "AND event_type = 's2c_safety_request'",
        (room_id,),
    ).fetchone()["count"] == 1
    safety_events = test_db.execute(
        "SELECT payload FROM events WHERE room_id = %s "
        "AND event_type = 's2c_safety_state_changed' ORDER BY sequence",
        (room_id,),
    ).fetchall()
    assert [event["payload"]["status"] for event in safety_events] == [
        "safety_paused",
        "active",
    ]
    assert all(
        "characterId" not in event["payload"] and message not in str(event["payload"])
        for event in safety_events
    )


def test_table_steward_can_extend_pause_or_end_session_but_cannot_force_resume(
    client,
    test_db,
):
    room_id, _, player_token = _setup_player(client, test_db)
    owner_token = test_db.execute(
        "SELECT owner_token FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["owner_token"]
    created = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "safety-end-session",
            "rawText": "请停止这一幕。",
            "inputMode": "safety",
        },
    )

    extended = client.post(
        f"/api/host/{room_id}/safety/extend",
        headers={"X-Owner-Token": owner_token},
    )
    still_paused = client.get(
        "/api/player/safety-state",
        headers={"X-Room-Token": player_token},
    )
    ended = client.post(
        f"/api/host/{room_id}/safety/end-session",
        headers={"X-Owner-Token": owner_token},
    )

    assert created.status_code == 201
    assert extended.status_code == 200
    assert extended.json()["status"] == "safety_paused"
    assert still_paused.json()["status"] == "safety_paused"
    assert ended.status_code == 200
    assert ended.json() == {
        "status": "completed",
        "endingType": "safe_abort",
        "roomId": room_id,
    }
    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["status"] == "completed"
    assert test_db.execute(
        "SELECT status FROM player_action_submissions "
        "WHERE action_id = 'safety-end-session'"
    ).fetchone()["status"] == "safety_ended"
    archive = test_db.execute(
        "SELECT ending_type, character_arcs FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert archive["ending_type"] == "safe_abort"
    assert len(archive["character_arcs"]) == 1


def test_rule_question_is_private_to_its_author_and_never_enters_actions(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    other_player = client.post(f"/api/player/rooms/{room_id}/join").json()["player_token"]
    headers = {"X-Room-Token": player_token}

    created = client.post(
        "/api/player/action-submissions",
        headers=headers,
        json={
            "actionId": "rule-question-1",
            "rawText": "心理学能判断他说谎吗？",
            "inputMode": "rule_question",
        },
    )
    mine = client.get("/api/player/rule-questions", headers=headers)
    others = client.get("/api/player/rule-questions", headers={"X-Room-Token": other_player})

    assert created.status_code == 201
    assert mine.status_code == 200
    assert mine.json()["questions"] == [{
        "actionId": "rule-question-1",
        "text": "心理学能判断他说谎吗？",
        "createdAt": mine.json()["questions"][0]["createdAt"],
    }]
    assert others.status_code == 200
    assert others.json()["questions"] == []
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s", (room_id,)
    ).fetchone()["count"] == 0


def test_action_submission_rejects_reusing_client_action_id_with_changed_text(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    client.post(
        "/api/player/action-submissions",
        headers=headers,
        json={"actionId": "client-action-2", "rawText": "我观察大厅。", "inputMode": "action"},
    )

    conflict = client.post(
        "/api/player/action-submissions",
        headers=headers,
        json={"actionId": "client-action-2", "rawText": "我放火烧掉大厅。", "inputMode": "action"},
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "action_id_reused"


def test_action_analysis_must_match_the_received_submission_text(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    client.post(
        "/api/player/action-submissions",
        headers=headers,
        json={"actionId": "client-action-3", "rawText": "我观察大厅。", "inputMode": "action"},
    )

    mismatch = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我放火烧掉大厅。", "submission_action_id": "client-action-3"},
    )
    matched = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我观察大厅。", "submission_action_id": "client-action-3"},
    )

    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "submission_text_mismatch"
    assert matched.status_code == 200
    row = test_db.execute(
        "SELECT status FROM player_action_submissions WHERE action_id = %s",
        ("client-action-3",),
    ).fetchone()
    assert row["status"] == "awaiting_confirmation"


def test_non_stateful_submission_cannot_enter_action_analysis(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    client.post(
        "/api/player/action-submissions",
        headers=headers,
        json={"actionId": "client-speech-2", "rawText": "我提醒大家安静。", "inputMode": "speech"},
    )

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我提醒大家安静。", "submission_action_id": "client-speech-2"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "submission_not_stateful"


@pytest.mark.parametrize(
    ("declared_intent", "expected_intent_type"),
    [
        ("我前往港口邮驿站", "move"),
        ("我用手枪射击门后的怪物", "combat_action"),
        ("我检定侦查技能", "skill_check"),
        ("我使用急救包", "use_item"),
    ],
)
def test_natural_language_action_overrides_dialogue_ui_default(
    declared_intent,
    expected_intent_type,
):
    draft = analyze_action_draft(ActionDraftAnalyzeRequest(
        declared_intent=declared_intent,
        intent_type="dialogue",
    ))

    assert draft.intent_type == expected_intent_type


def test_analyze_stateful_action_requires_confirmation_and_persists(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={"declared_intent": "我用手枪射击门后的怪物"},
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["draft_id"]
    assert draft["status"] == "awaiting_confirmation"
    assert draft["intent_type"] == "combat_action"
    assert draft["risk"] == "high"
    assert draft["requires_confirmation"] is True
    assert "attack" in draft["confirmation_requirements"]
    assert draft["analysis_source"] == "local_fallback"

    row = test_db.execute(
        "SELECT room_id, character_id, status, risk_level, current_revision "
        "FROM action_drafts WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert dict(row) == {
        "room_id": room_id,
        "character_id": character_id,
        "status": "awaiting_confirmation",
        "risk_level": "high",
        "current_revision": 1,
    }
    revision = test_db.execute(
        "SELECT revision_number, declared_intent FROM action_draft_revisions WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert dict(revision) == {
        "revision_number": 1,
        "declared_intent": "我用手枪射击门后的怪物",
    }


def test_action_draft_exposes_a_complete_intent_contract(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={"declared_intent": "如果门后的怪物靠近，我就用手枪射击它。"},
    )

    assert response.status_code == 200
    contract = response.json()["intent_contract"]
    assert set(contract) == {
        "target",
        "method",
        "object",
        "constraints",
        "resources",
        "conditions",
        "visibility",
        "ambiguities",
    }
    assert contract["method"] == "射击"
    assert contract["visibility"] == "public"
    assert contract["conditions"] == ["如果门后的怪物靠近"]


def test_high_risk_ambiguous_target_requires_clarification_before_confirmation(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={"declared_intent": "我开枪打它。"},
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["risk"] == "high"
    assert draft["status"] == "analyzing"
    assert draft["requires_confirmation"] is False
    assert draft["adjudication_stage"] == "player_clarification_required"
    assert draft["intent_contract"]["ambiguities"] == ["目标指代不明确"]


def test_player_can_restore_current_awaiting_confirmation_draft(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    created = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我检查车尾的行李架"},
    ).json()

    response = client.get("/api/player/action-drafts/current", headers=headers)

    assert response.status_code == 200
    assert response.json()["draft_id"] == created["draft_id"]
    assert response.json()["status"] == "awaiting_confirmation"
    assert response.json()["declared_intent"] == "我检查车尾的行李架"


def test_player_does_not_restore_a_stale_confirmation_draft(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我检查车尾的行李架"},
    )
    test_db.execute(
        "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s",
        (room_id,),
    )

    response = client.get("/api/player/action-drafts/current", headers=headers)

    assert response.status_code == 200
    assert response.json() is None


def test_ephemeral_idle_analysis_never_persists_text(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={
            "declared_intent": "我看看桌上的旧报纸",
            "ephemeral": True,
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["draft_id"] is None
    assert draft["ephemeral"] is True
    assert draft["risk"] == "low"
    assert draft["requires_confirmation"] is False
    assert draft["confirmation_requirements"] == []
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_draft_revisions").fetchone()["count"] == 0


def test_persisted_draft_and_first_revision_are_atomic(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    test_db.executescript(
        """
        CREATE OR REPLACE FUNCTION reject_action_draft_revision() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'revision rejected for atomicity test';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER reject_action_draft_revision_trigger
        BEFORE INSERT ON action_draft_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_action_draft_revision();
        """
    )

    try:
        with pytest.raises(Exception, match="revision rejected for atomicity test"):
            client.post(
                "/api/player/action-drafts/analyze",
                headers={"X-Room-Token": player_token},
                json={"declared_intent": "我看看桌上的旧报纸"},
            )
    finally:
        test_db.executescript(
            "DROP TRIGGER IF EXISTS reject_action_draft_revision_trigger ON action_draft_revisions; "
            "DROP FUNCTION IF EXISTS reject_action_draft_revision();"
        )

    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0


def test_action_analysis_requires_player_token(client):
    response = client.post(
        "/api/player/action-drafts/analyze",
        json={"declared_intent": "我向前走"},
    )

    assert response.status_code == 401


def test_completed_room_rejects_action_confirmation(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我继续调查"},
    ).json()
    test_db.execute("UPDATE rooms SET status = 'completed' WHERE room_id = %s", (room_id,))
    test_db.commit()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "after-ending"},
        json={"confirmations": draft["confirmation_requirements"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "room_not_active"


def test_patch_draft_reanalyzes_and_keeps_revision_history(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    created = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()

    response = client.patch(
        f"/api/player/action-drafts/{created['draft_id']}",
        headers=headers,
        json={"declared_intent": "我用手枪射击门后的怪物"},
    )

    assert response.status_code == 200
    revised = response.json()
    assert revised["revision"] == 2
    assert revised["risk"] == "high"
    rows = test_db.execute(
        "SELECT revision_number, declared_intent FROM action_draft_revisions "
        "WHERE draft_id = %s ORDER BY revision_number",
        (created["draft_id"],),
    ).fetchall()
    assert [row["revision_number"] for row in rows] == [1, 2]
    assert rows[0]["declared_intent"] == "我看看桌上的旧报纸"
    assert rows[1]["declared_intent"] == "我用手枪射击门后的怪物"


def test_confirm_draft_is_idempotent_and_records_timeline(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我用手枪射击门后的怪物"},
    ).json()
    confirm_headers = {**headers, "Idempotency-Key": "confirm-shot-1"}
    body = {"confirmations": ["attack", "state_change"]}

    first = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers=confirm_headers,
        json=body,
    )
    second = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers=confirm_headers,
        json=body,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["action_id"] == second.json()["action_id"]
    assert first.json()["status"] == "queued"
    assert first.json()["can_cancel"] is True
    assert first.json()["timeline"][0]["status"] == "queued"
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 1


def test_confirm_draft_is_idempotent_under_concurrent_requests(client, test_db, monkeypatch):
    _, character_id, player_token = _setup_player(client, test_db)
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    character = dict(
        test_db.execute(
            "SELECT * FROM characters WHERE character_id = %s",
            (character_id,),
        ).fetchone()
    )
    initial_reads = Barrier(2)
    original_execute = PgConnection.execute

    def synchronized_execute(conn, sql, params=None):
        result = original_execute(conn, sql, params)
        if (
            "SELECT action_id, draft_id FROM actions WHERE character_id" in sql
            and not getattr(conn, "_idempotency_read_synchronized", False)
        ):
            conn._idempotency_read_synchronized = True
            initial_reads.wait(timeout=5)
        return result

    monkeypatch.setattr(PgConnection, "execute", synchronized_execute)

    def confirm_once():
        conn = PgConnection(test_db._pool)
        try:
            return confirm_action_draft(
                conn,
                character,
                draft["draft_id"],
                "concurrent-confirm",
                [],
            )
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(lambda _: confirm_once(), range(2)))

    assert receipts[0].action_id == receipts[1].action_id
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 1


def test_confirm_rejects_missing_required_confirmation(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我用手枪射击门后的怪物"},
    ).json()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "missing-confirmation"},
        json={"confirmations": ["attack"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "confirmation_required"
    assert response.json()["detail"]["missing"] == ["state_change"]


def test_luck_spend_and_pushed_roll_require_explicit_second_confirmation(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}

    luck = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我想花幸运把失败改成成功"},
    ).json()
    pushed = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我选择孤注一掷重新检定"},
    ).json()

    assert luck["risk"] == "high"
    assert "luck_spend" in luck["confirmation_requirements"]
    assert luck["resource_impacts"] == [
        {"kind": "luck", "direction": "decrease", "amount": "pending_roll"}
    ]
    assert pushed["risk"] == "high"
    assert pushed["confirmation_requirements"] == [
        "pushed_roll",
        "irreversible_consequence",
    ]


def test_ambiguous_local_fallback_routes_to_host_exception_without_state_change(
    client,
    test_db,
):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    before_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"]
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我尝试用一种无法确定规则的方式改变现实"},
    ).json()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "ambiguous-action"},
        json={"confirmations": ["stateful_action"]},
    )

    assert draft["resolution_route"] == "host_exception"
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["status"] == "awaiting_host_exception"
    assert [event["status"] for event in receipt["timeline"]] == [
        "queued",
        "resolving",
        "awaiting_host_exception",
    ]
    recovery_event = test_db.execute(
        "SELECT audience, payload FROM events WHERE room_id = %s AND event_type = %s "
        "ORDER BY sequence DESC LIMIT 1",
        (room_id, "s2c_ai_recovery_required"),
    ).fetchone()
    assert recovery_event["audience"] in {"player", "party"}
    assert recovery_event["payload"]["actionId"] == receipt["action_id"]
    stage_rows = test_db.execute(
        "SELECT status, metadata FROM action_status_events WHERE action_id = %s "
        "ORDER BY status_event_id ASC",
        (receipt["action_id"],),
    ).fetchall()
    assert any(row["metadata"].get("ai_stage") == "recovering" for row in stage_rows)
    after_version = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"]
    assert after_version == before_version


def test_confirming_stale_draft_requires_sync_and_creates_no_action(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    assert draft["base_state_version"] == 0
    test_db.execute(
        "UPDATE rooms SET state_version = 1 WHERE room_id = %s",
        (room_id,),
    )

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "stale-draft"},
        json={"confirmations": []},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "sync_required",
        "base_state_version": 0,
        "current_state_version": 1,
    }
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0


def test_analysis_rebases_stale_client_version_to_current_room_state(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    test_db.execute(
        "UPDATE rooms SET state_version = 4 WHERE room_id = %s",
        (room_id,),
    )

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={
            "declared_intent": "我继续观察周围环境",
            "base_state_version": 3,
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["base_state_version"] == 4
    row = test_db.execute(
        "SELECT base_state_version FROM action_drafts WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert row["base_state_version"] == 4


def test_host_exception_queue_is_owner_only_and_can_request_player_choice(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    room = test_db.execute(
        "SELECT owner_token FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我用无法确定规则的方式改变现实"},
    ).json()
    action = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "host-exception"},
        json={"confirmations": ["stateful_action"]},
    ).json()

    denied = client.get(
        f"/api/host/{room_id}/action-exceptions",
        headers={"X-Owner-Token": "wrong"},
    )
    listed = client.get(
        f"/api/host/{room_id}/action-exceptions",
        headers={"X-Owner-Token": room["owner_token"]},
    )
    resolved = client.post(
        f"/api/host/{room_id}/action-exceptions/{action['action_id']}/resolve",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"decision": "request_player_choice", "reason": "请说明具体实现方式"},
    )

    assert denied.status_code == 403
    assert listed.status_code == 200
    assert [item["action_id"] for item in listed.json()["items"]] == [action["action_id"]]
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "awaiting_player_choice"
    receipt = client.get(
        f"/api/player/actions/{action['action_id']}",
        headers=headers,
    ).json()
    assert receipt["timeline"][-1]["status"] == "awaiting_player_choice"


def test_host_can_reject_an_exception_without_applying_state_changes(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    room = test_db.execute(
        "SELECT owner_token, state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我用无法确定规则的方式改变现实"},
    ).json()
    action = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "host-reject-exception"},
        json={"confirmations": ["stateful_action"]},
    ).json()

    resolved = client.post(
        f"/api/host/{room_id}/action-exceptions/{action['action_id']}/resolve",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"decision": "rejected", "reason": "请重新描述可验证的行动。"},
    )

    assert resolved.status_code == 200
    assert resolved.json()["status"] == "rejected"
    receipt = client.get(
        f"/api/player/actions/{action['action_id']}",
        headers=headers,
    ).json()
    assert receipt["status"] == "rejected"
    current_room = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert current_room["state_version"] == room["state_version"]


def test_configured_ai_analysis_is_structured_and_cannot_change_player_text(
    client,
    test_db,
):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            assert context["declared_intent"] == "我悄悄前往图书馆"
            return {
                "understanding_summary": "玩家想秘密移动到图书馆",
                "risk": "high",
                "intent_type": "move",
                "suggested_skill": "潜行",
                "difficulty": "hard",
                "resource_impacts": [],
                "visibility": "private",
                "movement_target": "图书馆",
                "confirmation_requirements": [
                    "movement",
                    "secret_action",
                    "state_change",
                ],
                "confidence": 0.94,
                "citations": [{"source_ref": "scenario#library"}],
                "declared_intent": "AI 不得覆盖原文",
                "mutations": [{"op": "replace", "path": "/character/luck", "value": 0}],
            }

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我悄悄前往图书馆"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["analysis_source"] == "configured_provider"
    assert draft["resolution_route"] == "ai"
    assert draft["declared_intent"] == "我悄悄前往图书馆"
    assert draft["movement_target"] == "图书馆"
    assert draft["citations"] == [
        {"label": "已校验依据", "page": None, "scene": None, "verified": True}
    ]
    assert "scenario#library" not in response.text
    assert "mutations" not in draft


def test_player_must_choose_an_ai_suggested_alternative_skill_before_confirming(
    client,
    test_db,
):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            return {
                "understanding_summary": "你想从档案中找出与案件有关的记录。",
                "risk": "medium",
                "intent_type": "skill_check",
                "suggested_skill": "侦查",
                "alternative_skills": ["图书馆使用"],
                "difficulty": "regular",
                "resource_impacts": [],
                "visibility": "public",
                "confirmation_requirements": ["stateful_action"],
                "confidence": 0.93,
                "citations": [],
            }

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        draft = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我去翻查档案"},
        ).json()
    finally:
        client.app.state.gateway = previous_gateway

    assert draft["alternative_skills"] == ["图书馆使用"]
    missing = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={"X-Room-Token": player_token, "Idempotency-Key": "alternative-missing"},
        json={"confirmations": draft["confirmation_requirements"]},
    )
    invalid = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={"X-Room-Token": player_token, "Idempotency-Key": "alternative-invalid"},
        json={
            "confirmations": draft["confirmation_requirements"],
            "selected_skill": "话术",
        },
    )
    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={"X-Room-Token": player_token, "Idempotency-Key": "alternative-confirmed"},
        json={
            "confirmations": draft["confirmation_requirements"],
            "selected_skill": "图书馆使用",
        },
    )

    assert missing.status_code == 409
    assert missing.json()["detail"]["code"] == "skill_selection_required"
    assert invalid.status_code == 409
    assert invalid.json()["detail"]["code"] == "skill_selection_invalid"
    assert confirmed.status_code == 200
    action = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (confirmed.json()["action_id"],),
    ).fetchone()
    assert action["params"]["skillName"] == "图书馆使用"


def test_ai_composite_action_keeps_two_steps_and_persists_player_selected_order(
    client,
    test_db,
):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            return {
                "understanding_summary": "你会先开枪压制人影，再掩护安娜撤向铁门。",
                "risk": "high",
                "intent_type": "combat_action",
                "suggested_skill": "射击",
                "difficulty": "regular",
                "resource_impacts": [{"kind": "ammo", "direction": "decrease", "amount": 1}],
                "visibility": "public",
                "confirmation_requirements": ["attack", "state_change"],
                "confidence": 0.93,
                "citations": [],
                "action_steps": [
                    {
                        "step_id": "step_1",
                        "summary": "朝走廊中的人影开枪",
                        "declared_intent": "朝走廊中的人影开枪",
                        "intent_type": "combat_action",
                        "params": {"actionKind": "attack"},
                    },
                    {
                        "step_id": "step_2",
                        "summary": "掩护安娜退向北侧铁门",
                        "declared_intent": "掩护安娜退向北侧铁门",
                        "intent_type": "move",
                        "params": {"targetNodeId": "north-door"},
                        "on_previous_failure": "ask",
                    },
                    {
                        "step_id": "ignored",
                        "summary": "不应成为第三次行动",
                        "declared_intent": "再检查门锁",
                        "intent_type": "skill_check",
                    },
                ],
            }

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        draft_response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我先朝人影开枪，再掩护安娜撤向北侧铁门"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert draft_response.status_code == 200
    draft = draft_response.json()
    assert [step["step_id"] for step in draft["composite_steps"]] == ["step_1", "step_2"]
    assert draft["composite_steps"][1]["on_previous_failure"] == "cancel"
    assert draft["requires_confirmation"] is True

    invalid = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={"X-Room-Token": player_token, "Idempotency-Key": "composite-invalid-order"},
        json={
            "confirmations": draft["confirmation_requirements"],
            "composite_step_order": ["step_2"],
        },
    )
    assert invalid.status_code == 409
    assert invalid.json()["detail"]["code"] == "composite_order_invalid"

    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={"X-Room-Token": player_token, "Idempotency-Key": "composite-reversed-order"},
        json={
            "confirmations": draft["confirmation_requirements"],
            "composite_step_order": ["step_2", "step_1"],
        },
    )
    assert confirmed.status_code == 200
    action = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (confirmed.json()["action_id"],),
    ).fetchone()
    assert [step["step_id"] for step in action["params"]["composite_steps"]] == [
        "step_2",
        "step_1",
    ]


def test_ai_analysis_failure_keeps_local_host_exception_fallback(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            raise RuntimeError("provider unavailable")

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我用无法确定规则的方式改变现实"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    assert response.json()["analysis_source"] == "local_fallback"
    assert response.json()["resolution_route"] == "host_exception"


def test_ai_analysis_cannot_lower_local_risk_or_remove_confirmations(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            return {
                "understanding_summary": "普通交流",
                "risk": "low",
                "intent_type": "dialogue",
                "confirmation_requirements": [],
                "confidence": 0.99,
            }

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我用手枪射击门后的怪物"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["risk"] == "high"
    assert draft["intent_type"] == "combat_action"
    assert set(draft["confirmation_requirements"]) >= {"attack", "state_change"}
    assert draft["requires_confirmation"] is True


def test_low_confidence_ai_analysis_routes_to_host_exception(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            return {
                "understanding_summary": "无法可靠理解该行动",
                "risk": "medium",
                "intent_type": "dialogue",
                "confirmation_requirements": ["stateful_action"],
                "confidence": 0.3,
            }

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我尝试用一种无法确定规则的方式改变现实"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    assert response.json()["resolution_route"] == "host_exception"


def test_v2_legacy_retroactive_claim_cannot_bypass_draft_chain(
    client,
    test_db,
    monkeypatch,
):
    _, _, player_token = _setup_player(client, test_db)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")

    response = client.post(
        "/api/player/intent",
        headers={"X-Room-Token": player_token},
        json={
            "action_id": "legacy-retro",
            "intent_type": "retroactive_item_claim",
            "declared_intent": "我刚才其实带了撬棍",
            "params": {},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "v2_action_draft_required"


def test_v2_legacy_skill_check_cannot_bypass_draft_chain(
    client,
    test_db,
    monkeypatch,
):
    _, _, player_token = _setup_player(client, test_db)
    monkeypatch.setenv("AIKEEPER_DEV_MODE", "0")

    response = client.post(
        "/api/player/skill-check",
        headers={"X-Room-Token": player_token},
        json={
            "skill_name": "侦查",
            "skill_value": 60,
            "difficulty": "regular",
            "bonus_dice": 0,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "v2_action_draft_required"


def test_confirmed_local_action_is_scheduled_for_background_resolution(
    client,
    test_db,
    monkeypatch,
):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    scheduled = []
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_action_resolution",
        lambda app, conn, action_id: scheduled.append(action_id),
        raising=False,
    )

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "schedule-local"},
        json={"confirmations": []},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert scheduled == [response.json()["action_id"]]


def test_active_scene_confirmation_does_not_wait_for_every_player(
    client,
    test_db,
    monkeypatch,
):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('active-scene-turn', %s, 1, 'collecting', 'scene')",
        (room_id,),
    )
    test_db.commit()
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我检查桌上的旧报纸"},
    ).json()
    scheduled = []
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_action_resolution",
        lambda app, conn, action_id: scheduled.append(action_id),
        raising=False,
    )

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "active-scene-direct"},
        json={"confirmations": []},
    )

    assert response.status_code == 200
    action_id = response.json()["action_id"]
    action = test_db.execute(
        "SELECT turn_id FROM actions WHERE action_id = %s", (action_id,)
    ).fetchone()
    assert action["turn_id"] is None
    assert scheduled == [action_id]


def test_stale_combat_turn_does_not_block_a_new_scene_action(
    client,
    test_db,
    monkeypatch,
):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('finished-combat-encounter', %s, 'combat', 'resolved', 1)",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id) "
        "VALUES ('stale-combat-turn', %s, 1, 'resolving', 'combat', 'finished-combat-encounter')",
        (room_id,),
    )
    test_db.commit()
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我检查桌上的旧报纸"},
    ).json()
    scheduled = []
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_action_resolution",
        lambda app, conn, action_id: scheduled.append(action_id),
        raising=False,
    )

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "stale-combat-scene-action"},
        json={"confirmations": []},
    )

    assert response.status_code == 200
    action_id = response.json()["action_id"]
    action = test_db.execute(
        "SELECT turn_id FROM actions WHERE action_id = %s", (action_id,)
    ).fetchone()
    assert action["turn_id"] is None
    assert scheduled == [action_id]


def test_active_combat_confirmation_creates_a_combat_turn_after_scene_turn(
    client,
    test_db,
    monkeypatch,
):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('previous-scene-turn', %s, 1, 'collecting', 'scene')",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('active-combat-encounter', %s, 'combat', 'active', 1)",
        (room_id,),
    )
    test_db.commit()
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我检查桌上的旧报纸"},
    ).json()
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_action_resolution",
        lambda *_: None,
        raising=False,
    )

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "active-combat-turn"},
        json={"confirmations": []},
    )

    assert response.status_code == 200
    action = test_db.execute(
        "SELECT turn_id FROM actions WHERE action_id = %s", (response.json()["action_id"],)
    ).fetchone()
    assert action["turn_id"] != "previous-scene-turn"
    turn = test_db.execute(
        "SELECT mode, encounter_id FROM room_turns WHERE turn_id = %s", (action["turn_id"],)
    ).fetchone()
    assert turn == {"mode": "combat", "encounter_id": "active-combat-encounter"}


def test_tactical_draft_preserves_server_validated_intent_params(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "declared_intent": "我攻击敌人",
            "intent_type": "combat_action",
            "params": {"actionKind": "attack", "skillName": "斗殴", "clientRoll": 1},
        },
    ).json()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "tactical-params"},
        json={"confirmations": ["attack", "state_change"]},
    )

    assert response.status_code == 200
    action = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s",
        (response.json()["action_id"],),
    ).fetchone()
    assert action["params"]["actionKind"] == "attack"
    assert action["params"]["skillName"] == "斗殴"
    assert "clientRoll" not in action["params"]


def test_retroactive_item_claim_uses_v2_preview_and_preserves_claim_fields(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player_token},
        json={
            "declared_intent": "我主张角色背景中应有撬棍",
            "intent_type": "retroactive_item_claim",
            "params": {
                "claimedItemName": "撬棍",
                "justificationText": "角色曾长期从事锁匠工作",
                "clientRoll": 1,
            },
        },
    )

    assert response.status_code == 200
    draft = response.json()
    assert draft["intent_type"] == "retroactive_item_claim"
    assert draft["params"] == {
        "claimedItemName": "撬棍",
        "justificationText": "角色曾长期从事锁匠工作",
    }
    assert draft["resolution_route"] == "host_exception"


def test_one_effective_action_per_player_per_turn(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.commit()
    headers = {"X-Room-Token": player_token}

    first_draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    first = client.post(
        f"/api/player/action-drafts/{first_draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "turn-action-1"},
        json={"confirmations": []},
    )
    second_draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我询问门卫昨晚发生了什么"},
    ).json()
    second = client.post(
        f"/api/player/action-drafts/{second_draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "turn-action-2"},
        json={"confirmations": []},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "action_already_submitted"


def test_cancel_action_is_atomic_before_resolving(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    receipt = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "cancel-me"},
        json={"confirmations": []},
    ).json()

    response = client.post(
        f"/api/player/actions/{receipt['action_id']}/cancel",
        headers=headers,
    )

    assert response.status_code == 200
    canceled = response.json()
    assert canceled["status"] == "canceled"
    assert canceled["can_cancel"] is False
    assert [event["status"] for event in canceled["timeline"]] == ["queued", "canceled"]

    second = client.post(
        f"/api/player/actions/{receipt['action_id']}/cancel",
        headers=headers,
    )
    assert second.status_code == 409


def test_cancel_action_is_rejected_when_its_combat_round_is_locked(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('combat-lock-cancel-turn', %s, 1, 'collecting', 'combat')",
        (room_id,),
    )
    test_db.commit()
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    receipt = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "combat-lock-cancel"},
        json={"confirmations": []},
    ).json()
    assert receipt.get('action_id'), receipt
    test_db.execute(
        "UPDATE room_turns SET mode = 'combat', status = 'resolving' WHERE turn_id = "
        "(SELECT turn_id FROM actions WHERE action_id = %s)",
        (receipt['action_id'],),
    )
    test_db.commit()

    locked_receipt = client.get(
        f"/api/player/actions/{receipt['action_id']}",
        headers=headers,
    )
    assert locked_receipt.status_code == 200
    assert locked_receipt.json()['can_cancel'] is False

    response = client.post(
        f"/api/player/actions/{receipt['action_id']}/cancel",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'action_round_locked'
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (receipt['action_id'],),
    ).fetchone()
    assert action['status'] == 'queued'


def test_confirm_draft_is_rejected_when_a_combat_round_is_already_locked(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.commit()
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('combat-lock-confirm-turn', %s, 1, 'resolving', 'combat')",
        (room_id,),
    )
    test_db.commit()

    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "combat-lock-confirm"},
        json={"confirmations": draft.get("confirmation_requirements", [])},
    )

    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'action_round_locked'
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()['count'] == 0


def test_player_can_cancel_retryable_semantic_progression_recovery(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, intent_type, declared_intent, params, status
        ) VALUES (%s, %s, %s, 'skill_check', '我尝试挣脱锁链', %s, 'awaiting_host_exception')
        """,
        (
            "retryable-recovery-action",
            room_id,
            character_id,
            '{"analysis":{"semantic_progression":{"reason":"semantic_progression_evidence_required"}}}',
        ),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('retryable-recovery-action', 'awaiting_host_exception', '{}')"
    )

    response = client.post(
        "/api/player/actions/retryable-recovery-action/cancel",
        headers={"X-Room-Token": player_token},
    )

    assert response.status_code == 200
    receipt = response.json()
    assert receipt["status"] == "canceled"
    assert receipt["can_cancel"] is False
    assert [event["status"] for event in receipt["timeline"]] == [
        "awaiting_host_exception",
        "canceled",
    ]


def test_delete_draft_preserves_a_canceled_audit_record(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={"declared_intent": "我看看桌上的旧报纸"},
    ).json()

    response = client.delete(
        f"/api/player/action-drafts/{draft['draft_id']}",
        headers=headers,
    )

    assert response.status_code == 204
    row = test_db.execute(
        "SELECT status FROM action_drafts WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert row["status"] == "canceled"
