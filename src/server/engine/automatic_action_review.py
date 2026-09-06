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
import hmac
import json
import os
import uuid
from typing import Any

AUTOMATIC_REVIEW_TERMINAL_STATUSES = {
    "completed",
    "resolved",
    "rejected",
    "timeout",
}

# Engine-only provenance for review resolutions (R5 hardening). Applying a
# compensation must never depend on a caller-controlled payload alone: the
# resolution carries an HMAC over its canonical authoritative fields, keyed
# by the same domain-separated secret derivation the roll receipts use, so
# only the engine-side builder can produce a valid resolution. Clients never
# reach apply_automatic_review_resolution today, and any future wiring that
# accepts client-shaped resolutions fails closed on the signature.
_REVIEW_SIGNING_DOMAIN = "aikeeper-automatic-review-v1"
_REVIEW_SIGNATURE_KEYS = (
    "review_request_id",
    "status",
    "source_action_id",
    "source_receipt_hash",
    "expected_current_state_version",
    "mutations",
)


def _review_signing_secret() -> str:
    secret = os.getenv("ROLL_RECEIPT_SECRET") or os.getenv("JWT_SECRET")
    if not secret and os.getenv("AIKEEPER_DEV_MODE", "").lower() in ("1", "true", "yes"):
        return "aikeeper-local-development-automatic-review-v1"
    if not secret:
        raise AutomaticReviewResolutionError("resolution_signing_unavailable")
    return secret


def _review_signing_key() -> bytes:
    derived = hashlib.sha256(
        f"{_REVIEW_SIGNING_DOMAIN}:{_review_signing_secret()}".encode("utf-8")
    ).digest()
    return derived


