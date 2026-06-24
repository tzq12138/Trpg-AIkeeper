import json
from datetime import datetime, timezone
from .models import EventLogEntry, Checkpoint


class EventLog:
    def __init__(self, conn):
        self.conn = conn

    def log_event(self, room_id: str, event_type: str, audience: str, payload: dict) -> int:
        cursor = self.conn.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s) RETURNING sequence",
            (room_id, event_type, audience, json.dumps(payload)),
        )
        self.conn.commit()
        row = cursor.fetchone()
        return row['sequence'] if row else 0

    def get_events(self, room_id: str, since_sequence: int = 0, limit: int = 100) -> list[EventLogEntry]:
        rows = self.conn.execute(
            "SELECT sequence, room_id, event_type, audience, payload, issued_at "
            "FROM events WHERE room_id = %s AND sequence > %s ORDER BY sequence LIMIT %s",
            (room_id, since_sequence, limit),
        ).fetchall()
        return [
            EventLogEntry(
                sequence=r["sequence"],
                room_id=r["room_id"],
                event_type=r["event_type"],
                audience=r["audience"],
                payload=json.loads(r["payload"]),
                issued_at=r["issued_at"],
            )
            for r in rows
        ]

    def get_public_events(self, room_id: str, since_sequence: int = 0, limit: int = 100) -> list[EventLogEntry]:
        rows = self.conn.execute(
            "SELECT sequence, room_id, event_type, audience, payload, issued_at "
            "FROM events WHERE room_id = %s AND sequence > %s AND audience != 'player' "
            "ORDER BY sequence LIMIT %s",
            (room_id, since_sequence, limit),
        ).fetchall()
        return [
            EventLogEntry(
                sequence=r["sequence"],
                room_id=r["room_id"],
                event_type=r["event_type"],
                audience=r["audience"],
                payload=json.loads(r["payload"]),
                issued_at=r["issued_at"],
            )
            for r in rows
        ]

    def create_checkpoint(self, room_id: str, checkpoint_id: str | None = None) -> Checkpoint:
        if checkpoint_id is None:
            checkpoint_id = str(__import__("uuid").uuid4())[:8]

        snapshot = self._build_snapshot(room_id)
        snapshot_json = json.dumps(snapshot)

        self.conn.execute(
            "INSERT INTO checkpoints (checkpoint_id, room_id, state_snapshot) VALUES (%s, %s, %s)",
            (checkpoint_id, room_id, snapshot_json),
        )
        self.conn.commit()

        return Checkpoint(
            checkpoint_id=checkpoint_id,
            room_id=room_id,
            state_snapshot=snapshot,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def restore_checkpoint(self, room_id: str, checkpoint_id: str) -> dict:
        row = self.conn.execute(
            "SELECT state_snapshot FROM checkpoints WHERE checkpoint_id = %s AND room_id = %s",
            (checkpoint_id, room_id),
        ).fetchone()
        if not row:
            raise ValueError(f"Checkpoint {checkpoint_id} not found for room {room_id}")

        snapshot = json.loads(row["state_snapshot"])
        self._apply_snapshot(room_id, snapshot)
        return snapshot

    def list_checkpoints(self, room_id: str) -> list[Checkpoint]:
        rows = self.conn.execute(
            "SELECT checkpoint_id, room_id, state_snapshot, created_at "
            "FROM checkpoints WHERE room_id = %s ORDER BY created_at DESC",
            (room_id,),
        ).fetchall()
        return [
            Checkpoint(
                checkpoint_id=r["checkpoint_id"],
                room_id=r["room_id"],
                state_snapshot=json.loads(r["state_snapshot"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def _build_snapshot(self, room_id: str) -> dict:
        room = self.conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
        characters = self.conn.execute(
            "SELECT * FROM characters WHERE room_id = %s", (room_id,)
        ).fetchall()
        actions = self.conn.execute(
            "SELECT * FROM actions WHERE room_id = %s", (room_id,)
        ).fetchall()
        events = self.conn.execute(
            "SELECT * FROM events WHERE room_id = %s", (room_id,)
        ).fetchall()

        return {
            "room": dict(room) if room else {},
            "characters": [dict(c) for c in characters],
            "actions": [dict(a) for a in actions],
            "events": [dict(e) for e in events],
        }

    def _apply_snapshot(self, room_id: str, snapshot: dict):
        self.conn.execute("DELETE FROM actions WHERE room_id = %s", (room_id,))
        self.conn.execute("DELETE FROM events WHERE room_id = %s", (room_id,))
        self.conn.execute("DELETE FROM characters WHERE room_id = %s", (room_id,))

        room_data = snapshot.get("room", {})
        if room_data:
            self.conn.execute(
                "UPDATE rooms SET status = %s, scenario_id = %s, spoiler_level = %s WHERE room_id = %s",
                (room_data.get("status", "lobby"), room_data.get("scenario_id"),
                 room_data.get("spoiler_level", "standard"), room_id),
            )

        for char in snapshot.get("characters", []):
            self.conn.execute(
                "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data, is_ready) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (char["character_id"], room_id, char["player_name"], char["player_token"],
                 char.get("xlsx_data"), char.get("is_ready", 0)),
            )

        for action in snapshot.get("actions", []):
            self.conn.execute(
                "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, "
                "status, batch_id, result, created_at, completed_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (action["action_id"], room_id, action["character_id"], action["intent_type"],
                 action.get("declared_intent"), action["status"], action.get("batch_id"),
                 action.get("result"), action.get("created_at"), action.get("completed_at")),
            )

        for event in snapshot.get("events", []):
            self.conn.execute(
                "INSERT INTO events (room_id, event_type, audience, payload, issued_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (room_id, event["event_type"], event["audience"],
                 event["payload"], event.get("issued_at", datetime.now(timezone.utc).isoformat())),
            )

        self.conn.commit()
