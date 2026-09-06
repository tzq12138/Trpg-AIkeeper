import json
from types import SimpleNamespace

import pytest

from src.server.player import router_actions_v2
from src.server.player.router_player import (
    _block_collaboration_batch,
    _resolve_collaboration_batch_background,
    _settle_turn_background,
)
from tests.server.conftest import create_room, setup_auth_test_data


def _setup_contract_room(client, test_db, player_count=3):
    setup_auth_test_data(test_db)
    room = create_room(client)
    players = [
        client.post(f"/api/player/rooms/{room['room_id']}/join").json()
        for _ in range(player_count)
    ]
    return room, players


def _bind_ai_only_runtime(test_db, room_id: str) -> None:
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    package_id = f"collaboration-ai-only-{room_id}"
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) VALUES "
        "(%s, %s, 99, 'ready', %s, %s, 'test')",
        (
            package_id,
            scenario_version_id,
            package_id,
            json.dumps({"runtime_policy": {"session_mode": "ai_only"}}),
        ),
    )
    test_db.execute(
        "UPDATE rooms SET runtime_package_version_id = %s WHERE room_id = %s",
        (package_id, room_id),
    )


def test_ai_only_collaboration_infrastructure_failure_pauses_without_host_queue(
    client,
    test_db,
):
    room, players = _setup_contract_room(client, test_db, player_count=1)
    room_id = room["room_id"]
    character_id = players[0]["character_id"]
    _bind_ai_only_runtime(test_db, room_id)
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, status, expires_at) "
        "VALUES ('ai-only-block-contract', %s, %s, '一起调查', 'accepted', "
        "NOW() + INTERVAL '10 minutes')",
        (room_id, character_id),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_batches "
        "(contract_id, room_id, action_ids, status) VALUES "
        "('ai-only-block-contract', %s, '[\"ai-only-block-action\"]', 'resolving')",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('ai-only-block-action', %s, %s, 'dialogue', '一起调查', 'batched')",
        (room_id, character_id),
    )
    test_db.commit()

    _block_collaboration_batch(
        test_db,
        "ai-only-block-contract",
        ["ai-only-block-action"],
        "resolution_pipeline_unavailable",
    )

    # R1/R7A migration (04 §6): an ai_only integrity pause PRESERVES the
    # in-flight batch action (verified recovery resumes it later) instead of
    # terminating it as rejected.
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'ai-only-block-action'"
    ).fetchone()["status"] == "batched"
    assert test_db.execute(
        "SELECT status, integrity_reason FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone() == {
        "status": "paused",
        "integrity_reason": "resolution_pipeline_unavailable",
    }
    assert test_db.execute(
        "SELECT 1 FROM action_status_events "
        "WHERE action_id = 'ai-only-block-action' "
        "AND status = 'awaiting_host_exception'"
    ).fetchone() is None
    assert test_db.execute(
        "SELECT event_type FROM events WHERE room_id = %s "
        "AND event_type = 's2c_room_paused'",
        (room_id,),
    ).fetchone() is not None


def test_collaboration_contract_creates_linked_confirmation_drafts_only_after_all_accept(
    client,
    test_db,
):
    room, players = _setup_contract_room(client, test_db)
    initiator, first_invitee, second_invitee = players

    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "我负责撬锁，请你们一起警戒并掩护。",
            "inviteeCharacterIds": [
                first_invitee["character_id"],
                second_invitee["character_id"],
            ],
        },
    )

    assert created.status_code == 201, created.text
    contract = created.json()
    assert contract["status"] == "pending"
    assert contract["pendingCharacterIds"] == [
        first_invitee["character_id"],
        second_invitee["character_id"],
    ]
    assert contract["linkedDrafts"] == []

    first_acceptance = client.post(
        f"/api/player/collaboration-contracts/{contract['contractId']}/responses",
        headers={"X-Room-Token": first_invitee["player_token"]},
        json={"decision": "accept"},
    )

    assert first_acceptance.status_code == 200, first_acceptance.text
    assert first_acceptance.json()["status"] == "pending"
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0

    second_acceptance = client.post(
        f"/api/player/collaboration-contracts/{contract['contractId']}/responses",
        headers={"X-Room-Token": second_invitee["player_token"]},
        json={"decision": "accept"},
    )

    assert second_acceptance.status_code == 200, second_acceptance.text
    accepted = second_acceptance.json()
    assert accepted["status"] == "accepted"
    assert {draft["characterId"] for draft in accepted["linkedDrafts"]} == {
        initiator["character_id"],
        first_invitee["character_id"],
        second_invitee["character_id"],
    }
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0
    drafts = test_db.execute(
        "SELECT character_id, status, params FROM action_drafts ORDER BY character_id"
    ).fetchall()
    assert len(drafts) == 3
    assert all(row["status"] == "awaiting_confirmation" for row in drafts)
    assert all(row["params"]["collaborationContractId"] == contract["contractId"] for row in drafts)


