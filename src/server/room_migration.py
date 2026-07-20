import hashlib
import io
import json
import secrets
import uuid
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


PACKAGE_SCHEMA = "aikeeper.room-migration"
PACKAGE_VERSION = 1
PACKAGE_FILES = (
    "room.json",
    "characters.json",
    "objectives.json",
    "events.json",
    "player_notes.json",
)
MAX_PACKAGE_BYTES = 10 * 1024 * 1024


class RoomMigrationError(ValueError):
    pass


@dataclass(frozen=True)
class RoomMigrationPackage:
    manifest: dict[str, Any]
    room: dict[str, Any]
    characters: list[dict[str, Any]]
    objectives: list[dict[str, Any]]
    events: list[dict[str, Any]]
    player_notes: list[dict[str, Any]]

    @property
    def counts(self) -> dict[str, int]:
        return {
            "characters": len(self.characters),
            "objectives": len(self.objectives),
            "events": len(self.events),
            "player_notes": len(self.player_notes),
        }


def build_room_package(conn, room_id: str) -> bytes:
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise RoomMigrationError("房间不存在")

    payloads = {
        "room.json": _json_bytes(_export_room(dict(room))),
        "characters.json": _json_bytes([
            _export_character(dict(row))
            for row in conn.execute(
                "SELECT * FROM characters WHERE room_id = %s ORDER BY character_id", (room_id,)
            ).fetchall()
        ]),
        "objectives.json": _json_bytes([
            _json_safe(dict(row))
            for row in conn.execute(
                "SELECT * FROM objectives WHERE room_id = %s ORDER BY objective_id", (room_id,)
            ).fetchall()
        ]),
        "events.json": _json_bytes([
            _export_event(dict(row))
            for row in conn.execute(
                "SELECT * FROM events WHERE room_id = %s ORDER BY sequence", (room_id,)
            ).fetchall()
        ]),
        "player_notes.json": _json_bytes([
            _json_safe(dict(row))
            for row in conn.execute(
                "SELECT * FROM player_notes WHERE room_id = %s ORDER BY note_id", (room_id,)
            ).fetchall()
        ]),
    }
    manifest = {
        "schema": PACKAGE_SCHEMA,
        "version": PACKAGE_VERSION,
        "source_room_id": room_id,
        "files": [
            {
                "path": path,
                "sha256": hashlib.sha256(payloads[path]).hexdigest(),
                "size": len(payloads[path]),
            }
            for path in PACKAGE_FILES
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        for path in PACKAGE_FILES:
            archive.writestr(path, payloads[path])
    return buffer.getvalue()


def inspect_room_package(package_bytes: bytes) -> RoomMigrationPackage:
    if not package_bytes or len(package_bytes) > MAX_PACKAGE_BYTES:
        raise RoomMigrationError("迁移包为空或超过大小限制")
    try:
        with zipfile.ZipFile(io.BytesIO(package_bytes)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise RoomMigrationError("迁移包包含重复文件")
            if any(_unsafe_archive_path(name) for name in names):
                raise RoomMigrationError("迁移包包含非法文件路径")
            if "manifest.json" not in names:
                raise RoomMigrationError("迁移包缺少 manifest.json")

            manifest = _read_json(archive.read("manifest.json"), "manifest.json")
            _validate_manifest(manifest, names, archive)
            data = {
                path: _read_json(archive.read(path), path)
                for path in PACKAGE_FILES
            }
    except zipfile.BadZipFile as exc:
        raise RoomMigrationError("迁移包不是有效 ZIP") from exc

    if not isinstance(data["room.json"], dict):
        raise RoomMigrationError("room.json 必须是对象")
    for path in PACKAGE_FILES[1:]:
        if not isinstance(data[path], list) or not all(isinstance(item, dict) for item in data[path]):
            raise RoomMigrationError(f"{path} 必须是对象数组")
    if _contains_token_key(data):
        raise RoomMigrationError("迁移包不能包含 owner_token 或 player_token")

    return RoomMigrationPackage(
        manifest=manifest,
        room=data["room.json"],
        characters=data["characters.json"],
        objectives=data["objectives.json"],
        events=data["events.json"],
        player_notes=data["player_notes.json"],
    )


def import_room_package(conn, package: RoomMigrationPackage, owner_account_id: str) -> str:
    old_room_id = package.manifest.get("source_room_id", "")
    new_room_id = str(uuid.uuid4())[:8]
    character_ids = {
        item["character_id"]: str(uuid.uuid4())
        for item in package.characters
        if isinstance(item.get("character_id"), str) and item["character_id"]
    }
    objective_ids = {
        item["objective_id"]: str(uuid.uuid4())
        for item in package.objectives
        if isinstance(item.get("objective_id"), str) and item["objective_id"]
    }
    note_ids = {
        item["note_id"]: str(uuid.uuid4())
        for item in package.player_notes
        if isinstance(item.get("note_id"), str) and item["note_id"]
    }
    id_map = {old_room_id: new_room_id, **character_ids, **objective_ids, **note_ids}

    with conn.transaction() as tx:
        _insert_room(tx, new_room_id, package.room, owner_account_id)
        _insert_characters(tx, new_room_id, package.characters, character_ids)
        _insert_objectives(tx, new_room_id, package.objectives, objective_ids, id_map)
        _insert_events(tx, new_room_id, package.events, id_map)
        _insert_player_notes(tx, new_room_id, package.player_notes, note_ids, id_map)
    return new_room_id


def _export_room(room: dict[str, Any]) -> dict[str, Any]:
    for field in ("room_id", "owner_token", "owner_account_id"):
        room.pop(field, None)
    return _json_safe(room)


def _export_character(character: dict[str, Any]) -> dict[str, Any]:
    for field in ("room_id", "player_token", "account_id", "profile_id"):
        character.pop(field, None)
    return _json_safe(character)


def _export_event(event: dict[str, Any]) -> dict[str, Any]:
    event.pop("sequence", None)
    return _json_safe(_strip_token_fields(event))


def _insert_room(tx, room_id: str, room: dict[str, Any], owner_account_id: str) -> None:
    runtime_package_version_id = str(room.get("runtime_package_version_id") or "")
    if runtime_package_version_id:
        runtime_package = tx.execute(
            "SELECT 1 FROM runtime_package_versions "
            "WHERE runtime_package_version_id = %s AND scenario_version_id = %s "
            "AND gate_status = 'ready'",
            (runtime_package_version_id, room.get("scenario_version_id")),
        ).fetchone()
        if not runtime_package:
            runtime_package_version_id = ""
    tx.execute(
        "INSERT INTO rooms (room_id, scenario_id, scenario_version_id, runtime_package_version_id, owner_token, "
        "owner_account_id, status, spoiler_level, state_version, player_experience_version, "
        "action_pacing_preset, action_timing, draft_analysis_enabled, speech_routing, created_at, started_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, NOW()), %s)",
        (
            room_id,
            room.get("scenario_id"),
            room.get("scenario_version_id"),
            runtime_package_version_id or None,
            secrets.token_urlsafe(32),
            owner_account_id,
            room.get("status", "lobby"),
            room.get("spoiler_level", "standard"),
            room.get("state_version", 0),
            room.get("player_experience_version", "v2"),
            room.get("action_pacing_preset", "standard"),
            _as_json(room.get("action_timing")),
            room.get("draft_analysis_enabled", True),
            room.get("speech_routing", "party_message"),
            room.get("created_at"),
            room.get("started_at"),
        ),
    )


def _insert_characters(tx, room_id: str, characters: list[dict[str, Any]], character_ids: dict[str, str]) -> None:
    for character in characters:
        old_character_id = character.get("character_id")
        new_character_id = character_ids.get(old_character_id)
        if not new_character_id:
            raise RoomMigrationError("角色缺少 character_id")
        tx.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data, "
            "is_ready, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                new_character_id,
                room_id,
                character.get("player_name", "调查员"),
                secrets.token_urlsafe(32),
                _as_json(character.get("xlsx_data")),
                character.get("is_ready", False),
                character.get("status", "joined"),
            ),
        )


def _insert_objectives(tx, room_id: str, objectives: list[dict[str, Any]], objective_ids: dict[str, str], id_map: dict[str, str]) -> None:
    for objective in objectives:
        old_objective_id = objective.get("objective_id")
        new_objective_id = objective_ids.get(old_objective_id)
        if not new_objective_id:
            raise RoomMigrationError("目标缺少 objective_id")
        tx.execute(
            "INSERT INTO objectives (objective_id, room_id, character_id, text, type, status, assigned_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, NOW()))",
            (
                new_objective_id,
                room_id,
                id_map.get(objective.get("character_id")),
                objective.get("text", ""),
                objective.get("type", "team"),
                objective.get("status", "active"),
                objective.get("assigned_at"),
            ),
        )


def _insert_events(tx, room_id: str, events: list[dict[str, Any]], id_map: dict[str, str]) -> None:
    for event in events:
        tx.execute(
            "INSERT INTO events (room_id, event_type, audience, payload, issued_at) "
            "VALUES (%s, %s, %s, %s, COALESCE(%s, NOW()))",
            (
                room_id,
                event.get("event_type", "migration_event"),
                event.get("audience", "host"),
                _as_json(_remap_json_values(event.get("payload", {}), id_map)),
                event.get("issued_at"),
            ),
        )


def _insert_player_notes(tx, room_id: str, notes: list[dict[str, Any]], note_ids: dict[str, str], id_map: dict[str, str]) -> None:
    for note in notes:
        old_note_id = note.get("note_id")
        new_note_id = note_ids.get(old_note_id)
        if not new_note_id:
            raise RoomMigrationError("笔记缺少 note_id")
        tx.execute(
            "INSERT INTO player_notes (note_id, room_id, character_id, parent_note_id, "
            "title_ciphertext, body_ciphertext, visibility, is_redacted_copy, created_at, updated_at) "
            "VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, COALESCE(%s, NOW()), COALESCE(%s, NOW()))",
            (
                new_note_id,
                room_id,
                id_map.get(note.get("character_id")),
                note.get("title_ciphertext", ""),
                note.get("body_ciphertext", ""),
                note.get("visibility", "private"),
                note.get("is_redacted_copy", False),
                note.get("created_at"),
                note.get("updated_at"),
            ),
        )
    for note in notes:
        parent_note_id = note.get("parent_note_id")
        if parent_note_id:
            tx.execute(
                "UPDATE player_notes SET parent_note_id = %s WHERE note_id = %s",
                (note_ids.get(parent_note_id), note_ids[note["note_id"]]),
            )


def _validate_manifest(manifest: Any, names: list[str], archive: zipfile.ZipFile) -> None:
    if not isinstance(manifest, dict):
        raise RoomMigrationError("manifest.json 必须是对象")
    if manifest.get("schema") != PACKAGE_SCHEMA or manifest.get("version") != PACKAGE_VERSION:
        raise RoomMigrationError("不支持的迁移包 schema 或版本")
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != len(PACKAGE_FILES):
        raise RoomMigrationError("manifest 文件列表无效")
    expected_paths = set(PACKAGE_FILES)
    actual_paths = {entry.get("path") for entry in entries if isinstance(entry, dict)}
    if actual_paths != expected_paths or set(names) != expected_paths | {"manifest.json"}:
        raise RoomMigrationError("迁移包文件列表不匹配")
    for entry in entries:
        if not isinstance(entry.get("sha256"), str):
            raise RoomMigrationError("manifest 缺少 SHA-256")
        data = archive.read(entry["path"])
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RoomMigrationError(f"文件哈希校验失败: {entry['path']}")


def _read_json(data: bytes, name: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoomMigrationError(f"{name} 不是有效 JSON") from exc


def _unsafe_archive_path(path: str) -> bool:
    return not path or path.startswith(("/", "\\")) or ".." in path.replace("\\", "/").split("/")


def _contains_token_key(value: Any) -> bool:
    if isinstance(value, dict):
        if {"owner_token", "player_token"} & set(value):
            return True
        return any(_contains_token_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_token_key(item) for item in value)
    return False


def _strip_token_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_token_fields(item)
            for key, item in value.items()
            if key not in {"owner_token", "player_token"}
        }
    if isinstance(value, list):
        return [_strip_token_fields(item) for item in value]
    return value


def _remap_json_values(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, list):
        return [_remap_json_values(item, id_map) for item in value]
    if isinstance(value, dict):
        return {key: _remap_json_values(item, id_map) for key, item in value.items()}
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(_json_safe(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _as_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)
