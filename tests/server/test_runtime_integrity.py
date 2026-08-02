import hashlib
import json

import pytest

from src.server.engine.runtime_integrity import (
    CheckpointIntegrityError,
    canonical_json_bytes,
    checkpoint_snapshot_hash,
    validate_runtime_snapshot,
)
from src.server.events.event_log import EventLog
from tests.server.conftest import create_room, setup_auth_test_data


def _seed_runtime_room(conn):
    conn.execute(
        "INSERT INTO accounts (account_id, username, password_hash, role) "
        "VALUES ('checkpoint-account', 'checkpoint-user', 'hash', 'player')"
    )
    conn.execute(
        "INSERT INTO rooms "
        "(room_id, owner_token, owner_account_id, status, state_version, risk_contract) "
        "VALUES ('integrity-room', 'owner-secret', 'checkpoint-account', 'active', 7, %s)",
        (json.dumps({"rawSafetyBoundaryText": "private boundary"}),),
    )
    conn.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, account_id, status, is_ready, xlsx_data) "
        "VALUES ('integrity-char', 'integrity-room', 'Alice', 'player-secret', "
        "'checkpoint-account', 'joined', TRUE, %s)",
        (json.dumps({"name": "Investigator", "unrevealedSecret": "do not snapshot"}),),
    )
    conn.execute(
        "INSERT INTO character_runtime_state "
        "(character_id, room_id, hp, hp_max, san, san_max, mp, mp_max, luck, version) "
        "VALUES ('integrity-char', 'integrity-room', 9, 10, 45, 50, 8, 10, 40, 2)"
    )
    conn.execute(
        "INSERT INTO room_scene_state "
        "(room_id, current_scene, visited_scenes, scene_variables, version) "
        "VALUES ('integrity-room', 'archive', '[\"lobby\", \"archive\"]', %s, 3)",
        (json.dumps({"door": "open", "player_token": "nested-secret"}),),
    )
    conn.commit()


def test_canonical_json_hash_matches_independent_fixture():
    payload = {"b": 2, "a": {"text": "规则", "enabled": True}}
    expected_bytes = '{"a":{"enabled":true,"text":"规则"},"b":2}'.encode("utf-8")

    assert canonical_json_bytes(payload) == expected_bytes
    assert checkpoint_snapshot_hash(payload) == hashlib.sha256(expected_bytes).hexdigest()


def test_event_binds_action_committed_state_version_and_payload_hash(test_db):
    _seed_runtime_room(test_db)
    payload = {"stateVersion": 8, "actionId": "action-verified", "patch": {"hp": 8}}

    sequence = EventLog(test_db).log_event(
        "integrity-room",
        "s2c_state_patch",
        "party",
        payload,
    )

    row = test_db.execute(
        "SELECT action_id, state_version, payload_hash FROM events WHERE sequence = %s",
        (sequence,),
    ).fetchone()
    assert row == {
        "action_id": "action-verified",
        "state_version": 8,
        "payload_hash": checkpoint_snapshot_hash(payload),
    }


def test_checkpoint_backfills_integrity_metadata_for_legacy_event_writers(test_db):
    _seed_runtime_room(test_db)
    payload = {"actionId": "legacy-action", "text": "legacy writer"}
    sequence = test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) "
        "VALUES ('integrity-room', 'legacy_event', 'system', %s) RETURNING sequence",
        (json.dumps(payload),),
    ).fetchone()["sequence"]

    EventLog(test_db).create_checkpoint("integrity-room", "legacy-event-cp")

    row = test_db.execute(
        "SELECT action_id, state_version, payload_hash FROM events WHERE sequence = %s",
        (sequence,),
    ).fetchone()
    assert row == {
        "action_id": "legacy-action",
        "state_version": 7,
        "payload_hash": checkpoint_snapshot_hash(payload),
    }


def test_checkpoint_binds_boundary_and_omits_credentials_and_raw_secrets(test_db):
    _seed_runtime_room(test_db)
    event_log = EventLog(test_db)
    event_log.log_event(
        "integrity-room",
        "s2c_public_observation",
        "party",
        {"text": "public fact"},
    )

    checkpoint = event_log.create_checkpoint("integrity-room", "verified-cp")
    row = test_db.execute(
        "SELECT schema_version, state_version, event_sequence, snapshot_sha256, "
        "invariant_report, verification_status FROM checkpoints WHERE checkpoint_id = 'verified-cp'"
    ).fetchone()
    serialized = json.dumps(checkpoint.state_snapshot, ensure_ascii=False)

    assert row["schema_version"] == 2
    assert row["state_version"] == 7
    assert row["event_sequence"] >= 1
    assert row["snapshot_sha256"] == checkpoint_snapshot_hash(checkpoint.state_snapshot)
    assert row["verification_status"] == "verified"
    assert row["invariant_report"]["valid"] is True
    assert checkpoint.snapshot_sha256 == row["snapshot_sha256"]
    assert checkpoint.event_sequence == row["event_sequence"]
    for secret in (
        "owner-secret",
        "player-secret",
        "checkpoint-account",
        "private boundary",
        "do not snapshot",
        "nested-secret",
    ):
        assert secret not in serialized