def test_collaboration_actions_wait_for_every_participant_before_creating_one_batch(
    client,
    test_db,
    monkeypatch,
):
    _room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    scheduled_batches = []
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_collaboration_batch_resolution",
        lambda app, conn, batch_contract_id: scheduled_batches.append(batch_contract_id),
        raising=False,
    )
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "我撬开侧门，请你警戒走廊。",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    )
    assert created.status_code == 201, created.text
    contract_id = created.json()["contractId"]
    accepted = client.post(
        f"/api/player/collaboration-contracts/{contract_id}/responses",
        headers={"X-Room-Token": invitee["player_token"]},
        json={"decision": "accept"},
    )
    assert accepted.status_code == 200, accepted.text

    first_draft = client.get(
        "/api/player/action-drafts/current",
        headers={"X-Room-Token": initiator["player_token"]},
    ).json()
    first_confirmation = client.post(
        f"/api/player/action-drafts/{first_draft['draft_id']}/confirm",
        headers={"X-Room-Token": initiator["player_token"], "Idempotency-Key": "contract-first"},
        json={"confirmations": first_draft["confirmation_requirements"]},
    )

    assert first_confirmation.status_code == 200, first_confirmation.text
    assert first_confirmation.json()["status"] == "batched"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["count"] == 0
    assert scheduled_batches == []

    second_draft = client.get(
        "/api/player/action-drafts/current",
        headers={"X-Room-Token": invitee["player_token"]},
    ).json()
    second_confirmation = client.post(
        f"/api/player/action-drafts/{second_draft['draft_id']}/confirm",
        headers={"X-Room-Token": invitee["player_token"], "Idempotency-Key": "contract-second"},
        json={"confirmations": second_draft["confirmation_requirements"]},
    )

    assert second_confirmation.status_code == 200, second_confirmation.text
    assert second_confirmation.json()["status"] == "batched"
    batch = test_db.execute(
        "SELECT status, action_ids FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()
    assert batch["status"] == "queued"
    assert set(batch["action_ids"]) == {
        first_confirmation.json()["action_id"],
        second_confirmation.json()["action_id"],
    }
    assert scheduled_batches == [contract_id]


def test_collaboration_batch_uses_contract_participant_order(
    client,
    test_db,
    monkeypatch,
):
    _room, players = _setup_contract_room(client, test_db, player_count=3)
    initiator, first_invitee, second_invitee = players
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_collaboration_batch_resolution",
        lambda *_: None,
    )
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "我先打开暗门，你们分别掩护和观察。",
            "inviteeCharacterIds": [
                first_invitee["character_id"],
                second_invitee["character_id"],
            ],
        },
    )
    contract_id = created.json()["contractId"]
    for player in (first_invitee, second_invitee):
        accepted = client.post(
            f"/api/player/collaboration-contracts/{contract_id}/responses",
            headers={"X-Room-Token": player["player_token"]},
            json={"decision": "accept"},
        )
        assert accepted.status_code == 200, accepted.text

    participant_ids = sorted(
        player["character_id"] for player in (initiator, first_invitee, second_invitee)
    )
    expected_character_order = list(reversed(participant_ids))
    for invite_order, character_id in enumerate(expected_character_order):
        test_db.execute(
            "UPDATE collaboration_contract_participants SET invite_order = %s "
            "WHERE contract_id = %s AND character_id = %s",
            (invite_order, contract_id, character_id),
        )

    action_by_character = {}
    for index, player in enumerate((second_invitee, initiator, first_invitee), start=1):
        draft = client.get(
            "/api/player/action-drafts/current",
            headers={"X-Room-Token": player["player_token"]},
        ).json()
        confirmed = client.post(
            f"/api/player/action-drafts/{draft['draft_id']}/confirm",
            headers={"X-Room-Token": player["player_token"], "Idempotency-Key": f"ordered-{index}"},
            json={"confirmations": draft["confirmation_requirements"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        action_by_character[player["character_id"]] = confirmed.json()["action_id"]

    batch = test_db.execute(
        "SELECT action_ids FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()
    assert batch["action_ids"] == [
        action_by_character[character_id] for character_id in expected_character_order
    ]


def test_collaboration_dependency_is_preserved_validated_and_orders_the_batch(
    client,
    test_db,
    monkeypatch,
):
    _room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_collaboration_batch_resolution",
        lambda *_: None,
    )
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "You open the hatch, then I cover the corridor.",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    )
    contract_id = created.json()["contractId"]
    accepted = client.post(
        f"/api/player/collaboration-contracts/{contract_id}/responses",
        headers={"X-Room-Token": invitee["player_token"]},
        json={"decision": "accept"},
    )
    assert accepted.status_code == 200, accepted.text

    initiator_draft = client.get(
        "/api/player/action-drafts/current",
        headers={"X-Room-Token": initiator["player_token"]},
    ).json()
    revised = client.patch(
        f"/api/player/action-drafts/{initiator_draft['draft_id']}",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "declared_intent": "I cover the corridor after the hatch opens.",
            "base_state_version": initiator_draft["base_state_version"],
            "params": {"dependsOnCharacterIds": [invitee["character_id"]]},
        },
    )
    assert revised.status_code == 200, revised.text
    revised_payload = revised.json()
    assert revised_payload["risk"] == "high"
    assert revised_payload["visibility"] == "party"
    assert revised_payload["params"] == {
        "collaborationContractId": contract_id,
        "dependsOnCharacterIds": [invitee["character_id"]],
    }

    invitee_draft = client.get(
        "/api/player/action-drafts/current",
        headers={"X-Room-Token": invitee["player_token"]},
    ).json()
    cyclic = client.patch(
        f"/api/player/action-drafts/{invitee_draft['draft_id']}",
        headers={"X-Room-Token": invitee["player_token"]},
        json={
            "declared_intent": "I open the hatch after cover is ready.",
            "base_state_version": invitee_draft["base_state_version"],
            "params": {"dependsOnCharacterIds": [initiator["character_id"]]},
        },
    )
    assert cyclic.status_code == 409, cyclic.text
    assert cyclic.json()["detail"]["code"] == "collaboration_dependency_cycle"

    invitee_confirmed = client.post(
        f"/api/player/action-drafts/{invitee_draft['draft_id']}/confirm",
        headers={"X-Room-Token": invitee["player_token"], "Idempotency-Key": "depends-invitee"},
        json={"confirmations": invitee_draft["confirmation_requirements"]},
    )
    initiator_confirmed = client.post(
        f"/api/player/action-drafts/{initiator_draft['draft_id']}/confirm",
        headers={"X-Room-Token": initiator["player_token"], "Idempotency-Key": "depends-initiator"},
        json={"confirmations": revised_payload["confirmation_requirements"]},
    )
    assert invitee_confirmed.status_code == 200, invitee_confirmed.text
    assert initiator_confirmed.status_code == 200, initiator_confirmed.text
    batch = test_db.execute(
        "SELECT action_ids FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()
    assert batch["action_ids"] == [
        invitee_confirmed.json()["action_id"],
        initiator_confirmed.json()["action_id"],
    ]


def test_combat_collaboration_batch_defers_to_turn_scheduler(test_db, monkeypatch):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('contract-combat-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('contract-combat-character', 'contract-combat-room', 'Player', 'token', 'ready')"
    )
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, status, expires_at) "
        "VALUES ('contract-combat', 'contract-combat-room', 'contract-combat-character', "
        "'Hold the line together.', 'accepted', NOW() + INTERVAL '10 minutes')"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode) "
        "VALUES ('contract-combat-turn', 'contract-combat-room', 1, 'collecting', 'combat')"
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, turn_id, intent_type, declared_intent, status) "
        "VALUES ('contract-combat-action', 'contract-combat-room', 'contract-combat-character', "
        "'contract-combat-turn', 'combat_action', 'Hold position.', 'batched')"
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_batches (contract_id, room_id, action_ids) "
        "VALUES ('contract-combat', 'contract-combat-room', %s)",
        (json.dumps(['contract-combat-action']),),
    )
    test_db.commit()

    scheduled_action_ids = []
    background_jobs = []
    monkeypatch.setattr(
        router_actions_v2,
        "_schedule_action_resolution",
        lambda _app, _conn, action_id: scheduled_action_ids.append(action_id),
    )

    def record_background_job(coroutine):
        coroutine.close()
        background_jobs.append(True)

    monkeypatch.setattr(router_actions_v2.asyncio, "create_task", record_background_job)
    app = SimpleNamespace(state=SimpleNamespace(pipeline=object(), pg_db=None))

    router_actions_v2._schedule_collaboration_batch_resolution(app, test_db, 'contract-combat')

    assert scheduled_action_ids == ['contract-combat-action']
    assert background_jobs == []


