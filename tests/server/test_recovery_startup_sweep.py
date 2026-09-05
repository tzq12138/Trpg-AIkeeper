"""R3 slice B — startup sweep reclaims expired claims and classifies restarts.

A worker that died mid-resolution without a system pause leaves a live claim;
startup sweep must release ONLY expired claims and leave live ones untouched.
Resolving actions with released journal rows are then classified by room
runtime status: paused_by_owner actions are explicitly never startup resume
candidates.
"""

import uuid

import pytest

from src.server.engine.resolution_journal import (
    claim_resolution,
    load_resolution,
    release_interrupted_resolution,
    sweep_expired_resolution_claims,
)
from src.server.engine.system_recovery import categorize_restart_recovery


def _room_row(test_db, room_id: str, runtime_status: str, character_id: str = "char-sweep"):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, scenario_id, status, runtime_status) "
        "VALUES (%s, 'tok-' || %s, 'sc-sweep', 'paused', %s) "
        "ON CONFLICT (room_id) DO UPDATE SET runtime_status = EXCLUDED.runtime_status",
        (room_id, room_id, runtime_status),
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES (%s, %s, 'p', 'tok-' || %s) "
        "ON CONFLICT (character_id) DO NOTHING",
        (character_id, room_id, character_id),
    )
    test_db.commit()


def _resolving_action_row(test_db, room_id: str, character_id: str = "char-sweep"):
    action_id = f"action-sweep-{uuid.uuid4().hex[:8]}"
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, draft_id, intent_type, "
        "declared_intent, params, status) "
        "VALUES (%s, %s, %s, 'draft-sweep', 'dialogue', 'x', '{}', 'resolving') "
        "ON CONFLICT (action_id) DO NOTHING",
        (action_id, room_id, character_id),
    )
    test_db.commit()
    return action_id


def test_sweep_releases_only_expired_claims(test_db):
    room_id = "room-sweep-expired"
    _room_row(test_db, room_id, "running")
    expired_id = _resolving_action_row(test_db, room_id)
    live_id = _resolving_action_row(test_db, room_id)
    # Expired claim: simulate a worker that died long ago.
    claimed = claim_resolution(test_db, expired_id, "dead-worker")
    test_db.execute(
        "UPDATE action_resolution_runs SET claim_expires_at = NOW() - INTERVAL '1 minute' "
        "WHERE action_id = %s",
        (expired_id,),
    )
    test_db.commit()
    # Live claim: another worker is still resolving.
    claim_resolution(test_db, live_id, "live-worker")
    test_db.commit()

    result = sweep_expired_resolution_claims(test_db)
    test_db.commit()

    assert result["released"] == 1
    assert result["action_ids"] == [expired_id]
    expired_row = load_resolution(test_db, expired_id)
    assert expired_row["claim_token"] is None
    assert expired_row["worker_id"] == "startup-sweep"
    live_row = load_resolution(test_db, live_id)
    assert live_row["claim_token"] is not None, "live claims must survive the sweep"


def test_sweep_is_idempotent(test_db):
    room_id = "room-sweep-idem"
    _room_row(test_db, room_id, "running")
    action_id = _resolving_action_row(test_db, room_id)
    claim_resolution(test_db, action_id, "dead-worker")
    test_db.execute(
        "UPDATE action_resolution_runs SET claim_expires_at = NOW() - INTERVAL '1 minute' "
        "WHERE action_id = %s",
        (action_id,),
    )
    test_db.commit()
    first = sweep_expired_resolution_claims(test_db)
    test_db.commit()
    second = sweep_expired_resolution_claims(test_db)
    test_db.commit()
    assert first["released"] == 1
    assert second["released"] == 0


def test_categorize_restart_never_touches_paused_by_owner(test_db):
    room_running = "room-cat-running"
    room_owner = "room-cat-owner"
    room_recovering = "room-cat-recovering"
    room_paused_system = "room-cat-paused"
    _room_row(test_db, room_running, "running")
    _room_row(test_db, room_owner, "paused_by_owner")
    _room_row(test_db, room_recovering, "recovering")
    _room_row(test_db, room_paused_system, "paused_system")
    running_id = _resolving_action_row(test_db, room_running)
    owner_id = _resolving_action_row(test_db, room_owner)
    recovering_id = _resolving_action_row(test_db, room_recovering)
    paused_id = _resolving_action_row(test_db, room_paused_system)
    # Each has a pause-written (released) journal row, like a real pause.
    for action_id in (running_id, owner_id, recovering_id, paused_id):
        release_interrupted_resolution(test_db, action_id)
    test_db.commit()

    grouped = categorize_restart_recovery(test_db)

    assert grouped["running"] == [running_id]
    assert grouped["recovering"] == [recovering_id]
    assert grouped["paused_system"] == [paused_id]
    assert grouped["paused_by_owner"] == [owner_id]
