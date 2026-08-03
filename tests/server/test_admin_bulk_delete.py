import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import asynccontextmanager

import pytest

from tests.server.conftest import (
    create_account,
    create_room,
    create_scenario,
    login,
    setup_auth_test_data,
)


def _admin_headers(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(client, 'admin')}"}


def _insert_character(test_db, character_id: str, room_id: str, *, account_id: str | None = None):
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, account_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        (character_id, room_id, character_id, f"token-{character_id}", account_id),
    )


def _insert_room(test_db, room_id: str, *, scenario_id: str | None = None, owner_account_id: str | None = None):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, scenario_id, owner_account_id) "
        "VALUES (%s, %s, %s, %s)",
        (room_id, f"owner-{room_id}", scenario_id, owner_account_id),
    )


def _count(test_db, table: str, where_sql: str, params: tuple[str, ...]) -> int:
    return test_db.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE {where_sql}",
        params,
    ).fetchone()["count"]


def test_batch_delete_rooms_removes_real_collaboration_and_session_dependencies(client, test_db):
    setup_auth_test_data(test_db)
    room = create_room(client, login(client))
    room_id = room["room_id"]
    character_id = "bulk-room-character"
    session_id = "bulk-room-session"
    summary_id = "bulk-room-summary"
    contract_id = "bulk-room-contract"
    _insert_character(test_db, character_id, room_id)
    test_db.execute(
        "INSERT INTO player_notes "
        "(note_id, room_id, character_id, title_ciphertext, body_ciphertext) "
        "VALUES ('bulk-room-note', %s, %s, 'title', 'body')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO private_data_access_audits "
        "(private_data_access_audit_id, room_id, note_id, owner_character_id, "
        "host_account_id, reason) VALUES "
        "('bulk-room-access-audit', %s, 'bulk-room-note', %s, 'acc-host', 'incident')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO campaign_sessions (campaign_session_id, room_id, started_by_character_id) "
        "VALUES (%s, %s, %s)",
        (session_id, room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO session_summaries "
        "(session_summary_id, campaign_session_id, room_id, summary_text) VALUES (%s, %s, %s, %s)",
        (summary_id, session_id, room_id, "测试摘要"),
    )
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, expires_at) "
        "VALUES (%s, %s, %s, %s, NOW() + INTERVAL '10 minutes')",
        (contract_id, room_id, character_id, "共同调查"),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_participants (contract_id, character_id, role) "
        "VALUES (%s, %s, 'initiator')",
        (contract_id, character_id),
    )
    test_db.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs) "
        "VALUES ('bulk-room-archive', %s, 'mixed', '公开结局摘要', '[]', '[]')",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO ai_call_logs "
        "(room_id, action_id, task_type, provider, status, response_summary, "
        "error_message, spoiler_hit_items) "
        "VALUES (%s, 'bulk-room-action', 'narrate_action', 'configured:test', 'success', "
        "'可能含私人角色文本', '可能含请求上下文', %s)",
        (
            room_id,
            json.dumps([{"matched_text": "未揭示真相"}], ensure_ascii=False),
        ),
    )
    test_db.execute(
        "INSERT INTO spoiler_audits "
        "(audit_id, room_id, action_id, original_text, final_text, "
        "violations, unlock_snapshot) "
        "VALUES ('bulk-room-spoiler-audit', %s, 'bulk-room-action', "
        "'不应长期保留的原始文本', '不应长期保留的最终文本', %s, %s)",
        (
            room_id,
            json.dumps(
                [{
                    "label": "幕后真相",
                    "matched_text": "未揭示真相",
                    "source_ref": "secret:ending",
                }],
                ensure_ascii=False,
            ),
            json.dumps({"private_clue": "secret"}),
        ),
    )
    test_db.execute(
        "UPDATE ai_call_logs SET draft_id = 'deleted-room-draft', draft_revision = 3, "
        "audit_state = 'superseded', context_hash = 'deleted-room-context', "
        "citations = %s, structured_proposal = %s, engine_validation = %s, final_delta = %s "
        "WHERE room_id = %s",
        (
            json.dumps([{"source_ref": "private:room"}]),
            json.dumps({"private_role_detail": "must be minimized"}),
            json.dumps({"private_validation": "must be minimized"}),
            json.dumps({"private_delta": "must be minimized"}),
            room_id,
        ),
    )
    test_db.commit()

    response = client.post(
        "/api/admin/rooms/batch-delete",
        headers=_admin_headers(client),
        json={"ids": [room_id, "room-missing", room_id], "confirm": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requested_ids"] == [room_id, "room-missing"]
    assert payload["deleted_ids"] == [room_id]
    assert payload["not_found_ids"] == ["room-missing"]
    assert payload["errors"] == []
    assert _count(test_db, "rooms", "room_id = %s", (room_id,)) == 0
    assert _count(test_db, "collaboration_contracts", "contract_id = %s", (contract_id,)) == 0
    assert _count(test_db, "session_summaries", "session_summary_id = %s", (summary_id,)) == 0
    assert _count(
        test_db,
        "campaign_archives",
        "archive_id = %s",
        ("bulk-room-archive",),
    ) == 1
    assert _count(
        test_db,
        "ai_call_logs",
        "room_id = %s",
        (room_id,),
    ) == 1
    ai_audit = test_db.execute(
        "SELECT action_id, draft_id, draft_revision, audit_state, context_hash, "
        "response_summary, error_message, spoiler_hit_items, citations, "
        "structured_proposal, engine_validation, final_delta "
        "FROM ai_call_logs WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert ai_audit["action_id"] is None
    assert ai_audit["draft_id"] is None
    assert ai_audit["draft_revision"] is None
    assert ai_audit["audit_state"] == "minimized"
    assert ai_audit["context_hash"] == ""
    assert ai_audit["response_summary"] == ""
    assert ai_audit["error_message"] == ""
    assert ai_audit["spoiler_hit_items"] == []
    assert ai_audit["citations"] == []
    assert ai_audit["structured_proposal"] == {}
    assert ai_audit["engine_validation"] == {}
    assert ai_audit["final_delta"] == {}
    spoiler_audit = test_db.execute(
        "SELECT original_text, final_text, violations, unlock_snapshot "
        "FROM spoiler_audits WHERE audit_id = 'bulk-room-spoiler-audit'"
    ).fetchone()
    assert spoiler_audit is not None
    assert spoiler_audit["original_text"] == ""
    assert spoiler_audit["final_text"] == ""
    assert spoiler_audit["violations"] == []
    assert spoiler_audit["unlock_snapshot"] == {}
    access_audit = test_db.execute(
        "SELECT room_id, note_id, owner_character_id, host_account_id "
        "FROM private_data_access_audits "
        "WHERE private_data_access_audit_id = 'bulk-room-access-audit'"
    ).fetchone()
    assert access_audit == {
        "room_id": None,
        "note_id": None,
        "owner_character_id": None,
        "host_account_id": "acc-host",
    }


def test_batch_delete_characters_keeps_room_sessions_and_cleans_both_sides_of_relations(client, test_db):
    setup_auth_test_data(test_db)
    room_id = "bulk-character-room"
    character_id = "bulk-character-target"
    peer_id = "bulk-character-peer"
    contract_id = "bulk-character-contract"
    _insert_room(test_db, room_id)
    _insert_character(test_db, character_id, room_id)
    _insert_character(test_db, peer_id, room_id)
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('bulk-character-action', %s, %s, 'dialogue', 'private intent', 'completed')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO ai_call_logs "
        "(room_id, action_id, task_type, provider, status, record_kind, "
        "structured_proposal, expires_at) VALUES "
        "(%s, 'bulk-character-action', 'analyze_director_action', 'configured:test', "
        "'success', 'decision', %s, NOW() + INTERVAL '90 days')",
        (room_id, json.dumps({"private": "character detail"})),
    )
    test_db.execute(
        "INSERT INTO campaign_sessions (campaign_session_id, room_id, started_by_character_id) "
        "VALUES ('bulk-character-session', %s, %s)",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, expires_at) "
        "VALUES (%s, %s, %s, %s, NOW() + INTERVAL '10 minutes')",
        (contract_id, room_id, peer_id, "共同调查"),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_participants (contract_id, character_id, role) "
        "VALUES (%s, %s, 'invitee')",
        (contract_id, character_id),
    )
    test_db.execute(
        "INSERT INTO inventory_transfer_requests "
        "(transfer_id, room_id, item_id, from_character_id, to_character_id, item_name, quantity) "
        "VALUES ('bulk-character-transfer', %s, 'item-1', %s, %s, '线索', 1)",
        (room_id, character_id, peer_id),
    )
    test_db.commit()

    response = client.post(
        "/api/admin/characters/batch-delete",
        headers=_admin_headers(client),
        json={"ids": [character_id], "confirm": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["deleted_ids"] == [character_id]
    assert response.json()["errors"] == []
    assert _count(test_db, "characters", "character_id = %s", (character_id,)) == 0
    assert _count(test_db, "campaign_sessions", "campaign_session_id = %s", ("bulk-character-session",)) == 1
    assert test_db.execute(
        "SELECT started_by_character_id FROM campaign_sessions WHERE campaign_session_id = 'bulk-character-session'"
    ).fetchone()["started_by_character_id"] is None
    assert _count(test_db, "inventory_transfer_requests", "transfer_id = %s", ("bulk-character-transfer",)) == 0
    assert _count(test_db, "collaboration_contracts", "contract_id = %s", (contract_id,)) == 1
    assert _count(
        test_db,
        "collaboration_contract_participants",
        "contract_id = %s AND character_id = %s",
        (contract_id, character_id),
    ) == 0
    character_audit = test_db.execute(
        "SELECT action_id, structured_proposal, record_kind "
        "FROM ai_call_logs WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert character_audit == {
        "action_id": None,
        "structured_proposal": {},
        "record_kind": "decision",
    }


def test_character_delete_cancels_collaboration_batch_for_remaining_participants(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    room_id = "delete-collaboration-room"
    target_id = "delete-collaboration-target"
    peer_id = "delete-collaboration-peer"
    contract_id = "delete-collaboration-contract"
    target_draft_id = "delete-collaboration-target-draft"
    peer_draft_id = "delete-collaboration-peer-draft"
    target_action_id = "delete-collaboration-target-action"
    peer_action_id = "delete-collaboration-peer-action"
    _insert_room(test_db, room_id)
    _insert_character(test_db, target_id, room_id)
    _insert_character(test_db, peer_id, room_id)
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, status, expires_at) "
        "VALUES (%s, %s, %s, 'search together', 'accepted', NOW() + INTERVAL '10 minutes')",
        (contract_id, room_id, peer_id),
    )
    for order, (character_id, role, draft_id, action_id) in enumerate(
        (
            (peer_id, "initiator", peer_draft_id, peer_action_id),
            (target_id, "invitee", target_draft_id, target_action_id),
        )
    ):
        test_db.execute(
            "INSERT INTO collaboration_contract_participants "
            "(contract_id, character_id, role, invite_order, decision) "
            "VALUES (%s, %s, %s, %s, 'accepted')",
            (contract_id, character_id, role, order),
        )
        test_db.execute(
            "INSERT INTO action_drafts "
            "(draft_id, room_id, character_id, intent_type, status) "
            "VALUES (%s, %s, %s, 'action', 'awaiting_confirmation')",
            (draft_id, room_id, character_id),
        )
        test_db.execute(
            "INSERT INTO collaboration_contract_drafts "
            "(contract_id, character_id, draft_id) VALUES (%s, %s, %s)",
            (contract_id, character_id, draft_id),
        )
        test_db.execute(
            "INSERT INTO actions "
            "(action_id, room_id, character_id, draft_id, intent_type, status, params) "
            "VALUES (%s, %s, %s, %s, 'action', 'batched', %s)",
            (
                action_id,
                room_id,
                character_id,
                draft_id,
                json.dumps({"collaborationContractId": contract_id}),
            ),
        )
    test_db.execute(
        "INSERT INTO collaboration_contract_batches "
        "(contract_id, room_id, action_ids, status) VALUES (%s, %s, %s, 'queued')",
        (contract_id, room_id, json.dumps([peer_action_id, target_action_id])),
    )
    test_db.commit()

    response = client.delete(
        f"/api/admin/characters/{target_id}",
        headers=_admin_headers(client),
    )

    assert response.status_code == 200, response.text
    assert test_db.execute(
        "SELECT status FROM collaboration_contracts WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "canceled"
    assert test_db.execute(
        "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "canceled"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (peer_action_id,),
    ).fetchone()["status"] == "canceled"
    assert _count(test_db, "actions", "action_id = %s", (target_action_id,)) == 0
    event = test_db.execute(
        "SELECT status, metadata FROM action_status_events "
        "WHERE action_id = %s ORDER BY status_event_id DESC LIMIT 1",
        (peer_action_id,),
    ).fetchone()
    assert event["status"] == "canceled"
    assert event["metadata"]["reason_code"] == "collaboration_participant_canceled"


def test_character_delete_cancels_pending_action_that_requires_the_character(
    client,
    test_db,
):
    from src.server.ai.decision_audit import DecisionAuditRecorder

    setup_auth_test_data(test_db)
    room_id = "delete-consent-room"
    target_id = "delete-consent-target"
    peer_id = "delete-consent-peer"
    action_id = "delete-consent-action"
    consent_id = "delete-consent-record"
    _insert_room(test_db, room_id)
    _insert_character(test_db, target_id, room_id)
    _insert_character(test_db, peer_id, room_id)
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, status) "
        "VALUES (%s, %s, %s, 'combat_action', 'awaiting_player_consent')",
        (action_id, room_id, peer_id),
    )
    test_db.execute(
        "INSERT INTO action_consents "
        "(consent_id, action_id, room_id, requester_character_id, "
        "affected_character_id, consent_kind, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, 'pvp_damage', NOW() + INTERVAL '2 minutes')",
        (consent_id, action_id, room_id, peer_id, target_id),
    )
    audit_id = DecisionAuditRecorder(test_db).record(
        room_id=room_id,
        action_id=action_id,
        task_type="analyze_director_action",
        provider="character-delete-test",
        model="deterministic",
    )
    test_db.commit()

    response = client.delete(
        f"/api/admin/characters/{target_id}",
        headers=_admin_headers(client),
    )

    assert response.status_code == 200, response.text
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    assert action["status"] == "canceled"
    assert action["result"] == {
        "outcome": "no_effect",
        "reason": "affected_character_deleted",
    }
    assert _count(test_db, "action_consents", "consent_id = %s", (consent_id,)) == 0
    event = test_db.execute(
        "SELECT status, metadata FROM action_status_events "
        "WHERE action_id = %s ORDER BY status_event_id DESC LIMIT 1",
        (action_id,),
    ).fetchone()
    assert event["status"] == "canceled"
    assert event["metadata"] == {
        "reason_code": "affected_character_deleted",
        "effect": "no_effect",
    }
    audit = test_db.execute(
        "SELECT engine_validation, final_delta FROM ai_call_logs "
        "WHERE decision_audit_id = %s",
        (audit_id,),
    ).fetchone()
    assert audit["engine_validation"] == {
        "valid": False,
        "reasonCode": "affected_character_deleted",
    }
    assert audit["final_delta"] == {
        "action_status": "canceled",
        "state_version": 0,
        "reason_code": "affected_character_deleted",
        "effect": "no_effect",
    }


@pytest.mark.asyncio
async def test_character_delete_waits_for_queued_consent_action_lifecycle(
    client,
    test_db,
):
    import asyncio

    from src.server.engine.resolution_pipeline import ResolutionPipeline

    setup_auth_test_data(test_db)
    room_id = "delete-accepted-consent-room"
    target_id = "delete-accepted-consent-target"
    peer_id = "delete-accepted-consent-peer"
    action_id = "delete-accepted-consent-action"
    _insert_room(test_db, room_id)
    _insert_character(test_db, target_id, room_id)
    _insert_character(test_db, peer_id, room_id)
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, status) "
        "VALUES (%s, %s, %s, 'combat_action', 'queued')",
        (action_id, room_id, peer_id),
    )
    test_db.execute(
        "INSERT INTO action_consents "
        "(consent_id, action_id, room_id, requester_character_id, "
        "affected_character_id, consent_kind, decision, expires_at, responded_at) "
        "VALUES ('delete-accepted-consent-record', %s, %s, %s, %s, "
        "'pvp_damage', 'accepted', NOW() + INTERVAL '2 minutes', NOW())",
        (action_id, room_id, peer_id, target_id),
    )
    test_db.commit()
    entered = asyncio.Event()
    release = asyncio.Event()
    pipeline = ResolutionPipeline(test_db)

    async def hold_resolution(_action_id):
        entered.set()
        await release.wait()
        return {"status": "queued", "action_id": action_id}

    pipeline._resolve_action_locked = hold_resolution
    resolving = asyncio.create_task(pipeline.resolve_action(action_id))
    await entered.wait()
    deletion = asyncio.create_task(asyncio.to_thread(
        client.delete,
        f"/api/admin/characters/{target_id}",
        headers=_admin_headers(client),
    ))
    await asyncio.sleep(0.05)

    assert not deletion.done()

    release.set()
    await resolving
    response = await deletion
    assert response.status_code == 200, response.text
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    assert action["status"] == "canceled"
    assert action["result"]["reason"] == "affected_character_deleted"