@pytest.mark.asyncio
async def test_collaboration_batch_worker_claims_once_and_resolves_confirmed_actions(
    client,
    test_db,
    monkeypatch,
):
    _room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_collaboration_batch_resolution",
        lambda *_: None,
    )
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "我撬开侧门，请你警戒走廊。",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    )
    contract_id = created.json()["contractId"]
    client.post(
        f"/api/player/collaboration-contracts/{contract_id}/responses",
        headers={"X-Room-Token": invitee["player_token"]},
        json={"decision": "accept"},
    )
    action_ids = []
    for index, player in enumerate((initiator, invitee), start=1):
        draft = client.get(
            "/api/player/action-drafts/current",
            headers={"X-Room-Token": player["player_token"]},
        ).json()
        confirmed = client.post(
            f"/api/player/action-drafts/{draft['draft_id']}/confirm",
            headers={"X-Room-Token": player["player_token"], "Idempotency-Key": f"worker-{index}"},
            json={"confirmations": draft["confirmation_requirements"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        action_ids.append(confirmed.json()["action_id"])

    class BatchPipeline:
        def __init__(self):
            self.action_ids = []

        async def resolve_action(self, action_id):
            self.action_ids.append(action_id)
            test_db.execute(
                "UPDATE actions SET status = 'completed' WHERE action_id = %s",
                (action_id,),
            )
            return {"status": "completed", "action_id": action_id}

    pipeline = BatchPipeline()
    monkeypatch.setattr(client.app.state, "pipeline", pipeline, raising=False)

    await _resolve_collaboration_batch_background(client.app, contract_id)
    await _resolve_collaboration_batch_background(client.app, contract_id)

    batch = test_db.execute(
        "SELECT status, action_ids FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()
    assert batch["status"] == "completed"
    assert test_db.execute(
        "SELECT status FROM collaboration_contracts WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "completed"
    listed = client.get(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
    )
    assert listed.status_code == 200, listed.text
    assert next(
        item for item in listed.json()["items"] if item["contractId"] == contract_id
    )["status"] == "completed"
    assert pipeline.action_ids == batch["action_ids"]
    assert set(pipeline.action_ids) == set(action_ids)


@pytest.mark.asyncio
async def test_collaboration_batch_worker_leaves_queued_batch_untouched_when_room_retires(
    client,
    test_db,
    monkeypatch,
):
    room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_collaboration_batch_resolution",
        lambda *_: None,
    )
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "一起调查走廊。",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    )
    contract_id = created.json()["contractId"]
    accepted = client.post(
        f"/api/player/collaboration-contracts/{contract_id}/responses",
        headers={"X-Room-Token": invitee["player_token"]},
        json={"decision": "accept"},
    )
    assert accepted.status_code == 200, accepted.text
    for index, player in enumerate((initiator, invitee), start=1):
        draft = client.get(
            "/api/player/action-drafts/current",
            headers={"X-Room-Token": player["player_token"]},
        ).json()
        confirmed = client.post(
            f"/api/player/action-drafts/{draft['draft_id']}/confirm",
            headers={"X-Room-Token": player["player_token"], "Idempotency-Key": f"retired-{index}"},
            json={"confirmations": draft["confirmation_requirements"]},
        )
        assert confirmed.status_code == 200, confirmed.text

    test_db.execute(
        "UPDATE rooms SET rule_source_status = 'rule_source_retired', "
        "rule_source_reason = 'local_test_rule_version' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    class FailingPipeline:
        async def resolve_action(self, _action_id):
            raise AssertionError("retired batch must not reach the pipeline")

    monkeypatch.setattr(client.app.state, "pipeline", FailingPipeline(), raising=False)
    await _resolve_collaboration_batch_background(client.app, contract_id)

    assert test_db.execute(
        "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "queued"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id IN ("
        "SELECT action_id FROM actions WHERE room_id = %s) "
        "ORDER BY action_id LIMIT 1",
        (room["room_id"],),
    ).fetchone()["status"] == "batched"


@pytest.mark.asyncio
async def test_collaboration_batch_stops_when_room_retires_after_last_action_resolution(
    client,
    test_db,
    monkeypatch,
):
    room, players = _setup_contract_room(client, test_db, player_count=1)
    player = players[0]
    room_id = room["room_id"]
    contract_id = "retired-after-resolution-contract"
    action_id = "retired-after-resolution-batch-action"
    draft_id = "retired-after-resolution-batch-draft"
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO action_drafts "
        "(draft_id, room_id, character_id, intent_type, declared_intent, params, status) "
        "VALUES (%s, %s, %s, 'dialogue', 'Wait.', '{}', 'confirmed')",
        (draft_id, room_id, player["character_id"]),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, draft_id, intent_type, declared_intent, status) "
        "VALUES (%s, %s, %s, %s, 'dialogue', 'Wait.', 'batched')",
        (action_id, room_id, player["character_id"], draft_id),
    )
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, status, expires_at) "
        "VALUES (%s, %s, %s, 'Wait.', 'accepted', NOW() + INTERVAL '10 minutes')",
        (contract_id, room_id, player["character_id"]),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_drafts (contract_id, character_id, draft_id) "
        "VALUES (%s, %s, %s)",
        (contract_id, player["character_id"], draft_id),
    )
    test_db.execute(
        "INSERT INTO collaboration_contract_batches (contract_id, room_id, action_ids) "
        "VALUES (%s, %s, %s)",
        (contract_id, room_id, json.dumps([action_id])),
    )
    test_db.commit()
    events_before = test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"]

    class RetiringPipeline:
        async def resolve_action(self, resolved_action_id):
            test_db.execute(
                "UPDATE actions SET status = 'completed' WHERE action_id = %s",
                (resolved_action_id,),
            )
            test_db.execute(
                "UPDATE rooms SET rule_source_status = 'rule_source_retired', "
                "rule_source_reason = 'local_test_rule_version' WHERE room_id = %s",
                (room_id,),
            )
            test_db.commit()
            return {"status": "completed", "action_id": resolved_action_id}

    monkeypatch.setattr(client.app.state, "pipeline", RetiringPipeline(), raising=False)
    await _resolve_collaboration_batch_background(client.app, contract_id)

    assert test_db.execute(
        "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "resolving"
    assert test_db.execute(
        "SELECT status FROM collaboration_contracts WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "accepted"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()["status"] == "completed"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == events_before


@pytest.mark.asyncio
async def test_collaboration_batch_stops_when_room_retires_between_actions(
    client,
    test_db,
    monkeypatch,
):
    room, players = _setup_contract_room(client, test_db, player_count=2)
    first_player, second_player = players
    room_id = room["room_id"]
    contract_id = "retired-between-batch-actions-contract"
    action_ids = [
        "retired-between-batch-actions-first",
        "retired-between-batch-actions-second",
    ]
    draft_ids = [
        "retired-between-batch-actions-first-draft",
        "retired-between-batch-actions-second-draft",
    ]
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, status, expires_at) "
        "VALUES (%s, %s, %s, 'Wait.', 'accepted', NOW() + INTERVAL '10 minutes')",
        (contract_id, room_id, first_player["character_id"]),
    )
    for action_id, draft_id, player in zip(action_ids, draft_ids, players):
        test_db.execute(
            "INSERT INTO action_drafts "
            "(draft_id, room_id, character_id, intent_type, declared_intent, params, status) "
            "VALUES (%s, %s, %s, 'dialogue', 'Wait.', '{}', 'confirmed')",
            (draft_id, room_id, player["character_id"]),
        )
        test_db.execute(
            "INSERT INTO actions "
            "(action_id, room_id, character_id, draft_id, intent_type, declared_intent, status) "
            "VALUES (%s, %s, %s, %s, 'dialogue', 'Wait.', 'batched')",
            (action_id, room_id, player["character_id"], draft_id),
        )
        test_db.execute(
            "INSERT INTO collaboration_contract_drafts (contract_id, character_id, draft_id) "
            "VALUES (%s, %s, %s)",
            (contract_id, player["character_id"], draft_id),
        )
    test_db.execute(
        "INSERT INTO collaboration_contract_batches (contract_id, room_id, action_ids) "
        "VALUES (%s, %s, %s)",
        (contract_id, room_id, json.dumps(action_ids)),
    )
    test_db.commit()
    events_before = test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"]

    class RetiringBetweenActionsPipeline:
        def __init__(self):
            self.calls = []

        async def resolve_action(self, action_id):
            self.calls.append(action_id)
            if action_id == action_ids[0]:
                test_db.execute(
                    "UPDATE actions SET status = 'completed' WHERE action_id = %s",
                    (action_id,),
                )
                test_db.execute(
                    "UPDATE rooms SET rule_source_status = 'rule_source_retired', "
                    "rule_source_reason = 'local_test_rule_version' WHERE room_id = %s",
                    (room_id,),
                )
                test_db.commit()
                return {"status": "completed", "action_id": action_id}
            from src.server.rule_source_lifecycle import RuleSourceRetiredError

            raise RuleSourceRetiredError("local_test_rule_version")

    pipeline = RetiringBetweenActionsPipeline()
    monkeypatch.setattr(client.app.state, "pipeline", pipeline, raising=False)
    await _resolve_collaboration_batch_background(client.app, contract_id)

    assert pipeline.calls == action_ids
    assert test_db.execute(
        "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "resolving"
    assert test_db.execute(
        "SELECT status FROM collaboration_contracts WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "accepted"
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_ids[1],),
    ).fetchone()["status"] == "batched"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM events WHERE room_id = %s",
        (room_id,),
    ).fetchone()["count"] == events_before


