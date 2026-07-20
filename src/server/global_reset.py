from __future__ import annotations

import hashlib
import io
import json
import os
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .room_migration import RoomMigrationError, build_room_package, inspect_room_package


BACKUP_SCHEMA = "aikeeper.global-reset-backup"
BACKUP_VERSION = 1
RETENTION_DAYS = 90
_BACKUP_ID_RE = re.compile(r"^[a-f0-9-]{36}$")


class GlobalResetError(RuntimeError):
    pass


@dataclass(frozen=True)
class GlobalResetBackup:
    backup_id: str
    sha256: str
    created_at: str
    counts: dict[str, int]
    downloaded_at: str | None = None


def collect_reset_counts(conn) -> dict[str, int]:
    return {
        "rooms": _count(conn, "rooms"),
        "characters": _count(conn, "characters"),
        "events": _count(conn, "events"),
        "actions": _count(conn, "actions"),
        "campaign_archives": _count(conn, "campaign_archives"),
    }


def create_global_reset_backup(conn, backup_dir: Path | None = None) -> GlobalResetBackup:
    directory = _prepare_backup_dir(backup_dir)
    _cleanup_expired_backups(directory)
    counts = collect_reset_counts(conn)
    room_rows = conn.execute("SELECT room_id FROM rooms ORDER BY room_id").fetchall()
    entries: list[dict[str, str]] = []
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        for row in room_rows:
            room_id = str(row["room_id"])
            room_package = build_room_package(conn, room_id)
            path = f"rooms/{room_id}.zip"
            archive.writestr(path, room_package)
            entries.append({"path": path, "sha256": hashlib.sha256(room_package).hexdigest()})
        manifest = {
            "schema": BACKUP_SCHEMA,
            "version": BACKUP_VERSION,
            "created_at": _utc_now(),
            "counts": counts,
            "files": entries,
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True))

    raw = payload.getvalue()
    backup = GlobalResetBackup(
        backup_id=str(uuid.uuid4()),
        sha256=hashlib.sha256(raw).hexdigest(),
        created_at=manifest["created_at"],
        counts=counts,
    )
    _backup_path(directory, backup.backup_id).write_bytes(raw)
    _metadata_path(directory, backup.backup_id).write_text(
        json.dumps(_backup_to_metadata(backup), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return backup


def download_global_reset_backup(backup_id: str, backup_dir: Path | None = None) -> tuple[GlobalResetBackup, bytes]:
    directory = _prepare_backup_dir(backup_dir)
    backup = _load_backup(directory, backup_id)
    raw = _backup_path(directory, backup_id).read_bytes()
    _validate_raw_backup(raw, backup.sha256)
    updated = GlobalResetBackup(
        backup_id=backup.backup_id,
        sha256=backup.sha256,
        created_at=backup.created_at,
        counts=backup.counts,
        downloaded_at=_utc_now(),
    )
    _metadata_path(directory, backup_id).write_text(
        json.dumps(_backup_to_metadata(updated), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return updated, raw


def verify_global_reset_backup(backup_id: str, backup_dir: Path | None = None) -> GlobalResetBackup:
    directory = _prepare_backup_dir(backup_dir)
    backup = _load_backup(directory, backup_id)
    raw = _backup_path(directory, backup_id).read_bytes()
    _validate_raw_backup(raw, backup.sha256)
    return backup


def execute_global_reset(conn, backup_id: str, backup_dir: Path | None = None) -> dict[str, int]:
    backup = verify_global_reset_backup(backup_id, backup_dir)
    if not backup.downloaded_at:
        raise GlobalResetError("必须先下载并确认备份包")

    deleted = collect_reset_counts(conn)
    tables = _room_data_tables(conn)
    try:
        for table in tables:
            if table == "document_chunks":
                conn.execute("DELETE FROM document_chunks WHERE room_id IS NOT NULL")
            else:
                conn.execute(f'DELETE FROM "{table}"')
        conn.execute("DELETE FROM characters")
        conn.execute("DELETE FROM rooms")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return deleted


def get_backup_dir() -> Path:
    configured = os.getenv("AIKEEPER_MIGRATION_BACKUP_DIR", "")
    if configured:
        return Path(configured)
    return Path(".runtime") / "migration-backups"


def _room_data_tables(conn) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT table_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND column_name IN ('room_id', 'character_id')"
    ).fetchall()
    protected = {"rooms", "characters"}
    tables = {
        str(row["table_name"])
        for row in rows
        if str(row["table_name"]) not in protected
    }
    return sorted(table for table in tables if re.fullmatch(r"[a-z_][a-z0-9_]*", table))


def _count(conn, table: str) -> int:
    row = conn.execute(f'SELECT COUNT(*) AS count FROM "{table}"').fetchone()
    return int(row["count"])


def _prepare_backup_dir(backup_dir: Path | None) -> Path:
    directory = backup_dir or get_backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _cleanup_expired_backups(directory: Path) -> None:
    threshold = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
    for metadata in directory.glob("*.json"):
        try:
            created_at = json.loads(metadata.read_text(encoding="utf-8")).get("created_at", "")
            if datetime.fromisoformat(created_at) >= threshold:
                continue
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        backup_id = metadata.stem
        metadata.unlink(missing_ok=True)
        _backup_path(directory, backup_id).unlink(missing_ok=True)


def _load_backup(directory: Path, backup_id: str) -> GlobalResetBackup:
    if not _BACKUP_ID_RE.fullmatch(backup_id):
        raise GlobalResetError("备份标识无效")
    metadata_path = _metadata_path(directory, backup_id)
    package_path = _backup_path(directory, backup_id)
    if not metadata_path.exists() or not package_path.exists():
        raise GlobalResetError("备份不存在或已过期")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return GlobalResetBackup(
            backup_id=backup_id,
            sha256=str(metadata["sha256"]),
            created_at=str(metadata["created_at"]),
            counts={key: int(value) for key, value in metadata["counts"].items()},
            downloaded_at=metadata.get("downloaded_at"),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GlobalResetError("备份元数据无效") from exc


def _validate_raw_backup(raw: bytes, expected_sha256: str) -> None:
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise GlobalResetError("备份包哈希校验失败")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("schema") != BACKUP_SCHEMA or manifest.get("version") != BACKUP_VERSION:
                raise GlobalResetError("备份包格式不受支持")
            files = manifest.get("files")
            if not isinstance(files, list):
                raise GlobalResetError("备份包文件清单无效")
            for entry in files:
                path = entry.get("path") if isinstance(entry, dict) else None
                expected = entry.get("sha256") if isinstance(entry, dict) else None
                if not isinstance(path, str) or not path.startswith("rooms/") or not isinstance(expected, str):
                    raise GlobalResetError("备份包文件清单无效")
                data = archive.read(path)
                if hashlib.sha256(data).hexdigest() != expected:
                    raise GlobalResetError("备份包内文件哈希校验失败")
                inspect_room_package(data)
    except (KeyError, OSError, RoomMigrationError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise GlobalResetError("备份包校验失败") from exc


def _backup_to_metadata(backup: GlobalResetBackup) -> dict[str, Any]:
    return {
        "backup_id": backup.backup_id,
        "sha256": backup.sha256,
        "created_at": backup.created_at,
        "counts": backup.counts,
        "downloaded_at": backup.downloaded_at,
    }


def _backup_path(directory: Path, backup_id: str) -> Path:
    return directory / f"{backup_id}.zip"


def _metadata_path(directory: Path, backup_id: str) -> Path:
    return directory / f"{backup_id}.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