def test_tampered_checkpoint_is_rejected_and_live_state_is_preserved(test_db):
    _seed_runtime_room(test_db)
    event_log = EventLog(test_db)
    event_log.create_checkpoint("integrity-room", "tampered-cp")
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'live-scene', version = 4 "
        "WHERE room_id = 'integrity-room'"
    )
    checkpoint_row = test_db.execute(
        "SELECT state_snapshot FROM checkpoints WHERE checkpoint_id = 'tampered-cp'"
    ).fetchone()
    snapshot = dict(checkpoint_row["state_snapshot"])
    snapshot["room_scene_state"][0]["current_scene"] = "forged-scene"
    test_db.execute(
        "UPDATE checkpoints SET state_snapshot = %s WHERE checkpoint_id = 'tampered-cp'",
        (json.dumps(snapshot),),
    )
    test_db.commit()

    with pytest.raises(CheckpointIntegrityError, match="hash"):
        event_log.restore_checkpoint("integrity-room", "tampered-cp")

    assert test_db.execute(
        "SELECT current_scene FROM room_scene_state WHERE room_id = 'integrity-room'"
    ).fetchone()["current_scene"] == "live-scene"
    room = test_db.execute(
        "SELECT integrity_status, integrity_reason FROM rooms WHERE room_id = 'integrity-room'"
    ).fetchone()
    assert room["integrity_status"] == "read_only_recovery"
    assert room["integrity_reason"] == "checkpoint_hash_mismatch"


def test_checkpoint_dry_run_returns_diff_without_writing_state(test_db):
    _seed_runtime_room(test_db)
    event_log = EventLog(test_db)
    event_log.create_checkpoint("integrity-room", "dry-run-cp")
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'changed', version = 4 "
        "WHERE room_id = 'integrity-room'"
    )
    test_db.execute(
        "UPDATE rooms SET state_version = 8 WHERE room_id = 'integrity-room'"
    )
    test_db.commit()

    result = event_log.dry_run_restore("integrity-room", "dry-run-cp")

    assert result["verified"] is True
    assert "room_scene_state" in result["diff"]["changedSections"]
    assert result["currentStateVersion"] == 8
    assert test_db.execute(
        "SELECT current_scene FROM room_scene_state WHERE room_id = 'integrity-room'"
    ).fetchone()["current_scene"] == "changed"
    assert test_db.execute(
        "SELECT integrity_status FROM rooms WHERE room_id = 'integrity-room'"
    ).fetchone()["integrity_status"] == "healthy"


def test_automatic_restore_rejects_a_checkpoint_not_marked_verified(test_db):
    _seed_runtime_room(test_db)
    event_log = EventLog(test_db)
    event_log.create_checkpoint("integrity-room", "unverified-cp")
    test_db.execute(
        "UPDATE checkpoints SET verification_status = 'unverified' "
        "WHERE checkpoint_id = 'unverified-cp'"
    )
    test_db.commit()

    with pytest.raises(CheckpointIntegrityError) as exc_info:
        event_log.restore_checkpoint(
            "integrity-room",
            "unverified-cp",
            automatic=True,
        )

    assert exc_info.value.code == "checkpoint_not_verified"
    assert test_db.execute(
        "SELECT integrity_status FROM rooms WHERE room_id = 'integrity-room'"
    ).fetchone()["integrity_status"] == "read_only_recovery"