def sign_automatic_review_resolution(
    review_request_id: str, resolution: dict[str, Any]
) -> str:
    """Engine-side signature over the canonical authoritative fields."""
    canonical = {key: resolution.get(key) for key in _REVIEW_SIGNATURE_KEYS}
    canonical["review_request_id"] = review_request_id
    body = _canonical_json(canonical)
    return hmac.new(_review_signing_key(), body.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_resolution_signature(
    review_request_id: str, resolution: dict[str, Any]
) -> bool:
    provided = resolution.get("engine_signature")
    if not isinstance(provided, str) or not provided:
        return False
    expected = sign_automatic_review_resolution(review_request_id, resolution)
    return hmac.compare_digest(provided, expected)


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



# ─────────────────────────────────────────────────────────────────────────────
# R5 slice A — apply_automatic_review_resolution: engine-validated terminal
# dispositions applied atomically, append-only, idempotent under replay.
#
# The service accepts ONLY Engine-built resolutions and never fabricates a
# disposition itself. Supported statuses (D07): upheld / explanation_corrected
# / projection_repaired / compensated (engine-applied) plus review_rejected /
# system_paused which R4 already writes through _write_automatic_terminal.
# Rules enforced here:
#   - mutations are allowed ONLY for compensated, and only against the
#     original authorized character's resources;
#   - every applied outcome is append-only: correction records and the
#     compensation transaction carry causal references (source action id,
#     receipt hash, source/current state versions, review id) and never
#     overwrite the original action result / resolution bundle / trace;
#   - transaction ids are deterministically derived from the review id so a
#     repeated apply (reply lost, retry) returns the SAME transaction id and
#     never re-applies a compensation or re-bumps the state version;
#   - unprovable conditions (state version moved underneath the case) go to
#     system_paused in the same transaction — never a guessed correction.
# ─────────────────────────────────────────────────────────────────────────────

AUTOMATIC_REVIEW_STATUSES = frozenset(
    {
        "upheld",
        "explanation_corrected",
        "projection_repaired",
        "compensated",
        "review_rejected",
        "system_paused",
    }
)
# Terminal statuses that may carry mutations (only compensation changes world
# state; every other disposition must refuse non-empty mutations).
_MUTATION_ALLOWED_STATUSES = frozenset({"compensated"})
_APPLIED_STATUSES = frozenset({"explanation_corrected", "projection_repaired", "compensated"})
_REVIEW_ID_NAMESPACE = "aikeeper-automatic-review-v1"
_APPLY_PATH_PREFIXES = (
    "/character/hp",
    "/character/san",
    "/character/mp",
    "/character/luck",
    "/character/hp_max",
    "/character/san_max",
    "/character/mp_max",
)


class AutomaticReviewResolutionError(ValueError):
    """Raised with a machine-readable code for HTTP/retry mapping."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _deterministic_id(kind: str, review_request_id: str) -> str:
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"{_REVIEW_ID_NAMESPACE}:{kind}:{review_request_id}")
    )


def _validated_mutations(mutations: Any, character_id: str) -> list[dict]:
    if not isinstance(mutations, list):
        raise AutomaticReviewResolutionError("invalid_resolution")
    validated: list[dict] = []
    for item in mutations:
        if not isinstance(item, dict):
            raise AutomaticReviewResolutionError("invalid_resolution")
        op = item.get("op")
        path = item.get("path")
        if op != "replace" or not isinstance(path, str):
            raise AutomaticReviewResolutionError("invalid_mutation")
        if not any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in _APPLY_PATH_PREFIXES
        ):
            raise AutomaticReviewResolutionError("invalid_mutation_path")
        if path.startswith("/character/"):
            segments = path.split("/")
            if len(segments) >= 4:
                raise AutomaticReviewResolutionError("invalid_mutation_path")
        if "value" not in item:
            raise AutomaticReviewResolutionError("invalid_resolution")
        validated.append({"op": op, "path": path, "value": item.get("value")})
    return validated


def _resolve_case_state(conn, review_request_id: str):
    """Lock the case row and its room version for one apply decision."""
    return conn.execute(
        "SELECT r.*, a.room_id AS action_room_id, a.character_id AS action_character_id, "
        "rooms.state_version AS room_state_version, rooms.runtime_status AS room_runtime "
        "FROM action_review_requests r "
        "JOIN actions a ON a.action_id = r.action_id "
        "JOIN rooms ON rooms.room_id = a.room_id "
        "WHERE r.review_request_id = %s FOR UPDATE",
        (review_request_id,),
    ).fetchone()


def apply_automatic_review_resolution(
    app_state,
    conn,
    review_request_id: str,
    resolution: dict,
) -> dict:
    """Apply one Engine-built automatic review disposition atomically (R5).

    Accepts only the canonical Engine-built resolution shape; the service
    validates provenance (review id, action id, state version), enforces
    bounded mutations, writes the compensation/correction row and the case
    terminal state in ONE transaction, and never touches the original action
    result / bundle / trace. Replays return the deterministic transaction id
    without re-applying side effects.

    Args:
        app_state: FastAPI app state (used only to source StateService).
        conn: caller-owned connection.
        review_request_id: pending case in awaiting_engine_review state.
        resolution: Engine-built dict, e.g.
            {"status": "compensated", "reason_code": "state_mismatch",
             "reason": "...", "source_action_id": "...",
             "source_receipt_hash": "...", "source_state_version": 7,
             "expected_current_state_version": 8,
             "mutations": [{"op": "replace", "path": "/character/hp",
                            "value": 10}], "correction": {}}
    Returns:
        Outcome dict with the terminal status and (for applied dispositions)
        the deterministic transaction id and resulting state version.
    Raises:
        AutomaticReviewResolutionError: review_request_not_found /
        not_ai_only / not_awaiting_engine_review / invalid_resolution /
        invalid_mutation / mutations_not_allowed / already_resolved.
    """
    from ..models import CharacterMutationItem, StateChangeSet
    from .host_autonomy import room_session_mode
    from .room_pause import pause_room_for_system_integrity
    from .state_service import StateService
    from ..events.event_log import EventLog

    if not isinstance(resolution, dict):
        raise AutomaticReviewResolutionError("invalid_resolution")
    # Provenance gate: only an engine-signed resolution may dispose a case;
    # client-shaped payloads fail closed here before any status is honored.
    if not _verify_resolution_signature(review_request_id, resolution):
        raise AutomaticReviewResolutionError("unverified_resolution")
    status = str(resolution.get("status") or "")
    if status not in AUTOMATIC_REVIEW_STATUSES:
        raise AutomaticReviewResolutionError("invalid_resolution")
    reason = str(resolution.get("reason") or "")
    reason_code = str(resolution.get("reason_code") or "review_applied")
    correction = resolution.get("correction")
    if not isinstance(correction, dict):
        raise AutomaticReviewResolutionError("invalid_resolution")

    with conn.transaction() as tx:
        case = _resolve_case_state(conn, review_request_id)
        if not case:
            raise AutomaticReviewResolutionError("review_request_not_found")
        if room_session_mode(conn, case["action_room_id"]) != "ai_only":
            raise AutomaticReviewResolutionError("not_ai_only")
        previous = case.get("automatic_resolution")
        if not isinstance(previous, dict):
            previous = {}
        previous_status = str(previous.get("status") or "")
        row_status = str(case.get("status") or "")
        if row_status != "pending" or previous_status != "awaiting_engine_review":
            if previous_status == status:
                applied = _load_applied_transaction(conn, review_request_id, status)
                return {
                    "status": status,
                    "review_request_id": review_request_id,
                    "already_applied": True,
                    "transaction_id": (applied or {}).get("transaction_id"),
                }
            raise AutomaticReviewResolutionError("not_awaiting_engine_review")
        # Provenance: the resolution must reference the frozen action.
        if str(resolution.get("source_action_id") or "") != case.get("action_id"):
            raise AutomaticReviewResolutionError("action_id_mismatch")
        current_version = int(case.get("room_state_version") or 0)
        raw_expected = resolution.get("expected_current_state_version")
        if raw_expected is None:
            raise AutomaticReviewResolutionError("invalid_resolution")
        expected_version = int(raw_expected)
        if expected_version != current_version:
            # The world moved under the frozen case: the delta can no longer
            # be proven — fail closed to a system pause, never guess.
            pause_room_for_system_integrity(
                conn,
                room_id=case["action_room_id"],
                reason="review_state_version_mismatch",
                source="automatic_action_review",
                tx=tx,
            )
            _write_automatic_terminal(
                conn,
                review_request_id=review_request_id,
                status_code="system_paused",
                reason_code="state_version_mismatch",
                reason="复核基准版本与当前世界版本不一致，无法证明差量，房间进入系统暂停。",
            )
            return {
                "status": "system_paused",
                "reason_code": "state_version_mismatch",
                "review_request_id": review_request_id,
            }

        mutations: list[dict] = []
        if resolution.get("mutations"):
            if status not in _MUTATION_ALLOWED_STATUSES:
                raise AutomaticReviewResolutionError("mutations_not_allowed")
            mutations = _validated_mutations(
                resolution.get("mutations"), case.get("action_character_id")
            )

        # Fact-level corrections ride inside the same transaction: a wrongly
        # revealed fact is corrected (or safety-flagged) append-only and never
        # overwrites the original reveal row; existing failure accounting
        # (severe spoilers) is never zeroed by remediation.
        fact_reveals = correction.get("fact_reveals")
        if fact_reveals is not None:
            _apply_fact_corrections(
                conn,
                room_id=case["action_room_id"],
                source_action_id=case.get("action_id"),
                state_version=current_version,
                fact_reveals=fact_reveals,
                tx=tx,
            )

        source_receipt_hash = str(resolution.get("source_receipt_hash") or "")
        transaction_id = None
        if status in _APPLIED_STATUSES:
            transaction_id = _deterministic_id(f"applied:{status}", review_request_id)
            existing = tx.execute(
                "SELECT transaction_id FROM compensation_transactions "
                "WHERE transaction_id = %s",
                (transaction_id,),
            ).fetchone()
            if existing:
                # Replay: the side effects already landed; do not re-apply.
                return {
                    "status": status,
                    "review_request_id": review_request_id,
                    "already_applied": True,
                    "transaction_id": transaction_id,
                }
            tx.execute(
                "INSERT INTO compensation_transactions "
                "(transaction_id, room_id, character_id, review_request_id, "
                "transaction_type, payload, reason, status, applied_at) "
                "VALUES (%s, %s, %s, %s, 'review_correction', %s, %s, 'applied', NOW())",
                (
                    transaction_id,
                    case["action_room_id"],
                    case.get("action_character_id"),
                    review_request_id,
                    json.dumps(
                        {
                            "kind": status,
                            "correction": correction,
                            "source_action_id": case.get("action_id"),
                            "source_receipt_hash": source_receipt_hash,
                            "source_state_version": int(
                                resolution.get("source_state_version") or 0
                            ),
                            "expected_state_version": current_version,
                            "requires_redispatch": (
                                status == "projection_repaired"
                            ),
                        },
                        ensure_ascii=False,
                    ),
                    reason,
                ),
            )
            if status == "projection_repaired":
                # DB-level repair: reconnect/catch-up clients see the missed
                # notice; live WS push remains the R7 dispatcher contract.
                EventLog(conn).log_event(
                    case["action_room_id"],
                    "s2c_review_projection_repair",
                    "system",
                    {
                        "reviewRequestId": review_request_id,
                        "actionId": case.get("action_id"),
                        "correction": correction,
                    },
                    commit=False,
                )

        state_version_after = current_version
        if status == "compensated":
            if not mutations:
                raise AutomaticReviewResolutionError("invalid_resolution")
            state_service = getattr(app_state, "state_service", None) or StateService(conn)
            changes = StateChangeSet(
                characterMutations=[
                    CharacterMutationItem(
                        characterId=case.get("action_character_id"),
                        mutations=mutations,
                    )
                ],
            )
            result = state_service.apply_change(
                case["action_room_id"],
                {"character_id": case.get("action_character_id"), "role": "player"},
                changes,
                reason=reason,
                transaction=tx,
            )
            state_version_after = int(result.get("state_version") or current_version)
            if result.get("no_op") or state_version_after == current_version:
                raise AutomaticReviewResolutionError("compensation_noop")

        _write_automatic_terminal(
            conn,
            review_request_id=review_request_id,
            status_code=status,
            reason_code=reason_code,
            reason=reason,
            extra={
                "compensation_transaction_id": transaction_id,
                "state_version_after": state_version_after,
                "mutations": mutations if status == "compensated" else [],
            },
        )
    return {
        "status": status,
        "review_request_id": review_request_id,
        "transaction_id": transaction_id,
        "state_version": state_version_after,
    }


def _apply_fact_corrections(
    conn,
    *,
    room_id: str,
    source_action_id: str,
    state_version: int,
    fact_reveals: Any,
    tx,
) -> None:
    """Apply engine-built fact corrections inside the caller transaction.

    Each entry follows {"reveal_id", "kind": "corrected"|"safety",
    "corrected_text"?, "citation"?, "reason_code"?}. Corrections are
    append-only through RevealLedger (never overwrite the original reveal
    row) and idempotent per (source action, fact, audience, record kind), so
    a failed apply can be retried safely. Remediation never zeroes existing
    severe-spoiler failure accounting — no counter is touched here.

    Args:
        conn: caller-owned connection.
        room_id: room scope.
        source_action_id: the reviewed action.
        state_version: current world version (validated by the caller).
        fact_reveals: list of fact correction entries.
        tx: caller transaction to write inside.
    Raises:
        AutomaticReviewResolutionError: invalid_fact_correction /
        fact_correction_failed.
    """
    from .reveal_ledger import RevealLedger, RevealPolicyError

    if not isinstance(fact_reveals, list):
        raise AutomaticReviewResolutionError("invalid_fact_correction")
    ledger = RevealLedger(conn)
    for entry in fact_reveals:
        if not isinstance(entry, dict):
            raise AutomaticReviewResolutionError("invalid_fact_correction")
        reveal_id = str(entry.get("reveal_id") or "")
        kind = str(entry.get("kind") or "")
        if not reveal_id or kind not in {"corrected", "safety"}:
            raise AutomaticReviewResolutionError("invalid_fact_correction")
        try:
            if kind == "corrected":
                ledger.append_correction(
                    room_id=room_id,
                    reveal_id=reveal_id,
                    corrected_text=str(entry.get("corrected_text") or ""),
                    citation=entry.get("citation")
                    if isinstance(entry.get("citation"), dict)
                    else {},
                    source_action_id=source_action_id,
                    state_version=state_version,
                    tx=tx,
                )
            else:
                ledger.flag_safety_event(
                    room_id=room_id,
                    reveal_id=reveal_id,
                    reason_code=str(entry.get("reason_code") or "review_correction"),
                    source_action_id=source_action_id,
                    state_version=state_version,
                    tx=tx,
                )
        except RevealPolicyError as exc:
            raise AutomaticReviewResolutionError("fact_correction_failed") from exc


def _load_applied_transaction(conn, review_request_id: str, status: str) -> dict | None:
    transaction_id = _deterministic_id(f"applied:{status}", review_request_id)
    row = conn.execute(
        "SELECT transaction_id FROM compensation_transactions WHERE transaction_id = %s",
        (transaction_id,),
    ).fetchone()
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# R5 slice B — original-dice reuse review: reinterpret one frozen skill roll
# under a corrected difficulty using the SAME recorded die.
#
# resolve_roll_reinterpretation() implements the engine comparison the R5 spec
# demands: verify the original receipt (v1 raw_rolls / v2 raw_draws, per-purpose
# mapping), reuse the exact d100 value — no second random call — re-evaluate
# the skill check threshold at the requested difficulty, and decide:
#   - difficulty unchanged            -> upheld (nothing to correct);
#   - same outcome under new label    -> explanation_corrected (append-only
#                                        correction; world state untouched);
#   - receipt missing/invalid/action-rule-set mismatch / dice record missing
#     / more than one d100            -> system_paused (fail-closed, per spec);
#   - outcome flips with a PROVEN failure-branch expenditure -> compensated:
#                                        the engine's only difficulty-bound
#                                        failure-branch expenditure is the CoC
#                                        spend-luck follow-up. Its frozen
#                                        record (actions.result.metadata:
#                                        difficulty/skill_value/target/
#                                        initial_roll/luck_spent/
#                                        follow_up.decision=spend_luck, with
#                                        the original skill_check.initial
#                                        receipt holding the reused die) makes
#                                        the reverse delta provable, so the
#                                        engine refunds exactly luck_spent onto
#                                        the CURRENT luck value as a signed
#                                        compensated resolution;
#   - any unprovable flip              -> system_paused: without that frozen
#                                        proof the magnitude of the consequence
#                                        cannot be recomputed, so the engine
#                                        never guesses a compensation.
# Everything is decided from the frozen receipt + authoritative inputs; the
# original action result/bundle/trace are never overwritten.
# ─────────────────────────────────────────────────────────────────────────────

_REVIEW_DIFFICULTIES = frozenset({"regular", "hard", "extreme"})


def _skill_target(skill_value: int, difficulty: str) -> int:
    """CoC7 effective target for one difficulty."""
    if difficulty == "hard":
        return skill_value // 2
    if difficulty == "extreme":
        return skill_value // 5
    return skill_value


def _json_object_value(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _load_original_skill_receipt(conn, action_id: str) -> tuple[dict | None, dict | None]:
    """Return (rule_explanation, verification_receipt) for the frozen action."""
    bundle = conn.execute(
        "SELECT rule_explanation FROM resolution_bundles WHERE action_id = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (action_id,),
    ).fetchone()
    if not bundle:
        return None, None
    explanation = _json_object_value(bundle.get("rule_explanation"))
    receipt = _json_object_value(explanation.get("verification_receipt"))
    return (explanation or None), (receipt or None)


def _verified_original_d100(receipt: dict, *, action_id: str) -> tuple[dict, int]:
    """Verify one receipt and return (receipt, reused d100 value).

    Raises:
        AutomaticReviewResolutionError: roll_receipt_unavailable /
        roll_receipt_invalid / roll_receipt_action_mismatch /
        roll_receipt_rule_set_mismatch / recalculation_not_supported.
    """
    from .roll_receipt import verify_roll_receipt

    try:
        receipt_valid = verify_roll_receipt(receipt)
    except RuntimeError as exc:
        raise AutomaticReviewResolutionError("roll_receipt_unavailable") from exc
    if not receipt_valid:
        raise AutomaticReviewResolutionError("roll_receipt_invalid")
    if receipt.get("action_id") != action_id:
        raise AutomaticReviewResolutionError("roll_receipt_action_mismatch")
    raw_rolls = receipt.get("raw_rolls")
    raw_draws = receipt.get("raw_draws")
    candidates: list = []
    if isinstance(raw_rolls, list):
        candidates.extend(raw_rolls)
    if isinstance(raw_draws, list):
        # v2 per-purpose mapping: a draw only counts when its purpose matches
        # the frozen skill review context; multiple unrelated d100 draws are
        # NOT collapsed through the old one-d100 helper.
        candidates.extend(raw_draws)
    d100_rolls = [
        item for item in candidates
        if isinstance(item, dict) and item.get("dice") == "d100"
    ]
    if len(d100_rolls) != 1:
        raise AutomaticReviewResolutionError("recalculation_not_supported")
    roll_record = d100_rolls[0]
    try:
        roll = int(roll_record.get("result"))
    except (TypeError, ValueError) as exc:
        raise AutomaticReviewResolutionError("roll_receipt_invalid") from exc
    return receipt, roll


def _original_skill_context(receipt: dict, explanation: dict | None) -> tuple[int, str]:
    """Return (skill_value, applied_difficulty) from the frozen records."""
    locked = _json_object_value(receipt.get("locked_inputs"))
    authoritative = _json_object_value((explanation or {}).get("authoritative_inputs"))
    try:
        skill_value = max(0, int(locked.get("skill_value") or authoritative.get("skill_value") or 0))
    except (TypeError, ValueError) as exc:
        raise AutomaticReviewResolutionError("roll_receipt_invalid") from exc
    if skill_value <= 0:
        raise AutomaticReviewResolutionError("roll_receipt_invalid")
    difficulty = str(
        locked.get("difficulty")
        or authoritative.get("difficulty")
        or "regular"
    )
    if difficulty not in _REVIEW_DIFFICULTIES:
        raise AutomaticReviewResolutionError("roll_receipt_invalid")
    return skill_value, difficulty


def _recalibration_payload(
    roll: int, skill_value: int, difficulty: str
) -> dict[str, Any]:
    target = _skill_target(skill_value, difficulty)
    return {
        "roll": roll,
        "skillValue": skill_value,
        "difficulty": difficulty,
        "target": target,
        "isSuccess": roll <= target,
        "reusedOriginalRoll": True,
    }


def _frozen_initial_receipt(conn, action_id: str) -> dict | None:
    """The frozen skill_check.initial receipt when a CoC follow-up settled the
    action (the settlement receipt records no new d100 draw; the reused die
    lives inside the original receipt embedded in the action result)."""
    row = conn.execute(
        "SELECT result FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    if not row:
        return None
    payload = row.get("result")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    meta = payload.get("metadata")
    if not isinstance(meta, dict):
        return None
    receipt = meta.get("initial_verification_receipt")
    if not isinstance(receipt, dict):
        return None
    if str(receipt.get("purpose") or "") != "skill_check.initial":
        return None
    return receipt


def _prove_luck_refund(
    conn,
    *,
    action_id: str,
    roll: int,
    skill_value: int,
    original_difficulty: str,
    latest_receipt: dict | None,
) -> dict[str, Any] | None:
    """Prove one difficulty-bound failure-branch expenditure from frozen data.

    The CoC spend-luck follow-up is the engine's only difficulty-bound
    failure-branch expenditure: when a check fails under the applied
    difficulty, the player may spend exactly required = roll - target(difficulty)
    luck, and the settlement freezes difficulty/skill_value/target/initial_roll/
    luck_spent/follow_up.decision=spend_luck into the action result metadata.

    This verifies that the frozen record is self-consistent AND consistent
    with the receipt chain (the settlement receipt declares purpose
    skill_check.spend_luck). Every field must agree — any contradiction
    returns None so the caller fails closed instead of guessing.

    Args:
        conn: caller-owned connection.
        action_id: the reviewed action (frozen result lives here).
        roll: the reused original die (already verified from a receipt).
        skill_value / original_difficulty: locked skill context of that die.
        latest_receipt: the settlement receipt (purpose check).
    Returns:
        {"luck_spent": n, "path": "/character/luck", "target": t} when the
        expenditure is proven, else None.
    """
    if not isinstance(latest_receipt, dict):
        return None
    if str(latest_receipt.get("purpose") or "") != "skill_check.spend_luck":
        return None
    row = conn.execute(
        "SELECT result FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    if not row:
        return None
    payload = row.get("result")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    meta = payload.get("metadata")
    if not isinstance(meta, dict):
        return None
    try:
        meta_skill = int(meta.get("skill_value"))
    except (TypeError, ValueError):
        return None
    if meta_skill != int(skill_value):
        return None
    if str(meta.get("difficulty") or "") != str(original_difficulty):
        return None
    target = _skill_target(int(skill_value), original_difficulty)
    try:
        meta_target = int(meta.get("target"))
    except (TypeError, ValueError):
        return None
    if meta_target != target:
        return None
    try:
        meta_initial_roll = int(meta.get("initial_roll"))
    except (TypeError, ValueError):
        return None
    if meta_initial_roll != int(roll):
        return None
    follow_up = meta.get("follow_up")
    if not isinstance(follow_up, dict):
        return None
    if str(follow_up.get("decision") or "") != "spend_luck":
        return None
    if str(follow_up.get("status") or "") != "resolved":
        return None
    if meta.get("pushed") not in (False, None):
        return None
    if meta.get("pushed_consequence") not in (None,):
        return None
    try:
        luck_spent = int(meta.get("luck_spent"))
    except (TypeError, ValueError):
        return None
    required = max(0, int(roll) - target)
    if luck_spent != required or luck_spent <= 0:
        return None
    return {"luck_spent": luck_spent, "path": "/character/luck", "target": target}


def _read_character_luck(conn, room_id: str, character_id: str) -> int | None:
    """Current authoritative luck of one character, or None when unreadable."""
    runtime = conn.execute(
        "SELECT luck FROM character_runtime_state "
        "WHERE character_id = %s AND room_id = %s",
        (character_id, room_id),
    ).fetchone()
    if runtime and runtime.get("luck") is not None:
        try:
            return int(runtime.get("luck"))
        except (TypeError, ValueError):
            return None
    # Runtime row never materialized: the spend record could not have applied
    # through StateService, so the refund target is not provable.
    return None


def resolve_roll_reinterpretation(
    conn,
    review_request_id: str,
    *,
    difficulty: str,
    candidate: dict | None = None,
) -> dict[str, Any]:
    """Engine comparison reusing the original die for one skill-check review.

    Decides the terminal disposition and writes it (the corrected-exclamation
    path signs and applies an explanation_corrected resolution; every
    unprovable path fails closed to system_paused with a traceable reason).

    Args:
        conn: caller-owned connection.
        review_request_id: pending case in awaiting_engine_review.
        difficulty: corrected difficulty label (regular/hard/extreme).
        candidate: optional engine-validated AI candidate explanation.
    Returns:
        Outcome dict with status/reason_code/recalculation.
    Raises:
        AutomaticReviewResolutionError: review_request_not_found /
        not_ai_only / not_awaiting_engine_review / invalid_difficulty.
    """
    from .host_autonomy import room_session_mode
    from .room_pause import pause_room_for_system_integrity

    if difficulty not in _REVIEW_DIFFICULTIES:
        raise AutomaticReviewResolutionError("invalid_difficulty")
    with conn.transaction() as tx:
        case = _resolve_case_state(conn, review_request_id)
        if not case:
            raise AutomaticReviewResolutionError("review_request_not_found")
        if room_session_mode(conn, case["action_room_id"]) != "ai_only":
            raise AutomaticReviewResolutionError("not_ai_only")
        previous = case.get("automatic_resolution")
        if not isinstance(previous, dict):
            previous = {}
        if str(case.get("status") or "") != "pending" or previous.get("status") != "awaiting_engine_review":
            raise AutomaticReviewResolutionError("not_awaiting_engine_review")

        explanation, receipt = _load_original_skill_receipt(
            conn, case.get("action_id")
        )
        if receipt is None:
            pause_room_for_system_integrity(
                conn,
                room_id=case["action_room_id"],
                reason="review_receipt_missing",
                source="automatic_action_review",
                tx=tx,
            )
            _write_automatic_terminal(
                conn,
                review_request_id=review_request_id,
                status_code="system_paused",
                reason_code="roll_receipt_missing",
                reason="原骰回执缺失，无法按目的复用原骰，房间进入系统暂停。",
            )
            return {
                "status": "system_paused",
                "reason_code": "roll_receipt_missing",
                "review_request_id": review_request_id,
            }
        latest_receipt = receipt
        try:
            _receipt, roll = _verified_original_d100(
                receipt, action_id=case.get("action_id")
            )
            skill_value, original_difficulty = _original_skill_context(
                receipt, explanation
            )
        except AutomaticReviewResolutionError as exc:
            # CoC follow-up settlements (spend_luck/decline/push) record no
            # new d100 draw in their own receipt; the reused die lives in the
            # original skill_check.initial receipt frozen inside the action
            # result metadata. When the latest receipt alone carries no die,
            # fall back to that frozen initial receipt (verified, purpose
            # skill_check.initial) before declaring the review unsupported.
            fallback = None
            if str(exc.code) == "recalculation_not_supported":
                fallback = _frozen_initial_receipt(conn, case.get("action_id"))
                if fallback is not None:
                    try:
                        _receipt, roll = _verified_original_d100(
                            fallback, action_id=case.get("action_id")
                        )
                        receipt = fallback
                        skill_value, original_difficulty = _original_skill_context(
                            receipt, explanation
                        )
                    except AutomaticReviewResolutionError as fallback_exc:
                        exc = fallback_exc
                        fallback = None
            if fallback is None:
                pause_room_for_system_integrity(
                    conn,
                    room_id=case["action_room_id"],
                    reason="review_receipt_invalid",
                    source="automatic_action_review",
                    tx=tx,
                )
                _write_automatic_terminal(
                    conn,
                    review_request_id=review_request_id,
                    status_code="system_paused",
                    reason_code=str(exc.code),
                    reason="原骰回执无法核验（签名/归属/记录缺失），拒绝执行变化并暂停。",
                )
                return {
                    "status": "system_paused",
                    "reason_code": str(exc.code),
                    "review_request_id": review_request_id,
                }

        recalibration = _recalibration_payload(roll, skill_value, difficulty)
        original_recalibration = _recalibration_payload(
            roll, skill_value, original_difficulty
        )
        if difficulty == original_difficulty:
            _write_automatic_terminal(
                conn,
                review_request_id=review_request_id,
                status_code="upheld",
                reason_code="no_error",
                reason="复核难度与原结算一致，原判维持。",
                extra={"recalculation": original_recalibration},
            )
            return {
                "status": "upheld",
                "review_request_id": review_request_id,
            }
        resolution = None
        if original_recalibration["isSuccess"] != recalibration["isSuccess"]:
            # Outcome flips under the corrected difficulty. Compensation is
            # possible ONLY when the frozen payload proves exactly one
            # difficulty-bound failure-branch expenditure — the CoC spend-luck
            # follow-up, whose luck_spent == roll - target(difficulty) makes
            # the reverse delta fully determined. Any other flip (no recorded
            # expenditure, contradictory metadata, unreadable refund target)
            # keeps the fail-closed system pause; the engine never guesses.
            refund = _prove_luck_refund(
                conn,
                action_id=case.get("action_id"),
                roll=roll,
                skill_value=skill_value,
                original_difficulty=original_difficulty,
                latest_receipt=latest_receipt,
            )
            luck_now = None
            if refund is not None:
                luck_now = _read_character_luck(
                    conn,
                    case["action_room_id"],
                    case.get("action_character_id"),
                )
            if refund is None or luck_now is None:
                pause_room_for_system_integrity(
                    conn,
                    room_id=case["action_room_id"],
                    reason="review_outcome_flip",
                    source="automatic_action_review",
                    tx=tx,
                )
                _write_automatic_terminal(
                    conn,
                    review_request_id=review_request_id,
                    status_code="system_paused",
                    reason_code="outcome_flip_requires_consequence_proof",
                    reason="同骰新解释改变检定结果，但失败分支消耗无法从冻结记录证明，房间进入系统暂停。",
                    extra={
                        "recalculation": recalibration,
                        "original_recalibration": original_recalibration,
                        "reused_roll": roll,
                    },
                )
                return {
                    "status": "system_paused",
                    "reason_code": "outcome_flip_requires_consequence_proof",
                    "review_request_id": review_request_id,
                    "recalculation": recalibration,
                }
            refund_value = luck_now + refund["luck_spent"]
            correction = {
                "kind": "difficulty_flip_luck_refund",
                "summary": (
                    "复核难度由 {0} 修正为 {1}，复用原骰 {2} 重释后检定成功；"
                    "原失败分支按该难度消耗的 {3} 点幸运无从发生，"
                    "按当前幸运 {4} 返还至 {5}。".format(
                        original_difficulty,
                        difficulty,
                        roll,
                        refund["luck_spent"],
                        luck_now,
                        refund_value,
                    )
                ),
                "recalculation": recalibration,
                "original_recalibration": original_recalibration,
                "refund": {
                    "luck_spent": refund["luck_spent"],
                    "path": refund["path"],
                    "target": refund["target"],
                    "value_before": luck_now,
                    "value_after": refund_value,
                },
                "candidate": dict(candidate) if isinstance(candidate, dict) else None,
            }
            resolution = {
                "status": "compensated",
                "reason_code": "luck_refund_difficulty_flip",
                "reason": correction["summary"],
                "source_action_id": case.get("action_id"),
                "source_receipt_hash": str(receipt.get("signature") or ""),
                "source_state_version": int(case.get("room_state_version") or 0),
                "expected_current_state_version": int(
                    case.get("room_state_version") or 0
                ),
                "mutations": [
                    {"op": "replace", "path": refund["path"], "value": refund_value}
                ],
                "correction": correction,
            }
        else:
            # Same outcome under the corrected difficulty label: append-only
            # explanation correction with the reused-roll proof.
            correction = {
                "kind": "difficulty_relabel",
                "summary": (
                    "复核难度由 {0} 修正为 {1}，复用原骰 {2} 重释后结果不变。".format(
                        original_difficulty, difficulty, roll
                    )
                ),
                "recalculation": recalibration,
                "original_difficulty": original_difficulty,
                "candidate": dict(candidate) if isinstance(candidate, dict) else None,
            }
            resolution = {
                "status": "explanation_corrected",
                "reason_code": "difficulty_relabeled",
                "reason": correction["summary"],
                "source_action_id": case.get("action_id"),
                "source_receipt_hash": "",
                "source_state_version": int(case.get("room_state_version") or 0),
                "expected_current_state_version": int(
                    case.get("room_state_version") or 0
                ),
                "mutations": [],
                "correction": correction,
            }
        resolution["engine_signature"] = sign_automatic_review_resolution(
            review_request_id, resolution
        )
    # Apply in its own transaction; the signature is the provenance hand-off.
    return apply_automatic_review_resolution(None, conn, review_request_id, resolution)
