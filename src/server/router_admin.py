"""Admin API router — requires admin-role account authentication."""
import asyncio
import json
import uuid
import os
import logging
import hashlib
import re
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import APIRouter, Request, Response, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse

from .campaign_archive import project_campaign_archive
from .router_auth import verify_token, get_account_from_token, _hash_password
from .runtime_lifecycle import (
    account_lifecycle_guard,
    character_lifecycle_guard,
    room_lifecycle_guard,
)

router = APIRouter(prefix="/api/admin")
logger = logging.getLogger(__name__)

ASSETS_ROOT = Path(os.path.dirname(__file__)).parent.parent / "data" / "scenario_assets"

# Allowed MIME types and extensions for asset upload
ALLOWED_MIME_TYPES = {
    "image/png", "image/jpeg", "image/webp", "image/gif",
    "audio/mpeg", "audio/wav", "audio/ogg", "audio/webm",
    "application/pdf",
}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp3", ".wav", ".ogg", ".webm", ".pdf"}
BLOCKED_EXTENSIONS = {".svg", ".html", ".htm", ".js", ".exe", ".sh", ".bat", ".ps1", ".php"}
MAX_ASSET_SIZE = 50 * 1024 * 1024  # 50 MB

# Magic bytes for file header validation
MAGIC_BYTES: dict[str, bytes] = {
    ".png": b'\x89PNG\r\n\x1a\n',
    ".jpg": b'\xff\xd8\xff',
    ".jpeg": b'\xff\xd8\xff',
    ".webp": b'RIFF',
    ".gif": b'GIF8',
    ".pdf": b'%PDF',
    ".mp3": b'\xff\xfb',  # MPEG audio frame sync
}


async def _safe_json(request: Request) -> dict:
    try:
        value = await request.json()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _get_account_id(request: Request) -> str:
    """Extract account_id from request token without raising. Returns 'unknown' if not authenticated."""
    try:
        account = get_account_from_token(request)
        return account.get("account_id", "unknown") if account else "unknown"
    except Exception:
        return "unknown"


def _require_admin(request: Request) -> dict:
    """Return authenticated admin account dict, or raise."""
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, "请先登录")
    if account.get("role") != "admin":
        raise HTTPException(403, "仅管理员可访问")
    # Touch last_seen_at
    try:
        request.app.state.db.execute(
            "UPDATE accounts SET last_seen_at = NOW() WHERE account_id = %s",
            (account["account_id"],),
        )
        request.app.state.db.commit()
    except Exception:
        pass
    return dict(account)


@asynccontextmanager
async def _governance_actor_guard(request: Request, account_id: str):
    conn = request.app.state.db
    async with account_lifecycle_guard([account_id], conn=conn):
        _assert_live_admin_actor(conn, account_id)
        yield conn


def _assert_live_admin_actor(conn, account_id: str) -> None:
    account = conn.execute(
        "SELECT account_id, role FROM accounts WHERE account_id = %s",
        (account_id,),
    ).fetchone()
    if not account:
        raise HTTPException(
            409,
            detail={"code": "governance_actor_deleted"},
        )
    if str(account.get("role") or "") != "admin":
        raise HTTPException(403, "administrator role required")


async def _get_id_list(request: Request, key: str) -> list[str]:
    payload = await _safe_json(request)
    value = payload.get(key, [])
    return _normalize_id_list(value, key)


async def _get_confirmed_id_list(request: Request, key: str) -> list[str]:
    payload = await _safe_json(request)
    if payload.get("confirm") is not True:
        raise HTTPException(400, "请确认后再执行删除")
    return _normalize_id_list(payload.get(key, []), key)


def _normalize_id_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise HTTPException(400, f"{field_name} must be a non-empty list")
    ids: list[str] = []
    seen: set[str] = set()
    for raw_id in value:
        if not isinstance(raw_id, str):
            raise HTTPException(400, f"{field_name} entries must be strings")
        normalized = raw_id.strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        ids.append(normalized)
    if not ids:
        raise HTTPException(400, f"{field_name} must contain at least one non-empty id")
    return ids


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT to_regclass(%s) IS NOT NULL AS exists",
        (f"public.{table_name}",),
    ).fetchone()
    return bool(row and row.get("exists"))


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table_name, column_name),
    ).fetchone()
    return bool(row)


def _in_clause(ids: list[str]) -> tuple[str, tuple[str, ...]]:
    return "(" + ",".join(["%s"] * len(ids)) + ")", tuple(ids)


def _delete_rows_by_ids(
    conn,
    table: str,
    column: str,
    ids: list[str],
) -> int:
    if not ids:
        return 0
    if not _table_exists(conn, table):
        return 0
    cond, params = _in_clause(ids)
    conn.execute(f"DELETE FROM {table} WHERE {column} IN {cond}", params)
    return int(conn.rowcount)


def _delete_rows_with_filter(conn, table: str, where_sql: str, params: tuple) -> int:
    if not _table_exists(conn, table):
        return 0
    conn.execute(f"DELETE FROM {table} WHERE {where_sql}", params)
    return int(conn.rowcount)


def _in_chunks(ids: list[str], chunk_size: int = 500) -> list[tuple[str, tuple[str, ...]]]:
    result = []
    for idx in range(0, len(ids), chunk_size):
        part = ids[idx: idx + chunk_size]
        clause = "(" + ",".join(["%s"] * len(part)) + ")"
        result.append((clause, tuple(part)))
    return result


