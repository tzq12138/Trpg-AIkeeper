from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path


CUTOVER_CONFIRMATION = "BACKUP_AND_CLEAR_V2"
BACKUP_SCHEMA = "aikeeper.v2-cutover-backup"
BACKUP_VERSION = 4
LIVE_STATE_SCHEMA = "aikeeper.v2-cutover-live-state"
LIVE_STATE_PATH = "live_state.json"

_CUTOVER_LOCK_TABLES = (
    "rooms",
    "characters",
    "actions",
    "action_drafts",
    "action_draft_revisions",
    "action_review_requests",
    "action_status_events",
    "ai_call_logs",
    "campaign_archives",
    "campaign_sessions",
    "checkpoints",
    "clarifications",
    "clue_shares",
    "clues",
    "collaboration_contract_batches",
    "collaboration_contract_drafts",
    "collaboration_contract_participants",
    "collaboration_contracts",
    "compensation_transactions",
    "document_chunks",
    "encounter_participants",
    "encounter_pending_reactions",
    "encounters",
    "events",
    "fact_reveals",
    "evidence_cards",
    "evidence_comments",
    "evidence_links",
    "evidence_references",
    "host_states",
    "inventory",
    "inventory_transfer_requests",
    "objectives",
    "player_action_submissions",
    "player_device_sessions",
    "player_notes",
    "note_attachments",
    "player_sequences",
    "prepared_rule_actions",
    "private_data_access_audits",
    "resolution_bundles",
    "room_map_state",
    "room_player_settings",
    "room_rule_bindings",
    "room_scene_state",
    "room_turns",
    "session_attendance",
    "session_summaries",
    "session_summary_citations",
    "session_zero_confirmations",
    "spoiler_audits",
    "character_map_positions",
    "character_runtime_state",
)
_CUTOVER_SNAPSHOT_TABLES = _CUTOVER_LOCK_TABLES

_BACKUP_SENSITIVE_KEYS = {
    "accountid",
    "authorization",
    "errormessage",
    "finaltext",
    "originaltext",
    "ownertoken",
    "passwordhash",
    "playername",
    "playertoken",
    "rawtext",
    "responsesummary",
    "spoilerhititems",
    "unlocksnapshot",
    "violations",
    "xlsxdata",
}


class V2CutoverError(RuntimeError):
    pass


