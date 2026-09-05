"""Fail-closed, system-generated recovery proposals for AI-only rooms."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..events.event_log import EventLog
from .runtime_integrity import CheckpointIntegrityError, checkpoint_snapshot_hash


class SystemRecoveryError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _proposal_hash(proposal: dict[str, Any]) -> str:
    canonical = dict(proposal)
    canonical.pop("proposal_hash", None)
    return checkpoint_snapshot_hash(canonical)


def _latest_verified_checkpoint(conn, room_id: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT checkpoint_id, state_version, event_sequence, snapshot_sha256, created_at "
        "FROM checkpoints WHERE room_id = %s AND verification_status = 'verified' "
        "ORDER BY state_version DESC, event_sequence DESC, created_at DESC LIMIT 1",
        (room_id,),
    ).fetchone()


def _proposal_events(conn, room_id: str, source_event_sequence: int) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    events = conn.execute(
        "SELECT sequence, event_type, action_id, state_version FROM events "
        "WHERE room_id = %s AND sequence > %s ORDER BY sequence",
        (room_id, source_event_sequence),
    ).fetchall()
    transactions = [
        {
            "event_sequence": int(row["sequence"]),
            "event_type": str(row["event_type"]),
            "action_id": row.get("action_id"),
            "state_version": int(row.get("state_version") or 0),
        }
        for row in events
        if int(row.get("state_version") or 0) > 0
    ]
    action_ids = sorted({str(row["action_id"]) for row in events if row.get("action_id")})
    receipts: list[dict] = []
    if action_ids:
        receipt_rows = conn.execute(
            "SELECT action_id FROM actions WHERE room_id = %s "
            "AND action_id = ANY(%s) AND receipt IS NOT NULL ORDER BY action_id",
            (room_id, action_ids),
        ).fetchall()
        receipts = [{"action_id": str(row["action_id"])} for row in receipt_rows]
    reveals = conn.execute(
        "SELECT reveal_id, event_sequence FROM fact_reveals "
        "WHERE room_id = %s AND event_sequence > %s ORDER BY event_sequence",
        (room_id, source_event_sequence),
    ).fetchall()
    projections = conn.execute(
        "SELECT action_id, release_status FROM resolution_bundles WHERE room_id = %s "
        "ORDER BY created_at",
        (room_id,),
    ).fetchall()
    return (
        transactions,
        receipts,
        [
            {"reveal_id": str(row["reveal_id"]), "event_sequence": int(row["event_sequence"])}
            for row in reveals
        ],
        [
            {"action_id": str(row["action_id"]), "release_status": str(row["release_status"])}
            for row in projections
        ],
    )


def create_system_recovery_proposal(conn, room_id: str) -> dict[str, Any]:
    """Select the latest verifiable checkpoint; callers never supply one."""
    with conn.transaction() as tx:
        room = tx.execute(
            "SELECT room_id, state_version, runtime_status FROM rooms "
            "WHERE room_id = %s FOR UPDATE",
            (room_id,),
        ).fetchone()
        if not room:
            raise SystemRecoveryError("room_not_found")
        if room.get("runtime_status") != "paused_system":
            raise SystemRecoveryError("room_not_paused_system")
        checkpoint = _latest_verified_checkpoint(tx, room_id)
        if not checkpoint:
            raise SystemRecoveryError("no_verified_checkpoint")
        try:
            dry_run = EventLog(tx).dry_run_restore(room_id, checkpoint["checkpoint_id"])
        except CheckpointIntegrityError as exc:
            raise SystemRecoveryError(exc.code) from exc
        current_version = int(room.get("state_version") or 0)
        source_version = int(checkpoint.get("state_version") or 0)
        transactions, receipts, reveals, projections = _proposal_events(
            tx,
            room_id,
            int(checkpoint.get("event_sequence") or 0),
        )
        # This first recovery path is deliberately strict: without a durable
        # replay log for an intervening authority write, do not overwrite the
        # room and pretend it was recovered.
        if source_version != current_version or any(
            item["state_version"] > source_version for item in transactions
        ):
            raise SystemRecoveryError("no_safe_recovery")
        proposal = {
            "proposal_id": f"recovery-{uuid.uuid4().hex}",
            "room_id": room_id,
            "source_checkpoint_id": str(checkpoint["checkpoint_id"]),
            "source_state_version": source_version,
            "target_state_version": current_version,
            "transactions_to_replay": transactions,
            "roll_receipts_to_reuse": receipts,
            "reveal_transactions_to_replay": reveals,
            "projection_events_to_replay": projections,
            "integrity_checks": {
                "checkpoint_verified": bool(dry_run.get("verified")),
                "checkpoint_hash": str(dry_run.get("checkpointHash") or ""),
                "state_version_matches": True,
                "authoritative_replay_required": False,
            },
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        }
        proposal["proposal_hash"] = _proposal_hash(proposal)
        tx.execute(
            "INSERT INTO runtime_recovery_proposals "
            "(proposal_id, room_id, source_checkpoint_id, source_state_version, "
            "target_state_version, proposal, proposal_hash, status, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'proposed', %s)",
            (
                proposal["proposal_id"],
                room_id,
                proposal["source_checkpoint_id"],
                source_version,
                current_version,
                json.dumps(proposal, ensure_ascii=False),
                proposal["proposal_hash"],
                proposal["expires_at"],
            ),
        )
        EventLog(tx).log_event(
            room_id,
            "s2c_system_recovery_proposed",
            "system",
            {
                "proposal_id": proposal["proposal_id"],
                "proposal_hash": proposal["proposal_hash"],
                "source_checkpoint_id": proposal["source_checkpoint_id"],
            },
            commit=False,
        )
    return proposal


def _load_verified_proposal(tx, room_id: str, proposal_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    row = tx.execute(
        "SELECT proposal, proposal_hash, status, expires_at FROM runtime_recovery_proposals "
        "WHERE proposal_id = %s AND room_id = %s FOR UPDATE",
        (proposal_id, room_id),
    ).fetchone()
    if not row:
        raise SystemRecoveryError("recovery_proposal_not_found")
    proposal = _json_object(row.get("proposal"))
    if not proposal or proposal.get("proposal_hash") != row.get("proposal_hash"):
        raise SystemRecoveryError("recovery_proposal_hash_mismatch")
    if _proposal_hash(proposal) != row.get("proposal_hash"):
        raise SystemRecoveryError("recovery_proposal_hash_mismatch")
    expires_at = row.get("expires_at")
    if isinstance(expires_at, datetime):
        # PostgreSQL TIMESTAMP values are naive on read.  The proposal writer
        # stores UTC, so preserve that contract instead of interpreting the
        # value in the server's local timezone.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise SystemRecoveryError("recovery_proposal_expired")
    return proposal, dict(row)


def dry_run_system_recovery(conn, room_id: str, proposal_id: str) -> dict[str, Any]:
    with conn.transaction() as tx:
        proposal, row = _load_verified_proposal(tx, room_id, proposal_id)
        room = tx.execute(
            "SELECT state_version, runtime_status FROM rooms WHERE room_id = %s FOR UPDATE",
            (room_id,),
        ).fetchone()
        if not room or room.get("runtime_status") != "paused_system":
            raise SystemRecoveryError("room_not_paused_system")
        if int(room.get("state_version") or 0) != int(proposal["target_state_version"]):
            raise SystemRecoveryError("recovery_state_changed")
        try:
            result = EventLog(tx).dry_run_restore(room_id, proposal["source_checkpoint_id"])
        except CheckpointIntegrityError as exc:
            raise SystemRecoveryError(exc.code) from exc
        tx.execute(
            "UPDATE runtime_recovery_proposals SET status = 'dry_run_verified', "
            "dry_run_at = NOW() WHERE proposal_id = %s",
            (proposal_id,),
        )
        EventLog(tx).log_event(
            room_id,
            "s2c_system_recovery_dry_run_verified",
            "system",
            {"proposal_id": proposal_id, "proposal_hash": proposal["proposal_hash"]},
            commit=False,
        )
    return {"status": "dry_run_verified", "proposal": proposal, "dry_run": result}


def execute_system_recovery(conn, room_id: str, proposal_id: str) -> dict[str, Any]:
    with conn.transaction() as tx:
        proposal, row = _load_verified_proposal(tx, room_id, proposal_id)
        if row.get("status") != "dry_run_verified":
            raise SystemRecoveryError("recovery_dry_run_required")
        room = tx.execute(
            "SELECT state_version, runtime_status FROM rooms WHERE room_id = %s FOR UPDATE",
            (room_id,),
        ).fetchone()
        if not room or room.get("runtime_status") != "paused_system":
            raise SystemRecoveryError("room_not_paused_system")
        if int(room.get("state_version") or 0) != int(proposal["target_state_version"]):
            raise SystemRecoveryError("recovery_state_changed")
        try:
            EventLog(tx).dry_run_restore(room_id, proposal["source_checkpoint_id"])
        except CheckpointIntegrityError as exc:
            raise SystemRecoveryError(exc.code) from exc
        tx.execute(
            "UPDATE rooms SET runtime_status = 'recovering' WHERE room_id = %s",
            (room_id,),
        )
        EventLog(tx).log_event(
            room_id,
            "s2c_system_recovery_started",
            "system",
            {"proposal_id": proposal_id, "proposal_hash": proposal["proposal_hash"]},
            commit=False,
        )
        tx.execute(
            "UPDATE rooms SET runtime_status = 'running', integrity_status = 'healthy', "
            "integrity_reason = NULL, integrity_source = NULL, "
            "integrity_state_version = state_version, integrity_updated_at = NOW() "
            "WHERE room_id = %s",
            (room_id,),
        )
        tx.execute(
            "UPDATE runtime_recovery_proposals SET status = 'executed', executed_at = NOW() "
            "WHERE proposal_id = %s",
            (proposal_id,),
        )
        EventLog(tx).log_event(
            room_id,
            "s2c_system_recovery_completed",
            "system",
            {"proposal_id": proposal_id, "proposal_hash": proposal["proposal_hash"]},
            commit=False,
        )
    return {"status": "running", "proposal_id": proposal_id}
