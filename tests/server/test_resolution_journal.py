"""R2 — resolution journal: claims, stage persistence and effect idempotency.

Two workers claiming the same action must yield exactly one writable claimant;
expired claims are refused; an unknown commit consults the journal and reuses
the recorded cursor/effects instead of re-applying; the load contract matches
the documented shape.
"""

import os
import uuid

import pytest

from src.server.db_adapter import PgDatabase
from src.server.engine.resolution_journal import (
    ResolutionJournalError,
    STAGE_ORDER,
    claim_resolution,
    effects_for_resolution,
    load_resolution,
    record_effect,
    save_resolution_stage,
)


def _second_pool() -> PgDatabase:
    """A second real connection pool over the same isolated test database."""
    dsn = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper_test",
    )
    pool = PgDatabase(dsn=dsn)
    pool.connect()
    pool.initialize()
    return pool


def _insert_action_row(test_db, action_id: str) -> None:
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, draft_id, intent_type, declared_intent, params, status) "
        "VALUES (%s, 'room-journal', 'char-journal', 'draft-journal', 'dialogue', '测试', '{}', 'queued') "
        "ON CONFLICT (action_id) DO NOTHING",
        (action_id,),
    )
    test_db.commit()


def test_load_shape_matches_documented_contract(test_db):
    action_id = f"journal-load-{uuid.uuid4().hex[:8]}"
    _insert_action_row(test_db, action_id)
    claimed = claim_resolution(test_db, action_id, "worker-a")
    assert claimed["action_id"] == action_id
    assert "claim_token" in claimed
    assert claimed["stage_cursor"] == ""
    assert claimed["claim_generation"] == 1
    loaded = load_resolution(test_db, action_id)
    assert loaded is not None
    assert loaded["resolution_id"] == claimed["resolution_id"]


def test_two_workers_share_one_claim_and_one_commit(test_db):
    """Only one worker may hold the live claim; late writes are refused."""
    action_id = f"journal-race-{uuid.uuid4().hex[:8]}"
    _insert_action_row(test_db, action_id)
    pool = _second_pool()
    conn_a = pool.get_connection()
    conn_b = pool.get_connection()
    try:
        first = claim_resolution(conn_a, action_id, "worker-a")
        assert first is not None

        # Worker B tries the same action: the live claim blocks it.
        second = claim_resolution(conn_b, action_id, "worker-b")
        assert second is None

        token = first["claim_token"]
        save_resolution_stage(
            conn_a,
            action_id,
            token,
            "intent_contract",
            {"intent_contract": {"ref": "art-1", "hash": "h1"}},
        )
        conn_a.commit()
        row = load_resolution(test_db, action_id)
        assert row["stage_cursor"] == "intent_contract"

        # A forged/foreign token is refused on any connection.
        with pytest.raises(ResolutionJournalError) as exc:
            save_resolution_stage(
                conn_b,
                action_id,
                "forged-token",
                "mechanic_plan",
                {},
            )
        assert exc.value.code in {"claim_mismatch", "claim_expired"}
    finally:
        conn_a.close()
        conn_b.close()
        pool.close()


def _advance_to(conn, action_id, token, stage):
    """Walk stages in order up to and including `stage` with distinct artifacts."""
    for index, cursor in enumerate(STAGE_ORDER):
        save_resolution_stage(
            conn,
            action_id,
            token,
            cursor,
            {cursor: {"ref": f"art-{cursor}", "hash": f"h-{index}"}},
        )
        if cursor == stage:
            return
    raise AssertionError(f"stage {stage} not in STAGE_ORDER")


def test_stage_order_and_duplicate_stage_are_enforced(test_db):
    action_id = f"journal-order-{uuid.uuid4().hex[:8]}"
    _insert_action_row(test_db, action_id)
    claimed = claim_resolution(test_db, action_id, "worker-a")
    token = claimed["claim_token"]
    with pytest.raises(ResolutionJournalError) as exc:
        save_resolution_stage(test_db, action_id, token, "roll_receipt", {})
    assert exc.value.code == "stage_out_of_order"
    _advance_to(test_db, action_id, token, "roll_receipt")
    # Re-saving the same stage with identical artifacts is a no-op success.
    save_resolution_stage(
        test_db,
        action_id,
        token,
        "roll_receipt",
        {"roll_receipt": {"ref": "art-roll_receipt", "hash": "h-2"}},
    )
    # ...but a conflicting artifact for the completed stage is refused.
    with pytest.raises(ResolutionJournalError) as exc:
        save_resolution_stage(
            test_db,
            action_id,
            token,
            "roll_receipt",
            {"roll_receipt": {"ref": "art-roll_receipt", "hash": "tampered"}},
        )
    assert exc.value.code == "artifact_conflict"
    assert load_resolution(test_db, action_id)["stage_cursor"] == "roll_receipt"


def test_expired_claim_rejects_late_writes(test_db):
    action_id = f"journal-expired-{uuid.uuid4().hex[:8]}"
    _insert_action_row(test_db, action_id)
    claimed = claim_resolution(test_db, action_id, "worker-a")
    token = claimed["claim_token"]
    # Age the claim beyond its TTL.
    test_db.execute(
        "UPDATE action_resolution_runs SET claim_expires_at = NOW() - INTERVAL '1 minute' "
        "WHERE action_id = %s",
        (action_id,),
    )
    test_db.commit()
    with pytest.raises(ResolutionJournalError) as exc:
        save_resolution_stage(test_db, action_id, token, "intent_contract", {})
    assert exc.value.code == "claim_expired"


def test_unknown_commit_queries_journal_before_retry(test_db):
    """A retry after commit-success/response-lost reuses recorded effects."""
    action_id = f"journal-unknown-{uuid.uuid4().hex[:8]}"
    _insert_action_row(test_db, action_id)
    claimed = claim_resolution(test_db, action_id, "worker-a")
    token = claimed["claim_token"]
    resolution_id = claimed["resolution_id"]
    _advance_to(test_db, action_id, token, "state_committed")
    record_effect(
        test_db,
        resolution_id=resolution_id,
        effect_kind="state_commit",
        effect_key="tx-9",
        effect_payload={"state_version": 7, "result_hash": "h-tx"},
    )
    test_db.commit()

    # The response was lost; the retry path consults the journal first.
    loaded = load_resolution(test_db, action_id)
    assert loaded["stage_cursor"] == "state_committed"
    effects = effects_for_resolution(test_db, resolution_id)
    assert len(effects) == 1
    assert effects[0]["effect_key"] == "tx-9"

    # A second worker claiming after expiry cannot replay the commit.
    test_db.execute(
        "UPDATE action_resolution_runs SET claim_expires_at = NOW() - INTERVAL '1 minute' "
        "WHERE action_id = %s",
        (action_id,),
    )
    test_db.commit()
    reclaimer = claim_resolution(test_db, action_id, "worker-b")
    assert reclaimer is not None
    assert reclaimer["claim_generation"] == 2
    # Re-recording the same effect stays single-row.
    record_effect(
        test_db,
        resolution_id=resolution_id,
        effect_kind="state_commit",
        effect_key="tx-9",
        effect_payload={"state_version": 7, "result_hash": "h-tx"},
    )
    test_db.commit()
    assert len(effects_for_resolution(test_db, resolution_id)) == 1
