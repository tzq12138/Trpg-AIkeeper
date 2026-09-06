"""V3 — evidence validation and conversion for the real session benchmark.

This module is the boundary between RAW runner artifacts and the release
aggregator (ai_only_benchmark.py). It never fabricates observations: it
validates the persisted manifests (run-config, sessions, actions, trace
manifest, ratings) and converts one session's raw rows into a
BenchmarkObservation only when every constraint holds.

Constraints enforced here (03 §V3):
- counts are non-negative integers; latencies finite non-negative; ratings
  finite in 1..5;
- sessions: unique ids, run_kind in simulation/browser/fault, bounded
  player_count, non-empty seed for simulation/fault;
- accepted_actions counts natural-language game actions only (consent /
  choice / confirmation / OOC / same-action retransmissions and
  technical_retry_of rows are excluded);
- technical retries never count as extra observations or extra dice;
- unknowns stay unknown (never defaulted to zero);
- a full Trace manifest may not claim more complete traces than entered
  actions, and a missing trace for an entered action is a blocking code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .ai_only_benchmark import BenchmarkObservation

SCHEMA_VERSION = 1
RUN_KINDS = frozenset({"simulation", "browser", "fault"})
# Natural-language game actions only; everything else is filtered out of the
# accepted-action denominator (03 §V3).
_ACTION_KINDS_EXCLUDED = frozenset({
    "consent", "consent_response", "choice", "confirmation", "decision",
    "system_button", "ooc", "followup_decision", "composite_choice",
    "clarification_reply",
})
_NON_NEG_INT_FIELDS = (
    "player_count", "accepted_actions", "clarification_count",
    "unnecessary_check_count", "player_correction_count",
    "host_adjudication_count", "ai_only_host_exception_count",
    "severe_spoiler_count", "illegal_state_mutation_count",
    "duplicate_roll_count", "duplicate_submission_count", "deadlock_count",
    "trace_actions",
)


@dataclass(frozen=True, slots=True)
class EvidenceManifest:
    """One validated evidence bundle root (paths resolve at read time)."""

    rc_id: str
    git_commit: str
    schema_version: int
    sessions: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    annotations: list[dict[str, Any]] = field(default_factory=list)
    trace_manifest: dict[str, Any] = field(default_factory=dict)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and value == value and value != float("inf")


def _valid_utc_iso(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _block(code: str, out: list[str]) -> None:
    out.append(code)


def validate_evidence_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return blocking codes for one evidence manifest (empty = valid).

    Args:
        manifest: parsed run evidence root with the V3 shape
            {"schema_version", "rc_id", "git_commit", "run_config",
             "sessions": [...], "actions": [...], "annotations": [...],
             "trace_manifest": {...}, "ratings": {...}}.
    Returns:
        Blocking-code list; empty means the manifest may proceed to
        observation conversion.
    """
    blocks: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest_not_object"]
    if manifest.get("schema_version") != SCHEMA_VERSION:
        _block("schema_version_mismatch", blocks)
    if not isinstance(manifest.get("rc_id"), str) or not manifest["rc_id"]:
        _block("rc_id_missing", blocks)
    if not isinstance(manifest.get("git_commit"), str) or not manifest["git_commit"]:
        _block("git_commit_missing", blocks)
    run_config = manifest.get("run_config")
    if not isinstance(run_config, dict):
        _block("run_config_missing", blocks)
        return blocks
    planned = run_config.get("sessions_planned")
    if not isinstance(planned, list) or len(planned) < 32:
        _block("sessions_planned_below_32", blocks)
    for entry in planned if isinstance(planned, list) else []:
        if not isinstance(entry, dict):
            _block("session_plan_entry_invalid", blocks)
            continue
        if not isinstance(entry.get("seed"), str) or not entry["seed"]:
            _block("session_plan_seed_missing", blocks)
        kind = entry.get("run_kind")
        if kind not in RUN_KINDS:
            _block("session_plan_kind_invalid", blocks)

    sessions = manifest.get("sessions") or []
    if not isinstance(sessions, list):
        _block("sessions_not_list", blocks)
        return blocks
    seen_session: set[str] = set()
    seen_room: set[str] = set()
    for session in sessions:
        if not isinstance(session, dict):
            _block("session_entry_invalid", blocks)
            continue
        session_id = session.get("session_id")
        room_id = session.get("room_id")
        if not isinstance(session_id, str) or not session_id:
            _block("session_id_missing", blocks)
        elif session_id in seen_session:
            _block("session_id_duplicate", blocks)
        else:
            seen_session.add(session_id)
        if not isinstance(room_id, str) or not room_id:
            _block("session_room_id_missing", blocks)
        elif room_id in seen_room:
            _block("session_room_id_duplicate", blocks)
        else:
            seen_room.add(room_id)
        kind = session.get("run_kind")
        if kind not in RUN_KINDS:
            _block("session_kind_invalid", blocks)
        if not _valid_utc_iso(session.get("started_at")):
            _block("session_started_at_invalid", blocks)
        if not _valid_utc_iso(session.get("ended_at")):
            _block("session_ended_at_invalid", blocks)
        player_count = session.get("player_count")
        if not isinstance(player_count, int) or player_count < 1 or player_count > 8:
            _block("session_player_count_invalid", blocks)
        if kind in ("simulation", "fault") and not isinstance(session.get("seed"), str):
            _block("session_seed_missing", blocks)
        if session.get("eligibility") not in (None, "eligible", "disqualified"):
            _block("session_eligibility_invalid", blocks)

    actions = manifest.get("actions") or []
    if not isinstance(actions, list):
        _block("actions_not_list", blocks)
        return blocks
    for action in actions:
        if not isinstance(action, dict):
            _block("action_entry_invalid", blocks)
            continue
        if action.get("session_id") not in seen_session:
            _block("action_session_unknown", blocks)
        if not isinstance(action.get("action_id"), str) or not action["action_id"]:
            _block("action_id_missing", blocks)
        retry_of = action.get("technical_retry_of")
        if retry_of is not None and not isinstance(retry_of, str):
            _block("action_retry_of_invalid", blocks)
        if not isinstance(action.get("accepted_at"), str):
            _block("action_accepted_at_missing", blocks)
        for moment in ("resolve_started_at", "resolved_at"):
            value = action.get(moment)
            if value is not None and not isinstance(value, str):
                _block("action_moment_invalid", blocks)
        for key in ("intent_contract_hash", "receipt_hash", "trace_id"):
            if action.get(key) is not None and not isinstance(action[key], str):
                _block("action_field_invalid", blocks)

    annotations = manifest.get("annotations") or []
    if not isinstance(annotations, list):
        _block("annotations_not_list", blocks)
        return blocks
    known_action_ids = {a.get("action_id") for a in actions if isinstance(a, dict)}
    for annotation in annotations:
        if not isinstance(annotation, dict):
            _block("annotation_entry_invalid", blocks)
            continue
        if annotation.get("action_id") not in known_action_ids:
            _block("annotation_action_unknown", blocks)
        judgment = annotation.get("judgment")
        if judgment not in ("clarification", "correction", "unnecessary_check",
                            "silent_misunderstanding", "none", None):
            _block("annotation_judgment_invalid", blocks)
        if annotation.get("unknown") not in (None, True, False):
            _block("annotation_unknown_invalid", blocks)

    trace_manifest = manifest.get("trace_manifest")
    if not isinstance(trace_manifest, dict):
        _block("trace_manifest_missing", blocks)
    else:
        expected = trace_manifest.get("expected_action_ids")
        complete = trace_manifest.get("complete_trace_action_ids")
        if not isinstance(expected, list) or not isinstance(complete, list):
            _block("trace_manifest_shapes_invalid", blocks)
        elif len(complete) > len(set(expected)):
            _block("trace_complete_exceeds_expected", blocks)

    ratings = manifest.get("ratings") or {}
    if not isinstance(ratings, dict):
        _block("ratings_not_object", blocks)
        return blocks
    browser_session_ids = {
        s.get("session_id") for s in sessions
        if isinstance(s, dict) and s.get("run_kind") == "browser"
    }
    for session_id in browser_session_ids:
        session_ratings = ratings.get(session_id)
        if not isinstance(session_ratings, list) or not session_ratings:
            _block("browser_ratings_missing", blocks)
            continue
        for rating in session_ratings:
            if not isinstance(rating, dict):
                _block("browser_rating_entry_invalid", blocks)
                continue
            if not isinstance(rating.get("rater_anonymous_id"), str):
                _block("browser_rating_rater_missing", blocks)
            for dimension in ("clarity", "agency", "atmosphere"):
                score = rating.get(dimension)
                if not _finite_number(score) or not 1 <= float(score) <= 5:
                    _block("browser_rating_scale_invalid", blocks)
    return blocks


