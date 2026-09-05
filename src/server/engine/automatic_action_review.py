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



# ─────────────────────────────────────────────────────────────────────────────
# R4 slice B — run_automatic_action_review: evidence verification, deterministic
# objection triage, bounded provider retry and terminal statuses. The AI only
# ever re-interprets the frozen original text via Gateway.review_action_intent;
# the Engine validates every outcome and applies no mutation here.
# ─────────────────────────────────────────────────────────────────────────────

REVIEW_MAX_ATTEMPTS = 3

# Objections that dispute the dice, demand a different method, or rely on
# post-hoc information are inadmissible by rule; each maps to a terminal
# review_rejected reason code. Patterns are substrings of the objection text.
_REJECTION_REASON_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("disagrees_with_dice", ("不喜欢骰", "重骰", "骰点", "骰子", "roll again")),
    ("alternative_method", ("改用", "换一种方法", "换成别的方法", "别的办法", "另一方法")),
    ("posthoc_information", ("事后", "后来才", "现在知道", "用后来的信息", "后来知道")),
)


def classify_objection(objection: str) -> str | None:
    """Deterministic inadmissibility classification of one objection text.

    Args:
        objection: the player's objection text.
    Returns:
        Reason code when the objection is inadmissible, else None (admissible
        for engine review).
    """
    lowered = (objection or "").lower()
    for code, patterns in _REJECTION_REASON_PATTERNS:
        if any(pattern.lower() in lowered for pattern in patterns):
            return code
    return None


def _verify_sealed_evidence(snapshot: dict | None, stored_hash: str) -> bool:
    """True when the frozen snapshot is present and its hash still verifies."""
    if not isinstance(snapshot, dict) or not snapshot:
        return False
    if not stored_hash:
        return False
    return review_evidence_hash(snapshot) == stored_hash


def _load_automatic_case(conn, review_request_id: str):
    return conn.execute(
        "SELECT r.*, a.room_id AS action_room_id, a.character_id AS action_character_id, "
        "a.status AS action_status, a.declared_intent AS action_declared_intent, "
        "a.intent_type AS action_intent_type, rooms.session_mode, rooms.runtime_status "
        "FROM action_review_requests r "
        "JOIN actions a ON a.action_id = r.action_id "
        "JOIN rooms ON rooms.room_id = a.room_id "
        "WHERE r.review_request_id = %s FOR UPDATE",
        (review_request_id,),
    ).fetchone()


def _write_automatic_terminal(
    conn,
    *,
    review_request_id: str,
    status_code: str,
    reason_code: str,
    reason: str,
    extra: dict | None = None,
) -> None:
    """Mark one automatic case resolved with its terminal outcome (append-only)."""
    resolution = {
        "status": status_code,
        "reason_code": reason_code,
        "reason": reason,
        **(extra or {}),
    }
    existing = conn.execute(
        "SELECT automatic_resolution FROM action_review_requests "
        "WHERE review_request_id = %s",
        (review_request_id,),
    ).fetchone()
    history = []
    previous = existing.get("automatic_resolution") if existing else {}
    if isinstance(previous, dict) and previous.get("status"):
        history = previous.get("history") or []
        history.append(previous)
        resolution["history"] = history
    conn.execute(
        "UPDATE action_review_requests SET status = 'resolved', resolved_at = NOW(), "
        "automatic_resolution = %s WHERE review_request_id = %s",
        (
            json.dumps(resolution, ensure_ascii=False),
            review_request_id,
        ),
    )


