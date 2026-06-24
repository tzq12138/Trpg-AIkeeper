import json
from datetime import datetime, timezone
from .models import CampaignEnding, CampaignSummary, CampaignArchiveQuery, EventLogEntry


class CampaignArchive:
    def __init__(self, conn):
        self.conn = conn

    def generate_ending(self, room_id: str) -> CampaignEnding:
        events = self._get_all_events(room_id)
        characters = self.conn.execute(
            "SELECT * FROM characters WHERE room_id = %s", (room_id,)
        ).fetchall()

        ending_type = self._determine_ending_type(events)
        summary = self._build_summary(room_id, events, characters)
        highlights = self._extract_highlights(events)
        character_arcs = self._build_character_arcs(room_id, characters)

        ending = CampaignEnding(
            ending_type=ending_type,
            summary=summary,
            highlights=highlights,
            character_arcs=character_arcs,
        )

        self._save_archive(room_id, ending)
        self.conn.execute(
            "UPDATE rooms SET status = 'completed' WHERE room_id = %s", (room_id,)
        )
        self.conn.commit()

        return ending

    def get_campaign_summary(self, room_id: str) -> CampaignSummary:
        room = self.conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
        if not room:
            raise ValueError(f"Room {room_id} not found")

        actions = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM actions WHERE room_id = %s", (room_id,)
        ).fetchone()
        events = self._get_all_events(room_id)

        duration = 0
        if room["started_at"]:
            start = _datetime_value(room["started_at"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            duration = int((now - start).total_seconds())

        key_events = [
            {"sequence": e["sequence"], "type": e["event_type"], "timestamp": e["issued_at"]}
            for e in events
            if e["event_type"] in ("s2c_campaign_ended", "s2c_reveal_transaction", "s2c_scene_sync")
        ]

        ending = None
        archive_row = self.conn.execute(
            "SELECT * FROM campaign_archives WHERE room_id = %s ORDER BY created_at DESC LIMIT 1",
            (room_id,),
        ).fetchone()
        if archive_row:
            ending = CampaignEnding(
                ending_type=archive_row["ending_type"],
                summary=archive_row["summary"],
                highlights=_json_value(archive_row["highlights"]),
                character_arcs=_json_value(archive_row["character_arcs"]),
            )

        return CampaignSummary(
            room_id=room_id,
            duration_seconds=duration,
            total_actions=actions["cnt"],
            clues_found=0,
            key_events=key_events,
            ending=ending,
        )

    def query_archive(self, room_id: str, filters: CampaignArchiveQuery) -> list[EventLogEntry]:
        query = "SELECT sequence, room_id, event_type, audience, payload, issued_at FROM events WHERE room_id = %s"
        params: list = [room_id]

        if filters.action_type:
            query += " AND event_type = %s"
            params.append(filters.action_type)

        if filters.since:
            query += " AND issued_at >= %s"
            params.append(filters.since)

        if filters.until:
            query += " AND issued_at <= %s"
            params.append(filters.until)

        if filters.character_id:
            query += " AND payload::text LIKE %s"
            params.append(f"%{filters.character_id}%")

        query += " ORDER BY sequence LIMIT %s"
        params.append(filters.limit)

        rows = self.conn.execute(query, params).fetchall()
        return [
            EventLogEntry(
                sequence=r["sequence"],
                room_id=r["room_id"],
                event_type=r["event_type"],
                audience=r["audience"],
                payload=_json_value(r["payload"]),
                issued_at=_iso_value(r["issued_at"]),
            )
            for r in rows
        ]

    def _get_all_events(self, room_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE room_id = %s ORDER BY sequence", (room_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def _determine_ending_type(self, events: list[dict]) -> str:
        for e in events:
            if e["event_type"] == "s2c_campaign_ended":
                payload = _json_value(e["payload"])
                return payload.get("ending_type", "mixed")
        return "mixed"

    def _build_summary(self, room_id: str, events: list[dict], characters: list) -> str:
        char_names = [c["player_name"] for c in characters]
        event_count = len(events)
        names_str = "、".join(char_names)
        return f"战役结束。角色 {names_str} 参与，共经历 {event_count} 个事件。"

    def _extract_highlights(self, events: list[dict]) -> list[str]:
        highlights = []
        for e in events:
            if e["event_type"] in ("s2c_reveal_transaction", "s2c_scene_sync"):
                payload = _json_value(e["payload"])
                if "text" in payload:
                    highlights.append(payload["text"])
                elif "summary" in payload:
                    highlights.append(payload["summary"])
        return highlights[:10]

    def _build_character_arcs(self, room_id: str, characters: list) -> list[dict]:
        arcs = []
        for char in characters:
            char_id = char["character_id"]
            actions = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM actions WHERE room_id = %s AND character_id = %s",
                (room_id, char_id),
            ).fetchone()
            arcs.append({
                "character_id": char_id,
                "player_name": char["player_name"],
                "total_actions": actions["cnt"],
            })
        return arcs

    def _save_archive(self, room_id: str, ending: CampaignEnding):
        archive_id = str(__import__("uuid").uuid4())[:8]
        self.conn.execute(
            "INSERT INTO campaign_archives (archive_id, room_id, ending_type, summary, highlights, character_arcs) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (archive_id, room_id, ending.ending_type, ending.summary,
             json.dumps(ending.highlights), json.dumps(ending.character_arcs)),
        )
        self.conn.commit()


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _datetime_value(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _iso_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value
