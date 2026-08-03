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
    _insert_event(test_db, room_id, 4, "s2c_private_notice", "player", {"text": "snake clue", "character_id": char_id})
    _insert_event(test_db, room_id, 5, "s2c_private_notice", "player", {"text": "unowned legacy clue"})

    resp = client.get("/api/player/archive/clues", headers={"X-Room-Token": token})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["clues"]) == 3
    assert data["clues"][0]["data"]["text"] == "public clue"
    assert data["clues"][1]["data"]["text"] == "private clue"
    assert data["clues"][2]["data"]["text"] == "snake clue"


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


def test_campaign_archive_highlights_exclude_host_and_player_only_events(
    client,
    test_db,
):
    room_id, owner_token, character_id, _ = _setup_player(client, test_db)
    _insert_event(
        test_db,
        room_id,
        1,
        "s2c_reveal_transaction",
        "host",
        {"text": "host-only-ending-secret"},
    )
    _insert_event(
        test_db,
        room_id,
        2,
        "s2c_scene_sync",
        "player",
        {"text": "player-only-ending-secret", "characterId": character_id},
    )
    _insert_event(
        test_db,
        room_id,
        3,
        "s2c_scene_sync",
        "party",
        {"text": "public-ending-highlight"},
    )
    test_db.execute(
        "SELECT setval(pg_get_serial_sequence('events', 'sequence'), "
        "(SELECT MAX(sequence) FROM events))"
    )
    test_db.commit()

    response = client.post(
        f"/api/rooms/{room_id}/end",
        headers={"X-Owner-Token": owner_token},
        json={"ending_type": "mixed"},
    )

    assert response.status_code == 200, response.text
    archive = test_db.execute(
        "SELECT highlights FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    rendered = json.dumps(archive["highlights"], ensure_ascii=False)
    assert "public-ending-highlight" in rendered
    assert "host-only-ending-secret" not in rendered
    assert "player-only-ending-secret" not in rendered


def test_player_campaign_summary_key_events_respect_event_audience(client, test_db):
    from src.server.campaign_archive import CampaignArchive

    room_id, _, character_id, _ = _setup_player(client, test_db)
    other = client.post(f"/api/player/rooms/{room_id}/join").json()
    _insert_event(
        test_db,
        room_id,
        901,
        "s2c_reveal_transaction",
        "host",
        {"text": "hidden reveal timing"},
    )
    _insert_event(
        test_db,
        room_id,
        902,
        "s2c_scene_sync",
        "party",
        {"summary": "public scene"},
    )
    _insert_event(
        test_db,
        room_id,
        903,
        "s2c_scene_sync",
        "player",
        {"characterId": character_id, "summary": "own private scene"},
    )
    _insert_event(
        test_db,
        room_id,
        904,
        "s2c_scene_sync",
        "player",
        {"characterId": other["character_id"], "summary": "other private scene"},
    )
    test_db.commit()

    summary = CampaignArchive(test_db).get_campaign_summary(
        room_id,
        character_id=character_id,
    )

    assert [event["sequence"] for event in summary.key_events] == [902, 903]


def test_account_delete_cannot_race_stale_identity_back_into_campaign_archive(
    client,
    test_db,
    monkeypatch,
):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from src.server.campaign_archive import CampaignArchive
    from src.server.db_adapter import PgConnection
    import src.server.router_admin as admin_module
    from tests.server.conftest import create_account

    setup_auth_test_data(test_db)
    account_id = "archive-race-account"
    room_id = "archive-race-room"
    character_id = "archive-race-character"
    create_account(test_db, account_id, "archive-race", "player")
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, owner_account_id, status) "
        "VALUES (%s, 'archive-race-owner', 'acc-host', 'active')",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, account_id, xlsx_data) "
        "VALUES (%s, %s, 'Archive Race Name', 'archive-race-token', %s, %s)",
        (
            character_id,
            room_id,
            account_id,
            json.dumps({"name": "Archive Investigator Name"}),
        ),
    )
    test_db.commit()

    arcs_built = threading.Event()
    deletion_reached_archive_redaction = threading.Event()
    release_ending = threading.Event()
    original_build = CampaignArchive._build_character_arcs

    def pause_after_arc_snapshot(self, target_room_id, characters, **kwargs):
        arcs = original_build(self, target_room_id, characters, **kwargs)
        arcs_built.set()
        assert release_ending.wait(timeout=5)
        return arcs

    monkeypatch.setattr(CampaignArchive, "_build_character_arcs", pause_after_arc_snapshot)
    original_pseudonymize = admin_module._pseudonymize_account_archives

    def observe_archive_redaction(*args, **kwargs):
        result = original_pseudonymize(*args, **kwargs)
        deletion_reached_archive_redaction.set()
        return result

    monkeypatch.setattr(
        admin_module,
        "_pseudonymize_account_archives",
        observe_archive_redaction,
    )
    ending_conn = PgConnection(test_db._pool)
    deletion_conn = PgConnection(test_db._pool)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            ending_future = pool.submit(
                CampaignArchive(ending_conn).generate_ending,
                room_id,
            )
            assert arcs_built.wait(timeout=5)

            def delete_account():
                with deletion_conn.transaction() as tx:
                    return admin_module._delete_account_rows(
                        tx,
                        [account_id],
                        requested_by="acc-admin",
                    )

            deletion_future = pool.submit(delete_account)
            deletion_reached_archive_redaction.wait(timeout=0.25)
            release_ending.set()
            ending_future.result(timeout=10)
            deletion_future.result(timeout=10)
    finally:
        release_ending.set()
        ending_conn.close()
        deletion_conn.close()

    archive = test_db.execute(
        "SELECT summary, highlights, character_arcs FROM campaign_archives "
        "WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    rendered = json.dumps(dict(archive), ensure_ascii=False)
    assert character_id not in rendered
    assert "Archive Race Name" not in rendered
    assert "Archive Investigator Name" not in rendered


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


def _insert_ending_actions(test_db, room_id: str, character_id: str):
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    for action_id, status in (
        ("ending-action", "resolving"),
        ("pending-action", "queued"),
        ("pending-choice", "awaiting_player_choice"),
    ):
        test_db.execute(
            "INSERT INTO actions "
            "(action_id, room_id, character_id, intent_type, declared_intent, status) "
            "VALUES (%s, %s, %s, 'dialogue', %s, %s)",
            (action_id, room_id, character_id, action_id, status),
        )
    test_db.commit()


def _ending_action_completion():
    return {
        "action_id": "ending-action",
        "from_statuses": ("resolving",),
        "to_status": "completed",
        "result": {"ending": "victory"},
        "receipt": {"verified": True},
        "metadata": {"completion_source": "verified_runtime_ending"},
    }


def test_campaign_finalization_atomically_completes_room_archives_and_cancels_pending_actions(
    client,
    test_db,
):
    from src.server.ai.decision_audit import DecisionAuditRecorder
    from src.server.campaign_archive import finalize_campaign

    room_id, _, character_id, _ = _setup_player(client, test_db)
    _insert_ending_actions(test_db, room_id, character_id)
    draft_id = "pending-ending-draft"
    test_db.execute(
        "INSERT INTO action_drafts "
        "(draft_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES (%s, %s, %s, 'dialogue', 'unfinished choice', "
        "'awaiting_confirmation')",
        (draft_id, room_id, character_id),
    )
    recorder = DecisionAuditRecorder(test_db)
    audit_ids = [
        recorder.record(
            room_id=room_id,
            action_id=action_id,
            task_type="analyze_director_action",
            provider="terminal-audit-test",
            model="deterministic",
        )
        for action_id in ("pending-action", "pending-choice")
    ]
    draft_audit_id = recorder.record(
        room_id=room_id,
        action_id=draft_id,
        draft_id=draft_id,
        draft_revision=1,
        task_type="analyze_director_action",
        provider="terminal-audit-test",
        model="deterministic",
    )
    test_db.commit()

    outcome = finalize_campaign(
        test_db,
        room_id,
        ending_type="victory",
        summary="Verified ending",
        highlights=["The team escaped."],
        current_action=_ending_action_completion(),
    )

    assert outcome is not None
    assert outcome.canceled_action_ids == ("pending-action", "pending-choice")
    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["status"] == "completed"
    action_rows = test_db.execute(
        "SELECT action_id, status FROM actions WHERE room_id = %s ORDER BY action_id",
        (room_id,),
    ).fetchall()
    assert {row["action_id"]: row["status"] for row in action_rows} == {
        "ending-action": "completed",
        "pending-action": "canceled",
        "pending-choice": "canceled",
    }
    assert test_db.execute(
        "SELECT ending_type FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone()["ending_type"] == "victory"
    audit_rows = test_db.execute(
        "SELECT final_delta FROM ai_call_logs "
        "WHERE decision_audit_id = ANY(%s) ORDER BY decision_audit_id",
        (audit_ids,),
    ).fetchall()
    assert len(audit_rows) == 2
    assert all(row["final_delta"]["action_status"] == "canceled" for row in audit_rows)
    assert all(row["final_delta"]["reason_code"] == "campaign_ended" for row in audit_rows)
    assert all(isinstance(row["final_delta"]["state_version"], int) for row in audit_rows)
    assert test_db.execute(
        "SELECT status FROM action_drafts WHERE draft_id = %s",
        (draft_id,),
    ).fetchone()["status"] == "canceled"
    draft_audit = test_db.execute(
        "SELECT action_id, audit_state, final_delta FROM ai_call_logs "
        "WHERE decision_audit_id = %s",
        (draft_audit_id,),
    ).fetchone()
    assert draft_audit["action_id"] is None
    assert draft_audit["audit_state"] == "canceled"
    assert draft_audit["final_delta"] == {
        "draft_status": "canceled",
        "reason_code": "campaign_ended",
        "draft_revision": 1,
    }


def test_campaign_finalization_rolls_back_everything_when_archive_insert_fails(
    client,
    test_db,
    monkeypatch,
):
    import src.server.campaign_archive as archive_module

    room_id, _, character_id, _ = _setup_player(client, test_db)
    _insert_ending_actions(test_db, room_id, character_id)

    def fail_archive(*_args, **_kwargs):
        raise RuntimeError("injected-archive-failure")

    monkeypatch.setattr(archive_module, "_insert_minimal_archive", fail_archive)

    with pytest.raises(RuntimeError, match="injected-archive-failure"):
        archive_module.finalize_campaign(
            test_db,
            room_id,
            ending_type="victory",
            summary="Verified ending",
            highlights=["The team escaped."],
            current_action=_ending_action_completion(),
        )

    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["status"] == "active"
    action_rows = test_db.execute(
        "SELECT action_id, status FROM actions WHERE room_id = %s ORDER BY action_id",
        (room_id,),
    ).fetchall()
    assert {row["action_id"]: row["status"] for row in action_rows} == {
        "ending-action": "resolving",
        "pending-action": "queued",
        "pending-choice": "awaiting_player_choice",
    }
    assert test_db.execute(
        "SELECT 1 FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone() is None


def test_campaign_finalization_cancels_prepared_rule_state(client, test_db):
    from src.server.campaign_archive import finalize_campaign

    room_id, _, character_id, _ = _setup_player(client, test_db)
    _insert_ending_actions(test_db, room_id, character_id)
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('prepared-before-ending', %s, %s, 'prepared_action', 'take cover', 'armed')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO prepared_rule_actions "
        "(action_id, room_id, character_id, trigger_kind, reaction_kind, status) "
        "VALUES ('prepared-before-ending', %s, %s, "
        "'enemy_public_attack_declared', 'take_cover', 'armed')",
        (room_id, character_id),
    )
    test_db.commit()

    finalize_campaign(
        test_db,
        room_id,
        ending_type="victory",
        summary="Verified ending",
        highlights=[],
        current_action=_ending_action_completion(),
    )

    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'prepared-before-ending'"
    ).fetchone()["status"] == "canceled"
    assert test_db.execute(
        "SELECT status FROM prepared_rule_actions "
        "WHERE action_id = 'prepared-before-ending'"
    ).fetchone()["status"] == "canceled"


def test_completed_campaign_database_boundary_rejects_new_ending_fact_event(
    client,
    test_db,
):
    import psycopg2

    room_id, _, _, _ = _setup_player(client, test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'completed' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    with pytest.raises(psycopg2.Error, match="campaign_completed_read_only"):
        test_db.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) "
            "VALUES (%s, 's2c_encounter_resolved', 'party', '{}')",
            (room_id,),
        )

    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == 0