@pytest.mark.asyncio
async def test_collaboration_dependency_failure_blocks_the_dependent_action(
    client,
    test_db,
    monkeypatch,
):
    _room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_collaboration_batch_resolution",
        lambda *_: None,
    )
    contract_id = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "Open the hatch before covering the corridor.",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    ).json()["contractId"]
    client.post(
        f"/api/player/collaboration-contracts/{contract_id}/responses",
        headers={"X-Room-Token": invitee["player_token"]},
        json={"decision": "accept"},
    )
    initiator_draft = client.get(
        "/api/player/action-drafts/current",
        headers={"X-Room-Token": initiator["player_token"]},
    ).json()
    revised = client.patch(
        f"/api/player/action-drafts/{initiator_draft['draft_id']}",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "declared_intent": "I cover the corridor after the hatch opens.",
            "base_state_version": initiator_draft["base_state_version"],
            "params": {"dependsOnCharacterIds": [invitee["character_id"]]},
        },
    )
    assert revised.status_code == 200, revised.text
    invitee_draft = client.get(
        "/api/player/action-drafts/current",
        headers={"X-Room-Token": invitee["player_token"]},
    ).json()
    invitee_action = client.post(
        f"/api/player/action-drafts/{invitee_draft['draft_id']}/confirm",
        headers={"X-Room-Token": invitee["player_token"], "Idempotency-Key": "failure-invitee"},
        json={"confirmations": invitee_draft["confirmation_requirements"]},
    ).json()["action_id"]
    initiator_action = client.post(
        f"/api/player/action-drafts/{initiator_draft['draft_id']}/confirm",
        headers={"X-Room-Token": initiator["player_token"], "Idempotency-Key": "failure-initiator"},
        json={"confirmations": revised.json()["confirmation_requirements"]},
    ).json()["action_id"]

    class RejectingPipeline:
        def __init__(self):
            self.action_ids = []

        async def resolve_action(self, action_id):
            self.action_ids.append(action_id)
            test_db.execute("UPDATE actions SET status = 'rejected' WHERE action_id = %s", (action_id,))
            return {"status": "rejected", "action_id": action_id}

    pipeline = RejectingPipeline()
    monkeypatch.setattr(client.app.state, "pipeline", pipeline, raising=False)

    await _resolve_collaboration_batch_background(client.app, contract_id)

    assert pipeline.action_ids == [invitee_action]
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s", (initiator_action,)
    ).fetchone()["status"] == "awaiting_host_exception"
    assert test_db.execute(
        "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s", (contract_id,)
    ).fetchone()["status"] == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ai_only", "dependent_status"),
    ((False, "awaiting_host_exception"), (True, "rejected")),
)
async def test_combat_dependency_failure_blocks_only_the_dependent_declaration(
    client,
    test_db,
    ai_only,
    dependent_status,
):
    room, players = _setup_contract_room(client, test_db, player_count=2)
    prerequisite_player, dependent_player = players
    room_id = room["room_id"]
    if ai_only:
        _bind_ai_only_runtime(test_db, room_id)
    contract_id = "combat-dependency-contract"
    turn_id = "combat-dependency-turn"
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('combat-dependency-encounter', %s, 'combat', 'active', 1)",
        (room_id,),
    )
    for player, dexterity in ((prerequisite_player, 20), (dependent_player, 90)):
        test_db.execute(
            "INSERT INTO encounter_participants (encounter_id, character_id, dex) "
            "VALUES ('combat-dependency-encounter', %s, %s)",
            (player["character_id"], dexterity),
        )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id) "
        "VALUES (%s, %s, 1, 'collecting', 'combat', 'combat-dependency-encounter')",
        (turn_id, room_id),
    )
    test_db.execute(
        "INSERT INTO collaboration_contracts "
        "(contract_id, room_id, initiator_character_id, shared_intent, status, expires_at) "
        "VALUES (%s, %s, %s, 'Open first, cover second.', 'accepted', NOW() + INTERVAL '10 minutes')",
        (contract_id, room_id, prerequisite_player["character_id"]),
    )
    action_specs = [
        ("combat-prerequisite", prerequisite_player["character_id"], "combat-prerequisite-draft", {}, 0),
        (
            "combat-dependent",
            dependent_player["character_id"],
            "combat-dependent-draft",
            {"depends_on_action_ids": ["combat-prerequisite"]},
            1,
        ),
    ]
    for action_id, character_id, draft_id, params, invite_order in action_specs:
        test_db.execute(
            "INSERT INTO action_drafts (draft_id, room_id, character_id, intent_type, declared_intent, params, status) "
            "VALUES (%s, %s, %s, 'combat_action', 'Declared combat action.', %s, 'confirmed')",
            (draft_id, room_id, character_id, json.dumps(params)),
        )
        test_db.execute(
            "INSERT INTO collaboration_contract_participants "
            "(contract_id, character_id, role, invite_order, decision) VALUES (%s, %s, %s, %s, 'accepted')",
            (contract_id, character_id, 'initiator' if invite_order == 0 else 'invitee', invite_order),
        )
        test_db.execute(
            "INSERT INTO collaboration_contract_drafts (contract_id, character_id, draft_id) VALUES (%s, %s, %s)",
            (contract_id, character_id, draft_id),
        )
        test_db.execute(
            "INSERT INTO actions "
            "(action_id, room_id, character_id, draft_id, turn_id, intent_type, declared_intent, params, status) "
            "VALUES (%s, %s, %s, %s, %s, 'combat_action', 'Declared combat action.', %s, 'batched')",
            (action_id, room_id, character_id, draft_id, turn_id, json.dumps(params)),
        )
    test_db.execute(
        "INSERT INTO collaboration_contract_batches (contract_id, room_id, action_ids) VALUES (%s, %s, %s)",
        (contract_id, room_id, json.dumps(["combat-prerequisite", "combat-dependent"])),
    )
    test_db.commit()

    class RejectingPipeline:
        def __init__(self):
            self.action_ids = []

        async def resolve_action(self, action_id):
            self.action_ids.append(action_id)
            test_db.execute("UPDATE actions SET status = 'rejected' WHERE action_id = %s", (action_id,))
            return {"status": "rejected", "action_id": action_id}

    pipeline = RejectingPipeline()
    app = SimpleNamespace(
        state=SimpleNamespace(db=test_db, pg_db=None, pipeline=pipeline, dispatcher=None),
    )

    await _settle_turn_background(app, room_id, turn_id)

    assert pipeline.action_ids == ["combat-prerequisite"]
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'combat-dependent'"
    ).fetchone()["status"] == dependent_status
    assert test_db.execute(
        "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s", (contract_id,)
    ).fetchone()["status"] == "blocked"