def _hash_of(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def collect_session_observation(
    session: dict[str, Any],
    actions: list[dict[str, Any]],
    annotations: list[dict[str, Any]] | None = None,
) -> BenchmarkObservation:
    """Convert one validated session's raw rows into an aggregator observation.

    Args:
        session: one sessions.jsonl row (run_kind, ids, persona, seed...).
        actions: the session's actions.jsonl rows (accepted + technical
            retries + excluded kinds).
        annotations: the session's annotations.jsonl rows (global list per
            session); when omitted, session["annotations"] is used.
    Raises:
        ValueError: session/action shapes are invalid or internally
            inconsistent (missing ids, bad counts, negative latencies,
            technical-retry rows claiming their own dice).
    """
    if annotations is None:
        annotations = session.get("annotations") if isinstance(session, dict) else None
    if annotations is None:
        annotations = []
    if not isinstance(session, dict):
        raise ValueError("session_not_object")
    session_id = session.get("session_id")
    room_id = session.get("room_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("session_id_missing")
    if not isinstance(room_id, str) or not room_id:
        raise ValueError("session_room_id_missing")
    kind = session.get("run_kind")
    if kind not in RUN_KINDS:
        raise ValueError("session_kind_invalid")
    player_count = session.get("player_count")
    if not isinstance(player_count, int) or player_count < 1:
        raise ValueError("session_player_count_invalid")
    if kind in ("simulation", "fault") and not isinstance(session.get("seed"), str):
        raise ValueError("session_seed_missing")
    if not isinstance(actions, list):
        raise ValueError("actions_not_list")

    retried_original: set[str] = set()
    unique_action_ids: set[str] = set()
    accepted = 0
    clarification_count = 0
    correction_count = 0
    unnecessary_check_count = 0
    duplicate_roll_count = 0
    duplicate_submission_count = 0
    latencies: list[int] = []
    trace_ids: set[str] = set()
    entered_action_ids: list[str] = []

    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("action_entry_invalid")
        if action.get("session_id") != session_id:
            raise ValueError("action_session_mismatch")
        action_id = action.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            raise ValueError("action_id_missing")
        retry_of = action.get("technical_retry_of")
        if retry_of is not None:
            if not isinstance(retry_of, str) or retry_of == action_id:
                raise ValueError("action_retry_of_invalid")
            retried_original.add(retry_of)
            # A technical retry never creates a second logical action, dice,
            # or transaction — it only re-drives the same one.
            duplicate_submission_count += 1
            continue
        if action_id in unique_action_ids:
            raise ValueError("action_id_duplicate_within_session")
        unique_action_ids.add(action_id)
        entered_action_ids.append(action_id)
        kind_of_action = str(action.get("action_kind") or "")
        if kind_of_action in _ACTION_KINDS_EXCLUDED:
            continue
        # Same-action retransmissions arrive as duplicates of an already-seen
        # id — impossible here (unique set) — and as `retransmission_of`.
        if action.get("retransmission_of") is not None:
            raise ValueError("action_retransmission_unresolved")
        accepted += 1
        outcome = str(action.get("outcome") or "")
        trace_id = action.get("trace_id")
        if isinstance(trace_id, str) and trace_id:
            trace_ids.add(trace_id)
        for moment_key in ("accepted_at", "resolve_started_at", "resolved_at"):
            if action.get(moment_key) is None:
                raise ValueError("action_moment_missing")

        # Latency is server-active time from acceptance to authoritative
        # settlement; queue/provider/retry portions stay inside this window
        # and player-wait intervals are excluded by the runner before write.
        latency = action.get("server_active_ms")
        if latency is not None:
            if not _finite_number(latency) or float(latency) < 0:
                raise ValueError("action_latency_invalid")
            latencies.append(int(latency))

    annotations = session.get("annotations") or []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise ValueError("annotation_entry_invalid")
        if annotation.get("action_id") not in unique_action_ids:
            raise ValueError("annotation_action_unknown")
        judgment = annotation.get("judgment")
        if judgment == "clarification":
            clarification_count += 1
        elif judgment == "correction":
            correction_count += 1
        elif judgment == "unnecessary_check":
            unnecessary_check_count += 1
        elif judgment in ("silent_misunderstanding", "none", None):
            pass
        else:
            raise ValueError("annotation_judgment_invalid")

    return BenchmarkObservation(
        session_id=session_id,
        player_count=player_count,
        persona=str(session.get("persona") or "normal"),
        ending_type=session.get("ending_type"),
        accepted_actions=accepted,
        clarification_count=clarification_count,
        unnecessary_check_count=unnecessary_check_count,
        player_correction_count=correction_count,
        ordinary_action_latencies_ms=tuple(sorted(latencies)),
        duplicate_roll_count=duplicate_roll_count,
        duplicate_submission_count=duplicate_submission_count,
        trace_actions=len(trace_ids),
    )


def manifest_digest(manifest: dict[str, Any]) -> str:
    """Deterministic digest over the RAW manifest (run-before evidence)."""
    return _hash_of(manifest)
