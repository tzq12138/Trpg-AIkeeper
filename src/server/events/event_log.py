import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ..engine.runtime_integrity import (
    CHECKPOINT_SCHEMA_VERSION,
    ROOM_SNAPSHOT_COLUMNS,
    SNAPSHOT_DELETE_ORDER,
    SNAPSHOT_INSERT_ORDER,
    SNAPSHOT_TABLE_COLUMNS,
    CheckpointIntegrityError,
    checkpoint_diff,
    checkpoint_snapshot_hash,
    sanitize_checkpoint_value,
    validate_runtime_snapshot,
)
from ..models import Checkpoint, EventLogEntry, redact_citation

PLAYER_VISIBLE_SYSTEM_EVENTS: set[str] = {
    "s2c_turn_resolved",
    "s2c_checkpoint_created",
}

FACT_REVEAL_EVENT_KINDS = {
    "s2c_fact_revealed": "reveal",
    "s2c_fact_corrected": "correction",
    "s2c_fact_safety_event": "safety_event",
}

MAX_AUTO_CHECKPOINTS = 20


class EventLog:
    def __init__(self, conn):
        self.conn = conn

    def log_event(
        self,
        room_id: str,
        event_type: str,
        audience: str,
        payload: dict,
        commit: bool = True,
        *,
        action_id: str | None = None,
        state_version: int | None = None,
    ) -> int:
        normalized_payload = sanitize_checkpoint_value(payload)
        bound_action_id = action_id or _payload_action_id(normalized_payload) or None
        bound_state_version = _payload_state_version(normalized_payload)
        if state_version is not None:
            bound_state_version = int(state_version)
        if bound_state_version is None:
            room = self.conn.execute(
                "SELECT state_version FROM rooms WHERE room_id = %s",
                (room_id,),
            ).fetchone()
            bound_state_version = int(room.get("state_version") or 0) if room else 0
        payload_hash = checkpoint_snapshot_hash(normalized_payload)
        cursor = self.conn.execute(
            "INSERT INTO events "
            "(room_id, event_type, audience, payload, action_id, state_version, payload_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING sequence",
            (
                room_id,
                event_type,
                audience,
                json.dumps(normalized_payload, ensure_ascii=False, default=_json_default),
                bound_action_id,
                bound_state_version,
                payload_hash,
            ),
        )
        if commit and hasattr(self.conn, "commit"):
            self.conn.commit()
        row = cursor.fetchone()
        return row["sequence"] if row else 0

    def get_events(
        self,
        room_id: str,
        since_sequence: int = 0,
        limit: int = 100,
    ) -> list[EventLogEntry]:
        rows = self.conn.execute(
            "SELECT sequence, room_id, event_type, audience, payload, action_id, "
            "state_version, payload_hash, issued_at FROM events "
            "WHERE room_id = %s AND sequence > %s ORDER BY sequence LIMIT %s",
            (room_id, since_sequence, limit),
        ).fetchall()
        return [_event_entry(row) for row in rows]

    def _can_player_see_event(
        self,
        event_type: str,
        audience: str,
        payload: dict,
        character_id: str,
        sequence: int | None = None,
        action_id: str | None = None,
        state_version: int | None = None,
        room_id: str | None = None,
    ) -> bool:
        if event_type.startswith("s2c_fact_"):
            if (
                event_type not in FACT_REVEAL_EVENT_KINDS
                or not self._ledger_authorizes_event(
                    sequence,
                    event_type,
                    audience,
                    character_id,
                    payload,
                    action_id,
                    state_version,
                    room_id,
                )
            ):
                return False
        if audience == "host":
            return False
        if audience == "party":
            return True
        if audience == "player":
            cid = payload.get("characterId") or payload.get("character_id") or ""
            return cid == character_id
        if audience == "system":
            return event_type in PLAYER_VISIBLE_SYSTEM_EVENTS
        return False

    def get_events_for_player(
        self,
        room_id: str,
        character_id: str,
        since_sequence: int = 0,
        limit: int = 100,
        latest: bool = False,
    ) -> list[EventLogEntry]:
        order = "DESC" if latest else "ASC"
        rows = self.conn.execute(
            "SELECT sequence, room_id, event_type, audience, payload, action_id, "
            "state_version, payload_hash, issued_at FROM events "
            "WHERE room_id = %s AND sequence > %s AND audience != 'host' "
            f"ORDER BY sequence {order} LIMIT %s",
            (room_id, since_sequence, limit),
        ).fetchall()
        result = []
        for row in rows:
            payload = _decode_json(row["payload"])
            if self._can_player_see_event(
                row["event_type"], row["audience"], payload, character_id,
                row["sequence"], row.get("action_id"), row.get("state_version"),
                row.get("room_id"),
            ):
                result.append(_event_entry(row, payload=payload))
        return list(reversed(result)) if latest else result

    def get_public_events(
        self,
        room_id: str,
        since_sequence: int = 0,
        limit: int = 100,
    ) -> list[EventLogEntry]:
        rows = self.conn.execute(
            "SELECT sequence, room_id, event_type, audience, payload, action_id, "
            "state_version, payload_hash, issued_at FROM events "
            "WHERE room_id = %s AND sequence > %s "
            "AND (audience = 'party' OR (audience = 'system' AND event_type = ANY(%s))) "
            "ORDER BY sequence LIMIT %s",
            (room_id, since_sequence, list(PLAYER_VISIBLE_SYSTEM_EVENTS), limit),
        ).fetchall()
        result = []
        for row in rows:
            payload = _decode_json(row["payload"])
            if row["event_type"].startswith("s2c_fact_"):
                if (
                    row["event_type"] not in FACT_REVEAL_EVENT_KINDS
                    or not self._ledger_authorizes_event(
                        row["sequence"],
                        row["event_type"],
                        row["audience"],
                        None,
                        payload,
                        row.get("action_id"),
                        row.get("state_version"),
                        row.get("room_id"),
                    )
                ):
                    continue
            result.append(_event_entry(row, payload=payload))
        return result

    def _ledger_authorizes_event(
        self,
        sequence: int | None,
        event_type: str,
        audience: str,
        character_id: str | None,
        payload: dict,
        action_id: str | None,
        state_version: int | None,
        room_id: str | None,
    ) -> bool:
        if (
            sequence is None
            or not room_id
            or not action_id
            or state_version is None
        ):
            return False
        try:
            row = self.conn.execute(
                "SELECT reveal_id, room_id, fact_id, content_item_id, fact_text, citation, "
                "audience, target_character_id, source_action_id, state_version, "
                "record_kind, status, corrects_reveal_id, reason_code "
                "FROM fact_reveals WHERE event_sequence = %s",
                (sequence,),
            ).fetchone()
        except Exception:
            return False
        if not row:
            return False
        if row.get("room_id") != room_id:
            return False
        if row.get("record_kind") != FACT_REVEAL_EVENT_KINDS.get(event_type):
            return False
        if row.get("audience") != audience:
            return False
        if audience == "player" and not (
            character_id
            and row.get("target_character_id") == character_id
        ):
            return False
        if audience not in {"party", "player"}:
            return False
        if row.get("source_action_id") != action_id:
            return False
        if int(row.get("state_version") or 0) != int(state_version):
            return False
        expected = {
            "revealId": row["reveal_id"],
            "factId": row["fact_id"],
            "status": row["status"],
        }
        if row["record_kind"] == "reveal":
            expected.update({
                "contentItemId": row.get("content_item_id") or "",
                "factText": row.get("fact_text") or "",
                "citation": redact_citation(_decode_json(row.get("citation"))),
            })
        else:
            expected.update({
                "correctsRevealId": row.get("corrects_reveal_id") or "",
                "reasonCode": row.get("reason_code") or "",
            })
            if row.get("fact_text"):
                expected["factText"] = row["fact_text"]
                expected["citation"] = redact_citation(
                    _decode_json(row.get("citation"))
                )
        if audience == "player":
            expected["characterId"] = row.get("target_character_id") or ""
        canonical_payload = _canonical_exact_json(payload)
        return (
            canonical_payload is not None
            and canonical_payload == _canonical_exact_json(expected)
        )

    def create_checkpoint(
        self,
        room_id: str,
        checkpoint_id: str | None = None,
        auto: bool = False,
        reason: str = "",
    ) -> Checkpoint:
        checkpoint_id = checkpoint_id or str(uuid.uuid4())[:8]
        checkpoint_type = "auto" if auto else "manual"
        created_at = datetime.now(timezone.utc)
        with self.conn.transaction() as tx:
            self._backfill_event_integrity(tx, room_id)
            snapshot = self._build_snapshot(room_id, executor=tx)
            boundary = snapshot["_checkpoint"]
            invariant_report = validate_runtime_snapshot(snapshot, room_id)
            verification_status = "verified" if invariant_report["valid"] else "invalid"
            snapshot_hash = checkpoint_snapshot_hash(snapshot)
            tx.execute(
                "INSERT INTO checkpoints "
                "(checkpoint_id, room_id, state_snapshot, schema_version, state_version, "
                "event_sequence, snapshot_sha256, invariant_report, verification_status, "
                "checkpoint_type, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    checkpoint_id,
                    room_id,
                    json.dumps(snapshot, ensure_ascii=False, default=_json_default),
                    CHECKPOINT_SCHEMA_VERSION,
                    boundary["stateVersion"],
                    boundary["eventSequence"],
                    snapshot_hash,
                    json.dumps(invariant_report, ensure_ascii=False),
                    verification_status,
                    checkpoint_type,
                    created_at,
                ),
            )

        self.log_event(
            room_id,
            "s2c_checkpoint_created",
            "system",
            {
                "checkpointId": checkpoint_id,
                "checkpointType": checkpoint_type,
                "reason": reason,
                "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
                "stateVersion": boundary["stateVersion"],
                "eventSequence": boundary["eventSequence"],
                "snapshotSha256": snapshot_hash,
                "verificationStatus": verification_status,
            },
            state_version=boundary["stateVersion"],
        )

        if auto:
            self._cleanup_old_auto_checkpoints(room_id)

        return Checkpoint(
            checkpoint_id=checkpoint_id,
            room_id=room_id,
            state_snapshot=snapshot,
            schema_version=CHECKPOINT_SCHEMA_VERSION,
            state_version=boundary["stateVersion"],
            event_sequence=boundary["eventSequence"],
            snapshot_sha256=snapshot_hash,
            invariant_report=invariant_report,
            verification_status=verification_status,
            checkpoint_type=checkpoint_type,
            created_at=created_at.isoformat(),
        )

    def _cleanup_old_auto_checkpoints(self, room_id: str) -> None:
        rows = self.conn.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE room_id = %s "
            "AND checkpoint_type = 'auto' ORDER BY created_at DESC",
            (room_id,),
        ).fetchall()
        for row in rows[MAX_AUTO_CHECKPOINTS:]:
            self.conn.execute(
                "DELETE FROM checkpoints WHERE checkpoint_id = %s",
                (row["checkpoint_id"],),
            )
        if rows[MAX_AUTO_CHECKPOINTS:] and hasattr(self.conn, "commit"):
            self.conn.commit()

    @staticmethod
    def _backfill_event_integrity(executor, room_id: str) -> None:
        room = executor.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        fallback_state_version = int(room.get("state_version") or 0) if room else 0
        rows = executor.execute(
            "SELECT sequence, payload, action_id, state_version, payload_hash FROM events "
            "WHERE room_id = %s AND (payload_hash = '' OR payload_hash IS NULL "
            "OR state_version IS NULL)",
            (room_id,),
        ).fetchall()
        for row in rows:
            payload = _decode_json(row.get("payload"))
            state_version = row.get("state_version")
            if state_version is None:
                state_version = _payload_state_version(payload)
            if state_version is None:
                state_version = fallback_state_version
            action_id = row.get("action_id") or _payload_action_id(payload) or None
            executor.execute(
                "UPDATE events SET action_id = %s, state_version = %s, payload_hash = %s "
                "WHERE sequence = %s AND room_id = %s",
                (
                    action_id,
                    int(state_version),
                    checkpoint_snapshot_hash(payload),
                    row["sequence"],
                    room_id,
                ),
            )

    def dry_run_restore(self, room_id: str, checkpoint_id: str) -> dict[str, Any]:
        row = self._checkpoint_row(self.conn, room_id, checkpoint_id)
        snapshot = self._verify_checkpoint_row(row, room_id)
        current = self._build_snapshot(room_id)
        current_room = self.conn.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        return {
            "verified": True,
            "checkpointId": checkpoint_id,
            "checkpointHash": row["snapshot_sha256"],
            "checkpointStateVersion": int(row["state_version"]),
            "currentStateVersion": int(current_room.get("state_version") or 0),
            "eventSequence": int(row["event_sequence"]),
            "invariantReport": _decode_json(row["invariant_report"]),
            "diff": checkpoint_diff(current, snapshot),
        }

    def restore_checkpoint(
        self,
        room_id: str,
        checkpoint_id: str,
        *,
        expected_current_state_version: int | None = None,
        automatic: bool = False,
    ) -> dict:
        try:
            initial_row = self._checkpoint_row(self.conn, room_id, checkpoint_id)
            self._verify_checkpoint_row(initial_row, room_id)
        except CheckpointIntegrityError as exc:
            self._mark_integrity_failure(room_id, exc.code, "checkpoint_restore")
            raise

        try:
            with self.conn.transaction() as tx:
                room = tx.execute(
                    "SELECT * FROM rooms WHERE room_id = %s FOR UPDATE",
                    (room_id,),
                ).fetchone()
                if not room:
                    raise ValueError(f"Room {room_id} not found")
                current_state_version = int(room.get("state_version") or 0)
                if (
                    expected_current_state_version is not None
                    and current_state_version != int(expected_current_state_version)
                ):
                    raise CheckpointIntegrityError("current_state_changed")
                row = self._checkpoint_row(tx, room_id, checkpoint_id)
                snapshot = self._verify_checkpoint_row(row, room_id)
                checkpoint_risk_hash = snapshot.get("room", {}).get("risk_contract_hash")
                if checkpoint_risk_hash != room.get("risk_contract_hash"):
                    raise CheckpointIntegrityError("risk_contract_changed")
                room_snapshot = snapshot["room"]
                for binding_field in (
                    "scenario_id",
                    "scenario_version_id",
                    "runtime_package_version_id",
                ):
                    if room_snapshot.get(binding_field) != room.get(binding_field):
                        raise CheckpointIntegrityError("room_run_binding_changed")
                self._apply_snapshot(tx, room_id, snapshot)
                new_state_version = current_state_version + 1
                tx.execute(
                    "UPDATE rooms SET status = %s, spoiler_level = %s, "
                    "state_version = %s, integrity_status = 'healthy', integrity_reason = NULL, "
                    "integrity_source = NULL, "
                    "integrity_state_version = %s, integrity_updated_at = NOW() "
                    "WHERE room_id = %s",
                    (
                        room_snapshot.get("status") or room.get("status") or "paused",
                        room_snapshot.get("spoiler_level") or room.get("spoiler_level") or "standard",
                        new_state_version,
                        new_state_version,
                        room_id,
                    ),
                )
        except CheckpointIntegrityError as exc:
            if exc.code not in {"current_state_changed"}:
                self._mark_integrity_failure(room_id, exc.code, "checkpoint_restore")
            raise
        except Exception:
            self._mark_integrity_failure(
                room_id,
                "checkpoint_apply_failed",
                "automatic_recovery" if automatic else "manual_recovery",
            )
            raise

        return snapshot

    def list_checkpoints(self, room_id: str) -> list[Checkpoint]:
        rows = self.conn.execute(
            "SELECT checkpoint_id, room_id, state_snapshot, schema_version, state_version, "
            "event_sequence, snapshot_sha256, invariant_report, verification_status, "
            "checkpoint_type, created_at FROM checkpoints "
            "WHERE room_id = %s ORDER BY created_at DESC",
            (room_id,),
        ).fetchall()
        return [
            Checkpoint(
                checkpoint_id=row["checkpoint_id"],
                room_id=row["room_id"],
                state_snapshot=_decode_json(row["state_snapshot"]),
                schema_version=int(row.get("schema_version") or 1),
                state_version=int(row.get("state_version") or 0),
                event_sequence=int(row.get("event_sequence") or 0),
                snapshot_sha256=str(row.get("snapshot_sha256") or ""),
                invariant_report=_decode_json(row.get("invariant_report")),
                verification_status=str(row.get("verification_status") or "unverified"),
                checkpoint_type=str(row.get("checkpoint_type") or "manual"),
                created_at=_to_iso(row["created_at"]),
            )
            for row in rows
        ]

    def _checkpoint_row(self, executor, room_id: str, checkpoint_id: str) -> dict:
        row = executor.execute(
            "SELECT checkpoint_id, room_id, state_snapshot, schema_version, state_version, "
            "event_sequence, snapshot_sha256, invariant_report, verification_status "
            "FROM checkpoints WHERE checkpoint_id = %s AND room_id = %s",
            (checkpoint_id, room_id),
        ).fetchone()
        if not row:
            raise ValueError(f"Checkpoint {checkpoint_id} not found for room {room_id}")
        return dict(row)

    @staticmethod
    def _verify_checkpoint_row(row: dict, room_id: str) -> dict[str, Any]:
        snapshot = _decode_json(row.get("state_snapshot"))
        if int(row.get("schema_version") or 0) != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointIntegrityError("checkpoint_schema_unsupported")
        actual_hash = checkpoint_snapshot_hash(snapshot)
        if actual_hash != str(row.get("snapshot_sha256") or ""):
            raise CheckpointIntegrityError("checkpoint_hash_mismatch")
        report = validate_runtime_snapshot(snapshot, room_id)
        if not report["valid"]:
            raise CheckpointIntegrityError("checkpoint_invariant_failed")
        stored_report = _decode_json(row.get("invariant_report"))
        if checkpoint_snapshot_hash(report) != checkpoint_snapshot_hash(stored_report):
            raise CheckpointIntegrityError("checkpoint_report_mismatch")
        if str(row.get("verification_status") or "") != "verified":
            raise CheckpointIntegrityError("checkpoint_not_verified")
        boundary = snapshot.get("_checkpoint") or {}
        if (
            int(boundary.get("stateVersion") or 0) != int(row.get("state_version") or 0)
            or int(boundary.get("eventSequence") or 0) != int(row.get("event_sequence") or 0)
            or int(boundary.get("schemaVersion") or 0) != int(row.get("schema_version") or 0)
        ):
            raise CheckpointIntegrityError("checkpoint_boundary_mismatch")
        return snapshot

    def _build_snapshot(self, room_id: str, *, executor=None) -> dict[str, Any]:
        executor = executor or self.conn
        room_columns = ", ".join(ROOM_SNAPSHOT_COLUMNS)
        room = executor.execute(
            f"SELECT {room_columns} FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        if not room:
            raise ValueError(f"Room {room_id} not found")
        event_row = executor.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS event_sequence "
            "FROM events WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        snapshot: dict[str, Any] = {
            "_checkpoint": {
                "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
                "stateVersion": int(room.get("state_version") or 0),
                "eventSequence": int(event_row.get("event_sequence") or 0),
            },
            "room": sanitize_checkpoint_value(dict(room)),
        }
        for table, columns in SNAPSHOT_TABLE_COLUMNS.items():
            column_sql = ", ".join(columns)
            if table == "clue_shares":
                rows = executor.execute(
                    f"SELECT {', '.join(f'shares.{column}' for column in columns)} "
                    "FROM clue_shares AS shares JOIN clues "
                    "ON clues.clue_id = shares.clue_id "
                    "WHERE clues.room_id = %s OR shares.room_id = %s",
                    (room_id, room_id),
                ).fetchall()
            elif table == "encounter_participants":
                rows = executor.execute(
                    f"SELECT {', '.join(f'participants.{column}' for column in columns)} "
                    "FROM encounter_participants AS participants JOIN encounters "
                    "ON encounters.encounter_id = participants.encounter_id "
                    "WHERE encounters.room_id = %s",
                    (room_id,),
                ).fetchall()
            else:
                rows = executor.execute(
                    f"SELECT {column_sql} FROM {table} WHERE room_id = %s",
                    (room_id,),
                ).fetchall()
            snapshot[table] = sanitize_checkpoint_value([dict(row) for row in rows])
        return snapshot

    def _apply_snapshot(self, tx, room_id: str, snapshot: dict[str, Any]) -> None:
        roster = {
            str(row.get("character_id") or ""): row
            for row in snapshot.get("characters", [])
        }
        if roster:
            current_rows = tx.execute(
                "SELECT character_id FROM characters WHERE room_id = %s",
                (room_id,),
            ).fetchall()
            current_ids = {str(row["character_id"]) for row in current_rows}
            if set(roster) != current_ids:
                raise CheckpointIntegrityError("character_roster_changed")

        for table in SNAPSHOT_DELETE_ORDER:
            if table == "encounter_participants":
                tx.execute(
                    "DELETE FROM encounter_participants WHERE encounter_id IN "
                    "(SELECT encounter_id FROM encounters WHERE room_id = %s)",
                    (room_id,),
                )
            elif table == "clue_shares":
                tx.execute(
                    "DELETE FROM clue_shares WHERE room_id = %s OR clue_id IN "
                    "(SELECT clue_id FROM clues WHERE room_id = %s)",
                    (room_id, room_id),
                )
            else:
                tx.execute(f"DELETE FROM {table} WHERE room_id = %s", (room_id,))

        for character_id, row in roster.items():
            tx.execute(
                "UPDATE characters SET status = %s, is_ready = %s "
                "WHERE character_id = %s AND room_id = %s",
                (
                    row.get("status") or "joined",
                    bool(row.get("is_ready")),
                    character_id,
                    room_id,
                ),
            )

        for table in SNAPSHOT_INSERT_ORDER:
            if table == "characters":
                continue
            allowed_columns = SNAPSHOT_TABLE_COLUMNS[table]
            for raw_row in snapshot.get(table, []):
                row = dict(raw_row)
                columns = [column for column in allowed_columns if column in row]
                if "room_id" in allowed_columns:
                    row["room_id"] = room_id
                    if "room_id" not in columns:
                        columns.append("room_id")
                placeholders = ", ".join(["%s"] * len(columns))
                tx.execute(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                    tuple(_safe_val(row[column]) for column in columns),
                )
        tx.execute(
            "UPDATE character_runtime_state AS runtime SET profile_id = characters.profile_id "
            "FROM characters WHERE runtime.room_id = %s "
            "AND characters.room_id = runtime.room_id "
            "AND characters.character_id = runtime.character_id",
            (room_id,),
        )

    def _mark_integrity_failure(self, room_id: str, reason: str, source: str) -> None:
        self.conn.execute(
            "UPDATE rooms SET integrity_status = 'read_only_recovery', "
            "integrity_reason = %s, integrity_source = %s, "
            "integrity_state_version = state_version, integrity_updated_at = NOW() "
            "WHERE room_id = %s",
            (reason, source, room_id),
        )
        if hasattr(self.conn, "commit"):
            self.conn.commit()


def _event_entry(row: dict, *, payload: dict | None = None) -> EventLogEntry:
    return EventLogEntry(
        sequence=row["sequence"],
        room_id=row["room_id"],
        event_type=row["event_type"],
        audience=row["audience"],
        payload=payload if payload is not None else _decode_json(row["payload"]),
        action_id=row.get("action_id"),
        state_version=row.get("state_version"),
        payload_hash=str(row.get("payload_hash") or ""),
        issued_at=_to_iso(row["issued_at"]),
    )


def _payload_action_id(payload: dict[str, Any]) -> str:
    return str(payload.get("actionId") or payload.get("action_id") or "").strip()


def _payload_state_version(payload: dict[str, Any]) -> int | None:
    value = payload.get("stateVersion", payload.get("state_version"))
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_val(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=_json_default)
    return value


def _decode_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _canonical_exact_json(value: Any) -> str | None:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None


def _to_iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