def test_restore_row_failure_rolls_back_the_entire_snapshot(test_db):
    _seed_runtime_room(test_db)
    event_log = EventLog(test_db)
    event_log.create_checkpoint("integrity-room", "bad-row-cp")
    test_db.execute(
        "INSERT INTO inventory (id, character_id, room_id, name, quantity) "
        "VALUES ('live-item', 'integrity-char', 'integrity-room', 'Live item', 1)"
    )
    row = test_db.execute(
        "SELECT state_snapshot FROM checkpoints WHERE checkpoint_id = 'bad-row-cp'"
    ).fetchone()
    snapshot = dict(row["state_snapshot"])
    snapshot["inventory"] = [{
        "id": "bad-item",
        "character_id": "integrity-char",
        "room_id": "integrity-room",
        "name": "Bad item",
        "quantity": "not-an-integer",
    }]
    report = validate_runtime_snapshot(snapshot, "integrity-room")
    assert report["valid"] is True
    test_db.execute(
        "UPDATE checkpoints SET state_snapshot = %s, snapshot_sha256 = %s, "
        "invariant_report = %s, verification_status = 'verified' "
        "WHERE checkpoint_id = 'bad-row-cp'",
        (
            json.dumps(snapshot),
            checkpoint_snapshot_hash(snapshot),
            json.dumps(report),
        ),
    )
    test_db.commit()

    with pytest.raises(Exception):
        event_log.restore_checkpoint("integrity-room", "bad-row-cp")

    items = test_db.execute(
        "SELECT id FROM inventory WHERE room_id = 'integrity-room' ORDER BY id"
    ).fetchall()
    assert [item["id"] for item in items] == ["live-item"]
    assert test_db.execute(
        "SELECT integrity_status FROM rooms WHERE room_id = 'integrity-room'"
    ).fetchone()["integrity_status"] == "read_only_recovery"


def test_manual_restore_requires_dry_run_bound_confirmations_and_notifies_party(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    room = create_room(client)
    room_id = room["room_id"]
    owner_headers = {"X-Owner-Token": room["owner_token"]}
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, version) VALUES (%s, 'before', 1)",
        (room_id,),
    )
    test_db.commit()
    checkpoint = EventLog(test_db).create_checkpoint(room_id, "manual-cp")
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'after', version = 2 WHERE room_id = %s",
        (room_id,),
    )
    test_db.execute(
        "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()
    proposal = {"mode": "checkpoint_restore", "checkpointId": "manual-cp"}
    reason = "Repair verified runtime state"

    missing = client.post(
        f"/api/rooms/{room_id}/restore/manual-cp",
        headers=owner_headers,
        json={"confirm": True, "reason": reason},
    )
    assert missing.status_code == 400

    dry_run = client.post(
        f"/api/rooms/{room_id}/restore/manual-cp/dry-run",
        headers=owner_headers,
        json={"proposal": proposal, "reason": reason},
    )
    assert dry_run.status_code == 200
    dry_data = dry_run.json()
    assert dry_data["verified"] is True
    assert dry_data["dryRunToken"]

    valid_body = {
        "proposal": proposal,
        "reason": reason,
        "dryRunToken": dry_data["dryRunToken"],
        "confirm": True,
        "confirmations": {
            "checkpointHash": checkpoint.snapshot_sha256,
            "currentStateVersion": dry_data["currentStateVersion"],
        },
    }
    for missing_key in ("proposal", "reason", "dryRunToken", "confirm", "confirmations"):
        incomplete = dict(valid_body)
        incomplete.pop(missing_key)
        rejected = client.post(
            f"/api/rooms/{room_id}/restore/manual-cp",
            headers=owner_headers,
            json=incomplete,
        )
        assert rejected.status_code == 400, (missing_key, rejected.text)

    apply_response = client.post(
        f"/api/rooms/{room_id}/restore/manual-cp",
        headers=owner_headers,
        json=valid_body,
    )

    assert apply_response.status_code == 200, apply_response.text
    assert apply_response.json()["status"] == "restored"
    assert test_db.execute(
        "SELECT current_scene FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()["current_scene"] == "before"
    event_types = {
        row["event_type"]
        for row in test_db.execute(
            "SELECT event_type FROM events WHERE room_id = %s",
            (room_id,),
        ).fetchall()
    }
    assert "s2c_checkpoint_restored" in event_types
    assert "s2c_runtime_integrity_changed" in event_types


def test_read_only_recovery_blocks_actions_but_allows_export_and_recovery_checks(
    client,
    test_db,
):
    setup_auth_test_data(test_db)
    room = create_room(client)
    player = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
    EventLog(test_db).create_checkpoint(room["room_id"], "read-only-cp")
    test_db.execute(
        "UPDATE rooms SET integrity_status = 'read_only_recovery', "
        "integrity_reason = 'test_integrity_failure' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    action = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player["player_token"]},
        json={"declared_intent": "我进行侦查。", "intent_type": "skill_check"},
    )
    exported = client.get(
        f"/api/rooms/{room['room_id']}/export?format=json&scope=full",
        headers={"X-Owner-Token": room["owner_token"]},
    )
    checked = client.post(
        f"/api/rooms/{room['room_id']}/restore/read-only-cp/dry-run",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "proposal": {"mode": "checkpoint_restore", "checkpointId": "read-only-cp"},
            "reason": "Check recovery",
        },
    )

    assert action.status_code == 409
    assert action.json()["detail"]["code"] == "room_read_only_recovery"
    assert exported.status_code == 200
    assert checked.status_code == 200