def test_character_delete_invalidates_runtime_snapshots_and_live_connection(
    client,
    test_db,
):
    from src.server.host import router_host
    from src.server.host.ws_manager import manager as ws_manager

    class FakeSocket:
        def __init__(self):
            self.closed = None

        async def close(self, *, code, reason):
            self.closed = (code, reason)

    setup_auth_test_data(test_db)
    room_id = "character-runtime-room"
    character_id = "character-runtime-target"
    peer_id = "character-runtime-peer"
    action_id = "character-runtime-action"
    peer_action_id = "character-runtime-peer-action"
    _insert_room(test_db, room_id, owner_account_id="acc-host")
    _insert_character(test_db, character_id, room_id)
    _insert_character(test_db, peer_id, room_id)
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES (%s, %s, %s, 'dialogue', 'private runtime intent', 'completed')",
        (action_id, room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, turn_id, intent_type, declared_intent, status) "
        "VALUES (%s, %s, %s, 'character-runtime-turn', 'dialogue', 'peer intent', 'queued')",
        (peer_action_id, room_id, peer_id),
    )
    test_db.execute(
        "UPDATE actions SET turn_id = 'character-runtime-turn' WHERE action_id = %s",
        (action_id,),
    )
    test_db.execute(
        "INSERT INTO ai_call_logs "
        "(room_id, action_id, task_type, provider, status, engine_validation, final_delta) "
        "VALUES (%s, %s, 'analyze_director_action', 'configured:test', 'success', %s, %s)",
        (
            room_id,
            action_id,
            json.dumps({"character_id": character_id, "private": "validation-secret"}),
            json.dumps({"character_id": character_id, "private": "delta-secret"}),
        ),
    )
    test_db.execute(
        "INSERT INTO host_states (room_id, state) VALUES (%s, %s)",
        (
            room_id,
            json.dumps({
                "players": {
                    character_id: {"name": "Secret Name"},
                    peer_id: {"name": "Peer Name"},
                },
                "queuedActions": [
                    {"action_id": action_id, "secret": "host-action-secret"},
                    {"action_id": peer_action_id, "intent": "peer intent"},
                ],
                "scene": {"name": "Shared Scene"},
            }),
        ),
    )
    test_db.execute(
        "INSERT INTO checkpoints (checkpoint_id, room_id, state_snapshot) "
        "VALUES ('character-runtime-checkpoint', %s, %s)",
        (
            room_id,
            json.dumps({
                "characters": {
                    character_id: {"secret": "checkpoint-secret"},
                    peer_id: {"public": "peer-state"},
                },
                "actions": [
                    {"action_id": action_id, "declared_intent": "checkpoint-secret"},
                    {"action_id": peer_action_id, "declared_intent": "peer intent"},
                ],
            }),
        ),
    )
    test_db.execute(
        "INSERT INTO room_turns "
        "(turn_id, room_id, combat_plan, combat_summary, summary) "
        "VALUES ('character-runtime-turn', %s, %s, %s, 'turn-secret')",
        (
            room_id,
            json.dumps({
                "actions": [
                    {"character_id": character_id, "intent": "turn-secret"},
                    {"character_id": peer_id, "intent": "peer intent"},
                ],
            }),
            json.dumps({
                "results": [
                    {"action_id": action_id, "result": "summary-secret"},
                    {"action_id": peer_action_id, "result": "peer result"},
                ],
            }),
        ),
    )
    test_db.execute(
        "INSERT INTO room_map_state (room_id, map_id, token_visibility) "
        "VALUES (%s, 'character-runtime-map', %s)",
        (room_id, json.dumps({character_id: "party", "peer-character": "party"})),
    )
    test_db.commit()

    router_host.get_host_store(room_id)
    socket = FakeSocket()
    ws_manager.register_accepted(socket, room_id, f"player:{character_id}")

    try:
        response = client.delete(
            f"/api/admin/characters/{character_id}",
            headers=_admin_headers(client),
        )

        assert response.status_code == 200, response.text
        host_state = test_db.execute(
            "SELECT state FROM host_states WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        assert host_state is not None
        rendered_host_state = json.dumps(host_state["state"], ensure_ascii=False)
        assert character_id not in rendered_host_state
        assert action_id not in rendered_host_state
        assert "Secret Name" not in rendered_host_state
        assert "host-action-secret" not in rendered_host_state
        assert peer_id in rendered_host_state
        assert peer_action_id in rendered_host_state
        assert "Shared Scene" in rendered_host_state
        checkpoint = test_db.execute(
            "SELECT state_snapshot FROM checkpoints WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        turn = test_db.execute(
            "SELECT combat_plan, combat_summary, summary FROM room_turns WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        assert checkpoint is not None
        assert turn is not None
        preserved_runtime = json.dumps(
            {"checkpoint": dict(checkpoint), "turn": dict(turn)},
            ensure_ascii=False,
        )
        assert character_id not in preserved_runtime
        assert action_id not in preserved_runtime
        assert "checkpoint-secret" not in preserved_runtime
        assert "turn-secret" not in preserved_runtime
        assert "summary-secret" not in preserved_runtime
        assert peer_id in preserved_runtime
        assert peer_action_id in preserved_runtime
        assert _count(
            test_db,
            "actions",
            "action_id = %s AND turn_id = 'character-runtime-turn'",
            (peer_action_id,),
        ) == 1
        visibility = test_db.execute(
            "SELECT token_visibility FROM room_map_state WHERE room_id = %s",
            (room_id,),
        ).fetchone()["token_visibility"]
        assert character_id not in visibility
        assert visibility["peer-character"] == "party"
        audit = test_db.execute(
            "SELECT action_id, structured_proposal, engine_validation, final_delta "
            "FROM ai_call_logs WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        assert audit == {
            "action_id": None,
            "structured_proposal": {},
            "engine_validation": {},
            "final_delta": {},
        }
        assert room_id not in router_host._host_stores
        assert not ws_manager.is_connected(room_id, f"player:{character_id}")
        assert socket.closed == (4003, "character_control_revoked")
    finally:
        router_host.remove_host_store(room_id)
        ws_manager.disconnect(room_id, f"player:{character_id}")


@pytest.mark.asyncio
async def test_character_delete_waits_for_inflight_character_lifecycle(
    client,
    test_db,
):
    from src.server.runtime_lifecycle import character_lifecycle_guard

    setup_auth_test_data(test_db)
    room_id = "character-lifecycle-room"
    character_id = "character-lifecycle-target"
    _insert_room(test_db, room_id, owner_account_id="acc-host")
    _insert_character(test_db, character_id, room_id)
    test_db.commit()

    async with character_lifecycle_guard([character_id]):
        deletion = asyncio.create_task(asyncio.to_thread(
            client.delete,
            f"/api/admin/characters/{character_id}",
            headers=_admin_headers(client),
        ))
        await asyncio.sleep(0.05)
        assert not deletion.done()

    response = await deletion
    assert response.status_code == 200, response.text
    assert _count(test_db, "characters", "character_id = %s", (character_id,)) == 0


def test_batch_delete_accounts_uses_character_cleanup_and_preserves_ai_audit(client, test_db):
    setup_auth_test_data(test_db)
    account_id = "bulk-delete-account"
    room_id = "bulk-account-room"
    character_id = "bulk-account-character"
    peer_id = "bulk-account-peer"
    create_account(test_db, account_id, "bulk-delete", "player")
    test_db.execute(
        "INSERT INTO character_profiles "
        "(profile_id, account_id, name, occupation, background, backstory) "
        "VALUES ('bulk-account-profile', %s, 'private profile name', "
        "'private occupation', 'private background', %s)",
        (account_id, json.dumps({"private_history": "must be deleted"})),
    )
    _insert_room(test_db, room_id, owner_account_id="acc-host")
    _insert_character(test_db, character_id, room_id, account_id=account_id)
    _insert_character(test_db, peer_id, room_id)
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status) "
        "VALUES ('bulk-account-encounter', %s, 'combat', 'active')",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO encounter_participants "
        "(encounter_id, character_id, side, hp, hp_max, san, san_max, dex, mov, notes) "
        "VALUES ('bulk-account-encounter', %s, 'player', 7, 10, 42, 60, 55, 8, "
        "'private encounter notes')",
        (character_id,),
    )
    test_db.execute(
        "INSERT INTO evidence_cards "
        "(evidence_card_id, room_id, created_by_character_id, title, body, visibility) "
        "VALUES ('bulk-account-private-card', %s, %s, 'private title', "
        "'private evidence body', 'private')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO evidence_cards "
        "(evidence_card_id, room_id, created_by_character_id, title, body, visibility, "
        "question_closed_by_character_id, hypothesis_status_changed_by_character_id) "
        "VALUES ('bulk-account-party-card', %s, %s, 'party title', "
        "'party evidence body', 'party', %s, %s)",
        (room_id, character_id, character_id, character_id),
    )
    test_db.execute(
        "INSERT INTO player_notes "
        "(note_id, room_id, character_id, title_ciphertext, body_ciphertext) "
        "VALUES ('bulk-account-note', %s, %s, 'title', 'body')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO private_data_access_audits "
        "(private_data_access_audit_id, room_id, note_id, owner_character_id, "
        "host_account_id, reason) VALUES "
        "('bulk-account-access-audit', %s, 'bulk-account-note', %s, %s, 'incident')",
        (room_id, character_id, account_id),
    )
    test_db.execute(
        "UPDATE characters SET player_name = 'Alice Account' WHERE character_id = %s",
        (character_id,),
    )
    test_db.execute(
        "INSERT INTO inventory_transfer_requests "
        "(transfer_id, room_id, item_id, from_character_id, to_character_id, item_name, quantity) "
        "VALUES ('bulk-account-transfer', %s, 'item-2', %s, %s, '证物', 1)",
        (room_id, character_id, peer_id),
    )
    test_db.execute(
        "INSERT INTO ai_provider_config_audits (audit_id, action, actor_id) "
        "VALUES ('bulk-account-audit', 'created', %s)",
        (account_id,),
    )
    test_db.execute(
        "INSERT INTO retention_runs "
        "(retention_run_id, idempotency_key, cutoff, actor_id, counts) "
        "VALUES ('bulk-account-retention-run', 'bulk-account-retention-key', "
        "NOW(), %s, '{}')",
        (account_id,),
    )
    test_db.execute(
        "INSERT INTO action_drafts "
        "(draft_id, room_id, character_id, intent_type, declared_intent, status, analysis) "
        "VALUES ('bulk-account-unconfirmed-draft', %s, %s, 'dialogue', "
        "'private unconfirmed intent', 'awaiting_confirmation', '{}')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('bulk-account-action', %s, %s, 'dialogue', "
        "'private completed intent', 'completed')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO ai_call_logs "
        "(room_id, action_id, draft_id, draft_revision, audit_state, task_type, "
        "provider, model, status, record_kind, citations, structured_proposal, "
        "engine_validation, final_delta) VALUES (%s, NULL, "
        "'bulk-account-unconfirmed-draft', 1, 'superseded', "
        "'analyze_director_action', 'configured:test', 'model-v1', 'success', "
        "'decision', %s, %s, %s, %s)",
        (
            room_id,
            json.dumps([{"source_ref": "private-draft-source"}]),
            json.dumps({"interpreted_intent": "private unconfirmed intent"}),
            json.dumps({"private_validation": "must be minimized"}),
            json.dumps({"private_delta": "must be minimized"}),
        ),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) "
        "VALUES (%s, 's2c_private_notice', 'player', %s)",
        (
            room_id,
            json.dumps({
                "kind": "collaboration_invite",
                "characterId": character_id,
                "sharedIntent": "private collaboration plan",
            }),
        ),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload, action_id) "
        "VALUES (%s, 's2c_action_completed', 'player', %s, 'bulk-account-action')",
        (room_id, json.dumps({"status": "completed"})),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) "
        "VALUES (%s, 's2c_action_queued', 'player', %s)",
        (room_id, json.dumps({"actionId": "bulk-account-action"})),
    )
    test_db.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs) "
        "VALUES ('bulk-account-archive', %s, 'mixed', %s, %s, %s)",
        (
            room_id,
            f"角色 Alice Account（{character_id}）参与。",
            json.dumps([f"Alice Account 使用 {character_id} 找到了线索。"]),
            json.dumps([
                {
                    "character_id": character_id,
                    "player_name": "Alice Account",
                    "total_actions": 3,
                    "final_san": 41,
                    "sanity_outcome": {"phase": "underlying"},
                },
                {
                    "character_id": peer_id,
                    "player_name": peer_id,
                    "total_actions": 1,
                    "final_san": 55,
                },
            ]),
        ),
    )
    test_db.commit()

    response = client.post(
        "/api/admin/accounts/batch-delete",
        headers=_admin_headers(client),
        json={"ids": [account_id, "acc-admin", "account-missing", account_id], "confirm": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["requested_ids"] == [account_id, "acc-admin", "account-missing"]
    assert payload["deleted_ids"] == [account_id]
    assert payload["not_found_ids"] == ["account-missing"]
    errors = {item["id"]: item for item in payload["errors"]}
    assert errors["acc-admin"]["status"] == "409"
    assert errors["acc-admin"]["error"] == "不能删除当前登录的管理员账号"
    assert _count(test_db, "accounts", "account_id = %s", (account_id,)) == 0
    assert _count(
        test_db,
        "character_profiles",
        "account_id = %s",
        (account_id,),
    ) == 0
    assert _count(test_db, "characters", "character_id = %s", (character_id,)) == 0
    assert _count(
        test_db,
        "encounter_participants",
        "character_id = %s",
        (character_id,),
    ) == 0
    assert _count(
        test_db,
        "evidence_cards",
        "evidence_card_id = %s",
        ("bulk-account-private-card",),
    ) == 0
    party_card = test_db.execute(
        "SELECT created_by_character_id, question_closed_by_character_id, "
        "hypothesis_status_changed_by_character_id FROM evidence_cards "
        "WHERE evidence_card_id = 'bulk-account-party-card'"
    ).fetchone()
    assert party_card == {
        "created_by_character_id": None,
        "question_closed_by_character_id": None,
        "hypothesis_status_changed_by_character_id": None,
    }
    assert _count(
        test_db,
        "events",
        "audience = 'player' AND payload->>'characterId' = %s",
        (character_id,),
    ) == 0
    assert _count(
        test_db,
        "events",
        "audience = 'player' AND (action_id = %s OR payload->>'actionId' = %s)",
        ("bulk-account-action", "bulk-account-action"),
    ) == 0
    assert _count(test_db, "inventory_transfer_requests", "transfer_id = %s", ("bulk-account-transfer",)) == 0
    assert _count(test_db, "ai_provider_config_audits", "audit_id = %s", ("bulk-account-audit",)) == 1
    audit_actor = test_db.execute(
        "SELECT actor_id FROM ai_provider_config_audits "
        "WHERE audit_id = 'bulk-account-audit'"
    ).fetchone()["actor_id"]
    assert audit_actor.startswith("deleted-account:")
    assert account_id not in audit_actor
    draft_audit = test_db.execute(
        "SELECT action_id, draft_id, draft_revision, audit_state, context_hash, "
        "citations, structured_proposal, engine_validation, final_delta "
        "FROM ai_call_logs "
        "WHERE room_id = %s AND task_type = 'analyze_director_action'",
        (room_id,),
    ).fetchone()
    assert draft_audit == {
        "action_id": None,
        "draft_id": None,
        "draft_revision": None,
        "audit_state": "minimized",
        "context_hash": "",
        "citations": [],
        "structured_proposal": {},
        "engine_validation": {},
        "final_delta": {},
    }
    archive = test_db.execute(
        "SELECT summary, highlights, character_arcs FROM campaign_archives "
        "WHERE archive_id = 'bulk-account-archive'"
    ).fetchone()
    rendered_archive = json.dumps(dict(archive), ensure_ascii=False)
    assert "Alice Account" not in rendered_archive
    assert character_id not in rendered_archive
    target_arc = next(
        arc
        for arc in archive["character_arcs"]
        if arc["player_name"] == "已删除玩家"
    )
    assert target_arc["character_id"].startswith("deleted-character:")
    assert target_arc["total_actions"] == 3
    assert "final_san" not in target_arc
    assert "sanity_outcome" not in target_arc
    access_audit = test_db.execute(
        "SELECT room_id, note_id, owner_character_id, host_account_id, "
        "actor_tombstone FROM private_data_access_audits "
        "WHERE private_data_access_audit_id = 'bulk-account-access-audit'"
    ).fetchone()
    assert access_audit["room_id"] == room_id
    assert access_audit["note_id"] is None
    assert access_audit["owner_character_id"] is None
    assert access_audit["host_account_id"] is None
    assert access_audit["actor_tombstone"].startswith("deleted-account:")
    assert account_id not in access_audit["actor_tombstone"]
    retention_actor = test_db.execute(
        "SELECT actor_id FROM retention_runs "
        "WHERE retention_run_id = 'bulk-account-retention-run'"
    ).fetchone()["actor_id"]
    assert retention_actor.startswith("deleted-account:")
    assert account_id not in retention_actor
    deletion_audit = test_db.execute(
        "SELECT actor_id, target_count, details, expires_at "
        "FROM admin_data_purge_audits WHERE action = 'account_delete'"
    ).fetchone()
    assert deletion_audit["actor_id"] == "acc-admin"
    assert deletion_audit["target_count"] == 1
    assert deletion_audit["details"] == {}
    assert deletion_audit["expires_at"] is not None


def test_single_account_delete_writes_minimal_365_day_audit(client, test_db):
    setup_auth_test_data(test_db)
    account_id = "single-delete-account"
    create_account(test_db, account_id, "single-delete", "player")

    response = client.delete(
        f"/api/admin/accounts/{account_id}",
        headers=_admin_headers(client),
    )

    assert response.status_code == 200, response.text
    audit = test_db.execute(
        "SELECT actor_id, target_count, details, created_at, expires_at "
        "FROM admin_data_purge_audits WHERE action = 'account_delete'"
    ).fetchone()
    assert audit["actor_id"] == "acc-admin"
    assert audit["target_count"] == 1
    assert audit["details"] == {}
    assert 364 <= (audit["expires_at"] - audit["created_at"]).days <= 365


def test_account_delete_pseudonymizes_public_events_aliases_and_actor_references(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    account_id = "identity-delete-account"
    room_id = "identity-delete-room"
    character_id = "identity-delete-character"
    aliases = ["Account Display", "Investigator Alias", "Character Alias"]
    create_account(test_db, account_id, "identity-delete", "player")
    _insert_room(test_db, room_id, owner_account_id="acc-host")
    _insert_character(test_db, character_id, room_id, account_id=account_id)
    test_db.execute(
        "UPDATE characters SET player_name = %s, xlsx_data = %s "
        "WHERE character_id = %s",
        (
            aliases[0],
            json.dumps({
                "name": aliases[1],
                "investigator_name": aliases[1],
                "character_name": aliases[2],
            }),
            character_id,
        ),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('identity-delete-action', %s, %s, 'dialogue', 'private', 'completed')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) "
        "VALUES (%s, 's2c_team_message', 'party', %s)",
        (
            room_id,
            json.dumps({
                "characterId": character_id,
                "playerName": aliases[0],
                "investigatorName": aliases[1],
                "text": f"{aliases[1]} shares a public clue.",
            }),
        ),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) "
        "VALUES (%s, 's2c_player_moved', 'party', %s)",
        (
            room_id,
            json.dumps({"characterId": character_id, "toNodeId": "library"}),
        ),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) "
        "VALUES (%s, 'character_access_terminated', 'system', %s)",
        (
            room_id,
            json.dumps({
                "characterId": character_id,
                "accountId": account_id,
                "text": f"Access ended for {aliases[0]}",
            }),
        ),
    )
    for event_type, payload in (
        ("s2c_room_lobby_snapshot", {
            "players": [{
                "character_id": character_id,
                "player_name": aliases[0],
                "investigator_name": aliases[1],
                "status": "joined",
            }],
        }),
        ("s2c_clue_shared", {
            "sharedBy": character_id,
            "publicVersion": f"{aliases[2]} shared a safe clue.",
        }),
        ("s2c_encounter_updated", {
            "publicUnits": [{"kind": "investigator", "label": aliases[1]}],
        }),
        ("s2c_turn_resolved", {
            "narrative": f"{aliases[1]} completed the turn.",
            "actions": [{
                "actionId": "identity-delete-action",
                "characterId": character_id,
            }],
        }),
        ("s2c_state_patch", {
            "patches": [{
                "path": f"/characters/{character_id}",
                "value": {
                    "character_id": character_id,
                    "player_name": aliases[0],
                    "investigator_name": aliases[1],
                    "account_id": account_id,
                },
            }],
        }),
    ):
        test_db.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) "
            "VALUES (%s, %s, 'party', %s)",
            (room_id, event_type, json.dumps(payload)),
        )
    test_db.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs) "
        "VALUES ('identity-delete-archive', %s, 'mixed', %s, %s, %s)",
        (
            room_id,
            f"{aliases[1]} and {aliases[2]} reached the ending.",
            json.dumps([f"{aliases[2]} found the final clue."]),
            json.dumps([{
                "character_id": character_id,
                "player_name": aliases[0],
                "total_actions": 2,
            }]),
        ),
    )
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, license_type, created_by) "
        "VALUES ('identity-delete-rules', 'Rules', 'identity-delete-rules', "
        "'coc7e', 'internal', %s)",
        (account_id,),
    )
    test_db.execute(
        "INSERT INTO v2_cutover_records "
        "(cutover_id, status, backup_path, backup_sha256, requested_by) "
        "VALUES ('identity-delete-cutover', 'completed', 'backup.sql', 'sha256', %s)",
        (account_id,),
    )
    test_db.commit()

    response = client.delete(
        f"/api/admin/accounts/{account_id}",
        headers=_admin_headers(client),
    )

    assert response.status_code == 200, response.text
    rendered_archive = json.dumps(dict(test_db.execute(
        "SELECT summary, highlights, character_arcs FROM campaign_archives "
        "WHERE archive_id = 'identity-delete-archive'"
    ).fetchone()), ensure_ascii=False)
    rendered_events = json.dumps([
        dict(row)
        for row in test_db.execute(
            "SELECT event_type, payload FROM events WHERE room_id = %s ORDER BY sequence",
            (room_id,),
        ).fetchall()
    ], ensure_ascii=False)
    for private_identity in [character_id, *aliases]:
        assert private_identity not in rendered_archive
        assert private_identity not in rendered_events
    assert "shares a public clue" in rendered_events
    rule_actor = test_db.execute(
        "SELECT created_by FROM rule_sets WHERE rule_set_id = 'identity-delete-rules'"
    ).fetchone()["created_by"]
    cutover_actor = test_db.execute(
        "SELECT requested_by FROM v2_cutover_records "
        "WHERE cutover_id = 'identity-delete-cutover'"
    ).fetchone()["requested_by"]
    assert rule_actor.startswith("deleted-account:")
    assert cutover_actor.startswith("deleted-account:")
    assert account_id not in rule_actor
    assert account_id not in cutover_actor
    from src.server.engine.runtime_integrity import (
        checkpoint_snapshot_hash,
        sanitize_checkpoint_value,
    )
    for row in test_db.execute(
        "SELECT payload, payload_hash FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchall():
        assert row["payload_hash"] == checkpoint_snapshot_hash(
            sanitize_checkpoint_value(row["payload"])
        )


def test_batch_account_delete_rejects_current_admin_self_delete(client, test_db):
    setup_auth_test_data(test_db)
    admin_id = "batch-self-admin"
    target_id = "batch-self-target"
    create_account(test_db, admin_id, "batch-self-admin", "admin")
    create_account(test_db, target_id, "batch-self-target", "player")
    headers = {
        "Authorization": f"Bearer {login(client, 'batch-self-admin')}"
    }

    response = client.post(
        "/api/admin/accounts/batch-delete",
        headers=headers,
        json={"ids": [admin_id, target_id], "confirm": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["deleted_ids"] == [target_id]
    assert response.json()["errors"] == [{
        "id": admin_id,
        "error": "不能删除当前登录的管理员账号",
        "status": "409",
    }]
    assert _count(test_db, "accounts", "account_id = %s", (admin_id,)) == 1
    audit = test_db.execute(
        "SELECT actor_id FROM admin_data_purge_audits "
        "WHERE action = 'account_delete'"
    ).fetchone()
    assert audit["actor_id"] == admin_id


def test_account_delete_holds_requesting_admin_until_purge_audit_is_written(
    client,
    test_db,
    monkeypatch,
):
    from fastapi.testclient import TestClient

    from src.server.main import app
    import src.server.router_admin as router_admin

    setup_auth_test_data(test_db)
    actor_id = "account-delete-actor"
    target_id = "account-delete-target"
    room_id = "account-delete-actor-race-room"
    character_id = "account-delete-actor-race-character"
    create_account(test_db, actor_id, "account-delete-actor", "admin")
    create_account(test_db, target_id, "account-delete-target", "player")
    _insert_room(test_db, room_id, owner_account_id="acc-host")
    _insert_character(test_db, character_id, room_id, account_id=target_id)
    test_db.commit()

    target_guard_entered = threading.Event()
    release_target_guard = threading.Event()
    original_character_guard = router_admin.character_lifecycle_guard

    @asynccontextmanager
    async def delayed_character_guard(character_ids, *, conn=None):
        normalized = list(character_ids)
        if character_id in normalized:
            target_guard_entered.set()
            await asyncio.to_thread(release_target_guard.wait)
        async with original_character_guard(normalized, conn=conn):
            yield

    monkeypatch.setattr(
        router_admin,
        "character_lifecycle_guard",
        delayed_character_guard,
    )
    actor_client = TestClient(app)
    actor_token = login(actor_client, "account-delete-actor")
    admin_client = TestClient(app)
    admin_token = login(admin_client, "admin")

    actor_delete_blocked = False
    with ThreadPoolExecutor(max_workers=2) as executor:
        target_future = executor.submit(
            actor_client.delete,
            f"/api/admin/accounts/{target_id}",
            headers={"Authorization": f"Bearer {actor_token}"},
        )
        assert target_guard_entered.wait(timeout=2)
        actor_future = executor.submit(
            admin_client.delete,
            f"/api/admin/accounts/{actor_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        try:
            actor_future.result(timeout=0.25)
        except TimeoutError:
            actor_delete_blocked = True
        finally:
            release_target_guard.set()
        target_response = target_future.result(timeout=3)
        actor_response = actor_future.result(timeout=3)

    assert actor_delete_blocked is True
    assert target_response.status_code == 200, target_response.text
    assert actor_response.status_code == 200, actor_response.text
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM admin_data_purge_audits "
        "WHERE actor_id = %s",
        (actor_id,),
    ).fetchone()["count"] == 0


def test_account_owned_rows_reject_new_orphan_account_references(test_db):
    setup_auth_test_data(test_db)
    _insert_room(test_db, "account-fk-room")

    with pytest.raises(Exception):
        _insert_room(
            test_db,
            "account-fk-orphan-room",
            owner_account_id="missing-account",
        )
    with pytest.raises(Exception):
        _insert_character(
            test_db,
            "account-fk-orphan-character",
            "account-fk-room",
            account_id="missing-account",
        )
    with pytest.raises(Exception):
        test_db.execute(
            "INSERT INTO character_profiles (profile_id, account_id, name) "
            "VALUES ('account-fk-orphan-profile', 'missing-account', 'orphan')"
        )

    assert _count(
        test_db,
        "rooms",
        "room_id = %s",
        ("account-fk-orphan-room",),
    ) == 0
    assert _count(
        test_db,
        "characters",
        "character_id = %s",
        ("account-fk-orphan-character",),
    ) == 0
    assert _count(
        test_db,
        "character_profiles",
        "profile_id = %s",
        ("account-fk-orphan-profile",),
    ) == 0


def test_direct_character_delete_pseudonymizes_public_history_and_reveal_linkage(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    room_id = "direct-character-history-room"
    character_id = "direct-character-history-target"
    action_id = "direct-character-history-action"
    _insert_room(test_db, room_id, owner_account_id="acc-host")
    _insert_character(test_db, character_id, room_id)
    test_db.execute(
        "UPDATE characters SET player_name = 'Direct Secret Name', xlsx_data = %s "
        "WHERE character_id = %s",
        (json.dumps({"investigator_name": "Investigator Secret Alias"}), character_id),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES (%s, %s, %s, 'dialogue', 'public action', 'completed')",
        (action_id, room_id, character_id),
    )
    event_sequence = test_db.execute(
        "INSERT INTO events "
        "(room_id, event_type, audience, payload, action_id, state_version) "
        "VALUES (%s, 's2c_fact_revealed', 'party', %s, %s, 0) RETURNING sequence",
        (
            room_id,
            json.dumps({
                "revealId": "direct-character-reveal",
                "factId": "public-fact",
                "status": "revealed",
                "contentItemId": "",
                "factText": "public clue",
                "citation": {"label": "已校验依据", "verified": True},
            }),
            action_id,
        ),
    ).fetchone()["sequence"]
    identity_event_sequence = test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload, action_id) "
        "VALUES (%s, 's2c_team_message', 'party', %s, %s) RETURNING sequence",
        (
            room_id,
            json.dumps({
                "characterId": character_id,
                "playerName": "Direct Secret Name",
                "actionId": action_id,
                "text": "Investigator Secret Alias shares a public clue",
            }),
            action_id,
        ),
    ).fetchone()["sequence"]
    test_db.execute(
        "INSERT INTO fact_reveals "
        "(reveal_id, room_id, fact_id, fact_text, audience, source_action_id, "
        "state_version, event_sequence, trigger_snapshot) "
        "VALUES ('direct-character-reveal', %s, 'public-fact', 'public clue', "
        "'party', %s, 0, %s, %s)",
        (
            room_id,
            action_id,
            event_sequence,
            json.dumps({
                "character_id": character_id,
                "action_id": action_id,
                "label": "Direct Secret Name",
            }),
        ),
    )
    test_db.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs) "
        "VALUES ('direct-character-archive', %s, 'mixed', %s, %s, %s)",
        (
            room_id,
            f"Direct Secret Name used {action_id}.",
            json.dumps([f"Investigator Secret Alias completed {action_id}."]),
            json.dumps([{
                "character_id": character_id,
                "player_name": "Direct Secret Name",
                "total_actions": 1,
            }]),
        ),
    )
    test_db.commit()

    response = client.delete(
        f"/api/admin/characters/{character_id}",
        headers=_admin_headers(client),
    )

    assert response.status_code == 200, response.text
    archive = test_db.execute(
        "SELECT summary, highlights, character_arcs FROM campaign_archives "
        "WHERE archive_id = 'direct-character-archive'"
    ).fetchone()
    events = test_db.execute(
        "SELECT sequence, action_id, payload FROM events "
        "WHERE sequence = ANY(%s) ORDER BY sequence",
        ([event_sequence, identity_event_sequence],),
    ).fetchall()
    fact_event = next(row for row in events if row["sequence"] == event_sequence)
    identity_event = next(
        row for row in events if row["sequence"] == identity_event_sequence
    )
    reveal = test_db.execute(
        "SELECT source_action_id, trigger_snapshot FROM fact_reveals "
        "WHERE reveal_id = 'direct-character-reveal'"
    ).fetchone()
    rendered = json.dumps(
        {
            "archive": dict(archive),
            "events": [dict(row) for row in events],
            "reveal": dict(reveal),
        },
        ensure_ascii=False,
    )
    for private_identity in (
        character_id,
        action_id,
        "Direct Secret Name",
        "Investigator Secret Alias",
    ):
        assert private_identity not in rendered
    assert fact_event["action_id"] == reveal["source_action_id"]
    assert fact_event["action_id"].startswith("deleted-action:")
    assert "shares a public clue" in identity_event["payload"]["text"]
    assert reveal["source_action_id"].startswith("deleted-action:")
    from src.server.events.event_log import EventLog

    event_row = test_db.execute(
        "SELECT sequence, room_id, event_type, audience, payload, action_id, "
        "state_version FROM events WHERE sequence = %s",
        (event_sequence,),
    ).fetchone()
    reveal_row = test_db.execute(
        "SELECT * FROM fact_reveals WHERE reveal_id = 'direct-character-reveal'"
    ).fetchone()
    assert event_row["room_id"] == reveal_row["room_id"]
    assert event_row["audience"] == reveal_row["audience"]
    assert event_row["action_id"] == reveal_row["source_action_id"]
    assert event_row["state_version"] == reveal_row["state_version"]
    from src.server.models import redact_citation

    assert event_row["payload"] == {
        "revealId": reveal_row["reveal_id"],
        "factId": reveal_row["fact_id"],
        "status": reveal_row["status"],
        "contentItemId": reveal_row.get("content_item_id") or "",
        "factText": reveal_row.get("fact_text") or "",
        "citation": redact_citation(reveal_row.get("citation") or {}),
    }
    ledger = EventLog(test_db)
    assert ledger._ledger_authorizes_event(
        event_row["sequence"],
        event_row["event_type"],
        event_row["audience"],
        None,
        event_row["payload"],
        event_row["action_id"],
        event_row["state_version"],
        event_row["room_id"],
    ), {"event": dict(event_row), "reveal": dict(reveal)}
    visible_sequences = {
        event.sequence for event in ledger.get_public_events(room_id)
    }
    assert event_sequence in visible_sequences