def _json_value(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _replace_archive_identifiers(
    value,
    replacements: dict[str, str],
    *,
    global_sources: set[str] | None = None,
    protected: set[str] | None = None,
):
    if isinstance(value, str):
        result = value
        protected_tokens: dict[str, str] = {}
        for index, source in enumerate(
            sorted(protected or set(), key=len, reverse=True)
        ):
            if not source or source in replacements:
                continue
            token = f"\ue000archive-identity-{index}-{uuid.uuid4().hex}\ue001"
            if source in result:
                result = result.replace(source, token)
                protected_tokens[token] = source
        global_keys = global_sources or set()
        for source in sorted(global_keys, key=len, reverse=True):
            replacement = replacements.get(source)
            if source and replacement is not None:
                result = result.replace(source, replacement)
        bounded_keys = [
            source
            for source in replacements
            if source and source not in global_keys
        ]
        for source in sorted(bounded_keys, key=len, reverse=True):
            replacement = replacements[source]
            result = re.sub(
                rf"(?<![\w\u3400-\u9fff]){re.escape(source)}"
                rf"(?![\w\u3400-\u9fff])",
                replacement,
                result,
            )
        if any(source in result for source in bounded_keys):
            return "已匿名化内容"
        for token, source in protected_tokens.items():
            result = result.replace(token, source)
        return result
    if isinstance(value, list):
        return [
            _replace_archive_identifiers(
                item,
                replacements,
                global_sources=global_sources,
                protected=protected,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _replace_archive_identifiers(
                item,
                replacements,
                global_sources=global_sources,
                protected=protected,
            )
            for key, item in value.items()
        }
    return value


def _character_identity_aliases(character: dict) -> set[str]:
    aliases = {str(character.get("player_name") or "").strip()}
    xlsx_data = _json_value(character.get("xlsx_data"), {})
    if isinstance(xlsx_data, dict):
        for key in (
            "name",
            "investigator_name",
            "investigatorName",
            "character_name",
            "characterName",
        ):
            aliases.add(str(xlsx_data.get(key) or "").strip())
    return {alias for alias in aliases if alias}


def _pseudonymize_account_archives(conn, characters: list[dict]) -> int:
    if not characters or not _table_exists(conn, "campaign_archives"):
        return 0
    room_ids = sorted({str(item["room_id"]) for item in characters})
    room_filter, room_params = _in_clause(room_ids)
    archives = conn.execute(
        "SELECT archive_id, summary, highlights, character_arcs "
        f"FROM campaign_archives WHERE room_id IN {room_filter}",
        room_params,
    ).fetchall()
    replacements: dict[str, str] = {}
    deleted_characters: dict[str, dict[str, str]] = {}
    deleted_action_ids: set[str] = set()
    for character in characters:
        character_id = str(character["character_id"])
        player_name = str(character.get("player_name") or "").strip()
        deleted_characters[character_id] = {
            "player_name": player_name,
            "pseudonym": str(
                character.get("_pseudonym")
                or f"deleted-character:{uuid.uuid4().hex}"
            ),
        }
        replacements[character_id] = "已删除玩家"
        for action_id in character.get("_action_ids", []):
            normalized_action_id = str(action_id)
            if normalized_action_id:
                deleted_action_ids.add(normalized_action_id)
                replacements[normalized_action_id] = "deleted-action"
        for alias in _character_identity_aliases(character):
            replacements[alias] = "已删除玩家"

    deleted_reference_ids = {*deleted_characters, *deleted_action_ids}

    updated = 0
    conn.execute("SET LOCAL aikeeper.archive_redaction = 'on'")
    for archive in archives:
        highlights = _json_value(archive.get("highlights"), [])
        character_arcs = _json_value(archive.get("character_arcs"), [])
        protected_identities: set[str] = set()
        for raw_arc in character_arcs if isinstance(character_arcs, list) else []:
            if not isinstance(raw_arc, dict):
                continue
            arc_character_id = str(raw_arc.get("character_id") or "").strip()
            arc_player_name = str(raw_arc.get("player_name") or "").strip()
            if arc_character_id in deleted_characters:
                continue
            if (
                not arc_character_id
                and any(
                    item["player_name"] == arc_player_name
                    for item in deleted_characters.values()
                )
            ):
                continue
            protected_identities.update(
                item for item in (arc_character_id, arc_player_name) if item
            )
        sanitized_arcs = []
        for raw_arc in character_arcs if isinstance(character_arcs, list) else []:
            if not isinstance(raw_arc, dict):
                sanitized_arcs.append(
                    _replace_archive_identifiers(
                        raw_arc,
                        replacements,
                        global_sources=deleted_reference_ids,
                        protected=protected_identities,
                    )
                )
                continue
            arc_character_id = str(raw_arc.get("character_id") or "")
            target = deleted_characters.get(arc_character_id)
            if target is None and not arc_character_id:
                arc_player_name = str(raw_arc.get("player_name") or "")
                target = next(
                    (
                        item
                        for item in deleted_characters.values()
                        if item["player_name"]
                        and item["player_name"] == arc_player_name
                    ),
                    None,
                )
            if target is None:
                sanitized_arcs.append(
                    _replace_archive_identifiers(
                        raw_arc,
                        replacements,
                        global_sources=deleted_reference_ids,
                        protected=protected_identities,
                    )
                )
                continue
            public_arc = {
                "character_id": target["pseudonym"],
                "player_name": "已删除玩家",
            }
            if "total_actions" in raw_arc:
                public_arc["total_actions"] = int(raw_arc.get("total_actions") or 0)
            sanitized_arcs.append(public_arc)

        conn.execute(
            """
            UPDATE campaign_archives
            SET summary = %s, highlights = %s, character_arcs = %s
            WHERE archive_id = %s
            """,
            (
                _replace_archive_identifiers(
                    str(archive.get("summary") or ""),
                    replacements,
                    global_sources=deleted_reference_ids,
                    protected=protected_identities,
                ),
                json.dumps(
                    _replace_archive_identifiers(
                        highlights,
                        replacements,
                        global_sources=deleted_reference_ids,
                        protected=protected_identities,
                    ),
                    ensure_ascii=False,
                ),
                json.dumps(sanitized_arcs, ensure_ascii=False),
                archive["archive_id"],
            ),
        )
        updated += int(conn.rowcount)
    return updated


def _pseudonymize_account_public_events(conn, characters: list[dict]) -> int:
    """Redact identity fields in the small set of party event schemas we expose."""
    if not characters or not _table_exists(conn, "events"):
        return 0
    room_ids = sorted({str(item["room_id"]) for item in characters})
    room_filter, room_params = _in_clause(room_ids)
    rows = conn.execute(
        "SELECT sequence, event_type, payload, action_id FROM events "
        f"WHERE room_id IN {room_filter} "
        "AND audience IN ('party', 'system')",
        room_params,
    ).fetchall()
    identities = []
    for character in characters:
        action_tombstones = dict(character.get("_action_tombstones") or {})
        if not action_tombstones:
            action_tombstones = {
                str(action_id): f"deleted-action:{uuid.uuid4().hex}"
                for action_id in character.get("_action_ids", [])
                if str(action_id)
            }
        identities.append({
            "character_id": str(character["character_id"]),
            "pseudonym": str(
                character.get("_pseudonym")
                or f"deleted-character:{uuid.uuid4().hex}"
            ),
            "aliases": _character_identity_aliases(character),
            "action_ids": set(action_tombstones),
            "action_tombstones": action_tombstones,
            "account_id": str(character.get("_account_id") or ""),
        })

    id_keys = {"characterId", "character_id", "sharedBy", "shared_by"}
    action_keys = {"actionId", "action_id"}
    name_keys = {
        "playerName",
        "player_name",
        "investigatorName",
        "investigator_name",
        "characterName",
        "character_name",
        "label",
    }
    text_keys = {
        "text",
        "narrative",
        "narrativeText",
        "summary",
        "publicVersion",
    }

    def redact(value, identity: dict, *, field: str = ""):
        character_id = identity["character_id"]
        pseudonym = identity["pseudonym"]
        aliases = identity["aliases"]
        action_ids = identity["action_ids"]
        action_tombstones = identity["action_tombstones"]
        account_id = identity["account_id"]
        if isinstance(value, list):
            return [redact(item, identity) for item in value]
        if isinstance(value, dict):
            sanitized: dict = {}
            for key, item in value.items():
                sanitized_key = str(key)
                if sanitized_key == character_id:
                    sanitized_key = pseudonym
                elif sanitized_key in action_ids:
                    sanitized_key = action_tombstones[sanitized_key]
                elif account_id and sanitized_key == account_id:
                    sanitized_key = "deleted-account"
                if key == "currentPositions" and isinstance(item, dict):
                    positions = dict(item)
                    if character_id in positions:
                        positions[pseudonym] = positions.pop(character_id)
                    sanitized[sanitized_key] = {
                        position_key: redact(position, identity)
                        for position_key, position in positions.items()
                    }
                else:
                    sanitized[sanitized_key] = redact(
                        item,
                        identity,
                        field=str(key),
                    )
            return sanitized
        if isinstance(value, str):
            if field in id_keys and value == character_id:
                return pseudonym
            if field in action_keys and value in action_ids:
                return action_tombstones[value]
            if field in name_keys and value in aliases:
                return "已删除玩家"
            if value in aliases:
                return "已删除玩家"
            if character_id in value or any(
                action_id in value for action_id in action_ids
            ) or (account_id and account_id in value):
                replacements = {
                    character_id: pseudonym,
                    **action_tombstones,
                }
                if account_id:
                    replacements[account_id] = "deleted-account"
                return _replace_archive_identifiers(
                    value,
                    replacements,
                    global_sources=set(replacements),
                )
            if field in text_keys:
                replacements = {
                    character_id: "已删除玩家",
                    **action_tombstones,
                    **{alias: "已删除玩家" for alias in aliases},
                }
                return _replace_archive_identifiers(
                    value,
                    replacements,
                    global_sources={character_id, *action_ids},
                )
        return value

    updated = 0
    for row in rows:
        payload = _json_value(row.get("payload"), {})
        if not isinstance(payload, dict):
            continue
        sanitized = json.loads(json.dumps(payload, ensure_ascii=False))
        for identity in identities:
            sanitized = redact(sanitized, identity)
        action_id = str(row.get("action_id") or "")
        replacement_action_id = next(
            (
                identity["action_tombstones"][action_id]
                for identity in identities
                if action_id in identity["action_tombstones"]
            ),
            None,
        )
        if sanitized == payload and replacement_action_id is None:
            continue
        from .engine.runtime_integrity import (
            checkpoint_snapshot_hash,
            sanitize_checkpoint_value,
        )
        normalized = sanitize_checkpoint_value(sanitized)
        conn.execute(
            "UPDATE events SET payload = %s, payload_hash = %s, "
            "action_id = COALESCE(%s, action_id) "
            "WHERE sequence = %s",
            (
                json.dumps(normalized, ensure_ascii=False),
                checkpoint_snapshot_hash(normalized),
                replacement_action_id,
                row["sequence"],
            ),
        )
        updated += int(conn.rowcount)
    return updated


def _pseudonymize_character_fact_reveals(conn, characters: list[dict]) -> int:
    if not characters or not _table_exists(conn, "fact_reveals"):
        return 0
    room_ids = sorted({str(item["room_id"]) for item in characters})
    room_filter, room_params = _in_clause(room_ids)
    rows = conn.execute(
        "SELECT reveal_id, source_action_id, target_character_id, trigger_snapshot "
        f"FROM fact_reveals WHERE room_id IN {room_filter} FOR UPDATE",
        room_params,
    ).fetchall()

    identities = []
    for character in characters:
        action_tombstones = dict(character.get("_action_tombstones") or {})
        if not action_tombstones:
            action_tombstones = {
                str(action_id): f"deleted-action:{uuid.uuid4().hex}"
                for action_id in character.get("_action_ids", [])
                if str(action_id)
            }
        identities.append({
            "character_id": str(character["character_id"]),
            "pseudonym": str(
                character.get("_pseudonym")
                or f"deleted-character:{uuid.uuid4().hex}"
            ),
            "aliases": _character_identity_aliases(character),
            "account_id": str(character.get("_account_id") or ""),
            "action_tombstones": action_tombstones,
        })

    def scrub(value, replacements: dict[str, str], global_sources: set[str]):
        if isinstance(value, list):
            return [scrub(item, replacements, global_sources) for item in value]
        if isinstance(value, dict):
            return {
                str(scrub(str(key), replacements, global_sources)): scrub(
                    item,
                    replacements,
                    global_sources,
                )
                for key, item in value.items()
            }
        if isinstance(value, str):
            return _replace_archive_identifiers(
                value,
                replacements,
                global_sources=global_sources,
            )
        return value

    updated = 0
    for row in rows:
        source_action_id = str(row.get("source_action_id") or "")
        target_character_id = str(row.get("target_character_id") or "")
        trigger_snapshot = _json_value(row.get("trigger_snapshot"), {})
        sanitized_trigger = trigger_snapshot
        sanitized_source_action_id = source_action_id
        sanitized_target_character_id = target_character_id
        for identity in identities:
            action_tombstones = identity["action_tombstones"]
            replacements = {
                identity["character_id"]: identity["pseudonym"],
                **action_tombstones,
                **{alias: "已删除玩家" for alias in identity["aliases"]},
            }
            if identity["account_id"]:
                replacements[identity["account_id"]] = "deleted-account"
            global_sources = {
                identity["character_id"],
                *action_tombstones,
                *([identity["account_id"]] if identity["account_id"] else []),
            }
            sanitized_trigger = scrub(
                sanitized_trigger,
                replacements,
                global_sources,
            )
            if sanitized_source_action_id in action_tombstones:
                sanitized_source_action_id = action_tombstones[
                    sanitized_source_action_id
                ]
            if sanitized_target_character_id == identity["character_id"]:
                sanitized_target_character_id = identity["pseudonym"]
        if (
            sanitized_source_action_id == source_action_id
            and sanitized_target_character_id == target_character_id
            and sanitized_trigger == trigger_snapshot
        ):
            continue
        conn.execute(
            "UPDATE fact_reveals SET source_action_id = %s, "
            "target_character_id = %s, trigger_snapshot = %s WHERE reveal_id = %s",
            (
                sanitized_source_action_id,
                sanitized_target_character_id,
                json.dumps(sanitized_trigger, ensure_ascii=False),
                row["reveal_id"],
            ),
        )
        updated += int(conn.rowcount)
    return updated


def _unlink_action_audits(conn, action_ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not action_ids:
        return counts
    action_filter, action_params = _in_clause(action_ids)
    if _table_exists(conn, "spoiler_audits"):
        conn.execute(
            f"""
            UPDATE spoiler_audits
            SET action_id = '', original_text = '', final_text = '',
                violations = %s, unlock_snapshot = %s
            WHERE action_id IN {action_filter}
            """,
            (json.dumps([]), json.dumps({}), *action_params),
        )
        counts["spoiler_audits_scrubbed"] = int(conn.rowcount)
    if _table_exists(conn, "ai_call_logs"):
        conn.execute(
            f"""
            UPDATE ai_call_logs
            SET action_id = NULL, draft_id = NULL, draft_revision = NULL,
                audit_state = 'minimized', context_hash = '',
                response_summary = '', error_message = '',
                spoiler_hit_items = %s, citations = %s, structured_proposal = %s,
                engine_validation = %s, final_delta = %s
            WHERE action_id IN {action_filter} OR draft_id IN {action_filter}
            """,
            (
                json.dumps([]),
                json.dumps([]),
                json.dumps({}),
                json.dumps({}),
                json.dumps({}),
                *action_params,
                *action_params,
            ),
        )
        counts["ai_call_logs_minimized"] = int(conn.rowcount)
    return counts


def _delete_room_rows(
    conn,
    room_ids: list[str],
    *,
    affected_players: set[tuple[str, str]] | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not room_ids:
        return counts

    room_filter = "(" + ",".join(["%s"] * len(room_ids)) + ")"
    params = tuple(room_ids)

    character_ids = [
        str(row["character_id"])
        for row in conn.execute(
            f"SELECT character_id FROM characters WHERE room_id IN {room_filter}",
            params,
        ).fetchall()
    ]
    action_ids = [
        str(row["action_id"])
        for row in conn.execute(
            f"SELECT action_id FROM actions WHERE room_id IN {room_filter}",
            params,
        ).fetchall()
    ]
    encounter_rows = conn.execute(
        f"SELECT encounter_id FROM encounters WHERE room_id IN {room_filter}",
        params,
    ).fetchall()
    encounter_ids = [str(row["encounter_id"]) for row in encounter_rows]
    clue_rows = conn.execute(
        f"SELECT clue_id FROM clues WHERE room_id IN {room_filter}",
        params,
    ).fetchall()
    clue_ids = [str(row["clue_id"]) for row in clue_rows]

    # Characters reference rooms with a non-cascading foreign key. Reuse the
    # character-level cleanup so transfers and collaboration records that use
    # character ids are not left behind.
    if character_ids:
        for table, count in _delete_character_rows(
            conn,
            character_ids,
            affected_players=affected_players,
            scrub_room_map_projection=False,
        ).items():
            counts[table] = counts.get(table, 0) + count

    if action_ids:
        counts["action_review_requests"] = _delete_rows_by_ids(
            conn, "action_review_requests", "action_id", action_ids
        )
        counts["action_status_events"] = _delete_rows_by_ids(
            conn, "action_status_events", "action_id", action_ids
        )
    if _table_exists(conn, "spoiler_audits"):
        conn.execute(
            f"""
            UPDATE spoiler_audits
            SET original_text = '', final_text = '',
                violations = %s, unlock_snapshot = %s
            WHERE room_id IN {room_filter}
            """,
            (json.dumps([]), json.dumps({}), *params),
        )
        counts["spoiler_audits_scrubbed"] = max(
            counts.get("spoiler_audits_scrubbed", 0),
            int(conn.rowcount),
        )
    if _table_exists(conn, "ai_call_logs"):
        conn.execute(
            f"""
            UPDATE ai_call_logs
            SET action_id = NULL, draft_id = NULL, draft_revision = NULL,
                audit_state = 'minimized', context_hash = '',
                response_summary = '', error_message = '',
                spoiler_hit_items = %s, citations = %s, structured_proposal = %s,
                engine_validation = %s, final_delta = %s
            WHERE room_id IN {room_filter}
            """,
            (
                json.dumps([]),
                json.dumps([]),
                json.dumps({}),
                json.dumps({}),
                json.dumps({}),
                *params,
            ),
        )
        counts["ai_call_logs_minimized"] = max(
            counts.get("ai_call_logs_minimized", 0),
            int(conn.rowcount),
        )

    for table in (
        "compensation_transactions",
        "room_player_settings",
        "player_device_sessions",
        "session_summaries",
        "session_zero_confirmations",
        "player_notes",
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
        "player_sequences",
        "checkpoints",
        "events",
        "actions",
        "room_turns",
        "host_states",
        "room_rule_bindings",
        "prepared_rule_actions",
        "resolution_bundles",
        "player_action_submissions",
        "collaboration_contracts",
        "collaboration_contract_batches",
        "inventory_transfer_requests",
        "evidence_comments",
        "encounter_pending_reactions",
    ):
        counts[table] = _delete_rows_with_filter(
            conn, table, f"room_id IN {room_filter}", params
        )

    if encounter_ids:
        encounter_filter = "(" + ",".join(["%s"] * len(encounter_ids)) + ")"
        counts["encounter_participants"] = _delete_rows_with_filter(
            conn,
            "encounter_participants",
            f"encounter_id IN {encounter_filter}",
            tuple(encounter_ids),
        )
        counts["encounters"] = _delete_rows_by_ids(
            conn, "encounters", "encounter_id", encounter_ids
        )

    if clue_ids:
        clue_filter = "(" + ",".join(["%s"] * len(clue_ids)) + ")"
        counts["clue_shares"] = _delete_rows_with_filter(
            conn,
            "clue_shares",
            f"clue_id IN {clue_filter}",
            tuple(clue_ids),
        )

    counts["clues"] = _delete_rows_with_filter(
        conn, "clues", f"room_id IN {room_filter}", params
    )
    counts["rooms"] = _delete_rows_by_ids(conn, "rooms", "room_id", room_ids)
    return counts


def _delete_scenario_rows(conn, scenario_ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not scenario_ids:
        return counts

    scenario_filter = "(" + ",".join(["%s"] * len(scenario_ids)) + ")"
    scenario_params = tuple(scenario_ids)

    # Block scenarios currently used by active/in-process rooms.
    room_rows = conn.execute(
        f"SELECT room_id FROM rooms WHERE scenario_id IN {scenario_filter}",
        scenario_params,
    ).fetchall()
    room_ids = [str(row["room_id"]) for row in room_rows]
    if room_ids:
        raise HTTPException(
            409,
            f"scenario in use by room_id={', '.join(room_ids)}",
        )

    source_doc_rows = conn.execute(
        f"SELECT source_document_id FROM source_documents WHERE scenario_id IN {scenario_filter}",
        scenario_params,
    ).fetchall()
    source_doc_ids = [str(row["source_document_id"]) for row in source_doc_rows]
    version_rows = conn.execute(
        f"SELECT scenario_version_id FROM scenario_versions WHERE scenario_id IN {scenario_filter}",
        scenario_params,
    ).fetchall()
    scenario_version_ids = [str(row["scenario_version_id"]) for row in version_rows]

    if scenario_version_ids:
        version_filter = "(" + ",".join(["%s"] * len(scenario_version_ids)) + ")"
        counts["content_items"] = _delete_rows_with_filter(
            conn,
            "content_items",
            f"scenario_version_id IN {version_filter}",
            tuple(scenario_version_ids),
        )

    if source_doc_ids:
        source_doc_filter = "(" + ",".join(["%s"] * len(source_doc_ids)) + ")"
        _delete_rows_with_filter(
            conn,
            "source_parts",
            f"source_document_id IN {source_doc_filter}",
            tuple(source_doc_ids),
        )
        _delete_rows_with_filter(
            conn,
            "rule_documents",
            f"source_document_id IN {source_doc_filter}",
            tuple(source_doc_ids),
        )

    if scenario_version_ids:
        for table in (
            "scenario_version_sources",
            "scenario_review_drafts",
            "scenario_review_patches",
            "scenario_review_issue_resolutions",
            "scenario_asset_bindings",
            "scenario_rule_bindings",
        ):
            counts[table] = _delete_rows_with_filter(
                conn, table, f"scenario_version_id IN {version_filter}", tuple(scenario_version_ids)
            )

    for table in (
        "scenario_maps",
        "character_templates",
        "import_jobs",
        "scenario_assets",
        "spoiler_sensitive_items",
    ):
        counts[table] = _delete_rows_with_filter(
            conn, table, f"scenario_id IN {scenario_filter}", scenario_params
        )
    counts["scenario_versions"] = _delete_rows_with_filter(
        conn, "scenario_versions", "scenario_id IN %s" % scenario_filter, scenario_params
    )

    counts["source_documents"] = _delete_rows_with_filter(
        conn, "source_documents", f"scenario_id IN {scenario_filter}", scenario_params
    )
    counts["scenarios"] = _delete_rows_with_filter(
        conn, "scenarios", f"scenario_id IN {scenario_filter}", scenario_params
    )
    return counts


_DROP_RUNTIME_VALUE = object()


def _scrub_character_runtime_snapshots(
    conn,
    characters: list[dict],
    action_ids: list[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not characters:
        return counts
    character_ids = {str(row["character_id"]) for row in characters}
    aliases = set().union(*(
        _character_identity_aliases(character) for character in characters
    ))
    deleted_action_ids = set(action_ids)
    room_ids = sorted({str(row["room_id"]) for row in characters})
    identity_fields = {
        "character_id",
        "characterId",
        "actor",
        "actor_character_id",
        "actorCharacterId",
        "owner_character_id",
    }
    action_fields = {"action_id", "actionId"}

    def scrub(value, *, nested: bool = False):
        if isinstance(value, list):
            sanitized = []
            for item in value:
                cleaned = scrub(item, nested=True)
                if cleaned is not _DROP_RUNTIME_VALUE:
                    sanitized.append(cleaned)
            return sanitized
        if isinstance(value, dict):
            if nested and any(
                str(value.get(field) or "") in character_ids
                for field in identity_fields
            ):
                return _DROP_RUNTIME_VALUE
            if nested and any(
                str(value.get(field) or "") in deleted_action_ids
                for field in action_fields
            ):
                return _DROP_RUNTIME_VALUE
            sanitized: dict = {}
            for key, item in value.items():
                if str(key) in character_ids or str(key) in deleted_action_ids:
                    continue
                cleaned = scrub(item, nested=True)
                if cleaned is not _DROP_RUNTIME_VALUE:
                    sanitized[key] = cleaned
            return sanitized
        if isinstance(value, str):
            replacements = {
                **{character_id: "deleted-character" for character_id in character_ids},
                **{action_id: "deleted-action" for action_id in deleted_action_ids},
                **{alias: "已删除玩家" for alias in aliases},
            }
            return _replace_archive_identifiers(
                value,
                replacements,
                global_sources={*character_ids, *deleted_action_ids},
            )
        return value

    room_filter, room_params = _in_clause(room_ids)
    if _table_exists(conn, "host_states"):
        rows = conn.execute(
            "SELECT room_id, state FROM host_states "
            f"WHERE room_id IN {room_filter}",
            room_params,
        ).fetchall()
        updated = 0
        for row in rows:
            state = scrub(_json_value(row.get("state"), {}))
            conn.execute(
                "UPDATE host_states SET state = %s, updated_at = NOW() "
                "WHERE room_id = %s",
                (json.dumps(state, ensure_ascii=False), row["room_id"]),
            )
            updated += int(conn.rowcount)
        counts["host_states_scrubbed"] = updated

    if _table_exists(conn, "checkpoints"):
        from .engine.runtime_integrity import (
            checkpoint_snapshot_hash,
            sanitize_checkpoint_value,
            validate_runtime_snapshot,
        )

        rows = conn.execute(
            "SELECT checkpoint_id, room_id, state_snapshot FROM checkpoints "
            f"WHERE room_id IN {room_filter}",
            room_params,
        ).fetchall()
        updated = 0
        for row in rows:
            snapshot = _json_value(row.get("state_snapshot"), {})
            sanitized = sanitize_checkpoint_value(scrub(snapshot))
            report = validate_runtime_snapshot(sanitized, str(row["room_id"]))
            conn.execute(
                "UPDATE checkpoints SET state_snapshot = %s, snapshot_sha256 = %s, "
                "invariant_report = %s, verification_status = %s "
                "WHERE checkpoint_id = %s",
                (
                    json.dumps(sanitized, ensure_ascii=False),
                    checkpoint_snapshot_hash(sanitized),
                    json.dumps(report, ensure_ascii=False),
                    "verified" if report.get("valid") else "invalid",
                    row["checkpoint_id"],
                ),
            )
            updated += int(conn.rowcount)
        counts["checkpoints_scrubbed"] = updated

    if _table_exists(conn, "room_turns"):
        rows = conn.execute(
            "SELECT turn_id, combat_plan, combat_summary FROM room_turns "
            f"WHERE room_id IN {room_filter}",
            room_params,
        ).fetchall()
        updated = 0
        for row in rows:
            combat_plan = scrub(_json_value(row.get("combat_plan"), {}))
            combat_summary = scrub(_json_value(row.get("combat_summary"), {}))
            conn.execute(
                "UPDATE room_turns SET combat_plan = %s, combat_summary = %s, "
                "summary = '' WHERE turn_id = %s",
                (
                    json.dumps(combat_plan, ensure_ascii=False),
                    json.dumps(combat_summary, ensure_ascii=False),
                    row["turn_id"],
                ),
            )
            updated += int(conn.rowcount)
        counts["room_turns_scrubbed"] = updated
    return counts


def _lock_character_collaboration_contracts(
    conn,
    character_ids: list[str],
) -> list[str]:
    if not character_ids:
        return []
    char_filter, char_params = _in_clause(character_ids)
    rows = conn.execute(
        "SELECT contracts.contract_id FROM collaboration_contracts AS contracts "
        f"WHERE contracts.initiator_character_id IN {char_filter} "
        "OR EXISTS ("
        "SELECT 1 FROM collaboration_contract_participants AS participants "
        "WHERE participants.contract_id = contracts.contract_id "
        f"AND participants.character_id IN {char_filter}"
        ") ORDER BY contracts.contract_id FOR UPDATE",
        char_params * 2,
    ).fetchall()
    return [str(row["contract_id"]) for row in rows]


def _cancel_character_collaboration_contracts(
    conn,
    contract_ids: list[str],
) -> dict[str, int]:
    if not contract_ids:
        return {}
    from .player.action_service import ActionDraftError, _cancel_collaboration_batch

    canceled_contracts = 0
    canceled_batches = 0
    for contract_id in contract_ids:
        before_contract = conn.execute(
            "SELECT status FROM collaboration_contracts WHERE contract_id = %s",
            (contract_id,),
        ).fetchone()
        before_batch = conn.execute(
            "SELECT status FROM collaboration_contract_batches WHERE contract_id = %s",
            (contract_id,),
        ).fetchone()
        try:
            _cancel_collaboration_batch(conn, contract_id)
        except ActionDraftError as exc:
            raise HTTPException(exc.status_code, exc.detail) from exc
        canceled_contracts += int(
            bool(before_contract)
            and str(before_contract["status"]) in {"pending", "accepted"}
        )
        canceled_batches += int(
            bool(before_batch)
            and str(before_batch["status"]) in {"queued", "blocked"}
        )
    return {
        "collaboration_contracts_canceled": canceled_contracts,
        "collaboration_contract_batches_canceled": canceled_batches,
    }


def _cancel_actions_waiting_on_deleted_characters(
    conn,
    character_ids: list[str],
) -> dict[str, int]:
    if not character_ids:
        return {}
    char_filter, char_params = _in_clause(character_ids)
    rows = conn.execute(
        "SELECT actions.action_id FROM actions "
        "WHERE actions.status IN ("
        "'awaiting_player_consent', 'queued', 'batched', 'resolving', "
        "'awaiting_player_choice', 'awaiting_host_exception', 'sync_required'"
        ") "
        f"AND actions.character_id NOT IN {char_filter} "
        "AND EXISTS ("
        "SELECT 1 FROM action_consents AS consents "
        "WHERE consents.action_id = actions.action_id "
        f"AND consents.affected_character_id IN {char_filter}"
        ") ORDER BY actions.action_id FOR UPDATE",
        char_params * 2,
    ).fetchall()
    if not rows:
        return {}
    result = json.dumps(
        {"outcome": "no_effect", "reason": "affected_character_deleted"},
        ensure_ascii=False,
    )
    metadata = json.dumps(
        {"reason_code": "affected_character_deleted", "effect": "no_effect"},
        ensure_ascii=False,
    )
    for row in rows:
        action_id = str(row["action_id"])
        conn.execute(
            "UPDATE actions SET status = 'canceled', result = %s, canceled_at = NOW() "
            "WHERE action_id = %s AND status IN ("
            "'awaiting_player_consent', 'queued', 'batched', 'resolving', "
            "'awaiting_player_choice', 'awaiting_host_exception', 'sync_required'"
            ")",
            (result, action_id),
        )
        conn.execute(
            "UPDATE action_consents SET decision = 'expired', responded_at = NOW() "
            "WHERE action_id = %s AND decision = 'pending'",
            (action_id,),
        )
        conn.execute(
            "INSERT INTO action_status_events (action_id, status, metadata) "
            "VALUES (%s, 'canceled', %s)",
            (action_id, metadata),
        )
        if _table_exists(conn, "ai_call_logs"):
            from .ai.decision_audit import (
                DecisionAuditRecorder,
                finalize_terminal_decision_audit,
            )

            DecisionAuditRecorder(conn).finalize(
                action_id,
                engine_validation={
                    "valid": False,
                    "reasonCode": "affected_character_deleted",
                },
                final_delta=None,
            )
            finalize_terminal_decision_audit(
                conn,
                action_id,
                action_status="canceled",
                reason_code="affected_character_deleted",
                effect="no_effect",
            )
    return {"actions_canceled_for_deleted_consent_target": len(rows)}


def _delete_character_rows(
    conn,
    character_ids: list[str],
    *,
    affected_players: set[tuple[str, str]] | None = None,
    public_identities: list[dict] | None = None,
    scrub_room_map_projection: bool = True,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not character_ids:
        return counts
    char_filter = "(" + ",".join(["%s"] * len(character_ids)) + ")"
    char_params = tuple(character_ids)

    collaboration_contract_ids = _lock_character_collaboration_contracts(
        conn,
        character_ids,
    )

    locked_characters = [
        dict(row)
        for row in conn.execute(
            f"SELECT character_id, room_id, account_id, player_name, xlsx_data FROM characters "
            f"WHERE character_id IN {char_filter} "
            "ORDER BY character_id FOR UPDATE",
            char_params,
        ).fetchall()
    ]
    locked_ids = {str(row["character_id"]) for row in locked_characters}
    missing_ids = [character_id for character_id in character_ids if character_id not in locked_ids]
    if missing_ids:
        raise HTTPException(404, f"character not found: {', '.join(missing_ids)}")
    affected_room_ids = sorted({str(row["room_id"]) for row in locked_characters})
    if affected_players is not None:
        affected_players.update(
            (str(row["room_id"]), str(row["character_id"]))
            for row in locked_characters
        )

    _merge_delete_counts(
        counts,
        _cancel_character_collaboration_contracts(
            conn,
            collaboration_contract_ids,
        ),
    )
    _merge_delete_counts(
        counts,
        _cancel_actions_waiting_on_deleted_characters(conn, character_ids),
    )

    if affected_room_ids and scrub_room_map_projection:
        room_filter, room_params = _in_clause(affected_room_ids)
        conn.execute(
            f"SELECT room_id FROM rooms WHERE room_id IN {room_filter} "
            "ORDER BY room_id FOR UPDATE",
            room_params,
        ).fetchall()
        if _table_exists(conn, "room_map_state"):
            scrubbed = 0
            for row in locked_characters:
                conn.execute(
                    "UPDATE room_map_state "
                    "SET token_visibility = COALESCE(token_visibility, '{}'::jsonb) - %s "
                    "WHERE room_id = %s",
                    (str(row["character_id"]), str(row["room_id"])),
                )
                scrubbed += int(conn.rowcount)
            counts["room_map_state_token_visibility_scrubbed"] = scrubbed

    action_rows = conn.execute(
        f"SELECT action_id, character_id FROM actions "
        f"WHERE character_id IN {char_filter}",
        char_params,
    ).fetchall()
    action_ids = [str(row["action_id"]) for row in action_rows]
    draft_rows = conn.execute(
        f"SELECT draft_id FROM action_drafts WHERE character_id IN {char_filter}",
        char_params,
    ).fetchall()
    draft_ids = [str(row["draft_id"]) for row in draft_rows]
    action_ids_by_character: dict[str, list[str]] = {}
    for row in action_rows:
        action_ids_by_character.setdefault(
            str(row["character_id"]),
            [],
        ).append(str(row["action_id"]))
    identities = [
        dict(row) for row in (public_identities or locked_characters)
    ]
    for identity in identities:
        identity.setdefault("_pseudonym", f"deleted-character:{uuid.uuid4().hex}")
        identity.setdefault("_account_id", str(identity.get("account_id") or ""))
        identity.setdefault(
            "_action_ids",
            action_ids_by_character.get(str(identity["character_id"]), []),
        )
        identity.setdefault(
            "_action_tombstones",
            {
                str(action_id): f"deleted-action:{uuid.uuid4().hex}"
                for action_id in identity["_action_ids"]
                if str(action_id)
            },
        )
    counts["campaign_archives_pseudonymized"] = _pseudonymize_account_archives(
        conn,
        identities,
    )
    counts["public_events_pseudonymized"] = _pseudonymize_account_public_events(
        conn,
        identities,
    )
    counts["fact_reveals_pseudonymized"] = _pseudonymize_character_fact_reveals(
        conn,
        identities,
    )
    _merge_delete_counts(
        counts,
        _scrub_character_runtime_snapshots(
            conn,
            locked_characters,
            action_ids,
        ),
    )

    counts["private_evidence_cards"] = _delete_rows_with_filter(
        conn,
        "evidence_cards",
        f"visibility = 'private' AND created_by_character_id IN {char_filter}",
        char_params,
    )
    if _table_exists(conn, "evidence_cards"):
        conn.execute(
            "UPDATE evidence_cards SET "
            f"question_closed_by_character_id = CASE WHEN question_closed_by_character_id IN {char_filter} "
            "THEN NULL ELSE question_closed_by_character_id END, "
            f"question_undo_until = CASE WHEN question_closed_by_character_id IN {char_filter} "
            "THEN NULL ELSE question_undo_until END, "
            f"hypothesis_status_changed_by_character_id = CASE WHEN hypothesis_status_changed_by_character_id IN {char_filter} "
            "THEN NULL ELSE hypothesis_status_changed_by_character_id END, "
            f"hypothesis_status_undo_until = CASE WHEN hypothesis_status_changed_by_character_id IN {char_filter} "
            "THEN NULL ELSE hypothesis_status_undo_until END "
            f"WHERE question_closed_by_character_id IN {char_filter} "
            f"OR hypothesis_status_changed_by_character_id IN {char_filter}",
            char_params * 6,
        )
        counts["party_evidence_actor_ids_scrubbed"] = int(conn.rowcount)
    counts["encounter_participants"] = _delete_rows_with_filter(
        conn,
        "encounter_participants",
        f"character_id IN {char_filter}",
        char_params,
    )

    counts["private_character_events"] = _delete_rows_with_filter(
        conn,
        "events",
        "audience = 'player' AND "
        f"(payload->>'characterId' IN {char_filter} "
        f"OR payload->>'character_id' IN {char_filter})",
        char_params * 2,
    )

    if action_ids:
        action_filter = "(" + ",".join(["%s"] * len(action_ids)) + ")"
        counts["action_review_requests"] = _delete_rows_with_filter(
            conn, "action_review_requests", f"action_id IN {action_filter}", tuple(action_ids)
        )
        counts["action_status_events"] = _delete_rows_with_filter(
            conn, "action_status_events", f"action_id IN {action_filter}", tuple(action_ids)
        )
        counts["private_action_events"] = _delete_rows_with_filter(
            conn,
            "events",
            "audience = 'player' AND "
            f"(action_id IN {action_filter} "
            f"OR payload->>'actionId' IN {action_filter} "
            f"OR payload->>'action_id' IN {action_filter})",
            tuple(action_ids) * 3,
        )

    clue_rows = conn.execute(
        f"SELECT clue_id FROM clues WHERE character_id IN {char_filter}",
        char_params,
    ).fetchall()
    clue_ids = [str(row["clue_id"]) for row in clue_rows]
    if clue_ids:
        clue_filter = "(" + ",".join(["%s"] * len(clue_ids)) + ")"
        counts["clue_shares"] = _delete_rows_with_filter(
            conn,
            "clue_shares",
            f"clue_id IN {clue_filter}",
            tuple(clue_ids),
        )

    initiated_contract_ids = [
        str(row["contract_id"])
        for row in conn.execute(
            f"SELECT contract_id FROM collaboration_contracts "
            f"WHERE initiator_character_id IN {char_filter}",
            char_params,
        ).fetchall()
    ]
    if initiated_contract_ids:
        counts["collaboration_contracts"] = _delete_rows_by_ids(
            conn,
            "collaboration_contracts",
            "contract_id",
            initiated_contract_ids,
        )

    for table in (
        "prepared_rule_actions",
        "resolution_bundles",
        "action_drafts",
        "player_action_submissions",
        "compensation_transactions",
        "room_player_settings",
        "player_device_sessions",
        "session_attendance",
        "session_zero_confirmations",
        "player_notes",
        "evidence_comments",
        "character_runtime_state",
        "character_map_positions",
        "player_sequences",
        "inventory",
        "clarifications",
        "action_review_requests",
        "objectives",
        "collaboration_contract_participants",
        "collaboration_contract_drafts",
    ):
        counts[table] = _delete_rows_with_filter(
            conn, table, f"character_id IN {char_filter}", char_params
        )

    counts["inventory_transfer_requests"] = _delete_rows_with_filter(
        conn,
        "inventory_transfer_requests",
        f"from_character_id IN {char_filter} OR to_character_id IN {char_filter}",
        char_params * 2,
    )
    counts["encounter_pending_reactions"] = _delete_rows_with_filter(
        conn,
        "encounter_pending_reactions",
        f"character_id IN {char_filter} OR attacker_id IN {char_filter}",
        char_params * 2,
    )

    audit_reference_ids = list(dict.fromkeys([*action_ids, *draft_ids]))
    if audit_reference_ids:
        _merge_delete_counts(
            counts,
            _unlink_action_audits(conn, audit_reference_ids),
        )

    if action_ids:
        action_filter = "(" + ",".join(["%s"] * len(action_ids)) + ")"
        action_params = tuple(action_ids)
        counts["encounter_pending_reactions"] += _delete_rows_with_filter(
            conn,
            "encounter_pending_reactions",
            f"source_action_id IN {action_filter}",
            action_params,
        )
        counts["actions"] = _delete_rows_by_ids(conn, "actions", "action_id", action_ids)

    if clue_ids:
        counts["clues"] = _delete_rows_by_ids(
            conn, "clues", "clue_id", [str(r["clue_id"]) for r in clue_rows]
        )
    counts["characters"] = _delete_rows_by_ids(conn, "characters", "character_id", character_ids)
    return counts


_ACCOUNT_ACTOR_REFERENCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "source_documents": ("created_by",),
    "scenario_versions": ("created_by", "reviewed_by"),
    "scenario_review_drafts": ("created_by",),
    "scenario_review_patches": ("created_by",),
    "scenario_review_issue_resolutions": ("resolved_by",),
    "content_projection_runs": ("requested_by",),
    "runtime_package_versions": ("created_by",),
    "runtime_package_exception_confirmations": ("confirmed_by",),
    "v2_cutover_records": ("requested_by",),
    "rag_rebuild_records": ("requested_by",),
    "rule_sets": ("created_by",),
    "rule_set_versions": ("created_by",),
    "scenario_asset_bindings": ("reviewed_by",),
}


def _tombstone_account_actor_references(
    conn,
    account_id: str,
    tombstone: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, columns in _ACCOUNT_ACTOR_REFERENCE_COLUMNS.items():
        if not _table_exists(conn, table):
            continue
        for column in columns:
            if not _column_exists(conn, table, column):
                continue
            conn.execute(
                f"UPDATE {table} SET {column} = %s WHERE {column} = %s",
                (tombstone, account_id),
            )
            count = int(conn.rowcount)
            if count:
                counts[f"{table}.{column}_tombstoned"] = count
    return counts


def _delete_account_rows(
    conn,
    account_ids: list[str],
    *,
    requested_by: str,
    affected_players: set[tuple[str, str]] | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not account_ids:
        return counts
    account_filter = "(" + ",".join(["%s"] * len(account_ids)) + ")"
    account_params = tuple(account_ids)

    locked_accounts = conn.execute(
        f"SELECT account_id FROM accounts WHERE account_id IN {account_filter} "
        "ORDER BY account_id FOR UPDATE",
        account_params,
    ).fetchall()
    locked_ids = {str(row["account_id"]) for row in locked_accounts}
    missing_ids = [account_id for account_id in account_ids if account_id not in locked_ids]
    if missing_ids:
        raise HTTPException(404, f"account not found: {', '.join(missing_ids)}")

    blocked_room_rows = conn.execute(
        f"SELECT room_id FROM rooms WHERE owner_account_id IN {account_filter}",
        account_params,
    ).fetchall()
    if blocked_room_rows:
        room_ids = [str(r["room_id"]) for r in blocked_room_rows]
        raise HTTPException(
            409,
            f"account currently owns room(s): {', '.join(room_ids)}"
        )

    character_rows = [
        dict(row)
        for row in conn.execute(
            f"SELECT character_id, room_id, account_id, player_name, xlsx_data "
            f"FROM characters WHERE account_id IN {account_filter} "
            "ORDER BY character_id FOR UPDATE",
            account_params,
        ).fetchall()
    ]
    for character in character_rows:
        character["_pseudonym"] = f"deleted-character:{uuid.uuid4().hex}"
        character["_account_id"] = str(character.get("account_id") or "")
        character["_action_ids"] = [
            str(row["action_id"])
            for row in conn.execute(
                "SELECT action_id FROM actions WHERE character_id = %s",
                (str(character["character_id"]),),
            ).fetchall()
        ]
    character_ids = [str(row["character_id"]) for row in character_rows]
    character_room_ids = sorted({str(row["room_id"]) for row in character_rows})
    if character_room_ids:
        room_filter, room_params = _in_clause(character_room_ids)
        conn.execute(
            f"SELECT room_id FROM rooms WHERE room_id IN {room_filter} "
            "ORDER BY room_id FOR UPDATE",
            room_params,
        ).fetchall()
    if character_ids:
        for table, count in _delete_character_rows(
            conn,
            character_ids,
            affected_players=affected_players,
            public_identities=character_rows,
        ).items():
            counts[table] = counts.get(table, 0) + count

    counts["character_profiles"] = _delete_rows_with_filter(
        conn,
        "character_profiles",
        f"account_id IN {account_filter}",
        account_params,
    )

    audit_actor_id = requested_by
    for account_id in account_ids:
        tombstone = f"deleted-account:{uuid.uuid4().hex}"
        if account_id == requested_by:
            audit_actor_id = tombstone
        if _table_exists(conn, "private_data_access_audits"):
            conn.execute(
                "UPDATE private_data_access_audits "
                "SET host_account_id = NULL, actor_tombstone = %s "
                "WHERE host_account_id = %s",
                (tombstone, account_id),
            )
            counts["private_data_access_audits_tombstoned"] = (
                counts.get("private_data_access_audits_tombstoned", 0)
                + int(conn.rowcount)
            )
        if _table_exists(conn, "ai_provider_config_audits"):
            conn.execute(
                "UPDATE ai_provider_config_audits SET actor_id = %s WHERE actor_id = %s",
                (tombstone, account_id),
            )
            counts["ai_provider_config_audits_tombstoned"] = (
                counts.get("ai_provider_config_audits_tombstoned", 0)
                + int(conn.rowcount)
            )
        if _table_exists(conn, "ai_provider_configs"):
            conn.execute(
                "UPDATE ai_provider_configs SET created_by = %s WHERE created_by = %s",
                (tombstone, account_id),
            )
            config_rows = int(conn.rowcount)
            conn.execute(
                "UPDATE ai_provider_configs SET updated_by = %s WHERE updated_by = %s",
                (tombstone, account_id),
            )
            counts["ai_provider_configs_tombstoned"] = (
                counts.get("ai_provider_configs_tombstoned", 0)
                + config_rows
                + int(conn.rowcount)
            )
        if _table_exists(conn, "admin_data_purge_audits"):
            conn.execute(
                "UPDATE admin_data_purge_audits SET actor_id = %s WHERE actor_id = %s",
                (tombstone, account_id),
            )
            counts["admin_data_purge_audits_tombstoned"] = (
                counts.get("admin_data_purge_audits_tombstoned", 0)
                + int(conn.rowcount)
            )
        if _table_exists(conn, "retention_runs"):
            conn.execute(
                "UPDATE retention_runs SET actor_id = %s WHERE actor_id = %s",
                (tombstone, account_id),
            )
            counts["retention_runs_tombstoned"] = (
                counts.get("retention_runs_tombstoned", 0)
                + int(conn.rowcount)
            )
        _merge_delete_counts(
            counts,
            _tombstone_account_actor_references(conn, account_id, tombstone),
        )
    counts["accounts"] = _delete_rows_by_ids(conn, "accounts", "account_id", account_ids)
    if counts["accounts"] != len(account_ids):
        raise HTTPException(409, "account deletion conflict")
    conn.execute(
        "INSERT INTO admin_data_purge_audits "
        "(audit_id, action, actor_id, target_count, details) "
        "VALUES (%s, 'account_delete', %s, %s, %s)",
        (
            f"account-delete-{uuid.uuid4().hex}",
            audit_actor_id,
            len(account_ids),
            json.dumps({}),
        ),
    )
    counts["account_delete_audits"] = int(conn.rowcount)
    return counts


def _merge_delete_counts(
    target: dict[str, int],
    source: dict[str, int],
) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


async def _invalidate_deleted_players(
    affected_players: set[tuple[str, str]],
) -> None:
    """Drop runtime caches and revoke sockets only after the DB commit succeeds."""
    if not affected_players:
        return
    from .host.router_host import remove_host_store
    from .host.ws_manager import manager as ws_manager

    for room_id in sorted({room_id for room_id, _ in affected_players}):
        remove_host_store(room_id)
    for room_id, character_id in sorted(affected_players):
        try:
            await ws_manager.revoke_player(room_id, character_id)
        except Exception:
            logger.exception(
                "Failed to revoke deleted player socket room=%s character=%s",
                room_id,
                character_id,
            )


def _batch_delete_response(
    requested_ids: list[str],
    deleted_ids: list[str],
    not_found_ids: list[str],
    counts: dict[str, int],
    errors: list[dict[str, str]],
):
    return {
        "requested_ids": requested_ids,
        "deleted_ids": deleted_ids,
        "not_found_ids": not_found_ids,
        "deleted": counts,
        "errors": errors,
    }


# 鈹€鈹€ Admin Entity Delete 鈹€鈹€

async def _delete_room_with_lifecycle(
    request: Request,
    room_id: str,
    *,
    admin_id: str,
) -> tuple[dict[str, int], set[tuple[str, str]]]:
    async with _governance_actor_guard(request, admin_id) as conn:
        async with room_lifecycle_guard([room_id], conn=conn):
            room = conn.execute(
                "SELECT 1 FROM rooms WHERE room_id = %s",
                (room_id,),
            ).fetchone()
            if not room:
                raise HTTPException(404, "房间不存在")
            character_ids = [
                str(row["character_id"])
                for row in conn.execute(
                    "SELECT character_id FROM characters WHERE room_id = %s",
                    (room_id,),
                ).fetchall()
            ]
            affected_players: set[tuple[str, str]] = set()
            async with character_lifecycle_guard(character_ids, conn=conn):
                with conn.transaction() as tx:
                    counts = _delete_room_rows(
                        tx,
                        [room_id],
                        affected_players=affected_players,
                    )
    return counts, affected_players


async def _delete_scenario_with_actor_guard(
    request: Request,
    scenario_id: str,
    *,
    admin_id: str,
) -> dict[str, int]:
    async with _governance_actor_guard(request, admin_id) as conn:
        if not conn.execute(
            "SELECT 1 FROM scenarios WHERE scenario_id = %s",
            (scenario_id,),
        ).fetchone():
            raise HTTPException(404, "剧本不存在")
        with conn.transaction() as tx:
            return _delete_scenario_rows(tx, [scenario_id])


async def _delete_character_with_lifecycle(
    request: Request,
    character_id: str,
    *,
    admin_id: str,
) -> tuple[dict[str, int], set[tuple[str, str]]]:
    async with _governance_actor_guard(request, admin_id) as conn:
        async with character_lifecycle_guard([character_id], conn=conn):
            if not conn.execute(
                "SELECT 1 FROM characters WHERE character_id = %s",
                (character_id,),
            ).fetchone():
                raise HTTPException(404, "角色不存在")
            affected_players: set[tuple[str, str]] = set()
            with conn.transaction() as tx:
                counts = _delete_character_rows(
                    tx,
                    [character_id],
                    affected_players=affected_players,
                )
    return counts, affected_players

@router.delete("/rooms/{room_id}")
async def delete_room(request: Request, room_id: str):
    admin = _require_admin(request)
    counts, affected_players = await _delete_room_with_lifecycle(
        request,
        room_id,
        admin_id=str(admin["account_id"]),
    )
    await _invalidate_deleted_players(affected_players)
    return {"status": "deleted", "deleted_ids": [room_id], "counts": counts}


@router.post("/rooms/batch-delete")
async def delete_rooms(request: Request):
    admin = _require_admin(request)
    ids = await _get_confirmed_id_list(request, "ids")
    conn = request.app.state.db
    found_ids, not_found_ids = _split_found_and_missing(conn, "rooms", "room_id", ids)

    deleted_ids: list[str] = []
    deleted_counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    for room_id in found_ids:
        try:
            counts, affected_players = await _delete_room_with_lifecycle(
                request,
                room_id,
                admin_id=str(admin["account_id"]),
            )
            await _invalidate_deleted_players(affected_players)
            _merge_delete_counts(deleted_counts, counts)
            deleted_ids.append(room_id)
        except HTTPException as exc:
            errors.append({"id": room_id, "error": str(exc.detail), "status": str(exc.status_code)})
        except Exception:
            logger.exception("Failed to delete room %s", room_id)
            errors.append({
                "id": room_id,
                "error": "系统删除失败，请查看服务器日志",
                "status": "500",
                "code": "system_delete_failed",
            })

    return _batch_delete_response(ids, deleted_ids, not_found_ids, deleted_counts, errors)


@router.delete("/scenarios/{scenario_id}")
async def delete_scenario(request: Request, scenario_id: str):
    admin = _require_admin(request)
    counts = await _delete_scenario_with_actor_guard(
        request,
        scenario_id,
        admin_id=str(admin["account_id"]),
    )
    return {"status": "deleted", "deleted_ids": [scenario_id], "counts": counts}


@router.post("/scenarios/batch-delete")
async def delete_scenarios(request: Request):
    admin = _require_admin(request)
    ids = await _get_confirmed_id_list(request, "ids")
    conn = request.app.state.db
    found_ids, not_found_ids = _split_found_and_missing(conn, "scenarios", "scenario_id", ids)

    deleted_ids: list[str] = []
    deleted_counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    for scenario_id in found_ids:
        try:
            counts = await _delete_scenario_with_actor_guard(
                request,
                scenario_id,
                admin_id=str(admin["account_id"]),
            )
            _merge_delete_counts(deleted_counts, counts)
            deleted_ids.append(scenario_id)
        except HTTPException as exc:
            errors.append({"id": scenario_id, "error": str(exc.detail), "status": str(exc.status_code)})
        except Exception:
            logger.exception("Failed to delete scenario %s", scenario_id)
            errors.append({
                "id": scenario_id,
                "error": "系统删除失败，请查看服务器日志",
                "status": "500",
                "code": "system_delete_failed",
            })

    return _batch_delete_response(ids, deleted_ids, not_found_ids, deleted_counts, errors)


@router.delete("/characters/{character_id}")
async def delete_character(request: Request, character_id: str):
    admin = _require_admin(request)
    counts, affected_players = await _delete_character_with_lifecycle(
        request,
        character_id,
        admin_id=str(admin["account_id"]),
    )
    await _invalidate_deleted_players(affected_players)
    return {"status": "deleted", "deleted_ids": [character_id], "counts": counts}


@router.post("/characters/batch-delete")
async def delete_characters(request: Request):
    admin = _require_admin(request)
    ids = await _get_confirmed_id_list(request, "ids")
    conn = request.app.state.db
    found_ids, not_found_ids = _split_found_and_missing(conn, "characters", "character_id", ids)

    deleted_ids: list[str] = []
    deleted_counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    for character_id in found_ids:
        try:
            counts, affected_players = await _delete_character_with_lifecycle(
                request,
                character_id,
                admin_id=str(admin["account_id"]),
            )
            await _invalidate_deleted_players(affected_players)
            _merge_delete_counts(deleted_counts, counts)
            deleted_ids.append(character_id)
        except HTTPException as exc:
            errors.append({"id": character_id, "error": str(exc.detail), "status": str(exc.status_code)})
        except Exception:
            logger.exception("Failed to delete character %s", character_id)
            errors.append({
                "id": character_id,
                "error": "系统删除失败，请查看服务器日志",
                "status": "500",
                "code": "system_delete_failed",
            })

    return _batch_delete_response(ids, deleted_ids, not_found_ids, deleted_counts, errors)


async def _delete_account_with_character_guard(
    conn,
    account_id: str,
    *,
    requested_by: str,
) -> tuple[dict[str, int], set[tuple[str, str]]]:
    affected_players: set[tuple[str, str]] = set()
    character_ids = [
        str(row["character_id"])
        for row in conn.execute(
            "SELECT character_id FROM characters WHERE account_id = %s",
            (account_id,),
        ).fetchall()
    ]
    async with character_lifecycle_guard(character_ids, conn=conn):
        with conn.transaction() as tx:
            counts = _delete_account_rows(
                tx,
                [account_id],
                requested_by=requested_by,
                affected_players=affected_players,
            )
    return counts, affected_players


@router.delete("/accounts/{account_id}")
async def delete_account(request: Request, account_id: str):
    admin = _require_admin(request)
    conn = request.app.state.db
    admin_id = str(admin["account_id"])
    if account_id == admin_id:
        raise HTTPException(409, "不能删除当前登录的管理员账号")
    async with account_lifecycle_guard([admin_id, account_id], conn=conn):
        _assert_live_admin_actor(conn, admin_id)
        row = conn.execute(
            "SELECT account_id, username FROM accounts WHERE account_id = %s",
            (account_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        if row.get("username") == "admin":
            raise HTTPException(409, "管理员账号受保护，无法删除")
        counts, affected_players = await _delete_account_with_character_guard(
            conn,
            account_id,
            requested_by=admin_id,
        )
    await _invalidate_deleted_players(affected_players)
    return {"status": "deleted", "deleted_ids": [account_id], "counts": counts}


@router.post("/accounts/batch-delete")
async def delete_accounts(request: Request):
    admin = _require_admin(request)
    ids = await _get_confirmed_id_list(request, "ids")
    conn = request.app.state.db
    admin_id = str(admin["account_id"])
    deleted_ids: list[str] = []
    deleted_counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    invalidated_players: set[tuple[str, str]] = set()
    async with account_lifecycle_guard([admin_id, *ids], conn=conn):
        _assert_live_admin_actor(conn, admin_id)
        found_ids, not_found_ids = _split_found_and_missing(
            conn,
            "accounts",
            "account_id",
            ids,
        )
        found_rows = conn.execute(
            f"SELECT account_id, username FROM accounts WHERE account_id IN "
            f"{ '(' + ','.join(['%s'] * len(found_ids)) + ')' if found_ids else '()' }",
            tuple(found_ids),
        ).fetchall() if found_ids else []
        protected_accounts = {
            str(row["account_id"])
            for row in found_rows
            if row.get("username") == "admin"
        }

        for account_id in found_ids:
            if account_id == admin_id:
                errors.append({
                    "id": account_id,
                    "error": "不能删除当前登录的管理员账号",
                    "status": "409",
                })
                continue
            if account_id in protected_accounts:
                errors.append({
                    "id": account_id,
                    "error": "管理员账号受保护，无法删除",
                    "status": "409",
                })
                continue
            try:
                counts, affected_players = await _delete_account_with_character_guard(
                    conn,
                    account_id,
                    requested_by=admin_id,
                )
                invalidated_players.update(affected_players)
                _merge_delete_counts(deleted_counts, counts)
                deleted_ids.append(account_id)
            except HTTPException as exc:
                errors.append({
                    "id": account_id,
                    "error": str(exc.detail),
                    "status": str(exc.status_code),
                })
            except Exception:
                logger.exception("Failed to delete account %s", account_id)
                errors.append({
                    "id": account_id,
                    "error": "系统删除失败，请查看服务器日志",
                    "status": "500",
                    "code": "system_delete_failed",
                })

    await _invalidate_deleted_players(invalidated_players)
    return _batch_delete_response(ids, deleted_ids, not_found_ids, deleted_counts, errors)


@router.get("/campaign-archives")
async def list_campaign_archive_metadata(request: Request, limit: int = 100):
    _require_admin(request)
    rows = request.app.state.db.execute(
        "SELECT archive_id, room_id, ending_type, created_at "
        "FROM campaign_archives ORDER BY created_at DESC LIMIT %s",
        (min(max(limit, 1), 200),),
    ).fetchall()
    return {
        "archives": [
            project_campaign_archive(row, scope="admin_ops") for row in rows
        ]
    }


@router.post("/campaign-archives/purge")
async def purge_campaign_archives(request: Request):
    admin = _require_admin(request)
    payload = await _safe_json(request)
    if payload.get("confirm") is not True:
        raise HTTPException(400, "请确认后再执行彻底清除")
    if payload.get("purge_confirmation") != "PURGE_ARCHIVES":
        raise HTTPException(400, "请输入 PURGE_ARCHIVES 完成二次确认")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "彻底清除必须填写原因")
    archive_ids = _normalize_id_list(payload.get("archive_ids", []), "archive_ids")
    audit_reason = reason
    for archive_id in sorted(archive_ids, key=len, reverse=True):
        audit_reason = audit_reason.replace(archive_id, "[redacted-archive]")
    audit_reason = audit_reason[:500]
    async with _governance_actor_guard(
        request,
        str(admin["account_id"]),
    ) as conn:
        archive_filter, archive_params = _in_clause(archive_ids)
        with conn.transaction() as tx:
            tx.execute("SET LOCAL aikeeper.archive_purge = 'on'")
            deleted_rows = tx.execute(
                f"DELETE FROM campaign_archives WHERE archive_id IN {archive_filter} "
                "RETURNING archive_id",
                archive_params,
            ).fetchall()
            deleted_set = {str(row["archive_id"]) for row in deleted_rows}
            deleted_ids = [
                archive_id for archive_id in archive_ids if archive_id in deleted_set
            ]
            not_found_ids = [
                archive_id for archive_id in archive_ids if archive_id not in deleted_set
            ]
            if deleted_ids:
                target_hashes = [
                    hashlib.sha256(
                        f"{uuid.uuid4().hex}:{archive_id}".encode("utf-8")
                    ).hexdigest()
                    for archive_id in deleted_ids
                ]
                tx.execute(
                    """
                    INSERT INTO admin_data_purge_audits (
                        audit_id, action, actor_id, target_count, details
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        f"purge-audit-{uuid.uuid4().hex}",
                        "campaign_archive_full_purge",
                        admin["account_id"],
                        len(deleted_ids),
                        json.dumps(
                            {
                                "reason": audit_reason,
                                "target_hashes": target_hashes,
                                "retention_days": 365,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
    return _batch_delete_response(
        archive_ids,
        deleted_ids,
        not_found_ids,
        {"campaign_archives": len(deleted_ids)},
        [],
    )


def _split_found_and_missing(conn, table: str, id_field: str, ids: list[str]) -> tuple[list[str], list[str]]:
    if not ids:
        return [], []
    placeholder = "(" + ",".join(["%s"] * len(ids)) + ")"
    rows = conn.execute(
        f"SELECT {id_field} FROM {table} WHERE {id_field} IN {placeholder}",
        tuple(ids),
    ).fetchall()
    found = [str(row[id_field]) for row in rows]
    missing = [id_ for id_ in ids if id_ not in found]
    return found, missing


# ── Overview ──

@router.get("/acceptance")
async def admin_acceptance(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    rooms = conn.execute("SELECT COUNT(*) AS c FROM rooms").fetchone()["c"]
    scenarios = conn.execute("SELECT COUNT(*) AS c FROM scenarios").fetchone()["c"]
    return {
        "fixtures": [
            {
                "label": "玩家邀请与准备",
                "description": "登录、选预设角色、进入准备台。",
                "href": "/player/join",
            },
            {
                "label": "玩家叙事行动",
                "description": "自然语言、风险确认、判定卡与地图投影。",
                "href": "/player/join",
            },
            {
                "label": "房主开局检查",
                "description": "可开团剧本、玩家状态与开始门禁。",
                "href": "/host/create",
            },
            {
                "label": "剧本编译向导",
                "description": "导入、质量审核、素材绑定与发布。",
                "href": "/admin",
            },
        ],
        "counts": {"rooms": rooms, "scenarios": scenarios},
        "retention_days": 90,
    }

@router.get("/overview")
async def admin_overview(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    total_rooms = conn.execute("SELECT COUNT(*) as c FROM rooms").fetchone()["c"]
    active_rooms = conn.execute(
        "SELECT COUNT(*) as c FROM rooms WHERE status = 'active'"
    ).fetchone()["c"]
    total_accounts = conn.execute("SELECT COUNT(*) as c FROM accounts").fetchone()["c"]
    online_players = conn.execute(
        "SELECT COUNT(DISTINCT character_id) as c FROM characters WHERE status = 'active'"
    ).fetchone()["c"]
    pending_actions = conn.execute(
        "SELECT COUNT(*) as c FROM actions "
        "WHERE status IN ('awaiting_player_consent', 'queued', 'resolving')"
    ).fetchone()["c"]
    return {
        "total_rooms": total_rooms,
        "active_rooms": active_rooms,
        "total_accounts": total_accounts,
        "online_players": online_players,
        "pending_actions": pending_actions,
    }


# ── Rooms ──

@router.get("/rooms")
async def list_rooms(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT r.*, s.title as scenario_title FROM rooms r "
        "LEFT JOIN scenarios s ON r.scenario_id = s.scenario_id "
        "ORDER BY r.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/rooms/{room_id}")
async def get_room_detail(request: Request, room_id: str):
    _require_admin(request)
    conn = request.app.state.db
    room = conn.execute(
        "SELECT r.*, s.title as scenario_title FROM rooms r "
        "LEFT JOIN scenarios s ON r.scenario_id = s.scenario_id "
        "WHERE r.room_id = %s", (room_id,)
    ).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    chars = conn.execute(
        "SELECT * FROM characters WHERE room_id = %s", (room_id,)
    ).fetchall()
    result = dict(room)
    result["characters"] = [_char_summary(c) for c in chars]
    return result


@router.patch("/rooms/{room_id}")
async def update_room(request: Request, room_id: str):
    _require_admin(request)
    conn = request.app.state.db
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        raise HTTPException(404, "房间不存在")
    body = await request.json()
    allowed = ["status", "scenario_id", "spoiler_level"]
    sets, vals = [], []
    for k in allowed:
        if k in body:
            sets.append(f"{k} = %s")
            vals.append(body[k])
            if k == "scenario_id":
                scenario = conn.execute(
                    "SELECT publish_status, published_version_id FROM scenarios "
                    "WHERE scenario_id = %s",
                    (body[k],),
                ).fetchone()
                if not scenario:
                    raise HTTPException(404, "剧本不存在")
                scenario_version_id = scenario.get("published_version_id")
                if scenario.get("publish_status") != "published" or not scenario_version_id:
                    raise HTTPException(409, "剧本尚未确认发布，不能绑定房间")
                sets.append("scenario_version_id = %s")
                vals.append(scenario_version_id)
    if not sets:
        raise HTTPException(400, "没有有效字段")
    vals.append(room_id)
    conn.execute(f"UPDATE rooms SET {', '.join(sets)} WHERE room_id = %s", tuple(vals))
    conn.commit()
    return {"status": "updated", "room_id": room_id}


# ── Accounts ──

@router.get("/accounts")
async def list_accounts(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT account_id, username, display_name, role, last_seen_at, created_at "
        "FROM accounts ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.patch("/accounts/{account_id}")
async def update_account(request: Request, account_id: str):
    admin = _require_admin(request)
    conn = request.app.state.db
    body = await request.json()
    allowed = ["role", "display_name"]
    sets, vals = [], []
    for k in allowed:
        if k in body:
            if k == "role" and body[k] not in ("admin", "host", "player"):
                raise HTTPException(400, "角色必须是 admin, host 或 player")
            sets.append(f"{k} = %s")
            vals.append(body[k])
    if not sets:
        raise HTTPException(400, "没有有效字段")
    admin_id = str(admin["account_id"])
    async with account_lifecycle_guard([admin_id, account_id], conn=conn):
        _assert_live_admin_actor(conn, admin_id)
        with conn.transaction() as tx:
            acc = tx.execute(
                "SELECT * FROM accounts WHERE account_id = %s FOR UPDATE",
                (account_id,),
            ).fetchone()
            if not acc:
                raise HTTPException(404, "账户不存在")
            if acc["username"] == "admin" and "role" in body and body["role"] != "admin":
                raise HTTPException(409, "保留管理员账号不能降权")
            tx.execute(
                f"UPDATE accounts SET {', '.join(sets)} WHERE account_id = %s",
                (*vals, account_id),
            )
    return {"status": "updated", "account_id": account_id}


# ── Characters ──

@router.get("/characters")
async def list_characters(request: Request, room_id: str = ""):
    _require_admin(request)
    conn = request.app.state.db
    if room_id:
        rows = conn.execute(
            "SELECT * FROM characters WHERE room_id = %s ORDER BY player_name", (room_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM characters ORDER BY room_id, player_name"
        ).fetchall()
    return [_char_detail(c) for c in rows]


@router.patch("/characters/{character_id}")
async def update_character(request: Request, character_id: str):
    _require_admin(request)
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    if not char:
        raise HTTPException(404, "角色不存在")
    body = await request.json()

    # Fields that update xlsx_data
    stat_fields = {"hp", "max_hp", "san", "max_san", "mp", "max_mp", "luck", "status_tags"}
    xlsx = json.loads(char.get("xlsx_data") or "{}")
    for k in stat_fields & set(body.keys()):
        xlsx[k] = body[k]
    conn.execute(
        "UPDATE characters SET xlsx_data = %s WHERE character_id = %s",
        (json.dumps(xlsx, ensure_ascii=False), character_id),
    )

    # Fields that are top-level columns
    if "is_ready" in body:
        conn.execute("UPDATE characters SET is_ready = %s WHERE character_id = %s",
                     (body["is_ready"], character_id))
    if "status" in body:
        allowed_statuses = {"active", "removed"}
        if body["status"] not in allowed_statuses:
            raise HTTPException(400, f"Invalid status: {body['status']}")
        conn.execute("UPDATE characters SET status = %s WHERE character_id = %s",
                     (body["status"], character_id))

    conn.commit()

    # Push via ProjectionDispatcher for real-time Host/Player refresh
    try:
        updated_char = _char_summary(
            conn.execute("SELECT * FROM characters WHERE character_id = %s", (character_id,)).fetchone()
        )
        dispatcher = getattr(request.app.state, "dispatcher", None)
        if dispatcher is None:
            from .engine.projection import ProjectionDispatcher
            dispatcher = ProjectionDispatcher(conn)
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(dispatcher.emit(
                char["room_id"], "s2c_state_patch", "party",
                {"patches": [{"op": "replace", "path": f"/characters/{character_id}", "value": updated_char}]},
                character_id=character_id,
            ))
        except RuntimeError:
            pass  # no running event loop (sync context)
    except Exception as e:
        logger.warning("Admin character update WS push failed: %s", e)

    updated = conn.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    return _char_detail(updated)


# ── Scenarios & Assets ──

@router.get("/scenarios")
async def admin_list_scenarios(request: Request):
    _require_admin(request)
    from .scenario.import_service import is_import_job_retryable

    conn = request.app.state.db
    rows = conn.execute(
        """
        SELECT s.*, latest_job.job_id AS latest_import_job_id,
               latest_job.status AS latest_import_job_status,
               latest_job.updated_at AS latest_import_job_updated_at
        FROM scenarios s
        LEFT JOIN LATERAL (
            SELECT job_id, status, updated_at
            FROM import_jobs
            WHERE scenario_id = s.scenario_id
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
        ) latest_job ON TRUE
        ORDER BY s.created_at DESC
        """
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["latest_import_job_retryable"] = is_import_job_retryable(
            item.get("latest_import_job_status"),
            item.get("latest_import_job_updated_at"),
        )
        result.append(item)
    return result


@router.get("/scenarios/{scenario_id}/assets")
async def list_assets(request: Request, scenario_id: str):
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT * FROM scenario_assets WHERE scenario_id = %s ORDER BY created_at DESC",
        (scenario_id,)
    ).fetchall()
    # Admin-only: return full details including relative_path
    return [dict(r) for r in rows]


@router.post("/scenarios/{scenario_id}/assets")
async def upload_asset(request: Request, scenario_id: str,
                       file: UploadFile = File(...),
                       visibility: str = Form("host_only")):
    _require_admin(request)
    conn = request.app.state.db
    sc = conn.execute("SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone()
    if not sc:
        raise HTTPException(404, "剧本不存在")

    # ── Filename validation ──
    raw_name = file.filename or "unnamed"
    safe_name = Path(raw_name).name  # strip path traversal
    if safe_name != raw_name:
        raise HTTPException(400, "文件名不能包含路径分隔符")
    ext = Path(safe_name).suffix.lower() or ".bin"

    # Block dangerous extensions
    if ext in BLOCKED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: {ext}（安全策略禁止）")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: {ext}")

    # ── Size validation ──
    content = await file.read()
    if len(content) > MAX_ASSET_SIZE:
        raise HTTPException(400, f"文件过大（最大 50MB，当前 {len(content) // (1024*1024)}MB）")

    # ── MIME validation ──
    declared_mime = (file.content_type or "application/octet-stream").lower()
    if declared_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(400, f"不支持的 MIME 类型: {declared_mime}")

    # ── File header validation (magic bytes) ──
    if ext in MAGIC_BYTES:
        expected = MAGIC_BYTES[ext]
        if not content[:len(expected)] == expected:
            raise HTTPException(400, f"文件头与扩展名 {ext} 不匹配，可能是伪装文件")

    # ── Validate visibility ──
    if visibility not in ("host_only", "party", "private", "admin_only"):
        visibility = "host_only"

    # ── Persist ──
    asset_id = str(uuid.uuid4())[:8]
    stored_name = f"{asset_id}{ext}"
    asset_dir = ASSETS_ROOT / scenario_id
    asset_dir.mkdir(parents=True, exist_ok=True)

    asset_path = asset_dir / stored_name
    with open(asset_path, "wb") as f:
        f.write(content)

    relative_path = f"data/scenario_assets/{scenario_id}/{stored_name}"
    conn.execute(
        "INSERT INTO scenario_assets (asset_id, scenario_id, filename, original_name, mime_type, file_size, relative_path, visibility) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (asset_id, scenario_id, stored_name, safe_name,
         declared_mime, len(content), relative_path, visibility),
    )
    conn.commit()
    return {
        "asset_id": asset_id,
        "filename": safe_name,
        "mime_type": declared_mime,
        "file_size": len(content),
        "visibility": visibility,
    }


@router.delete("/scenarios/{scenario_id}/assets/{asset_id}")
async def delete_asset(request: Request, scenario_id: str, asset_id: str):
    _require_admin(request)
    conn = request.app.state.db
    row = conn.execute(
        "SELECT * FROM scenario_assets WHERE asset_id = %s AND scenario_id = %s",
        (asset_id, scenario_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "素材不存在")

    body = await _safe_json(request)
    force = (body or {}).get("force", False)
    force_confirm = (body or {}).get("confirm", False)
    force_reason = (body or {}).get("reason", "")

    # Check references before deletion
    refs = _find_asset_references(conn, asset_id, scenario_id)
    if refs:
        if not (force and force_confirm and force_reason):
            raise HTTPException(
                409,
                f"素材被 {len(refs)} 处引用，无法直接删除。使用 force=true + confirm=true + reason 强制删除",
            )
        logger.warning("Force-deleting asset %s with %d references by admin: %s",
                       asset_id, len(refs), force_reason)

    # Delete file (resolve symlinks, confirm within ASSETS_ROOT)
    row_dict = dict(row)
    rel_path = row_dict.get("relative_path", "")
    asset_path = (ASSETS_ROOT.parent / rel_path).resolve()
    if not str(asset_path).startswith(str(ASSETS_ROOT.resolve())):
        raise HTTPException(400, "素材路径异常，拒绝删除")
    try:
        os.remove(asset_path)
    except FileNotFoundError:
        pass

    conn.execute("DELETE FROM scenario_assets WHERE asset_id = %s", (asset_id,))
    conn.commit()
    return {"status": "deleted", "asset_id": asset_id, "reference_count": len(refs), "forced": force}


def _find_asset_references(conn, asset_id: str, scenario_id: str) -> list[dict]:
    """Find references to an asset across the database."""
    refs = []
    # Check room_scene_state
    rows = conn.execute(
        "SELECT room_id FROM room_scene_state WHERE current_asset_url LIKE %s",
        (f"%{asset_id}%",)
    ).fetchall()
    for r in rows:
        refs.append({"table": "room_scene_state", "room_id": r["room_id"]})
    # Check scenario_maps, including image/hybrid base assets.
    rows = conn.execute(
        "SELECT map_id FROM scenario_maps WHERE scenario_id = %s "
        "AND (nodes::text LIKE %s OR base_asset::text LIKE %s)",
        (scenario_id, f"%{asset_id}%", f"%{asset_id}%")
    ).fetchall()
    for r in rows:
        refs.append({"table": "scenario_maps", "map_id": r["map_id"]})
    rows = conn.execute(
        "SELECT binding_id FROM scenario_asset_bindings WHERE asset_id = %s",
        (asset_id,),
    ).fetchall()
    for r in rows:
        refs.append({"table": "scenario_asset_bindings", "binding_id": r["binding_id"]})
    return refs


# ── Scenario Import ──

@router.post("/scenarios/import-pdf")
async def admin_import_pdf(request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    from .scenario.router_scenarios import import_pdf
    return await import_pdf(request, file)


@router.post("/scenarios/{scenario_id}/classify")
async def admin_classify_scenario(request: Request, scenario_id: str):
    """Generate scenario type/classification from structured data."""
    _require_admin(request)
    conn = request.app.state.db
    sc = conn.execute("SELECT * FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone()
    if not sc:
        raise HTTPException(404, "剧本不存在")
    kg = _json_val(sc.get("knowledge_graph")) or {}
    synopsis = kg.get("synopsis", "")
    scene_count = len(kg.get("scenes", []))
    npc_count = len(kg.get("npcs", []))
    clue_count = len(kg.get("clues", []))
    truth = kg.get("truth", {})
    endings = kg.get("endings", [])

    classification = {
        "scenario_id": scenario_id,
        "title": sc["title"],
        "synopsis_preview": synopsis[:200] if synopsis else "",
        "scene_count": scene_count,
        "npc_count": npc_count,
        "clue_count": clue_count,
        "has_truth": bool(truth),
        "ending_count": len(endings),
        "type": _classify_type(synopsis, scene_count, npc_count, clue_count),
        "status": "classified",
    }
    return classification


def _classify_type(synopsis: str, scenes: int, npcs: int, clues: int) -> str:
    """Heuristic scenario type classification."""
    keywords = synopsis.lower() if synopsis else ""
    if any(w in keywords for w in ["凶杀", "谋杀", "杀人", "命案", "尸体"]):
        return "mystery"
    if any(w in keywords for w in ["失踪", "消失", "寻找", "搜索"]):
        return "investigation"
    if any(w in keywords for w in ["恐怖", "怪物", "诅咒", "疯狂"]):
        return "horror"
    if any(w in keywords for w in ["探险", "遗迹", "考古", "地下"]):
        return "expedition"
    if any(w in keywords for w in ["阴谋", "组织", "势力", "政治"]):
        return "conspiracy"
    if scenes >= 5 and npcs >= 5:
        return "epic"
    return "oneshot"


# ── Map Generation ──

def _map_base_asset(assets: dict) -> dict:
    if not isinstance(assets, dict):
        return {}
    candidates = [assets.get("baseMap"), assets.get("map"), assets.get("mapAsset")]
    maps = assets.get("maps")
    if isinstance(maps, list) and maps:
        candidates.append(maps[0])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return {"assetId": candidate}
        if isinstance(candidate, dict):
            asset_id = candidate.get("assetId", candidate.get("asset_id", ""))
            if isinstance(asset_id, str) and asset_id:
                return {"assetId": asset_id}
    return {}


def _select_map_base_asset(conn, scenario_id: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT asset_id, original_name, filename FROM scenario_assets "
        "WHERE scenario_id = %s AND mime_type LIKE 'image/%%' ORDER BY created_at",
        (scenario_id,),
    ).fetchall()
    exact = []
    partial = []
    for row in rows:
        name = Path(str(row.get("original_name") or row.get("filename") or "")).stem.lower()
        if name in {"地图", "map"}:
            exact.append(row)
        elif "地图" in name or "map" in name:
            partial.append(row)
    selected = (exact or partial)
    return {"assetId": selected[0]["asset_id"]} if selected else {}


def _map_draft_payload(map_data: dict) -> dict:
    return {
        "mapId": map_data["map_id"],
        "scenarioId": map_data["scenario_id"],
        "generatedBy": map_data["generated_by"],
        "status": map_data["status"],
        "mapType": map_data.get("map_type", "graph"),
        "baseAsset": map_data.get("base_asset", {}),
        "regions": map_data.get("regions", []),
        "paths": map_data.get("paths", []),
        "nodes": map_data["nodes"],
        "edges": map_data["edges"],
        "createdAt": map_data.get("created_at"),
        "confirmedAt": map_data.get("confirmed_at"),
    }


@router.post("/player-experience-v2/cutover")
async def cutover_player_experience_v2(request: Request):
    account = _require_admin(request)
    body = await _safe_json(request)
    from .v2_cutover import V2CutoverError, V2CutoverService

    backup_root = getattr(request.app.state, "v2_cutover_backup_root", None)
    if backup_root is None:
        backup_root = Path(__file__).resolve().parents[2] / "data" / "backups" / "v2-cutover"
    try:
        return V2CutoverService(
            request.app.state.db,
            Path(backup_root),
        ).backup_and_clear(
            str(body.get("confirmation") or ""),
            requested_by=str(account.get("account_id") or "unknown"),
        )
    except V2CutoverError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/scenarios/{scenario_id}/assets/{asset_id}/content")
async def preview_asset(request: Request, scenario_id: str, asset_id: str):
    _require_admin(request)
    row = request.app.state.db.execute(
        "SELECT filename, mime_type FROM scenario_assets "
        "WHERE asset_id = %s AND scenario_id = %s",
        (asset_id, scenario_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "素材不存在")
    asset_path = (ASSETS_ROOT / scenario_id / row["filename"]).resolve()
    if not asset_path.is_relative_to(ASSETS_ROOT.resolve()) or not asset_path.is_file():
        raise HTTPException(404, "素材文件不存在")
    return FileResponse(asset_path, media_type=row["mime_type"])


def _asset_binding_service(request: Request):
    from .scenario.asset_binding import ScenarioAssetBindingService

    asset_root = getattr(request.app.state, "scenario_asset_root", None)
    return ScenarioAssetBindingService(
        request.app.state.db,
        asset_root=Path(asset_root) if asset_root else None,
        gateway=getattr(request.app.state, "gateway", None),
    )


def _scene_image_service(request: Request):
    from .scenario.scene_image_service import SceneImageService

    asset_root = getattr(request.app.state, "scenario_asset_root", None)
    return SceneImageService(
        request.app.state.db,
        asset_root=Path(asset_root) if asset_root else None,
        gateway=getattr(request.app.state, "gateway", None),
    )


def _scene_image_error(exc: Exception) -> HTTPException:
    code = str(exc)
    if code.endswith("_provider_unavailable"):
        return HTTPException(503, code)
    if code in {"image_scene_not_found", "scenario_review_draft_not_found"}:
        return HTTPException(404, code)
    return HTTPException(400, code)


def _verify_asset_binding_version(conn, scenario_id: str, scenario_version_id: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM scenario_versions WHERE scenario_version_id = %s AND scenario_id = %s",
        (scenario_version_id, scenario_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "剧本版本不存在")


@router.post("/scenarios/{scenario_id}/versions/{scenario_version_id}/image-generations/suggestions")
async def suggest_scene_images(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
):
    _require_admin(request)
    _verify_asset_binding_version(request.app.state.db, scenario_id, scenario_version_id)
    try:
        body = await request.json()
    except Exception:
        body = {}
    requested_types = body.get("target_types") if isinstance(body, dict) else None
    target_types = {
        str(target_type).strip()
        for target_type in requested_types
        if str(target_type).strip()
    } if isinstance(requested_types, list) else {"scene"}
    try:
        return await _scene_image_service(request).suggest(
            scenario_id,
            scenario_version_id,
            target_types=target_types or {"scene"},
        )
    except Exception as exc:
        from .scenario.scene_image_service import SceneImageError

        if isinstance(exc, SceneImageError):
            raise _scene_image_error(exc) from exc
        logger.exception("Scene image suggestion failed version=%s", scenario_version_id)
        raise HTTPException(500, "场景配图建议失败") from exc


@router.post("/scenarios/{scenario_id}/versions/{scenario_version_id}/image-generations/preview")
async def preview_scene_image(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
):
    _require_admin(request)
    _verify_asset_binding_version(request.app.state.db, scenario_id, scenario_version_id)
    body = await request.json()
    try:
        return await _scene_image_service(request).preview(
            scenario_id,
            scenario_version_id,
            suggestion=body.get("suggestion") if isinstance(body.get("suggestion"), dict) else {},
            prompt=str(body.get("prompt") or ""),
            visibility=str(body.get("visibility") or "host_only"),
            size=str(body.get("size") or "1024x1024"),
        )
    except Exception as exc:
        from .scenario.scene_image_service import SceneImageError

        if isinstance(exc, SceneImageError):
            raise _scene_image_error(exc) from exc
        logger.exception("Scene image preview failed version=%s", scenario_version_id)
        raise HTTPException(500, "场景配图预览失败") from exc


@router.post("/scenarios/{scenario_id}/versions/{scenario_version_id}/image-generations/adopt")
async def adopt_scene_image(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
):
    _require_admin(request)
    _verify_asset_binding_version(request.app.state.db, scenario_id, scenario_version_id)
    body = await request.json()
    try:
        return _scene_image_service(request).adopt(
            scenario_id,
            scenario_version_id,
            preview_token=str(body.get("preview_token") or ""),
            data_url=str(body.get("data_url") or ""),
            adopted_by=_get_account_id(request),
        )
    except Exception as exc:
        from .scenario.scene_image_service import SceneImageError

        if isinstance(exc, SceneImageError):
            raise _scene_image_error(exc) from exc
        logger.exception("Scene image adoption failed version=%s", scenario_version_id)
        raise HTTPException(500, "场景配图采用失败") from exc


@router.post("/scenarios/{scenario_id}/versions/{scenario_version_id}/asset-bindings/generate")
async def generate_asset_bindings(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
):
    _require_admin(request)
    _verify_asset_binding_version(request.app.state.db, scenario_id, scenario_version_id)
    service = _asset_binding_service(request)
    try:
        bindings = await service.generate_bindings(scenario_version_id)
        targets = service.list_targets(scenario_version_id)
    except Exception as exc:
        logger.exception("Asset binding generation failed version=%s", scenario_version_id)
        raise HTTPException(500, "素材自动匹配失败") from exc
    return {"bindings": bindings, "targets": targets}


@router.get("/scenarios/{scenario_id}/versions/{scenario_version_id}/asset-bindings")
async def list_asset_bindings(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
):
    _require_admin(request)
    _verify_asset_binding_version(request.app.state.db, scenario_id, scenario_version_id)
    service = _asset_binding_service(request)
    return {
        "bindings": service.list_bindings(scenario_version_id),
        "targets": service.list_targets(scenario_version_id),
    }


@router.patch(
    "/scenarios/{scenario_id}/versions/{scenario_version_id}/asset-bindings/{binding_id}"
)
async def review_asset_binding(
    request: Request,
    scenario_id: str,
    scenario_version_id: str,
    binding_id: str,
):
    _require_admin(request)
    _verify_asset_binding_version(request.app.state.db, scenario_id, scenario_version_id)
    binding = request.app.state.db.execute(
        "SELECT 1 FROM scenario_asset_bindings "
        "WHERE binding_id = %s AND scenario_version_id = %s",
        (binding_id, scenario_version_id),
    ).fetchone()
    if not binding:
        raise HTTPException(404, "素材绑定不存在")
    body = await request.json()
    from .scenario.asset_binding import AssetBindingError

    try:
        result = _asset_binding_service(request).review_binding(
            binding_id,
            target_type=str(body.get("target_type") or ""),
            target_key=str(body.get("target_key") or ""),
            status=str(body.get("status") or "draft"),
            reviewed_by=_get_account_id(request),
        )
    except AssetBindingError as exc:
        code = str(exc)
        status_code = 404 if code == "binding_not_found" else 409
        raise HTTPException(status_code, code) from exc
    return result


def _load_golden_module(module_id: str) -> tuple[dict, Path]:
    if not re.fullmatch(r"[a-z0-9-]{1,120}", module_id):
        raise HTTPException(404, "黄金模组不存在")
    root = Path(__file__).resolve().parents[2] / "data" / "golden_modules"
    for path in root.glob("*/module.json"):
        try:
            module = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        manifest = module.get("manifest", {})
        if isinstance(manifest, dict) and manifest.get("module_id") == module_id:
            return module, path
    raise HTTPException(404, "黄金模组不存在")


def _golden_map_nodes(raw_nodes: list[dict]) -> list[dict]:
    total = max(1, len(raw_nodes))
    nodes = []
    for index, raw_node in enumerate(raw_nodes):
        node_id = raw_node.get("node_id", raw_node.get("nodeId", ""))
        if not isinstance(node_id, str) or not node_id:
            raise HTTPException(422, "黄金模组包含无效文字地图节点")
        x = 50 if total == 1 else round(15 + index * 70 / (total - 1), 1)
        nodes.append({
            "node_id": node_id,
            "name": raw_node.get("name", node_id),
            "description": raw_node.get("description", ""),
            "npcs_present": raw_node.get("npcs_present", raw_node.get("npcsPresent", [])),
            "clues_available": raw_node.get("clues_available", raw_node.get("cluesAvailable", [])),
            "position": raw_node.get("position", {"x": x, "y": 50}),
            "is_start": bool(raw_node.get("is_start", raw_node.get("isStart", index == 0))),
        })
    return nodes


def _golden_map_edges(raw_edges: list[dict]) -> list[dict]:
    edges = []
    for raw_edge in raw_edges:
        from_node = raw_edge.get("from_node", raw_edge.get("fromNode", raw_edge.get("from", "")))
        to_node = raw_edge.get("to_node", raw_edge.get("toNode", raw_edge.get("to", "")))
        if not isinstance(from_node, str) or not isinstance(to_node, str) or not from_node or not to_node:
            raise HTTPException(422, "黄金模组包含无效文字地图路径")
        edges.append({
            "from_node": from_node,
            "to_node": to_node,
            "is_one_way": bool(raw_edge.get("is_one_way", raw_edge.get("isOneWay", False))),
            "label": raw_edge.get("label", ""),
        })
    return edges


def _normalize_golden_knowledge_graph(
    raw_graph: dict,
    raw_citations: list,
    *,
    source_part_id: str,
) -> dict:
    """Adapt authored golden-module references into runtime-verifiable evidence."""
    graph = json.loads(json.dumps(raw_graph, ensure_ascii=False))
    citations = {
        str(entry.get("citation_id") or ""): entry
        for entry in raw_citations
        if isinstance(entry, dict) and str(entry.get("citation_id") or "")
    }

    def source_citation(value: dict, fallback_ref: str) -> dict:
        existing = value.get("citation")
        if isinstance(existing, dict) and (
            existing.get("source_part_id") or existing.get("source_ref")
        ):
            citation = dict(existing)
            citation.setdefault("source_part_id", source_part_id)
            citation.setdefault("source_ref", fallback_ref)
            return citation
        citation_ids = value.get("citation_ids")
        if not isinstance(citation_ids, list):
            citation_ids = []
        entry = next(
            (
                citations.get(str(citation_id))
                for citation_id in citation_ids
                if citations.get(str(citation_id))
            ),
            {},
        )
        citation = {
            "source_part_id": source_part_id,
            "source_ref": str(entry.get("source_ref") or fallback_ref),
        }
        if entry.get("citation_id"):
            citation["citation_id"] = str(entry["citation_id"])
        if entry.get("label"):
            citation["label"] = str(entry["label"])
        return citation

    for collection_name in ("scenes", "npcs", "clues", "endings"):
        values = graph.get(collection_name)
        if not isinstance(values, list):
            continue
        for ordinal, value in enumerate(values):
            if not isinstance(value, dict):
                continue
            value["citation"] = source_citation(
                value,
                f"module.json#/knowledge_graph/{collection_name}/{ordinal}",
            )
    truth = graph.get("truth")
    if isinstance(truth, dict):
        truth["citation"] = source_citation(
            truth,
            "module.json#/knowledge_graph/truth",
        )

    raw_rule_triggers = graph.get("rule_triggers") or graph.get("rule_citations")
    if isinstance(raw_rule_triggers, dict):
        raw_rule_triggers = [raw_rule_triggers]
    if isinstance(raw_rule_triggers, list):
        rule_triggers = []
        for ordinal, trigger in enumerate(raw_rule_triggers):
            if not isinstance(trigger, dict):
                continue
            normalized_trigger = dict(trigger)
            source_ref = str(normalized_trigger.get("source_ref") or "")
            if source_ref:
                normalized_trigger["citation"] = {
                    "source_ref": source_ref,
                    "citation_id": str(normalized_trigger.get("citation_id") or ""),
                }
            else:
                normalized_trigger["citation"] = source_citation(
                    normalized_trigger,
                    f"module.json#/knowledge_graph/rule_citations/{ordinal}",
                )
            rule_triggers.append(normalized_trigger)
        graph["rule_triggers"] = rule_triggers

    branches = graph.get("branches")
    if not isinstance(branches, list) or not branches:
        scene_ids = {
            str(scene.get("scene_id") or scene.get("id") or "")
            for scene in graph.get("scenes") or []
            if isinstance(scene, dict)
        }
        generated_branches = []
        emitted_pairs = set()
        for scene_index, scene in enumerate(graph.get("scenes") or []):
            if not isinstance(scene, dict):
                continue
            from_scene_id = str(scene.get("scene_id") or scene.get("id") or "")
            if not from_scene_id:
                continue
            for target in scene.get("exits") or []:
                to_scene_id = str(target or "")
                pair = (from_scene_id, to_scene_id)
                if to_scene_id not in scene_ids or pair in emitted_pairs:
                    continue
                emitted_pairs.add(pair)
                generated_branches.append({
                    "branch_id": f"{from_scene_id}-to-{to_scene_id}",
                    "from_scene_id": from_scene_id,
                    "to_scene_id": to_scene_id,
                    "conditions": [],
                    "citation": source_citation(
                        scene,
                        f"module.json#/knowledge_graph/scenes/{scene_index}",
                    ),
                })
        graph["branches"] = generated_branches
    else:
        for ordinal, branch in enumerate(branches):
            if isinstance(branch, dict):
                branch["citation"] = source_citation(
                    branch,
                    f"module.json#/knowledge_graph/branches/{ordinal}",
                )
    return graph


@router.post("/golden-modules/{module_id}/install", status_code=201)
async def install_golden_module(request: Request, module_id: str):
    account = _require_admin(request)
    module, module_path = _load_golden_module(module_id)
    manifest = module.get("manifest", {})
    raw_knowledge_graph = module.get("knowledge_graph", {})
    scenario_assets = module.get("scenario_assets", {})
    templates = module.get("character_templates", [])
    quality_report = module.get("quality_report", {})
    if (
        manifest.get("format") != "aikeeper-golden-module"
        or not isinstance(raw_knowledge_graph, dict)
        or not all(isinstance(raw_knowledge_graph.get(key), list) and raw_knowledge_graph[key] for key in ("scenes", "npcs", "clues"))
        or not isinstance(scenario_assets, dict)
        or not isinstance(templates, list)
        or not templates
    ):
        raise HTTPException(422, "黄金模组结构不完整")
    text_map = scenario_assets.get("text_map", {})
    if not isinstance(text_map, dict):
        raise HTTPException(422, "黄金模组缺少文字地图")
    nodes = _golden_map_nodes(text_map.get("nodes", []))
    edges = _golden_map_edges(text_map.get("edges", []))
    if not nodes:
        raise HTTPException(422, "黄金模组缺少文字地图节点")

    conn = request.app.state.db
    scenario_id = f"golden-{module_id}"
    if conn.execute("SELECT 1 FROM scenarios WHERE scenario_id = %s", (scenario_id,)).fetchone():
        raise HTTPException(409, "黄金模组已安装")
    rule_version = conn.execute(
        "SELECT rsv.rule_set_version_id FROM rule_set_versions rsv "
        "JOIN rule_sets rs ON rs.rule_set_id = rsv.rule_set_id "
        "WHERE rs.slug = 'coc7' AND rs.status = 'published' AND rsv.status = 'published' "
        "ORDER BY rsv.version_number DESC LIMIT 1"
    ).fetchone()
    if not rule_version:
        raise HTTPException(409, "需要先发布授权的 CoC7 规则版本")

    raw_module = module_path.read_bytes()
    source_sha256 = hashlib.sha256(raw_module).hexdigest()
    scenario_version_id = f"{scenario_id}-v1"
    source_document_id = f"{scenario_id}-source"
    source_part_id = f"{source_document_id}-part-1"
    map_id = f"{scenario_id}-map"
    created_by = account.get("account_id", "unknown")
    knowledge_graph = _normalize_golden_knowledge_graph(
        raw_knowledge_graph,
        module.get("citations", []),
        source_part_id=source_part_id,
    )
    prep_package = {
        "golden_module": manifest,
        "citations": module.get("citations", []),
        "rag_expectations": module.get("rag_expectations", []),
    }
    with conn.transaction() as transaction:
        transaction.execute(
            "INSERT INTO scenarios "
            "(scenario_id, title, raw_text, knowledge_graph, scenario_assets, quality_report, import_status, publish_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'structured', 'published')",
            (
                scenario_id, manifest.get("title", module_id), module.get("raw_text", ""),
                json.dumps(knowledge_graph, ensure_ascii=False), json.dumps(scenario_assets, ensure_ascii=False),
                json.dumps(quality_report, ensure_ascii=False),
            ),
        )
        transaction.execute(
            "INSERT INTO source_documents "
            "(source_document_id, scenario_id, source_kind, title, source_filename, mime_type, source_sha256, "
            "storage_path, license_type, license_ref, status, metadata, created_by) "
            "VALUES (%s, %s, 'golden_module', %s, 'module.json', 'application/json', %s, %s, 'authorized', %s, 'parsed', %s, %s)",
            (
                source_document_id, scenario_id, manifest.get("title", module_id), source_sha256,
                str(module_path.relative_to(Path(__file__).resolve().parents[2])).replace("\\", "/"),
                manifest.get("license", {}).get("license_id", ""),
                json.dumps({"module_id": module_id, "schema_version": manifest.get("schema_version", "")}, ensure_ascii=False),
                created_by,
            ),
        )
        transaction.execute(
            "INSERT INTO source_parts "
            "(source_part_id, source_document_id, ordinal, part_kind, text_content, mime_type, anchor, checksum) "
            "VALUES (%s, %s, 1, 'text', %s, 'application/json', %s, %s)",
            (
                source_part_id, source_document_id, module.get("raw_text", ""),
                json.dumps({"source_ref": "module.json#/raw_text"}), source_sha256,
            ),
        )
        transaction.execute(
            "INSERT INTO scenario_versions "
            "(scenario_version_id, scenario_id, version_number, status, knowledge_graph, quality_report, prep_package, created_by, published_at) "
            "VALUES (%s, %s, 1, 'published', %s, %s, %s, %s, NOW())",
            (
                scenario_version_id, scenario_id, json.dumps(knowledge_graph, ensure_ascii=False),
                json.dumps(quality_report, ensure_ascii=False), json.dumps(prep_package, ensure_ascii=False), created_by,
            ),
        )
        transaction.execute(
            "INSERT INTO scenario_version_sources (scenario_version_id, source_document_id, ordinal) VALUES (%s, %s, 1)",
            (scenario_version_id, source_document_id),
        )
        transaction.execute(
            "UPDATE scenarios SET published_version_id = %s WHERE scenario_id = %s",
            (scenario_version_id, scenario_id),
        )
        transaction.execute(
            "INSERT INTO scenario_rule_bindings (scenario_version_id, rule_set_version_id) VALUES (%s, %s)",
            (scenario_version_id, rule_version["rule_set_version_id"]),
        )
        for index, template in enumerate(templates):
            transaction.execute(
                "INSERT INTO character_templates "
                "(template_id, scenario_id, name, occupation, background, age, gender, attributes, skills, backstory) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    f"{scenario_id}-template-{index + 1}", scenario_id, template.get("name", f"预设角色 {index + 1}"),
                    template.get("occupation", ""), template.get("background", ""), template.get("age", 25),
                    template.get("gender", ""), json.dumps(template.get("attributes", {}), ensure_ascii=False),
                    json.dumps(template.get("skills", {}), ensure_ascii=False), json.dumps(template.get("backstory", {}), ensure_ascii=False),
                ),
            )
        transaction.execute(
            "INSERT INTO scenario_maps "
            "(map_id, scenario_id, generated_by, status, map_type, nodes, edges, paths, confirmed_at) "
            "VALUES (%s, %s, 'golden_module', 'confirmed', 'graph', %s, %s, %s, NOW())",
            (
                map_id, scenario_id, json.dumps(nodes, ensure_ascii=False), json.dumps(edges, ensure_ascii=False),
                json.dumps([
                    {"pathId": f"path-{index}", "fromNodeId": edge["from_node"], "toNodeId": edge["to_node"],
                     "isOneWay": edge["is_one_way"], "label": edge["label"]}
                    for index, edge in enumerate(edges)
                ], ensure_ascii=False),
            ),
        )
    from .scenario.content_projection import ContentProjectionService
    from .scenario.module_compiler import ModuleCompiler

    ContentProjectionService(conn).rebuild(
        scenario_version_id,
        knowledge_graph,
        requested_by=created_by,
    )
    runtime_package = ModuleCompiler(conn).compile(
        scenario_version_id,
        requested_by=created_by,
    )
    if runtime_package["gate_status"] != "ready":
        conn.execute(
            "UPDATE scenario_versions SET status = 'draft' WHERE scenario_version_id = %s",
            (scenario_version_id,),
        )
        conn.execute(
            "UPDATE scenarios SET publish_status = 'draft' WHERE scenario_id = %s",
            (scenario_id,),
        )
        conn.commit()
        raise HTTPException(422, {
            "message": "黄金模组运行包未达到可开团门槛",
            "quality_exceptions": runtime_package["quality_exceptions"],
        })
    return {
        "scenarioId": scenario_id,
        "scenarioVersionId": scenario_version_id,
        "title": manifest.get("title", module_id),
        "status": "published",
        "runtimePackage": runtime_package,
    }


@router.post("/scenarios/{scenario_id}/map/generate")
async def admin_generate_map(
    request: Request,
    scenario_id: str,
    scenario_version_id: str | None = None,
):
    """Generate a map draft from knowledge_graph.scenes (primary) or scenario_assets.scenes (fallback)."""
    _require_admin(request)
    conn = request.app.state.db

    scenario = conn.execute(
        "SELECT knowledge_graph, scenario_assets FROM scenarios WHERE scenario_id = %s", (scenario_id,)
    ).fetchone()
    if not scenario:
        raise HTTPException(404, "剧本不存在")

    if scenario_version_id:
        version = conn.execute(
            "SELECT knowledge_graph FROM scenario_versions "
            "WHERE scenario_version_id = %s AND scenario_id = %s",
            (scenario_version_id, scenario_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "剧本版本不存在")
        kg = _json_val(version.get("knowledge_graph")) or {}
    else:
        kg = _json_val(scenario.get("knowledge_graph")) or {}

    # Primary source: versioned knowledge_graph.scenes (WorldBook structured output)
    scenes = kg.get("scenes", [])

    # Fallback: scenario_assets.scenes (legacy)
    if not scenes:
        assets = _json_val(scenario.get("scenario_assets")) or {}
        scenes = assets.get("scenes", [])
        if scenes:
            logger.info("Map generation using legacy scenario_assets.scenes for %s", scenario_id)

    if not scenes:
        raise HTTPException(400, "剧本没有场景数据（knowledge_graph.scenes 和 scenario_assets.scenes 均为空）")

    from .config import Settings
    settings = Settings.from_env()

    from .ai.gateway import AiGateway
    from .ai.map_generator import MapGenerator
    gen = MapGenerator(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        gateway=AiGateway(settings=settings, db_conn=conn),
    )
    base_asset = (
        _map_base_asset(_json_val(scenario.get("scenario_assets")) or {})
        or _select_map_base_asset(conn, scenario_id)
    )
    try:
        draft = await asyncio.wait_for(
            gen.generate_draft(scenes, base_asset),
            timeout=35,
        )
        generated_by = gen.last_generated_by
    except TimeoutError:
        logger.warning("AI map generation timed out for scenario %s; using local fallback", scenario_id)
        fallback = MapGenerator(api_key="", gateway=None)
        draft = await fallback.generate_draft(scenes, base_asset)
        generated_by = fallback.last_generated_by

    map_id = f"map_{scenario_id}_{str(uuid.uuid4())[:4]}"
    from .map_persistence import create_scenario_map
    result = create_scenario_map(
        conn, map_id, scenario_id, generated_by, draft["nodes"], draft["edges"],
        draft["map_type"], draft["base_asset"], draft["regions"], draft["paths"],
    )

    return _map_draft_payload(result)


@router.get("/scenarios/{scenario_id}/map")
async def admin_get_map(request: Request, scenario_id: str):
    """Get the current map draft for a scenario."""
    _require_admin(request)
    conn = request.app.state.db
    from .map_persistence import get_scenario_map_by_scenario
    mp = get_scenario_map_by_scenario(conn, scenario_id)
    if not mp:
        raise HTTPException(404, "该剧本暂无地图")
    return _map_draft_payload(mp)


@router.patch("/scenarios/{scenario_id}/map")
async def admin_edit_map(request: Request, scenario_id: str):
    """Host edits map nodes/edges before confirming."""
    _require_admin(request)
    body = await request.json()
    conn = request.app.state.db
    from .map_persistence import get_scenario_map_by_scenario, update_scenario_map
    mp = get_scenario_map_by_scenario(conn, scenario_id)
    if not mp:
        raise HTTPException(404, "该剧本暂无地图")
    if mp["status"] == "confirmed":
        raise HTTPException(400, "已确认的地图不可编辑")
    nodes = body.get("nodes", [])
    edges = body.get("edges", [])
    map_type = body.get("mapType", mp.get("map_type", "graph"))
    if map_type not in {"graph", "image", "hybrid"}:
        raise HTTPException(422, "mapType must be graph, image, or hybrid")
    base_asset = body.get("baseAsset", mp.get("base_asset", {}))
    regions = body.get("regions", mp.get("regions", []))
    paths = body.get("paths", mp.get("paths", []))
    update_scenario_map(conn, mp["map_id"], nodes, edges, map_type, base_asset, regions, paths)
    return {"status": "updated", "mapId": mp["map_id"]}


@router.post("/scenarios/{scenario_id}/map/confirm")
async def admin_confirm_map(request: Request, scenario_id: str):
    """Host confirms map — locks it for use in rooms."""
    _require_admin(request)
    conn = request.app.state.db
    from .map_persistence import get_scenario_map_by_scenario, confirm_scenario_map
    mp = get_scenario_map_by_scenario(conn, scenario_id)
    if not mp:
        raise HTTPException(404, "该剧本暂无地图")
    result = confirm_scenario_map(conn, mp["map_id"])
    return {
        "mapId": result["map_id"],
        "status": result["status"],
        "confirmedAt": result.get("confirmed_at"),
    }


# ── AI Config ──

@router.get("/ai/config")
async def get_ai_config(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    from .ai.ai_config import get_global_ai_config
    return get_global_ai_config(conn)


@router.patch("/ai/config")
async def update_ai_config(request: Request):
    _require_admin(request)
    body = await request.json()
    conn = request.app.state.db
    from .ai.ai_config import update_global_ai_config
    update_global_ai_config(conn, body)
    return {"status": "updated"}


@router.post("/ai/health-check")
async def trigger_ai_health_check(request: Request):
    _require_admin(request)
    gateway = getattr(request.app.state, "gateway", None)
    if not gateway:
        raise HTTPException(503, "AiGateway not initialized")
    result = await gateway.health_check()
    return result


@router.get("/ai/providers")
async def list_ai_providers(request: Request):
    _require_admin(request)
    from .ai.provider_config import AiProviderConfigStore

    return AiProviderConfigStore(request.app.state.db).list_public()


@router.post("/ai/providers")
async def create_ai_provider(request: Request):
    account = _require_admin(request)
    body = await request.json()
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError

    async with _governance_actor_guard(request, str(account["account_id"])) as conn:
        try:
            return AiProviderConfigStore(conn).create(
                body,
                actor_id=account["account_id"],
            )
        except ProviderConfigError as exc:
            raise _provider_config_http_error(exc) from exc


@router.patch("/ai/providers/{provider_config_id}")
async def update_ai_provider(request: Request, provider_config_id: str):
    account = _require_admin(request)
    body = await request.json()
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError

    async with _governance_actor_guard(request, str(account["account_id"])) as conn:
        try:
            return AiProviderConfigStore(conn).update(
                provider_config_id,
                body,
                actor_id=account["account_id"],
            )
        except ProviderConfigError as exc:
            raise _provider_config_http_error(exc) from exc


@router.delete("/ai/providers/{provider_config_id}")
async def delete_ai_provider(request: Request, provider_config_id: str):
    account = _require_admin(request)
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError

    async with _governance_actor_guard(request, str(account["account_id"])) as conn:
        store = AiProviderConfigStore(conn)
        try:
            was_active = store.get_public(provider_config_id)["is_active"]
            store.delete(provider_config_id, actor_id=account["account_id"])
            return {"status": "deleted", "was_active": was_active}
        except ProviderConfigError as exc:
            raise _provider_config_http_error(exc) from exc


@router.post("/ai/providers/{provider_config_id}/test")
async def test_ai_provider(request: Request, provider_config_id: str):
    account = _require_admin(request)
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError
    from .ai.providers import ConfiguredOpenAIProvider

    async with _governance_actor_guard(request, str(account["account_id"])) as conn:
        store = AiProviderConfigStore(conn)
        try:
            config = store.get_internal(provider_config_id)
            result = await ConfiguredOpenAIProvider(config).test_connection()
            store.record_test(
                provider_config_id,
                passed=bool(result["ok"]),
                latency_ms=int(result.get("latency_ms") or 0),
                actor_id=account["account_id"],
            )
            return result
        except ProviderConfigError as exc:
            raise _provider_config_http_error(exc) from exc


@router.post("/ai/providers/{provider_config_id}/activate")
async def activate_ai_provider(request: Request, provider_config_id: str):
    account = _require_admin(request)
    from .ai.provider_config import AiProviderConfigStore, ProviderConfigError

    async with _governance_actor_guard(request, str(account["account_id"])) as conn:
        try:
            return AiProviderConfigStore(conn).activate(
                provider_config_id,
                actor_id=account["account_id"],
            )
        except ProviderConfigError as exc:
            raise _provider_config_http_error(exc) from exc


@router.get("/ai/logs")
async def get_ai_logs(request: Request, room_id: str = "", task_type: str = "",
                       provider: str = "", status: str = "", limit: int = 50):
    _require_admin(request)
    conn = request.app.state.db
    where = []
    params: list = []
    if room_id:
        where.append("room_id = %s"); params.append(room_id)
    if task_type:
        where.append("task_type = %s"); params.append(task_type)
    if provider:
        where.append("provider = %s"); params.append(provider)
    if status:
        where.append("status = %s"); params.append(status)
    where_clause = " AND ".join(where) if where else "TRUE"
    rows = conn.execute(
        f"SELECT id, decision_audit_id, room_id, action_id, task_type, provider, model, "
        f"duration_ms, status, record_kind, created_at, expires_at FROM ai_call_logs "
        f"WHERE {where_clause} ORDER BY created_at DESC LIMIT %s",
        tuple(params + [min(max(limit, 1), 200)]),
    ).fetchall()
    return {"logs": [dict(r) for r in rows]}


def _retention_request_fields(payload: dict) -> tuple[str, str]:
    from datetime import datetime, timedelta, timezone

    cutoff = str(payload.get("cutoff") or "").strip()
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    if not cutoff or not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(400, "cutoff and idempotency_key are required")
    try:
        parsed = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "cutoff must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise HTTPException(400, "cutoff must include a timezone")
    if parsed > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise HTTPException(400, "cutoff must not be in the future")
    return cutoff, idempotency_key


@router.post("/retention/dry-run")
async def retention_dry_run(request: Request):
    _require_admin(request)
    payload = await _safe_json(request)
    cutoff, idempotency_key = _retention_request_fields(payload)
    from .governance.retention import RetentionService

    return RetentionService(request.app.state.db).dry_run(
        cutoff=cutoff,
        idempotency_key=idempotency_key,
    )


@router.post("/retention/apply")
async def retention_apply(request: Request):
    account = _require_admin(request)
    payload = await _safe_json(request)
    if payload.get("confirm") is not True:
        raise HTTPException(400, "retention apply requires explicit confirmation")
    cutoff, idempotency_key = _retention_request_fields(payload)
    dry_run_token = str(payload.get("dry_run_token") or "").strip()
    if not dry_run_token:
        raise HTTPException(400, "dry_run_token is required")
    from .governance.retention import RetentionError, RetentionService

    async with _governance_actor_guard(request, str(account["account_id"])) as conn:
        try:
            return RetentionService(conn).apply(
                cutoff=cutoff,
                idempotency_key=idempotency_key,
                dry_run_token=dry_run_token,
                actor_id=account["account_id"],
            )
        except RetentionError as exc:
            raise HTTPException(409, detail={"code": exc.code}) from exc


@router.post("/sensitive-access/grants", status_code=201)
async def create_sensitive_access_grant(request: Request, response: Response):
    account = _require_admin(request)
    body = await _safe_json(request)
    incident_id = str(body.get("incident_id") or "").strip()
    reason = str(body.get("reason") or "").strip()
    scope = str(body.get("scope") or "").strip()
    try:
        ttl = int(body.get("ttl_seconds") or 0)
    except (TypeError, ValueError):
        ttl = 0
    if (
        not incident_id
        or not reason
        or scope != "ai_decision:read"
        or ttl < 1
        or ttl > 900
    ):
        raise HTTPException(400, "incident_id, reason, scope and short ttl are required")
    from .governance.retention import issue_sensitive_access_grant
    async with _governance_actor_guard(request, str(account["account_id"])):
        response.headers["Cache-Control"] = "no-store"
        return {"grant": issue_sensitive_access_grant(actor_id=account["account_id"],
                 incident_id=incident_id, reason=reason, scope=scope, ttl_seconds=ttl)}


@router.post("/ai/logs/{log_id}/sensitive")
async def get_sensitive_ai_log(request: Request, response: Response, log_id: int):
    account = _require_admin(request)
    body = await _safe_json(request)
    incident_id = str(body.get("incident_id") or "").strip()
    reason = str(body.get("reason") or "").strip()
    grant = request.headers.get("X-Sensitive-Access-Grant", "")
    from .governance.retention import RetentionError, verify_sensitive_access_grant
    async with _governance_actor_guard(request, str(account["account_id"])) as conn:
        try:
            verify_sensitive_access_grant(grant, actor_id=account["account_id"],
                incident_id=incident_id, reason=reason, scope="ai_decision:read")
        except RetentionError as exc:
            raise HTTPException(403, detail={"code": exc.code}) from exc
        with conn.transaction() as tx:
            row = tx.execute(
                "SELECT * FROM ai_call_logs WHERE id = %s AND record_kind = 'decision'",
                (log_id,),
            ).fetchone()
            if not row:
                raise HTTPException(404, "AI audit not found")
            room_link = tx.execute(
                "SELECT room_id FROM rooms WHERE room_id = %s",
                (row.get("room_id"),),
            ).fetchone() if row.get("room_id") else None
            tx.execute("INSERT INTO private_data_access_audits "
                "(private_data_access_audit_id, room_id, host_account_id, reason, incident_id, scope, resource_type, resource_id) "
                "VALUES (%s, %s, %s, %s, %s, 'ai_decision:read', 'ai_call_log', %s)",
                (f"access-{uuid.uuid4().hex}", room_link["room_id"] if room_link else None,
                 account["account_id"], reason, incident_id, str(log_id)))
            result = dict(row)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/ai/query")
async def test_knowledge_query(request: Request):
    _require_admin(request)
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    room_id = body.get("room_id", "")
    sources = body.get("sources", "both")
    gateway = getattr(request.app.state, "gateway", None)
    if not gateway:
        raise HTTPException(503, "AiGateway not initialized")
    result = await gateway.query_knowledge(query, room_id or "test", sources)
    return result.model_dump(by_alias=True) if hasattr(result, 'model_dump') else result


# ── RAG Admin ──

@router.post("/rag/context-preview")
async def rag_context_preview(request: Request):
    _require_admin(request)
    body = await request.json()
    room_id = body.get("room_id", "")
    action_text = body.get("action_text", "")
    character_id = body.get("character_id", "")
    scenario_id = body.get("scenario_id", "")
    rag = getattr(request.app.state, "rag", None)
    conn = request.app.state.db
    from .ai.rag_context import RAGContextBuilder
    builder = RAGContextBuilder(conn, rag)
    if not room_id:
        raise HTTPException(400, "room_id required")
    return builder.preview(room_id, action_text, character_id, scenario_id)


@router.post("/rag/reindex")
async def rag_reindex(request: Request):
    _require_admin(request)
    conn = request.app.state.db
    rag = getattr(request.app.state, "rag", None)
    if not rag:
        raise HTTPException(503, "RAG not available")
    body = await request.json()
    kinds = body.get("kinds", ["scenarios", "characters", "events", "rules"])

    counts = {}
    rebuilt_by = _get_account_id(request)
    rebuilt_at = None
    from datetime import datetime, timezone
    # Re-index scenarios
    if "scenarios" in kinds:
        rows = conn.execute("SELECT scenario_id, raw_text, knowledge_graph FROM scenarios WHERE raw_text IS NOT NULL").fetchall()
        for r in rows:
            rag.index_scenario(r["scenario_id"], r["raw_text"])
            kg = r.get("knowledge_graph") or {}
            if isinstance(kg, str):
                try:
                    from json import loads; kg = loads(kg)
                except Exception:
                    kg = {}
            if kg:
                rag.index_npc_graph(r["scenario_id"], kg)
        counts["scenarios"] = len(rows)
        rebuilt_at = datetime.now(timezone.utc).isoformat()

    # Re-index characters
    if "characters" in kinds:
        rows = conn.execute("SELECT * FROM characters WHERE xlsx_data IS NOT NULL").fetchall()
        for r in rows:
            xlsx = r.get("xlsx_data") or {}
            if isinstance(xlsx, str):
                try:
                    from json import loads; xlsx = loads(xlsx)
                except Exception:
                    xlsx = {}
            rag.index_character(r["room_id"], r["character_id"], xlsx)
        counts["characters"] = len(rows)

    # Re-index events
    if "events" in kinds:
        rows = conn.execute("SELECT room_id, sequence, event_type, payload FROM events ORDER BY sequence DESC LIMIT 500").fetchall()
        for r in rows:
            payload = r["payload"] or {}
            if isinstance(payload, str):
                try:
                    from json import loads; payload = loads(payload)
                except Exception:
                    payload = {}
            rag.index_event(r["room_id"], r["event_type"], payload, r["sequence"])
        counts["events"] = len(rows)

    return {
        "status": "reindexed",
        "counts": counts,
        "rebuilt_by": rebuilt_by,
        "rebuilt_at": rebuilt_at,
    }


@router.post("/rag/reindex-version")
async def rag_reindex_version(request: Request):
    account = _require_admin(request)
    conn = request.app.state.db
    rag = getattr(request.app.state, "rag", None)
    if not rag:
        raise HTTPException(503, "RAG not available")

    body = await request.json()
    scenario_version_id = str(body.get("scenario_version_id") or "").strip()
    if not scenario_version_id:
        raise HTTPException(400, "scenario_version_id required")

    version = conn.execute(
        "SELECT scenario_id FROM scenario_versions WHERE scenario_version_id = %s",
        (scenario_version_id,),
    ).fetchone()
    if not version:
        raise HTTPException(404, "剧本版本不存在")

    rows = conn.execute(
        """
        SELECT sp.source_part_id, sp.part_kind, sp.page_number, sp.text_content,
               sp.mime_type, sp.anchor, sd.source_filename
        FROM scenario_version_sources svs
        JOIN source_documents sd
          ON sd.source_document_id = svs.source_document_id
        JOIN source_parts sp
          ON sp.source_document_id = sd.source_document_id
        WHERE svs.scenario_version_id = %s
        ORDER BY svs.ordinal, sp.ordinal
        """,
        (scenario_version_id,),
    ).fetchall()
    if not rows:
        raise HTTPException(409, "剧本版本尚未绑定可索引来源")

    parts = []
    for row in rows:
        source_filename = os.path.basename(
            str(row.get("source_filename") or "source").replace("\\", "/")
        )
        page_number = row.get("page_number")
        source_ref = source_filename
        if page_number is not None:
            source_ref = f"{source_ref}#page={page_number}"
        parts.append({
            "source_part_id": row["source_part_id"],
            "text": row.get("text_content") or "",
            "part_kind": row.get("part_kind") or "text",
            "mime_type": row.get("mime_type") or "",
            "page_number": page_number,
            "source_ref": source_ref,
            "anchor": _json_val(row.get("anchor")) or {},
        })

    rebuild_id = str(uuid.uuid4())
    embedding_model, embedding_dimensions = _rag_embedding_metadata(rag)
    conn.execute(
        """
        INSERT INTO rag_rebuild_records (
            rebuild_id, scenario_version_id, status, embedding_model,
            embedding_dimensions, requested_by
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            rebuild_id,
            scenario_version_id,
            "running",
            embedding_model,
            embedding_dimensions,
            account.get("account_id", "unknown"),
        ),
    )

    try:
        chunk_count = rag.index_scenario_version(
            version["scenario_id"],
            scenario_version_id,
            parts,
            visibility="internal",
        )
        embedding_model, embedding_dimensions = _rag_embedding_metadata(rag)
        with conn.transaction() as tx:
            tx.execute(
                """
                UPDATE scenario_versions
                SET rag_index_version = %s
                WHERE scenario_version_id = %s
                """,
                (rebuild_id, scenario_version_id),
            )
            tx.execute(
                """
                UPDATE rag_rebuild_records
                SET status = %s, chunk_count = %s, embedding_model = %s,
                    embedding_dimensions = %s, completed_at = NOW()
                WHERE rebuild_id = %s
                """,
                (
                    "complete",
                    chunk_count,
                    embedding_model,
                    embedding_dimensions,
                    rebuild_id,
                ),
            )
    except Exception as exc:
        conn.execute(
            """
            UPDATE rag_rebuild_records
            SET status = %s, error_message = %s, completed_at = NOW()
            WHERE rebuild_id = %s
            """,
            ("failed", str(exc)[:1000], rebuild_id),
        )
        logger.exception("RAG version rebuild failed: %s", scenario_version_id)
        raise HTTPException(500, "RAG 版本重建失败") from exc
    return {
        "status": "complete",
        "scenario_id": version["scenario_id"],
        "scenario_version_id": scenario_version_id,
        "rebuild_id": rebuild_id,
        "chunks_indexed": chunk_count,
    }


# ── SpoilerGuard Audit ──

@router.get("/rooms/{room_id}/spoiler-audits")
async def get_spoiler_audits(request: Request, room_id: str, limit: int = 50):
    """View spoiler interception logs for a room. Admin-only."""
    _require_admin(request)
    conn = request.app.state.db
    rows = conn.execute(
        "SELECT * FROM spoiler_audits WHERE room_id = %s ORDER BY created_at DESC LIMIT %s",
        (room_id, min(limit, 200)),
    ).fetchall()
    audits = []
    for r in rows:
        violations_raw = r.get("violations")
        if isinstance(violations_raw, str):
            try:
                violations_raw = json.loads(violations_raw)
            except Exception:
                violations_raw = []
        unlock_raw = r.get("unlock_snapshot")
        if isinstance(unlock_raw, str):
            try:
                unlock_raw = json.loads(unlock_raw)
            except Exception:
                unlock_raw = {}
        audits.append({
            "auditId": r["audit_id"],
            "roomId": r["room_id"],
            "actionId": r.get("action_id", ""),
            "originalText": r["original_text"],
            "violations": violations_raw or [],
            "retryCount": r.get("retry_count", 0),
            "finalStatus": r.get("final_status", ""),
            "finalText": r.get("final_text", ""),
            "unlockSnapshot": unlock_raw or {},
            "createdAt": str(r.get("created_at", "")),
        })
    return {"room_id": room_id, "audits": audits}


@router.post("/scenarios/{scenario_id}/spoiler-index/rebuild")
async def rebuild_spoiler_index(request: Request, scenario_id: str):
    """Rebuild sensitive item index for a scenario. Admin-only. Idempotent."""
    _require_admin(request)
    conn = request.app.state.db
    from .engine.spoiler_guard import SpoilerGuard
    from datetime import datetime, timezone
    sg = SpoilerGuard(conn)
    count = sg.rebuild_index(scenario_id)
    rebuilt_by = _get_account_id(request)
    rebuilt_at = datetime.now(timezone.utc).isoformat()
    return {
        "scenario_id": scenario_id,
        "items_indexed": count,
        "rebuilt_by": rebuilt_by,
        "rebuilt_at": rebuilt_at,
    }


# ── Helpers ──

def _char_summary(row) -> dict:
    r = dict(row) if not isinstance(row, dict) else row
    xlsx = _json_val(r.get("xlsx_data")) or {}
    return {
        "character_id": r.get("character_id", ""),
        "player_name": r.get("player_name", ""),
        "investigator_name": xlsx.get("name", ""),
        "occupation": xlsx.get("occupation", ""),
        "hp": xlsx.get("hp", 0),
        "max_hp": xlsx.get("max_hp", 0),
        "san": xlsx.get("san", 0),
        "max_san": xlsx.get("max_san", 0),
        "is_ready": bool(r.get("is_ready")),
        "status": r.get("status", "active"),
        "account_id": r.get("account_id", ""),
    }


def _char_detail(row) -> dict:
    r = dict(row) if not isinstance(row, dict) else row
    xlsx = _json_val(r.get("xlsx_data")) or {}
    return {
        "character_id": r.get("character_id"),
        "room_id": r.get("room_id"),
        "player_name": r.get("player_name"),
        "xlsx_data": xlsx,
        "is_ready": r.get("is_ready"),
        "account_id": r.get("account_id"),
        "status": r.get("status"),
        "summary": _char_summary(r),
    }


def _json_val(value):
    if value is None: return None
    if isinstance(value, (dict, list)): return value
    if isinstance(value, str):
        try: return json.loads(value)
        except json.JSONDecodeError: return None
    return value


def _rag_embedding_metadata(rag) -> tuple[str | None, int | None]:
    embedding = getattr(rag, "embedding", None)
    if embedding is None:
        return None, None
    model_name = str(
        getattr(embedding, "model_name", "") or type(embedding).__name__
    )
    raw_dimensions = getattr(embedding, "dimension", None)
    try:
        dimensions = int(raw_dimensions) if raw_dimensions is not None else None
    except (TypeError, ValueError):
        dimensions = None
    return model_name, dimensions


def _provider_config_http_error(exc: Exception) -> HTTPException:
    code = str(exc)
    if code == "provider_config_not_found":
        return HTTPException(404, code)
    if code in {"provider_test_required", "key_unavailable"}:
        return HTTPException(409, code)
    return HTTPException(400, code)
