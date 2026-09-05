"""Automatic action review acceptance for AI-only rooms (R4).

In ai_only rooms a player dispute over their own settled action must never
enqueue a Host review. The request is accepted as a `pending` automatic case
with an immutable evidence snapshot taken from the server-side frozen records:
the original action row (the authoritative original intent), the version
bundle, the room state version, receipt/bundle hashes and resolution-journal
references. The submitter's `original_intent` is only a review statement; it
never overwrites the frozen action/draft/contract.

Only hashes and references leave this module's summary shape; the full
snapshot is stored per the trace minimum-permission rule and public GET
returns the redacted summary only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

AUTOMATIC_REVIEW_TERMINAL_STATUSES = {
    "completed",
    "resolved",
    "rejected",
    "timeout",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def review_evidence_hash(snapshot: dict[str, Any]) -> str:
    """Deterministic sha256 over the snapshot (excluding itself)."""
    canonical = dict(snapshot)
    canonical.pop("evidence_hash", None)
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


def _bounded_row(row: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: row.get(key) for key in keys if row.get(key) is not None}


def _hash_value(value: Any) -> str | None:
    """Canonical sha256 of a stored JSON artifact, or None when absent."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return hashlib.sha256(value.encode("utf-8")).hexdigest()
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_review_evidence_snapshot(conn, action: dict[str, Any]) -> dict[str, Any]:
    """Frozen, hash-anchored evidence for one automatic review case.

    The snapshot deliberately stores references/hashes instead of secret or
    per-audience payloads: the full action result, rule explanations and
    projections stay in their own encrypted/minimum-permission stores, and
    this snapshot proves the case was frozen against them without duplicating
    them.

    Args:
        conn: caller-owned connection.
        action: the settled action row (already verified as the caller's own).
    Returns:
        Evidence snapshot dict (without the evidence_hash member).
    """
    room = conn.execute(
        "SELECT room_id, state_version, version_bundle, version_bundle_hash, "
        "runtime_package_version_id, session_mode FROM rooms WHERE room_id = %s",
        (action["room_id"],),
    ).fetchone()
    bundle_rows = conn.execute(
        "SELECT action_id, release_status, rule_explanation FROM resolution_bundles "
        "WHERE action_id = %s ORDER BY created_at",
        (action["action_id"],),
    ).fetchall()
    journal = conn.execute(
        "SELECT resolution_id, stage_cursor, claim_generation, artifacts "
        "FROM action_resolution_runs WHERE action_id = %s",
        (action["action_id"],),
    ).fetchone()
    snapshot: dict[str, Any] = {
        "action": {
            "action_id": action["action_id"],
            "character_id": action["character_id"],
            "intent_type": action.get("intent_type"),
            "status": action.get("status"),
            "draft_id": action.get("draft_id"),
            "idempotency_key": action.get("idempotency_key"),
            # The frozen original intent recorded at submission time; the
            # submitter's review `original_intent` never replaces this.
            "declared_intent": action.get("declared_intent"),
            "params_hash": _hash_value(action.get("params")),
        },
        "room": {
            "room_id": action["room_id"],
            "state_version": int(room.get("state_version") or 0) if room else None,
            "version_bundle_hash": (room.get("version_bundle_hash") or "") if room else "",
            "runtime_package_version_id": (
                (room.get("runtime_package_version_id") or "") if room else ""
            ),
        },
        "resolution_refs": None,
        "receipt_hashes": [],
    }
    if room is not None and (room.get("version_bundle") not in (None, "")):
        snapshot["room"]["version_bundle"] = _bounded_row(
            dict(room),
            (
                "version_bundle",
            ),
        )["version_bundle"]
    if journal is not None:
        snapshot["resolution_refs"] = {
            "resolution_id": journal.get("resolution_id"),
            "stage_cursor": journal.get("stage_cursor"),
            "claim_generation": int(journal.get("claim_generation") or 0),
            "artifact_hashes": {
                str(key): _hash_value(item)
                for key, item in (journal.get("artifacts") or {}).items()
            }
            if isinstance(journal.get("artifacts"), dict)
            else {},
        }
    for bundle in bundle_rows:
        explanation = bundle.get("rule_explanation")
        receipt_hash = None
        if isinstance(explanation, dict):
            receipt = explanation.get("verification_receipt")
            if receipt is not None:
                receipt_hash = _hash_value(receipt)
        elif explanation is not None:
            receipt_hash = _hash_value(explanation)
        snapshot["receipt_hashes"].append(
            {
                "release_status": bundle.get("release_status"),
                "receipt_hash": receipt_hash,
            }
        )
    return snapshot


def automatic_review_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Redacted public summary for one automatic review case.

    Only non-secret fields and hashes are exposed; the full evidence snapshot
    is never returned through player-facing endpoints.

    Args:
        row: action_review_requests row (dict-like).
    Returns:
        Redacted summary dict.
    """
    return {
        "review_request_id": row.get("review_request_id"),
        "action_id": row.get("action_id"),
        "status": row.get("status"),
        "objection": row.get("objection"),
        "original_intent": row.get("original_intent"),
        "created_at": row.get("created_at"),
        "resolved_at": row.get("resolved_at"),
        "evidence_hash": row.get("evidence_hash"),
        "evidence_summary": {
            "state_version": (
                (row.get("evidence_snapshot") or {}).get("room", {}).get("state_version")
                if isinstance(row.get("evidence_snapshot"), dict)
                else None
            ),
            "resolution_id": (
                ((row.get("evidence_snapshot") or {}).get("resolution_refs") or {})
                .get("resolution_id")
                if isinstance(row.get("evidence_snapshot"), dict)
                else None
            ),
        }
        if row.get("evidence_snapshot")
        else None,
        "automatic_resolution": row.get("automatic_resolution") or {},
    }
