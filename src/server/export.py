"""Campaign exports with explicit public and owner/admin projections."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .events.event_log import EventLog


_PUBLIC_ROOM_FIELDS = (
    "room_id",
    "scenario_id",
    "status",
    "spoiler_level",
    "state_version",
    "player_experience_version",
    "created_at",
    "started_at",
)
_PUBLIC_CHARACTER_FIELDS = (
    "character_id",
    "player_name",
    "is_ready",
    "status",
)
_SENSITIVE_EXPORT_KEYS = {
    "account_id",
    "owner_account_id",
    "owner_token",
    "password_hash",
    "player_token",
    "profile_id",
}


def export_markdown(conn, room_id: str, scope: str = "public") -> dict:
    """Generate a human-readable campaign report for the requested scope."""
    scope = _validated_scope(scope)
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if not room:
        return {"error": "Room not found"}

    lines = [
        f"# AI-Keeper 战报 — Room {room_id}",
        "",
        f"**状态：** {room.get('status', 'unknown')}",
        f"**剧透级别：** {room.get('spoiler_level', 'standard')}",
        "",
    ]
    characters = conn.execute(
        "SELECT * FROM characters WHERE room_id = %s ORDER BY character_id",
        (room_id,),
    ).fetchall()
    if characters:
        lines.append("## 调查员")
        for character in characters:
            if scope == "public":
                name = character.get("player_name") or "未知调查员"
                lines.append(f"- **{name}**（{character.get('status', 'joined')}）")
                continue
            sheet = _json_object(character.get("xlsx_data"))
            name = sheet.get("name") or character.get("player_name") or "未知调查员"
            lines.append(
                f"- **{name}** HP:{sheet.get('hp', '?')}/{sheet.get('max_hp', '?')} "
                f"SAN:{sheet.get('san', '?')}/{sheet.get('max_san', '?')}"
            )
        lines.append("")

    events = _export_events(conn, room_id, scope, limit=200)
    if events:
        public_projection_action_ids = {
            event["payload"].get("actionId")
            for event in events
            if "public_observation" in event["event_type"]
            and event["payload"].get("actionId")
        }
        lines.append("## 关键事件")
        for event in events:
            payload = event["payload"]
            event_type = event["event_type"]
            timestamp = str(event.get("issued_at") or "")[:19]
            if "reveal_transaction" in event_type or "public_observation" in event_type:
                if (
                    "reveal_transaction" in event_type
                    and payload.get("actionId") in public_projection_action_ids
                ):
                    continue
                text = payload.get("text") or payload.get("summaryText") or ""
                if text:
                    lines.extend([f"### {timestamp} — KP叙事", f"> {str(text)[:200]}", ""])
            elif "action_completed" in event_type:
                skill = payload.get("skill_name") or payload.get("skillName") or ""
                roll = payload.get("roll")
                if skill and roll is not None:
                    lines.append(
                        f"- 🎲 **{skill}** 检定 {roll}/{payload.get('target', '?')} "
                        f"({payload.get('level', payload.get('success_level', ''))})"
                    )
            elif "player_moved" in event_type:
                lines.append(f"- 🚶 移动到 {payload.get('toNodeId', '?')}")
            elif "encounter_started" in event_type:
                lines.append("- ⚔️ 遭遇开始")
            elif "encounter_resolved" in event_type:
                lines.append(f"- ✅ 遭遇结束：{payload.get('reason', '')}")

    if scope == "public":
        shared = conn.execute(
            "SELECT cs.public_version FROM clue_shares cs "
            "JOIN clues c ON cs.clue_id = c.clue_id WHERE c.room_id = %s",
            (room_id,),
        ).fetchall()
        if shared:
            lines.append("## 团队证据链")
            lines.extend(f"- 📋 {item.get('public_version', '')}" for item in shared)
            lines.append("")
    else:
        clues = conn.execute(
            "SELECT character_id, text, is_private FROM clues WHERE room_id = %s",
            (room_id,),
        ).fetchall()
        if clues:
            lines.append("## 发现的线索")
            for clue in clues:
                lock = "🔒" if clue.get("is_private", False) else "📋"
                lines.append(
                    f"- {lock} ({str(clue.get('character_id') or '')[:8]}) "
                    f"{clue.get('text', '')}"
                )
            lines.append("")

    ending = conn.execute(
        "SELECT ending_type, summary, highlights FROM campaign_archives "
        "WHERE room_id = %s ORDER BY created_at DESC LIMIT 1",
        (room_id,),
    ).fetchone()
    if ending:
        lines.extend([
            "## 结局",
            f"**类型：** {ending.get('ending_type', 'mixed')}",
            f"**摘要：** {ending.get('summary', '')}",
        ])
        highlights = _json_list(ending.get("highlights"))
        if highlights:
            lines.append("**高光时刻：**")
            lines.extend(f"- {item}" for item in highlights)

    return {
        "format": "markdown",
        "scope": scope,
        "content": "\n".join(lines),
    }


def export_json(conn, room_id: str, scope: str = "public") -> dict:
    """Generate a structured export without credentials or account identities."""
    scope = _validated_scope(scope)
    room = conn.execute(
        "SELECT * FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    if not room:
        return {"error": "Room not found"}
    characters = conn.execute(
        "SELECT * FROM characters WHERE room_id = %s ORDER BY character_id",
        (room_id,),
    ).fetchall()
    if scope == "public":
        room_data = _allow_fields(dict(room), _PUBLIC_ROOM_FIELDS)
        character_data = [
            _allow_fields(dict(character), _PUBLIC_CHARACTER_FIELDS)
            for character in characters
        ]
    else:
        room_data = _strip_export_secrets(dict(room))
        character_data = [
            _strip_export_secrets(dict(character))
            for character in characters
        ]
    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "room": room_data,
        "characters": character_data,
        "events": _export_events(conn, room_id, scope),
        "scope": scope,
    }
    return {"format": "json", "scope": scope, "data": data}


def _export_events(
    conn,
    room_id: str,
    scope: str,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if scope == "public":
        entries = []
        since_sequence = 0
        remaining = limit
        while remaining is None or remaining > 0:
            page_size = min(500, remaining) if remaining is not None else 500
            page = EventLog(conn).get_public_events(
                room_id,
                since_sequence=since_sequence,
                limit=page_size,
            )
            if not page:
                break
            entries.extend(page)
            since_sequence = page[-1].sequence
            if remaining is not None:
                remaining -= len(page)
            if len(page) < page_size:
                break
        return [
            {
                "sequence": entry.sequence,
                "event_type": entry.event_type,
                "audience": entry.audience,
                "payload": _json_object(entry.payload),
                "issued_at": entry.issued_at,
            }
            for entry in entries
        ]

    sql = (
        "SELECT sequence, event_type, audience, payload, action_id, state_version, "
        "issued_at FROM events WHERE room_id = %s ORDER BY sequence"
    )
    params: tuple[Any, ...] = (room_id,)
    if limit is not None:
        sql += " LIMIT %s"
        params = (room_id, limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        _strip_export_secrets({
            **dict(row),
            "payload": _json_object(row.get("payload")),
        })
        for row in rows
    ]


def _validated_scope(scope: str) -> str:
    if scope not in {"public", "full"}:
        raise ValueError("invalid_export_scope")
    return scope


def _allow_fields(value: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: value[field] for field in fields if field in value}


def _strip_export_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.lower()
            if (
                normalized in _SENSITIVE_EXPORT_KEYS
                or normalized.endswith("_token")
                or normalized.endswith("_secret")
                or normalized.endswith("_account_id")
            ):
                continue
            result[key] = _strip_export_secrets(item)
        return result
    if isinstance(value, list):
        return [_strip_export_secrets(item) for item in value]
    return value


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return decoded if isinstance(decoded, list) else []
    return []