async def run_automatic_action_review(
    app_state,
    conn,
    review_request_id: str,
) -> dict[str, Any]:
    """Run one automatic review case to a terminal state or bounded retry.

    R4 dispatch target (production schedules it through the unified background
    machinery; tests call it directly). Deterministic order of operations:
      1. load the pending case in its room (ai_only rooms only);
      2. verify the sealed evidence (missing/tampered -> system pause);
      3. classify the objection — the three inadmissible classes terminate
         as review_rejected without any AI call;
      4. admissible objections ask the gateway to re-interpret ONLY the
         frozen original text; provider unavailability bumps a bounded retry
         counter and, once exhausted, pauses the room as system_paused;
      5. a valid candidate keeps the case pending for the engine review step
         (R5 consumes it) — nothing here mutates world state.

    Args:
        app_state: FastAPI app state carrying the gateway (tests replace it).
        conn: caller-owned connection.
        review_request_id: pending automatic review case id.
    Returns:
        Outcome summary dict.
    """
    from .host_autonomy import room_session_mode
    from .room_pause import pause_room_for_system_integrity

    case = _load_automatic_case(conn, review_request_id)
    if not case:
        return {"status": "missing", "review_request_id": review_request_id}
    # ai_only is a computed policy (runtime package), not the raw column; the
    # acceptance path used the same helper so the two always agree.
    if room_session_mode(conn, case["action_room_id"]) != "ai_only":
        return {
            "status": "skipped_host_mode",
            "review_request_id": review_request_id,
        }
    current_status = str(case.get("status") or "")
    if current_status != "pending":
        resolution = case.get("automatic_resolution") or {}
        return {
            "status": "known_state",
            "review_request_id": review_request_id,
            "outcome": (resolution or {}).get("status", current_status),
        }
    previous_resolution = case.get("automatic_resolution")
    if not isinstance(previous_resolution, dict):
        previous_resolution = {}
    # A case already awaiting the engine correction step must never re-run the
    # gateway: its candidate is frozen for R5 and the retry budget is spent.
    if previous_resolution.get("status") in {"awaiting_engine_review"}:
        return {
            "status": "known_state",
            "review_request_id": review_request_id,
            "outcome": "awaiting_engine_review",
        }

    # 2. Sealed-evidence verification before anything else is re-examined.
    snapshot = case.get("evidence_snapshot")
    if not isinstance(snapshot, dict):
        try:
            snapshot = json.loads(snapshot or "{}")
        except (TypeError, json.JSONDecodeError):
            snapshot = {}
    if not _verify_sealed_evidence(snapshot, str(case.get("evidence_hash") or "")):
        pause_room_for_system_integrity(
            conn,
            room_id=case["action_room_id"],
            reason="review_evidence_mismatch",
            source="automatic_action_review",
        )
        _write_automatic_terminal(
            conn,
            review_request_id=review_request_id,
            status_code="system_paused",
            reason_code="evidence_not_sealed",
            reason="自动复核所需的冻结证据缺失或哈希无法核验，房间进入系统暂停。",
        )
        conn.commit()
        return {
            "status": "system_paused",
            "reason_code": "evidence_not_sealed",
            "review_request_id": review_request_id,
        }

    # 3. Deterministic inadmissibility triage — no AI input needed.
    objection = str(case.get("objection") or "")
    rejection_code = classify_objection(objection)
    if rejection_code:
        _write_automatic_terminal(
            conn,
            review_request_id=review_request_id,
            status_code="review_rejected",
            reason_code=rejection_code,
            reason="异议针对骰点/更换方法/事后信息，不属于可自动复核的冻结文本歧义。",
            extra={"objection_classified": rejection_code},
        )
        conn.commit()
        return {
            "status": "review_rejected",
            "reason_code": rejection_code,
            "review_request_id": review_request_id,
        }

    # 4. Admissible: bounded gateway re-interpretation of the frozen text.
    attempts = 0
    try:
        attempts = int(
            (previous_resolution.get("review_attempts") or {}).get("count") or 0
        )
    except (TypeError, ValueError):
        attempts = 0
    gateway = getattr(app_state, "gateway", None)
    review_fn = getattr(gateway, "review_action_intent", None)
    candidate: dict | None = None
    if callable(review_fn):
        try:
            candidate = await review_fn(
                {
                    "review_request_id": review_request_id,
                    "action_id": case.get("action_id"),
                    "frozen_intent": str(case.get("action_declared_intent") or ""),
                    "intent_type": case.get("action_intent_type"),
                    "objection": objection,
                    "evidence_hash": case.get("evidence_hash"),
                },
                room_id=case["action_room_id"],
            )
        except Exception:
            candidate = None
    if candidate and isinstance(candidate, dict):
        from ..ai.contracts import ReviewIntentCandidate

        try:
            ReviewIntentCandidate(**candidate)
        except Exception:
            candidate = None
    if not candidate:
        attempts += 1
        if attempts >= REVIEW_MAX_ATTEMPTS:
            pause_room_for_system_integrity(
                conn,
                room_id=case["action_room_id"],
                reason="review_provider_unavailable",
                source="automatic_action_review",
            )
            _write_automatic_terminal(
                conn,
                review_request_id=review_request_id,
                status_code="system_paused",
                reason_code="review_provider_unavailable",
                reason="自动复核 Provider 暂不可用且重试次数已耗尽，房间进入系统暂停。",
            )
            conn.commit()
            return {
                "status": "system_paused",
                "reason_code": "review_provider_unavailable",
                "review_request_id": review_request_id,
            }
        payload = {
            "status": "pending_retry",
            "review_attempts": {"count": attempts, "max": REVIEW_MAX_ATTEMPTS},
            "reason": "自动复核 Provider 暂不可用，等待有界重试。",
        }
        conn.execute(
            "UPDATE action_review_requests SET automatic_resolution = %s "
            "WHERE review_request_id = %s",
            (
                json.dumps(payload, ensure_ascii=False),
                review_request_id,
            ),
        )
        conn.commit()
        return {
            "status": "pending_retry",
            "attempt": attempts,
            "review_request_id": review_request_id,
        }

    # 5. Valid engine-validated candidate: keep the case pending for the
    #    engine correction step (R5) — nothing was mutated here. The retry
    #    budget travels with the case so it can never be reset by re-entry.
    payload = {
        "status": "awaiting_engine_review",
        "candidate": candidate,
        "reason_code": "admissible",
        "review_attempts": {"count": attempts, "max": REVIEW_MAX_ATTEMPTS},
    }
    conn.execute(
        "UPDATE action_review_requests SET automatic_resolution = %s "
        "WHERE review_request_id = %s",
        (
            json.dumps(payload, ensure_ascii=False),
            review_request_id,
        ),
    )
    conn.commit()
    return {
        "status": "awaiting_engine_review",
        "review_request_id": review_request_id,
    }