def test_account_archive_pseudonymization_preserves_overlapping_chinese_name(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    account_id = "overlap-name-account"
    room_id = "overlap-name-room"
    character_id = "overlap-name-target"
    peer_id = "overlap-name-peer"
    create_account(test_db, account_id, "overlap-name", "player")
    _insert_room(test_db, room_id, owner_account_id="acc-host")
    _insert_character(test_db, character_id, room_id, account_id=account_id)
    _insert_character(test_db, peer_id, room_id)
    test_db.execute(
        "UPDATE characters SET player_name = '安' WHERE character_id = %s",
        (character_id,),
    )
    test_db.execute(
        "UPDATE characters SET player_name = '安娜' WHERE character_id = %s",
        (peer_id,),
    )
    test_db.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs) "
        "VALUES ('overlap-name-archive', %s, 'mixed', %s, %s, %s)",
        (
            room_id,
            "战役结束。角色 安、安娜 参与，共经历 3 个事件。",
            json.dumps(["安娜守住了入口。", "安 独自检查了门。"], ensure_ascii=False),
            json.dumps([
                {"character_id": character_id, "player_name": "安", "total_actions": 2},
                {"character_id": peer_id, "player_name": "安娜", "total_actions": 1},
            ], ensure_ascii=False),
        ),
    )
    test_db.commit()

    response = client.delete(
        f"/api/admin/accounts/{account_id}",
        headers=_admin_headers(client),
    )

    assert response.status_code == 200, response.text
    archive = test_db.execute(
        "SELECT summary, highlights, character_arcs FROM campaign_archives "
        "WHERE archive_id = 'overlap-name-archive'"
    ).fetchone()
    assert "安娜" in archive["summary"]
    assert "已删除玩家娜" not in archive["summary"]
    assert "角色 安、" not in archive["summary"]
    peer_arc = next(
        arc for arc in archive["character_arcs"] if arc["character_id"] == peer_id
    )
    assert peer_arc["player_name"] == "安娜"