class V2CutoverService:
    def __init__(self, conn, backup_root: Path):
        self.conn = conn
        self.backup_root = Path(backup_root)

    def backup_and_clear(self, confirmation: str, *, requested_by: str) -> dict:
        if confirmation != CUTOVER_CONFIRMATION:
            raise V2CutoverError("V2 切换确认短语不正确")
        self.backup_root.mkdir(parents=True, exist_ok=True)
        backup_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"v2-cutover-{timestamp}-{backup_id[:8]}.zip"
        destination = (self.backup_root / filename).resolve()
        root = self.backup_root.resolve()
        if root not in destination.parents:
            raise V2CutoverError("V2 备份路径无效")

        backup_written = False
        try:
            with self.conn.transaction() as tx:
                tx.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                tx.execute(
                    "LOCK TABLE "
                    + ", ".join(_CUTOVER_LOCK_TABLES)
                    + " IN SHARE ROW EXCLUSIVE MODE"
                )
                tx.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ("aikeeper:v2-cutover",),
                )
                room_rows = tx.execute(
                    "SELECT room_id FROM rooms ORDER BY room_id"
                ).fetchall()
                room_ids = [str(row["room_id"]) for row in room_rows]
                backup_bytes = self._build_backup(tx, room_ids)
                backup_sha256 = hashlib.sha256(backup_bytes).hexdigest()
                if not self._verify_backup(backup_bytes, room_ids):
                    raise V2CutoverError("V2 备份校验失败，未清理任何房间")
                temporary = destination.with_suffix(".tmp")
                temporary.write_bytes(backup_bytes)
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != backup_sha256:
                    temporary.unlink(missing_ok=True)
                    raise V2CutoverError("V2 备份落盘校验失败，未清理任何房间")
                os.replace(temporary, destination)
                backup_written = True
                tx.execute(
                    "INSERT INTO v2_cutover_records "
                    "(cutover_id, status, room_count, backup_path, backup_sha256, requested_by) "
                    "VALUES (%s, 'verified', %s, %s, %s, %s)",
                    (
                        backup_id,
                        len(room_ids),
                        str(destination),
                        backup_sha256,
                        requested_by,
                    ),
                )
                self._clear_rooms(tx, room_ids)
                tx.execute(
                    "UPDATE v2_cutover_records SET status = 'complete', completed_at = NOW() "
                    "WHERE cutover_id = %s",
                    (backup_id,),
                )
        except Exception:
            if backup_written:
                destination.unlink(missing_ok=True)
            raise

        return {
            "cutover_id": backup_id,
            "status": "complete",
            "rooms_backed_up": len(room_ids),
            "rooms_cleared": len(room_ids),
            "backup_filename": filename,
            "backup_sha256": backup_sha256,
        }

    def _build_backup(self, executor, room_ids: list[str]) -> bytes:
        live_state = self._build_live_state_snapshot(executor, room_ids)
        live_state_bytes = json.dumps(
            live_state,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest = {
            "schema": BACKUP_SCHEMA,
            "version": BACKUP_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "room_ids": room_ids,
            "table_counts": live_state["table_counts"],
            "table_inventory": live_state["table_inventory"],
            "files": [{
                "path": LIVE_STATE_PATH,
                "sha256": hashlib.sha256(live_state_bytes).hexdigest(),
                "size": len(live_state_bytes),
            }],
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            )
            archive.writestr(LIVE_STATE_PATH, live_state_bytes)
        return buffer.getvalue()

    def _build_live_state_snapshot(self, executor, room_ids: list[str]) -> dict:
        tables: dict[str, list[dict]] = {
            table: []
            for table in _CUTOVER_SNAPSHOT_TABLES
        }
        if not room_ids:
            table_inventory = _build_table_inventory(tables)
            return {
                "schema": LIVE_STATE_SCHEMA,
                "room_ids": [],
                "table_counts": {
                    table: item["count"]
                    for table, item in table_inventory.items()
                },
                "table_inventory": table_inventory,
                "tables": tables,
            }
        room_filter = "(" + ",".join(["%s"] * len(room_ids)) + ")"
        room_params = tuple(room_ids)

        def ids(table: str, column: str) -> list[str]:
            rows = executor.execute(
                f"SELECT {column} FROM {table} "
                f"WHERE room_id IN {room_filter} ORDER BY {column}",
                room_params,
            ).fetchall()
            return [
                str(row[column])
                for row in rows
                if row.get(column) not in (None, "")
            ]

        character_ids = ids("characters", "character_id")
        action_ids = ids("actions", "action_id")
        encounter_ids = ids("encounters", "encounter_id")
        clue_ids = ids("clues", "clue_id")
        contract_ids = ids("collaboration_contracts", "contract_id")
        campaign_session_ids = ids("campaign_sessions", "campaign_session_id")
        draft_ids = ids("action_drafts", "draft_id")
        note_ids = ids("player_notes", "note_id")
        session_summary_ids = ids("session_summaries", "session_summary_id")
        evidence_card_ids = ids("evidence_cards", "evidence_card_id")
        selectors = {
            "room_id": room_ids,
            "character_id": character_ids,
            "owner_character_id": character_ids,
            "from_character_id": character_ids,
            "to_character_id": character_ids,
            "attacker_id": character_ids,
            "initiator_character_id": character_ids,
            "started_by_character_id": character_ids,
            "action_id": action_ids,
            "source_action_id": action_ids,
            "target_action_id": action_ids,
            "encounter_id": encounter_ids,
            "clue_id": clue_ids,
            "contract_id": contract_ids,
            "campaign_session_id": campaign_session_ids,
            "draft_id": draft_ids,
            "note_id": note_ids,
            "session_summary_id": session_summary_ids,
            "evidence_card_id": evidence_card_ids,
        }
        selector_columns = [
            column
            for column, values in selectors.items()
            if values
        ]
        column_filter = "(" + ",".join(["%s"] * len(selector_columns)) + ")"
        schema_rows = executor.execute(
            "SELECT table_name, column_name "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name IN "
            f"({','.join(['%s'] * len(_CUTOVER_SNAPSHOT_TABLES))}) "
            "AND column_name IN "
            f"{column_filter} ORDER BY table_name, ordinal_position",
            (*_CUTOVER_SNAPSHOT_TABLES, *selector_columns),
        ).fetchall()
        table_columns: dict[str, list[str]] = {}
        for row in schema_rows:
            table_columns.setdefault(str(row["table_name"]), []).append(
                str(row["column_name"])
            )

        for table_name, columns in table_columns.items():
            clauses = []
            params: list[str] = []
            for column in columns:
                values = selectors.get(column) or []
                if not values:
                    continue
                value_filter = "(" + ",".join(["%s"] * len(values)) + ")"
                clauses.append(f'"{column}" IN {value_filter}')
                params.extend(values)
            if not clauses:
                continue
            rows = executor.execute(
                f'SELECT * FROM "{table_name}" WHERE ' + " OR ".join(clauses),
                tuple(params),
            ).fetchall()
            if rows:
                redacted_rows = [
                    _redact_backup_value(dict(row))
                    for row in rows
                ]
                redacted_rows.sort(
                    key=lambda row: json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                tables[table_name] = redacted_rows
        table_inventory = _build_table_inventory(tables)
        return {
            "schema": LIVE_STATE_SCHEMA,
            "room_ids": room_ids,
            "table_counts": {
                table: item["count"]
                for table, item in table_inventory.items()
            },
            "table_inventory": table_inventory,
            "tables": dict(sorted(tables.items())),
        }

    def _verify_backup(self, backup_bytes: bytes, expected_room_ids: list[str]) -> bool:
        try:
            with zipfile.ZipFile(io.BytesIO(backup_bytes)) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if (
                    manifest.get("schema") != BACKUP_SCHEMA
                    or manifest.get("version") != BACKUP_VERSION
                    or manifest.get("room_ids") != expected_room_ids
                ):
                    return False
                entries = manifest.get("files") or []
                expected_paths = {LIVE_STATE_PATH}
                if {entry.get("path") for entry in entries} != expected_paths:
                    return False
                if set(archive.namelist()) != {"manifest.json", LIVE_STATE_PATH}:
                    return False
                for entry in entries:
                    payload = archive.read(entry["path"])
                    if len(payload) != entry["size"]:
                        return False
                    if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                        return False
                live_state = json.loads(archive.read(LIVE_STATE_PATH))
                tables = live_state.get("tables") or {}
                actual_inventory = _build_table_inventory(tables)
                if (
                    live_state.get("schema") != LIVE_STATE_SCHEMA
                    or live_state.get("room_ids") != expected_room_ids
                    or set(tables) != set(_CUTOVER_SNAPSHOT_TABLES)
                    or set(manifest.get("table_inventory") or {})
                    != set(_CUTOVER_SNAPSHOT_TABLES)
                    or live_state.get("table_inventory") != actual_inventory
                    or manifest.get("table_inventory") != actual_inventory
                    or live_state.get("table_counts")
                    != manifest.get("table_counts")
                    or any(
                        live_state["table_counts"].get(table) != len(rows)
                        for table, rows in (live_state.get("tables") or {}).items()
                    )
                    or _contains_sensitive_backup_key(live_state)
                ):
                    return False
        except (KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError):
            return False
        return True

    @staticmethod
    def _clear_rooms(tx, room_ids: list[str]) -> None:
        from .router_admin import _delete_room_rows

        for room_id in room_ids:
            _delete_room_rows(tx, [room_id])


def _normalized_key(value: str) -> str:
    return "".join(
        character
        for character in value.lower()
        if character.isalnum()
    )


def _redact_backup_value(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = _normalized_key(str(key))
            if (
                normalized in _BACKUP_SENSITIVE_KEYS
                or normalized.endswith("accountid")
                or normalized.endswith("token")
                or normalized.endswith("secret")
                or normalized.endswith("ciphertext")
            ):
                continue
            result[str(key)] = _redact_backup_value(item)
        return result
    if isinstance(value, list):
        return [_redact_backup_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_backup_value(item) for item in value]
    if isinstance(value, bytes):
        return f"<redacted-bytes:{len(value)}>"
    if isinstance(value, memoryview):
        return f"<redacted-bytes:{len(value)}>"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _contains_sensitive_backup_key(value) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = _normalized_key(str(key))
            if (
                normalized in _BACKUP_SENSITIVE_KEYS
                or normalized.endswith("accountid")
                or normalized.endswith("token")
                or normalized.endswith("secret")
                or normalized.endswith("ciphertext")
                or _contains_sensitive_backup_key(item)
            ):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_backup_key(item) for item in value)
    return False


def _build_table_inventory(tables: dict[str, list[dict]]) -> dict[str, dict]:
    result = {}
    for table in sorted(_CUTOVER_SNAPSHOT_TABLES):
        rows = tables.get(table) or []
        canonical = json.dumps(
            rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        result[table] = {
            "count": len(rows),
            "sha256": hashlib.sha256(canonical).hexdigest(),
        }
    return result