def test_canceling_a_batched_collaboration_action_cancels_the_whole_batch(
    client,
    test_db,
    monkeypatch,
):
    _room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    monkeypatch.setattr(
        "src.server.player.router_actions_v2._schedule_collaboration_batch_resolution",
        lambda *_: None,
    )
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "我撬开侧门，请你警戒走廊。",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    )
    contract_id = created.json()["contractId"]
    client.post(
        f"/api/player/collaboration-contracts/{contract_id}/responses",
        headers={"X-Room-Token": invitee["player_token"]},
        json={"decision": "accept"},
    )
    actions = []
    for index, player in enumerate((initiator, invitee), start=1):
        draft = client.get(
            "/api/player/action-drafts/current",
            headers={"X-Room-Token": player["player_token"]},
        ).json()
        confirmed = client.post(
            f"/api/player/action-drafts/{draft['draft_id']}/confirm",
            headers={"X-Room-Token": player["player_token"], "Idempotency-Key": f"cancel-{index}"},
            json={"confirmations": draft["confirmation_requirements"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        actions.append(confirmed.json()["action_id"])

    canceled = client.post(
        f"/api/player/actions/{actions[0]}/cancel",
        headers={"X-Room-Token": initiator["player_token"]},
    )

    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled"
    assert test_db.execute(
        "SELECT status FROM collaboration_contracts WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "canceled"
    assert test_db.execute(
        "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "canceled"
    states = test_db.execute(
        "SELECT action_id, status FROM actions WHERE action_id = ANY(%s) ORDER BY action_id",
        (actions,),
    ).fetchall()
    assert {row["status"] for row in states} == {"canceled"}


def test_collaboration_contract_rejection_or_expiry_cancels_without_creating_drafts(client, test_db):
    _room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "我引开守卫，你从侧门进入。",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    )
    assert created.status_code == 201, created.text

    declined = client.post(
        f"/api/player/collaboration-contracts/{created.json()['contractId']}/responses",
        headers={"X-Room-Token": invitee["player_token"]},
        json={"decision": "decline"},
    )

    assert declined.status_code == 200, declined.text
    assert declined.json()["status"] == "canceled"
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0


def test_collaboration_contract_initiator_can_cancel_before_all_invitees_accept(client, test_db):
    _room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "我检查书桌，请你留意窗外。",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    )
    assert created.status_code == 201, created.text

    canceled = client.post(
        f"/api/player/collaboration-contracts/{created.json()['contractId']}/cancel",
        headers={"X-Room-Token": initiator["player_token"]},
    )

    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled"
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0


def test_collaboration_contract_cancels_if_an_invitee_gains_an_active_draft_before_accepting(
    client,
    test_db,
):
    room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "我拖住守卫，请你检查档案柜。",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    )
    assert created.status_code == 201, created.text
    contract_id = created.json()["contractId"]
    test_db.execute(
        "INSERT INTO action_drafts "
        "(draft_id, room_id, character_id, intent_type, declared_intent, status, expires_at) "
        "VALUES (%s, %s, %s, 'action', '已有行动预览', 'awaiting_confirmation', NOW() + INTERVAL '1 day')",
        ("draft-before-contract-accept", room["room_id"], invitee["character_id"]),
    )
    test_db.commit()

    response = client.post(
        f"/api/player/collaboration-contracts/{contract_id}/responses",
        headers={"X-Room-Token": invitee["player_token"]},
        json={"decision": "accept"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "collaboration_action_conflict"
    assert test_db.execute(
        "SELECT status FROM collaboration_contracts WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "canceled"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM collaboration_contract_drafts WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["count"] == 0


def test_collaboration_contract_expiry_is_persisted_before_an_invitee_can_accept(client, test_db):
    _room, players = _setup_contract_room(client, test_db, player_count=2)
    initiator, invitee = players
    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": "我在门口制造响动，你趁机翻找抽屉。",
            "inviteeCharacterIds": [invitee["character_id"]],
        },
    )
    contract_id = created.json()["contractId"]
    test_db.execute(
        "UPDATE collaboration_contracts SET expires_at = NOW() - INTERVAL '1 second' "
        "WHERE contract_id = %s",
        (contract_id,),
    )
    test_db.commit()

    expired = client.post(
        f"/api/player/collaboration-contracts/{contract_id}/responses",
        headers={"X-Room-Token": invitee["player_token"]},
        json={"decision": "accept"},
    )

    assert expired.status_code == 409
    assert expired.json()["detail"]["code"] == "collaboration_contract_expired"
    assert test_db.execute(
        "SELECT status FROM collaboration_contracts WHERE contract_id = %s",
        (contract_id,),
    ).fetchone()["status"] == "expired"
    assert test_db.execute("SELECT COUNT(*) AS count FROM action_drafts").fetchone()["count"] == 0


def test_collaboration_participant_projection_is_limited_to_the_current_room(client, test_db):
    room, players = _setup_contract_room(client, test_db, player_count=2)
    outsider_room, outsider_players = _setup_contract_room(client, test_db, player_count=1)
    assert outsider_room["room_id"] != room["room_id"]

    response = client.get(
        "/api/player/collaboration-contracts/participants",
        headers={"X-Room-Token": players[0]["player_token"]},
    )

    assert response.status_code == 200, response.text
    assert {item["characterId"] for item in response.json()["items"]} == {
        players[0]["character_id"],
        players[1]["character_id"],
    }
    assert outsider_players[0]["character_id"] not in response.text
    assert "playerToken" not in response.text


def test_four_player_contract_keeps_shared_intent_out_of_stage(
    client,
    test_db,
):
    room, players = _setup_contract_room(client, test_db, player_count=4)
    initiator, second_player, third_player, fourth_player = players
    shared_intent = "我撬开侧门；其余三人分别警戒、照明并留意后方。"

    created = client.post(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": initiator["player_token"]},
        json={
            "sharedIntent": shared_intent,
            "inviteeCharacterIds": [
                second_player["character_id"],
                third_player["character_id"],
            ],
        },
    )

    assert created.status_code == 201, created.text
    contract_id = created.json()["contractId"]
    stage_before = client.get(
        f"/api/host/{room['room_id']}/stage-projection",
        headers={"X-Owner-Token": room["owner_token"]},
    )
    assert stage_before.status_code == 200, stage_before.text
    assert shared_intent not in stage_before.text
    assert contract_id not in stage_before.text

    for invitee in (second_player, third_player):
        response = client.post(
            f"/api/player/collaboration-contracts/{contract_id}/responses",
            headers={"X-Room-Token": invitee["player_token"]},
            json={"decision": "accept"},
        )
        assert response.status_code == 200, response.text

    for player in (initiator, second_player, third_player):
        draft = client.get(
            "/api/player/action-drafts/current",
            headers={"X-Room-Token": player["player_token"]},
        )
        assert draft.status_code == 200, draft.text
        assert draft.json()["status"] == "awaiting_confirmation"
        assert draft.json()["params"]["collaborationContractId"] == contract_id

    uninvolved_contracts = client.get(
        "/api/player/collaboration-contracts",
        headers={"X-Room-Token": fourth_player["player_token"]},
    )
    assert uninvolved_contracts.status_code == 200, uninvolved_contracts.text
    assert uninvolved_contracts.json()["items"] == []
    uninvolved_draft = client.get(
        "/api/player/action-drafts/current",
        headers={"X-Room-Token": fourth_player["player_token"]},
    )
    assert uninvolved_draft.status_code == 200, uninvolved_draft.text
    assert uninvolved_draft.json() is None

    stage_after = client.get(
        f"/api/host/{room['room_id']}/stage-projection",
        headers={"X-Owner-Token": room["owner_token"]},
    )
    assert stage_after.status_code == 200, stage_after.text
    assert shared_intent not in stage_after.text
    assert contract_id not in stage_after.text
    assert test_db.execute("SELECT COUNT(*) AS count FROM actions").fetchone()["count"] == 0
