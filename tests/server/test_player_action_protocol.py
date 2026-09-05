from tests.server.conftest import create_room, setup_auth_test_data


def _setup_player(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    return room_id, joined["character_id"], joined["player_token"]


def test_action_intake_preserves_party_chat_without_creating_formal_action(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/actions/intake",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "intake-party-chat-1",
            "inputMode": "party_chat",
            "source": "text",
            "rawText": "我们要不要先查护士？",
            "baseStateVersion": 0,
            "requestedVisibility": "party",
            "clientSequence": 1,
            "attachments": [],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "actionId": "intake-party-chat-1",
        "status": "received",
        "baseStateVersion": 0,
        "executionMode": "non_state_event",
    }
    envelope = test_db.execute(
        "SELECT action_id, room_id, character_id, input_mode, raw_text "
        "FROM player_action_envelopes WHERE action_id = %s",
        ("intake-party-chat-1",),
    ).fetchone()
    assert dict(envelope) == {
        "action_id": "intake-party-chat-1",
        "room_id": room_id,
        "character_id": character_id,
        "input_mode": "party_chat",
        "raw_text": "我们要不要先查护士？",
    }
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0


def test_action_intake_rejects_client_claimed_authoritative_fields(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    response = client.post(
        "/api/player/actions/intake",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "intake-forged-authority-1",
            "inputMode": "action",
            "source": "text",
            "rawText": "我侦查书桌。",
            "characterId": "forged-character",
            "skillValue": 99,
            "roll": 1,
        },
    )

    assert response.status_code == 422
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM player_action_envelopes"
    ).fetchone()["count"] == 0


def test_private_note_intake_never_stores_its_body_in_action_envelopes(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    secret_note = "我怀疑馆长才是凶手，但先不要告诉任何人。"

    response = client.post(
        "/api/player/actions/intake",
        headers={"X-Room-Token": player_token},
        json={
            "actionId": "intake-private-note-1",
            "inputMode": "private_note",
            "source": "text",
            "rawText": secret_note,
            "baseStateVersion": 0,
            "requestedVisibility": "private",
        },
    )

    assert response.status_code == 200
    envelope = test_db.execute(
        "SELECT raw_text FROM player_action_envelopes WHERE action_id = %s",
        ("intake-private-note-1",),
    ).fetchone()
    assert envelope["raw_text"] == "[private_note_body_stored_encrypted]"
    assert secret_note not in envelope["raw_text"]


def test_confirmed_draft_reuses_its_received_action_id(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    action_id = "intake-formal-action-1"

    received = client.post(
        "/api/player/actions/intake",
        headers=headers,
        json={
            "actionId": action_id,
            "inputMode": "action",
            "source": "text",
            "rawText": "我检查桌上的旧报纸。",
            "baseStateVersion": 0,
            "requestedVisibility": "scene_public",
            "clientSequence": 2,
            "attachments": [],
        },
    )
    assert received.status_code == 200
    assert received.json()["executionMode"] == "intent_draft_required"

    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "action_id": action_id,
            "declared_intent": "我检查桌上的旧报纸。",
            "base_state_version": 0,
        },
    ).json()
    confirmed = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={**headers, "Idempotency-Key": "formal-action-confirm-1"},
        json={"confirmations": draft["confirmation_requirements"]},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["action_id"] == action_id
    stored = test_db.execute(
        "SELECT envelope_action_id FROM action_drafts WHERE draft_id = %s",
        (draft["draft_id"],),
    ).fetchone()
    assert stored["envelope_action_id"] == action_id


