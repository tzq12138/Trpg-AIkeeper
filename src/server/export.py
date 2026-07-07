"""Campaign export — Markdown (human-readable) and JSON (debug/audit)."""

import json
from datetime import datetime, timezone


def export_markdown(conn, room_id: str, scope: str = "public") -> dict:
    """Generate Markdown battle report."""
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        return {"error": "Room not found"}

    title = f"# AI-Keeper 战报 — Room {room_id}"
    lines = [title, "", f"**状态:** {room.get('status', 'unknown')}",
             f"**剧透级别:** {room.get('spoiler_level', 'standard')}", ""]

    # Characters
    chars = conn.execute(
        "SELECT * FROM characters WHERE room_id = %s", (room_id,)
    ).fetchall()
    if chars:
        lines.append("## 调查员")
        for c in chars:
            xlsx = json.loads(c.get("xlsx_data", "{}")) if isinstance(c.get("xlsx_data"), str) else (c.get("xlsx_data") or {})
            name = xlsx.get("name", c.get("player_name", "未知"))
            lines.append(f"- **{name}** HP:{xlsx.get('hp','?')}/{xlsx.get('max_hp','?')} SAN:{xlsx.get('san','?')}/{xlsx.get('max_san','?')}")
        lines.append("")

    # Key events (public only for public scope)
    audience_filter = "AND audience != 'player'" if scope == "public" else ""
    events = conn.execute(
        f"SELECT event_type, audience, payload, issued_at FROM events "
        f"WHERE room_id = %s {audience_filter} ORDER BY sequence LIMIT 200",
        (room_id,),
    ).fetchall()

    if events:
        lines.append("## 关键事件")
        for ev in events:
            payload = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else (ev["payload"] or {})
            ev_type = ev["event_type"]
            timestamp = str(ev.get("issued_at", ""))[:19]
            if "reveal_transaction" in ev_type or "public_observation" in ev_type:
                text = payload.get("text", payload.get("summaryText", ""))
                if text:
                    lines.append(f"### {timestamp} — KP叙事")
                    lines.append(f"> {text[:200]}")
                    lines.append("")
            elif "action_completed" in ev_type:
                skill = payload.get("skill_name", payload.get("skillName", ""))
                roll = payload.get("roll")
                if skill and roll:
                    lines.append(f"- 🎲 **{skill}** 检定: {roll}/{payload.get('target', '?')} "
                                 f"({payload.get('level', payload.get('success_level', ''))})")
            elif "player_moved" in ev_type:
                lines.append(f"- 🚶 移动到 {payload.get('toNodeId', '?')}")
            elif "encounter_started" in ev_type:
                lines.append(f"- ⚔️ 遭遇开始")
            elif "encounter_resolved" in ev_type:
                lines.append(f"- ✅ 遭遇结束: {payload.get('reason', '')}")

    # Clues — public export uses public_version, not raw text
    if scope == "public":
        # Public export: show shared public_version only
        shared = conn.execute(
            "SELECT cs.clue_id, cs.public_version, cs.shared_by "
            "FROM clue_shares cs JOIN clues c ON cs.clue_id = c.clue_id "
            "WHERE c.room_id = %s",
            (room_id,),
        ).fetchall()
        if shared:
            lines.append("## 队伍证据链")
            for sh in shared:
                lines.append(f"- 📋 {sh.get('public_version', '')}")
            lines.append("")
    else:
        # Private/debug export: include owned clues
        clues = conn.execute(
            "SELECT * FROM clues WHERE room_id = %s", (room_id,)
        ).fetchall()
        if clues:
            lines.append("## 发现的线索")
            for cl in clues:
                is_private = cl.get("is_private", False)
                lines.append(f"- {'🔒' if is_private else '📋'} ({cl.get('character_id', '')[:8]}) {cl.get('text', '')}")
            lines.append("")

    # Campaign ending
    ending_row = conn.execute(
        "SELECT * FROM campaign_archives WHERE room_id = %s ORDER BY created_at DESC LIMIT 1",
        (room_id,),
    ).fetchone()
    if ending_row:
        lines.append("## 结局")
        lines.append(f"**类型:** {ending_row.get('ending_type', 'mixed')}")
        lines.append(f"**摘要:** {ending_row.get('summary', '')}")
        highlights = json.loads(ending_row.get("highlights", "[]")) if isinstance(ending_row.get("highlights"), str) else (ending_row.get("highlights") or [])
        if highlights:
            lines.append("**高光时刻:**")
            for h in highlights:
                lines.append(f"- {h}")

    markdown = "\n".join(lines)
    return {"format": "markdown", "scope": scope, "content": markdown}


def export_json(conn, room_id: str, scope: str = "public") -> dict:
    """Generate structured JSON export with token sanitization."""
    room = conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
    if not room:
        return {"error": "Room not found"}

    room_dict = dict(room)
    # Sanitize tokens
    room_dict["owner_token"] = room_dict.get("owner_token", "")[:4] + "***"

    chars = conn.execute("SELECT * FROM characters WHERE room_id = %s", (room_id,)).fetchall()
    char_list = []
    for c in chars:
        cd = dict(c)
        cd["player_token"] = cd.get("player_token", "")[:4] + "***"
        char_list.append(cd)

    audience_filter = "AND audience != 'player'" if scope == "public" else ""
    events = conn.execute(
        f"SELECT sequence, event_type, audience, payload, issued_at FROM events "
        f"WHERE room_id = %s {audience_filter} ORDER BY sequence",
        (room_id,),
    ).fetchall()

    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "room": room_dict,
        "characters": char_list,
        "events": [dict(e) for e in events],
        "scope": scope,
    }
    return {"format": "json", "scope": scope, "data": data}