def test_full_archive_purge_requires_separate_double_confirmation_and_writes_minimal_audit(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    test_db.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs) "
        "VALUES ('purge-archive', 'deleted-room', 'mixed', '摘要', '[]', '[]')"
    )
    test_db.commit()
    headers = _admin_headers(client)

    missing_phrase = client.post(
        "/api/admin/campaign-archives/purge",
        headers=headers,
        json={
            "archive_ids": ["purge-archive"],
            "confirm": True,
            "reason": "用户申请彻底清除 purge-archive",
        },
    )

    assert missing_phrase.status_code == 400
    assert _count(
        test_db,
        "campaign_archives",
        "archive_id = %s",
        ("purge-archive",),
    ) == 1

    response = client.post(
        "/api/admin/campaign-archives/purge",
        headers=headers,
        json={
            "archive_ids": ["purge-archive"],
            "confirm": True,
            "purge_confirmation": "PURGE_ARCHIVES",
            "reason": "用户申请彻底清除 purge-archive",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["deleted_ids"] == ["purge-archive"]
    assert _count(
        test_db,
        "campaign_archives",
        "archive_id = %s",
        ("purge-archive",),
    ) == 0
    audit = test_db.execute(
        "SELECT action, target_count, details FROM admin_data_purge_audits "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert audit["action"] == "campaign_archive_full_purge"
    assert audit["target_count"] == 1
    assert "purge-archive" not in json.dumps(audit["details"], ensure_ascii=False)


def test_archive_purge_redacts_identifier_before_reason_truncation(client, test_db):
    setup_auth_test_data(test_db)
    archive_id = "SECRET-ARCHIVE-BOUNDARY"
    test_db.execute(
        "INSERT INTO campaign_archives "
        "(archive_id, room_id, ending_type, summary, highlights, character_arcs) "
        "VALUES (%s, 'deleted-room', 'mixed', '摘要', '[]', '[]')",
        (archive_id,),
    )
    test_db.commit()

    response = client.post(
        "/api/admin/campaign-archives/purge",
        headers=_admin_headers(client),
        json={
            "archive_ids": [archive_id],
            "confirm": True,
            "purge_confirmation": "PURGE_ARCHIVES",
            "reason": "x" * 497 + archive_id,
        },
    )

    assert response.status_code == 200, response.text
    reason = test_db.execute(
        "SELECT details->>'reason' AS reason FROM admin_data_purge_audits "
        "WHERE action = 'campaign_archive_full_purge' "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()["reason"]
    assert archive_id[:3] not in reason
    assert len(reason) <= 500


def test_batch_delete_scenarios_allows_partial_success_and_blocks_used_scenarios(client, test_db):
    setup_auth_test_data(test_db)
    create_scenario(test_db, "bulk-free-scenario", "可删除剧本")
    create_scenario(test_db, "bulk-used-scenario", "使用中剧本")
    _insert_room(test_db, "bulk-scenario-room", scenario_id="bulk-used-scenario")
    test_db.commit()

    response = client.post(
        "/api/admin/scenarios/batch-delete",
        headers=_admin_headers(client),
        json={
            "ids": ["bulk-free-scenario", "bulk-used-scenario", "scenario-missing"],
            "confirm": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deleted_ids"] == ["bulk-free-scenario"]
    assert payload["not_found_ids"] == ["scenario-missing"]
    errors = {item["id"]: item for item in payload["errors"]}
    assert errors["bulk-used-scenario"]["status"] == "409"
    assert _count(test_db, "scenarios", "scenario_id = %s", ("bulk-free-scenario",)) == 0
    assert _count(test_db, "scenarios", "scenario_id = %s", ("bulk-used-scenario",)) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/admin/rooms/batch-delete",
        "/api/admin/scenarios/batch-delete",
        "/api/admin/characters/batch-delete",
        "/api/admin/accounts/batch-delete",
    ],
)
def test_batch_delete_requires_admin_and_rejects_empty_ids(client, test_db, endpoint):
    setup_auth_test_data(test_db)

    forbidden = client.post(
        endpoint,
        headers={"Authorization": f"Bearer {login(client)}"},
        json={"ids": ["any-id"], "confirm": True},
    )
    invalid = client.post(
        endpoint,
        headers=_admin_headers(client),
        json={"ids": [], "confirm": True},
    )

    assert forbidden.status_code == 403
    assert invalid.status_code == 400


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/admin/rooms/batch-delete",
        "/api/admin/scenarios/batch-delete",
        "/api/admin/characters/batch-delete",
        "/api/admin/accounts/batch-delete",
    ],
)
@pytest.mark.parametrize("confirmation", [None, False])
def test_batch_delete_requires_explicit_backend_confirmation(
    client,
    test_db,
    endpoint,
    confirmation,
):
    setup_auth_test_data(test_db)
    payload = {"ids": ["any-id"]}
    if confirmation is not None:
        payload["confirm"] = confirmation

    response = client.post(
        endpoint,
        headers=_admin_headers(client),
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "请确认后再执行删除"