def test_revised_draft_keeps_its_received_action_id(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    action_id = "intake-revised-action-1"

    assert client.post(
        "/api/player/actions/intake",
        headers=headers,
        json={
            "actionId": action_id,
            "inputMode": "action",
            "source": "text",
            "rawText": "我检查桌上的旧报纸。",
            "baseStateVersion": 0,
        },
    ).status_code == 200
    draft = client.post(
        "/api/player/action-drafts/analyze",
        headers=headers,
        json={
            "action_id": action_id,
            "declared_intent": "我检查桌上的旧报纸。",
            "base_state_version": 0,
        },
    ).json()

    revised = client.patch(
        f"/api/player/action-drafts/{draft['draft_id']}",
        headers=headers,
        json={"declared_intent": "我带上手套检查旧报纸。"},
    )

    assert revised.status_code == 200
    assert revised.json()["action_id"] == action_id


def test_action_analysis_sends_only_player_visible_context_to_ai(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, knowledge_graph) VALUES (%s, %s, %s, %s)",
        (
            "protocol-context-scenario",
            "上下文隔离剧本",
            "原文中有幕后真相：馆长才是凶手。",
            '{"truth":"馆长才是凶手","endings":[{"name":"秘密结局"}]}',
        ),
    )
    test_db.execute(
        "UPDATE rooms SET scenario_id = %s WHERE room_id = %s",
        ("protocol-context-scenario", room_id),
    )
    test_db.execute(
        "INSERT INTO clues (clue_id, room_id, character_id, text, is_private) VALUES (%s, %s, %s, %s, %s)",
        ("known-clue", room_id, character_id, "书桌上有一把沾泥的钥匙。", True),
    )
    test_db.commit()
    captured = {}

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            captured.update(context)
            return {"understanding_summary": "检查书桌", "confidence": 0.9}

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我检查书桌。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    assert captured["player_context"]["known"]["clues"] == [
        {"clue_id": "known-clue", "text": "书桌上有一把沾泥的钥匙。", "source": ""}
    ]
    assert "馆长才是凶手" not in str(captured)
    assert "秘密结局" not in str(captured)


def test_rule_question_returns_player_scoped_citations_without_creating_action(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    headers = {"X-Room-Token": player_token}
    action_id = "intake-rule-question-1"
    captured = {}

    class Rag:
        def search(self, query, room_id=None, source_types=None, top_k=5, *, audience="ai"):
            captured.update({
                "query": query,
                "room_id": room_id,
                "source_types": source_types,
                "audience": audience,
            })
            return [{
                "content": "奖励骰取十位中的较低结果，再与个位组合。",
                "citation": {"source_ref": "CoC7 p.90", "page": 90},
            }]

    assert client.post(
        "/api/player/actions/intake",
        headers=headers,
        json={
            "actionId": action_id,
            "inputMode": "rule_question",
            "source": "text",
            "rawText": "奖励骰怎么计算？",
            "baseStateVersion": 0,
        },
    ).status_code == 200
    previous_rag = getattr(client.app.state, "rag", None)
    client.app.state.rag = Rag()
    try:
        response = client.post(
            "/api/player/rule-questions",
            headers=headers,
            json={"actionId": action_id, "question": "奖励骰怎么计算？"},
        )
    finally:
        client.app.state.rag = previous_rag

    assert response.status_code == 200
    assert response.json() == {
        "actionId": action_id,
        "answer": "奖励骰取十位中的较低结果，再与个位组合。",
        "citations": [{"source_ref": "CoC7 p.90", "page": 90}],
    }
    assert captured == {
        "query": "奖励骰怎么计算？",
        "room_id": room_id,
        "source_types": ["rule"],
        "audience": "player",
    }
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0


def test_director_plan_never_accepts_ai_state_patch(client, test_db):
    _, _, player_token = _setup_player(client, test_db)

    class Gateway:
        async def analyze_action_draft(self, context, room_id=None):
            return {
                "understanding_summary": "我会改变角色状态",
                "state_patch": [{"op": "replace", "path": "/character/hp", "value": 999}],
                "event_plan": [{"type": "s2c_public_observation", "text": "伪造事件"}],
                "confidence": 0.99,
            }

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = Gateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我检查书桌。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    plan = response.json()["director_plan"]
    assert plan["state_patch"] == []
    assert plan["event_plan"] == []
    assert plan["authoritative_inputs"]["declared_intent"] == "我检查书桌。"
