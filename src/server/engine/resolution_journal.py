"""Persistent resolution recovery journal (R2).

Every in-flight action gets one `action_resolution_runs` row carrying the
original idempotency key, version bundle and a stage cursor that only advances
past stages that were durably saved. Side effects (signed rolls, state commits,
reveals, projections) are recorded once in `resolution_effects` keyed by
(resolution_id, effect_kind, effect_key), so an unknown commit, a repeated
dispatch or an expired worker can never double-apply.

Claim semantics: a worker claims with a generation+expiry; expired claims are
refused on every write. `save_resolution_stage` must be called inside the
caller's transaction with a valid claim token.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

STAGE_ORDER = (
    "intent_contract",
    "mechanic_plan",
    "roll_receipt",
    "state_committed",
    "reveal",
    "narration",
    "spoiler_guard",
    "projection",
)
CLAIM_TTL_MINUTES = 30


class ResolutionJournalError(ValueError):
    """Raised with a machine-readable code for HTTP/retry mapping."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def release_interrupted_resolution(tx, action_id: str) -> None:
    """Record an interrupted resolution in the same transaction as its pause.

    Called from the system-pause write (R3). Creates the run row when the
    resolution was not journaled yet and always releases any live claim, so a
    later verified recovery can reclaim the SAME resolution_id with the next
    claim generation. The row carries no stage cursor here: the pause is the
    durable frontier at this stage, and resume_action decides how much of the
    frozen action row may be re-executed.

    Args:
        tx: caller-owned transaction/cursor (pause transaction).
        action_id: action being interrupted by the system pause.
    """
    existing = tx.execute(
        "SELECT 1 AS one FROM action_resolution_runs WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    if not existing:
        tx.execute(
            "INSERT INTO action_resolution_runs "
            "(action_id, resolution_id, worker_id, claim_token, claim_generation, "
            "claimed_at, claim_expires_at) "
            "VALUES (%s, %s, 'system-pause', NULL, 1, NOW(), NOW())",
            (action_id, str(uuid.uuid4())),
        )
        return
    tx.execute(
        "UPDATE action_resolution_runs SET claim_token = NULL, "
        "claim_expires_at = NOW(), worker_id = 'system-pause', updated_at = NOW() "
        "WHERE action_id = %s",
        (action_id,),
    )


def sweep_expired_resolution_claims(conn, *, worker_id: str = "startup-sweep") -> dict:
    """Release every expired claim still held over an unfinished resolution.

    Startup hygiene (R3): a worker that died without pausing leaves a live
    claim that would block any verified recovery until its TTL passes. This
    function reclaims only claims whose expiry already passed — live claims
    are never touched — and returns the released action ids so the caller can
    decide what to resume/diagnose.

    Args:
        conn: caller-owned connection (caller commits).
        worker_id: identity recorded on the released rows.
    Returns:
        Dict with released count and the released action ids.
    """
    rows = conn.execute(
        "SELECT action_id FROM action_resolution_runs "
        "WHERE claim_token IS NOT NULL AND claim_expires_at <= NOW() "
        "ORDER BY action_id",
    ).fetchall()
    released: list[str] = []
    for row in rows:
        action_id = str(row["action_id"])
        conn.execute(
            "UPDATE action_resolution_runs SET claim_token = NULL, "
            "claim_expires_at = NOW(), worker_id = %s, updated_at = NOW() "
            "WHERE action_id = %s AND claim_token IS NOT NULL "
            "AND claim_expires_at <= NOW()",
            (worker_id, action_id),
        )
        released.append(action_id)
    return {"released": len(released), "action_ids": released}


def claim_resolution(conn, action_id: str, worker_id: str) -> dict | None:
    """Claim exclusive resolution ownership for one action.

    Args:
        conn: caller-owned connection (caller commits).
        action_id: action being resolved.
        worker_id: identity of the claiming worker.
    Returns:
        The run row dict with `claim_token` when the claim succeeded, else
        None when another live worker holds the claim (or the row is missing).
    """
    now = conn.execute("SELECT NOW() AS now").fetchone()["now"]
    row = conn.execute(
        "SELECT * FROM action_resolution_runs WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    if not row:
        resolution_id = str(uuid.uuid4())
        claim_token = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO action_resolution_runs "
            "(action_id, resolution_id, worker_id, claim_token, claim_generation, "
            "claimed_at, claim_expires_at) "
            "VALUES (%s, %s, %s, %s, 1, %s, %s + INTERVAL '30 minutes')",
            (action_id, resolution_id, worker_id, claim_token, now, now),
        )
        return dict(
            conn.execute(
                "SELECT * FROM action_resolution_runs WHERE action_id = %s",
                (action_id,),
            ).fetchone()
        )
    if row.get("claim_token") and _claim_live(conn, row):
        return None
    claim_token = str(uuid.uuid4())
    conn.execute(
        "UPDATE action_resolution_runs SET worker_id = %s, claim_token = %s, "
        "claim_generation = claim_generation + 1, claimed_at = %s, "
        "claim_expires_at = %s + INTERVAL '30 minutes', updated_at = NOW() "
        "WHERE action_id = %s",
        (worker_id, claim_token, now, now, action_id),
    )
    return dict(
        conn.execute(
            "SELECT * FROM action_resolution_runs WHERE action_id = %s",
            (action_id,),
        ).fetchone()
    )


def _claim_live(conn, row: dict) -> bool:
    if not row.get("claim_token"):
        return False
    live = conn.execute(
        "SELECT 1 AS one FROM action_resolution_runs "
        "WHERE action_id = %s AND claim_token = %s AND claim_expires_at > NOW()",
        (row["action_id"], row["claim_token"]),
    ).fetchone()
    return bool(live)


def load_resolution(conn, action_id: str) -> dict | None:
    """Return the journal row in the documented load shape, or None.

    Args:
        conn: caller-owned connection.
        action_id: action being diagnosed/resumed.
    Returns:
        None when no journal row exists; otherwise the run row with its
        artifacts and stage cursor.
    """
    row = conn.execute(
        "SELECT * FROM action_resolution_runs WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def save_resolution_stage(
    tx,
    action_id: str,
    claim_token: str,
    stage: str,
    artifacts: dict,
) -> None:
    """Record a durably completed stage inside the caller's transaction.

    Args:
        tx: caller-owned transaction/cursor (commit owned by caller).
        action_id: action being resolved.
        claim_token: token returned by claim_resolution; expired or foreign
            tokens are refused.
        stage: one of STAGE_ORDER.
        artifacts: stage artifact map {"kind": {"ref": ..., "hash": ...}}.
    Raises:
        ResolutionJournalError: resolution_run_missing / claim_expired /
        claim_mismatch / stage_out_of_order / artifact_conflict.
    """
    if stage not in STAGE_ORDER:
        raise ResolutionJournalError("stage_out_of_order")
    row = tx.execute(
        "SELECT * FROM action_resolution_runs WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    if not row:
        raise ResolutionJournalError("resolution_run_missing")
    if not row.get("claim_token") or row["claim_token"] != claim_token:
        raise ResolutionJournalError("claim_mismatch")
    live = tx.execute(
        "SELECT 1 AS one FROM action_resolution_runs "
        "WHERE action_id = %s AND claim_token = %s AND claim_expires_at > NOW()",
        (action_id, claim_token),
    ).fetchone()
    if not live:
        raise ResolutionJournalError("claim_expired")
    current = str(row.get("stage_cursor") or "")
    current_index = STAGE_ORDER.index(current) if current else -1
    target_index = STAGE_ORDER.index(stage)
    if target_index <= current_index:
        existing = tx.execute(
            "SELECT artifacts FROM action_resolution_runs WHERE action_id = %s",
            (action_id,),
        ).fetchone()["artifacts"]
        existing_map = existing if isinstance(existing, dict) else json.loads(existing or "{}")
        kind = next(iter(artifacts), None)
        if kind and existing_map.get(kind) and existing_map[kind] != artifacts[kind]:
            raise ResolutionJournalError("artifact_conflict")
        return
    if target_index != current_index + 1:
        raise ResolutionJournalError("stage_out_of_order")
    stored_artifacts = row.get("artifacts") or {}
    if isinstance(stored_artifacts, str):
        stored_artifacts = json.loads(stored_artifacts or "{}")
    stored_artifacts.update(artifacts)
    tx.execute(
        "UPDATE action_resolution_runs SET stage_cursor = %s, artifacts = %s, "
        "updated_at = NOW() WHERE action_id = %s AND claim_token = %s",
        (
            stage,
            json.dumps(stored_artifacts, ensure_ascii=False),
            action_id,
            claim_token,
        ),
    )


def record_effect(
    tx,
    *,
    resolution_id: str,
    effect_kind: str,
    effect_key: str,
    effect_payload: dict,
) -> dict:
    """Record one authority-side side effect exactly once (idempotent).

    Args:
        tx: caller-owned transaction/cursor.
        resolution_id: journal resolution id.
        effect_kind: roll/state_commit/reveal/projection/...
        effect_key: stable identity inside the kind (e.g. purpose for rolls,
            event sequence for projections).
        effect_payload: commit credential / result hash / state version data.
    Returns:
        The existing row when already recorded (duplicate), else the new row.
    """
    tx.execute(
        "INSERT INTO resolution_effects "
        "(resolution_id, effect_kind, effect_key, effect_payload) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (resolution_id, effect_kind, effect_key) "
        "DO NOTHING",
        (
            resolution_id,
            effect_kind,
            effect_key,
            json.dumps(effect_payload, ensure_ascii=False),
        ),
    )
    return dict(
        tx.execute(
            "SELECT * FROM resolution_effects "
            "WHERE resolution_id = %s AND effect_kind = %s AND effect_key = %s",
            (resolution_id, effect_kind, effect_key),
        ).fetchone()
    )


def effects_for_resolution(conn, resolution_id: str) -> list[dict]:
    """Return all recorded effects for one resolution.

    Args:
        conn: caller-owned connection.
        resolution_id: journal resolution id.
    Returns:
        Effect rows ordered by recorded_at.
    """
    rows = conn.execute(
        "SELECT * FROM resolution_effects WHERE resolution_id = %s "
        "ORDER BY recorded_at, effect_kind, effect_key",
        (resolution_id,),
    ).fetchall()
    return [dict(row) for row in rows]
