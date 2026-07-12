from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .room_migration import build_room_package, inspect_room_package


CUTOVER_CONFIRMATION = "BACKUP_AND_CLEAR_V2"
BACKUP_SCHEMA = "aikeeper.v2-cutover-backup"
BACKUP_VERSION = 1


class V2CutoverError(RuntimeError):
    pass


class V2CutoverService:
    def __init__(self, conn, backup_root: Path):
        self.conn = conn
        self.backup_root = Path(backup_root)

    def backup_and_clear(self, confirmation: str, *, requested_by: str) -> dict:
        if confirmation != CUTOVER_CONFIRMATION:
            raise V2CutoverError("V2 切换确认短语不正确")
        room_rows = self.conn.execute(
            "SELECT room_id FROM rooms WHERE player_experience_version = 'v2' "
            "ORDER BY room_id"
        ).fetchall()
        room_ids = [str(row["room_id"]) for row in room_rows]
        backup_bytes = self._build_backup(room_ids)
        backup_sha256 = hashlib.sha256(backup_bytes).hexdigest()
        if not self._verify_backup(backup_bytes, room_ids):
            raise V2CutoverError("V2 备份校验失败，未清理任何房间")

        self.backup_root.mkdir(parents=True, exist_ok=True)
        backup_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"v2-cutover-{timestamp}-{backup_id[:8]}.zip"
        destination = (self.backup_root / filename).resolve()
        root = self.backup_root.resolve()
        if root not in destination.parents:
            raise V2CutoverError("V2 备份路径无效")
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(backup_bytes)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != backup_sha256:
            temporary.unlink(missing_ok=True)
            raise V2CutoverError("V2 备份落盘校验失败，未清理任何房间")
        os.replace(temporary, destination)

        with self.conn.transaction() as tx:
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

        return {
            "cutover_id": backup_id,
            "status": "complete",
            "rooms_backed_up": len(room_ids),
            "rooms_cleared": len(room_ids),
            "backup_filename": filename,
            "backup_sha256": backup_sha256,
        }

    def _build_backup(self, room_ids: list[str]) -> bytes:
        room_packages = {
            room_id: build_room_package(self.conn, room_id)
            for room_id in room_ids
        }
        manifest = {
            "schema": BACKUP_SCHEMA,
            "version": BACKUP_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "room_ids": room_ids,
            "files": [
                {
                    "path": f"rooms/{room_id}.zip",
                    "sha256": hashlib.sha256(room_packages[room_id]).hexdigest(),
                    "size": len(room_packages[room_id]),
                }
                for room_id in room_ids
            ],
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            )
            for room_id, package in room_packages.items():
                archive.writestr(f"rooms/{room_id}.zip", package)
        return buffer.getvalue()

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
                if len(entries) != len(expected_room_ids):
                    return False
                for entry in entries:
                    payload = archive.read(entry["path"])
                    if len(payload) != entry["size"]:
                        return False
                    if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                        return False
                    inspect_room_package(payload)
        except (KeyError, ValueError, zipfile.BadZipFile, json.JSONDecodeError):
            return False
        return True

    @staticmethod
    def _clear_rooms(tx, room_ids: list[str]) -> None:
        if not room_ids:
            return
        params = tuple(room_ids)
        room_filter = "(" + ",".join(["%s"] * len(room_ids)) + ")"
        character_rows = tx.execute(
            f"SELECT character_id FROM characters WHERE room_id IN {room_filter}",
            params,
        ).fetchall()
        character_ids = [str(row["character_id"]) for row in character_rows]
        action_rows = tx.execute(
            f"SELECT action_id FROM actions WHERE room_id IN {room_filter}",
            params,
        ).fetchall()
        action_ids = [str(row["action_id"]) for row in action_rows]
        if action_ids:
            action_filter = "(" + ",".join(["%s"] * len(action_ids)) + ")"
            tx.execute(
                f"DELETE FROM action_review_requests WHERE action_id IN {action_filter}",
                tuple(action_ids),
            )
            tx.execute(
                f"DELETE FROM action_status_events WHERE action_id IN {action_filter}",
                tuple(action_ids),
            )

        for table in (
            "compensation_transactions",
            "room_player_settings",
            "player_device_sessions",
            "session_summaries",
            "session_zero_confirmations",
            "player_notes",
            "private_data_access_audits",
            "evidence_cards",
            "evidence_links",
            "action_drafts",
            "campaign_sessions",
            "room_scene_state",
            "room_map_state",
            "character_map_positions",
            "character_runtime_state",
            "document_chunks",
            "clarifications",
            "inventory",
            "objectives",
            "spoiler_audits",
            "ai_call_logs",
            "player_sequences",
            "checkpoints",
            "campaign_archives",
            "events",
            "actions",
            "room_turns",
            "host_states",
            "room_rule_bindings",
        ):
            tx.execute(f"DELETE FROM {table} WHERE room_id IN {room_filter}", params)

        encounter_rows = tx.execute(
            f"SELECT encounter_id FROM encounters WHERE room_id IN {room_filter}", params
        ).fetchall()
        encounter_ids = [str(row["encounter_id"]) for row in encounter_rows]
        if encounter_ids:
            encounter_filter = "(" + ",".join(["%s"] * len(encounter_ids)) + ")"
            tx.execute(
                f"DELETE FROM encounter_participants WHERE encounter_id IN {encounter_filter}",
                tuple(encounter_ids),
            )
        tx.execute(f"DELETE FROM encounters WHERE room_id IN {room_filter}", params)

        clue_rows = tx.execute(
            f"SELECT clue_id FROM clues WHERE room_id IN {room_filter}", params
        ).fetchall()
        clue_ids = [str(row["clue_id"]) for row in clue_rows]
        if clue_ids:
            clue_filter = "(" + ",".join(["%s"] * len(clue_ids)) + ")"
            tx.execute(
                f"DELETE FROM clue_shares WHERE clue_id IN {clue_filter}", tuple(clue_ids)
            )
        tx.execute(f"DELETE FROM clues WHERE room_id IN {room_filter}", params)

        if character_ids:
            character_filter = "(" + ",".join(["%s"] * len(character_ids)) + ")"
            tx.execute(
                f"DELETE FROM characters WHERE character_id IN {character_filter}",
                tuple(character_ids),
            )
        tx.execute(f"DELETE FROM rooms WHERE room_id IN {room_filter}", params)