def test_completed_campaign_database_boundary_rejects_encounter_mutation(
    client,
    test_db,
):
    import psycopg2

    room_id, _, _, _ = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status) "
        "VALUES ('encounter-before-ending', %s, 'combat', 'active')",
        (room_id,),
    )
    test_db.execute(
        "UPDATE rooms SET status = 'completed' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    with pytest.raises(psycopg2.Error, match="campaign_completed_read_only"):
        test_db.execute(
            "UPDATE encounters SET status = 'resolved' "
            "WHERE encounter_id = 'encounter-before-ending'"
        )

    assert test_db.execute(
        "SELECT status FROM encounters "
        "WHERE encounter_id = 'encounter-before-ending'"
    ).fetchone()["status"] == "active"


def test_manual_campaign_end_rolls_back_event_when_archive_insert_fails(
    client,
    test_db,
    monkeypatch,
):
    import src.server.campaign_archive as archive_module

    room_id, owner_token, _, _ = _setup_player(client, test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    def fail_archive(*_args, **_kwargs):
        raise RuntimeError("injected-manual-archive-failure")

    monkeypatch.setattr(archive_module, "_insert_minimal_archive", fail_archive)

    with pytest.raises(RuntimeError, match="injected-manual-archive-failure"):
        client.post(
            f"/api/rooms/{room_id}/end",
            headers={"X-Owner-Token": owner_token},
            json={"ending_type": "mixed", "text": "manual ending"},
        )

    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["status"] == "active"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events "
        "WHERE room_id = %s AND event_type = 's2c_campaign_ended'",
        (room_id,),
    ).fetchone()["count"] == 0
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == 0


def test_completed_campaign_rejects_epilogue_state_writes(client, test_db):
    from src.server.campaign_archive import CampaignReadOnlyError
    from src.server.campaign_archive import finalize_campaign
    from src.server.engine.state_service import StateService
    from src.server.models import SceneChange, StateChangeSet

    room_id, _, character_id, _ = _setup_player(client, test_db)
    _insert_ending_actions(test_db, room_id, character_id)
    finalize_campaign(
        test_db,
        room_id,
        ending_type="victory",
        summary="Verified ending",
        highlights=[],
        current_action=_ending_action_completion(),
    )

    with pytest.raises(CampaignReadOnlyError, match="campaign_completed_read_only"):
        StateService(test_db).apply_change(
            room_id,
            {"character_id": character_id, "action_id": "epilogue-write"},
            StateChangeSet(
                sceneChanges=SceneChange(variableSet={"epilogue_mutation": True})
            ),
            reason="epilogue must remain read-only",
        )
    scene = test_db.execute(
        "SELECT scene_variables FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert not scene or "epilogue_mutation" not in (scene["scene_variables"] or {})


def test_authoritative_state_change_rolls_back_when_version_bump_fails(
    client,
    test_db,
    monkeypatch,
):
    from src.server.engine.state_service import StateService
    from src.server.models import SceneChange, StateChangeSet

    room_id, _, character_id, _ = _setup_player(client, test_db)
    service = StateService(test_db)

    def fail_version_bump(_service, _room_id):
        raise RuntimeError("injected-version-failure")

    monkeypatch.setattr(StateService, "_bump_room_version", fail_version_bump)

    with pytest.raises(RuntimeError, match="injected-version-failure"):
        service.apply_change(
            room_id,
            {"character_id": character_id, "action_id": "atomic-state-write"},
            StateChangeSet(
                sceneChanges=SceneChange(variableSet={"must_roll_back": True})
            ),
            reason="verify state transaction",
        )

    scene = test_db.execute(
        "SELECT scene_variables FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert not scene or "must_roll_back" not in (scene["scene_variables"] or {})


def test_minimal_archive_rejects_normal_update_and_delete(client, test_db):
    from src.server.campaign_archive import finalize_campaign

    room_id, _, character_id, _ = _setup_player(client, test_db)
    _insert_ending_actions(test_db, room_id, character_id)
    outcome = finalize_campaign(
        test_db,
        room_id,
        ending_type="victory",
        summary="Verified ending",
        highlights=[],
        current_action=_ending_action_completion(),
    )

    with pytest.raises(Exception, match="campaign_archive_immutable"):
        test_db.execute(
            "UPDATE campaign_archives SET summary = 'tampered' WHERE archive_id = %s",
            (outcome.archive_id,),
        )
    with pytest.raises(Exception, match="campaign_archive_immutable"):
        test_db.execute(
            "DELETE FROM campaign_archives WHERE archive_id = %s",
            (outcome.archive_id,),
        )
