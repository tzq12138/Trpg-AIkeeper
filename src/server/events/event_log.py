import json
import logging
from datetime import datetime, timezone
from ..models import EventLogEntry, Checkpoint

logger = logging.getLogger(__name__)

# System event types that are safe for Player visibility
# Events NOT in this list are host-only/internal and must NOT be returned to players
PLAYER_VISIBLE_SYSTEM_EVENTS: set[str] = {
    "s2c_turn_resolved",
    "s2c_checkpoint_created",
}

# Tables that need per-room cleanup before snapshot restore
SNAPSHOT_CHILD_TABLES = [
    "actions", "events", "characters", "clues", "clue_shares",
    "inventory", "objectives", "room_turns", "room_map_state",
    "character_map_positions", "encounters", "encounter_participants",
    "host_states",
]

# Tables snapshot includes (beyond rooms)
# Note: encounter_participants linked via encounters.encounter_id (no direct room_id)
SNAPSHOT_DATA_TABLES = [
    "characters", "actions", "events", "clues", "clue_shares",
    "inventory", "objectives", "room_turns", "room_map_state",
    "character_map_positions", "encounters", "encounter_participants",
    "host_states",
]

MAX_AUTO_CHECKPOINTS = 20


class EventLog:
    def __init__(self, conn):
        self.conn = conn

    def log_event(self, room_id: str, event_type: str, audience: str, payload: dict, commit: bool = True) -> int:
        cursor = self.conn.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s) RETURNING sequence",
            (room_id, event_type, audience, json.dumps(payload, ensure_ascii=False)),
        )
        if commit:
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
                sequence=r["sequence"], room_id=r["room_id"],
                event_type=r["event_type"], audience=r["audience"],
                payload=_decode_json(r["payload"]), issued_at=_to_iso(r["issued_at"]),
            ) for r in rows
        ]

    def _can_player_see_event(self, event_type: str, audience: str, payload: dict, character_id: str) -> bool:
        """Unified visibility helper for player archive/reconnect/catch-up.

        Rules (in priority order):
        - host audience: never visible
        - party audience: always visible
        - player audience: visible only if payload.character_id matches (supports both camel/snake)
        - system audience: only whitelisted types
        """
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

    def get_events_for_player(self, room_id: str, character_id: str,
                              since_sequence: int = 0, limit: int = 100,
                              latest: bool = False) -> list[EventLogEntry]:
        """Get events visible to a specific player on catch-up.

        Uses unified visibility helper — same rules as archive/reconnect.
        """
        order = "DESC" if latest else "ASC"
        rows = self.conn.execute(
            "SELECT sequence, room_id, event_type, audience, payload, issued_at "
            "FROM events WHERE room_id = %s AND sequence > %s "
            "AND audience != 'host' "
            f"ORDER BY sequence {order} LIMIT %s",
            (room_id, since_sequence, limit),
        ).fetchall()
        result = []
        for r in rows:
            payload = _decode_json(r["payload"])
            if self._can_player_see_event(r["event_type"], r["audience"], payload, character_id):
                result.append(EventLogEntry(
                    sequence=r["sequence"], room_id=r["room_id"],
                    event_type=r["event_type"], audience=r["audience"],
                    payload=payload, issued_at=_to_iso(r["issued_at"]),
                ))
        return list(reversed(result)) if latest else result

    def get_public_events(self, room_id: str, since_sequence: int = 0, limit: int = 100) -> list[EventLogEntry]:
        """Get public events — party audience + whitelisted system_safe events only.
        Does NOT return host, player:self, player:other, or non-whitelisted system events."""
        rows = self.conn.execute(
            "SELECT sequence, room_id, event_type, audience, payload, issued_at "
            "FROM events WHERE room_id = %s AND sequence > %s "
            "AND (audience = 'party' OR (audience = 'system' AND event_type = ANY(%s))) "
            "ORDER BY sequence LIMIT %s",
            (room_id, since_sequence, list(PLAYER_VISIBLE_SYSTEM_EVENTS), limit),
        ).fetchall()
        return [
            EventLogEntry(
                sequence=r["sequence"], room_id=r["room_id"],
                event_type=r["event_type"], audience=r["audience"],
                payload=_decode_json(r["payload"]), issued_at=_to_iso(r["issued_at"]),
            ) for r in rows
        ]

    def create_checkpoint(self, room_id: str, checkpoint_id: str | None = None,
                          auto: bool = False, reason: str = "") -> Checkpoint:
        if checkpoint_id is None:
            import uuid as _uuid
            checkpoint_id = str(_uuid.uuid4())[:8]

        checkpoint_type = "auto" if auto else "manual"
        snapshot = self._build_snapshot(room_id)
        snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=_json_default)

        self.conn.execute(
            "INSERT INTO checkpoints (checkpoint_id, room_id, state_snapshot, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (checkpoint_id, room_id, snapshot_json,
             datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

        # Log auto-checkpoint creation event
        self.log_event(room_id, "s2c_checkpoint_created", "system", {
            "checkpointId": checkpoint_id,
            "checkpointType": checkpoint_type,
            "reason": reason,
        })

        # Cleanup old auto checkpoints
        if auto:
            self._cleanup_old_auto_checkpoints(room_id)

        return Checkpoint(
            checkpoint_id=checkpoint_id,
            room_id=room_id,
            state_snapshot=snapshot,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _cleanup_old_auto_checkpoints(self, room_id: str):
        """Keep only the most recent MAX_AUTO_CHECKPOINTS auto checkpoints."""
        try:
            rows = self.conn.execute(
                "SELECT checkpoint_id FROM checkpoints WHERE room_id = %s "
                "ORDER BY created_at DESC",
                (room_id,),
            ).fetchall()
            if len(rows) > MAX_AUTO_CHECKPOINTS:
                to_delete = [r["checkpoint_id"] for r in rows[MAX_AUTO_CHECKPOINTS:]]
                for cid in to_delete:
                    self.conn.execute(
                        "DELETE FROM checkpoints WHERE checkpoint_id = %s", (cid,)
                    )
                self.conn.commit()
        except Exception as e:
            logger.debug("Failed to cleanup auto checkpoints: %s", e)

    def restore_checkpoint(self, room_id: str, checkpoint_id: str) -> dict:
        row = self.conn.execute(
            "SELECT state_snapshot FROM checkpoints WHERE checkpoint_id = %s AND room_id = %s",
            (checkpoint_id, room_id),
        ).fetchone()
        if not row:
            raise ValueError(f"Checkpoint {checkpoint_id} not found for room {room_id}")

        snapshot = _decode_json(row["state_snapshot"])
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
                checkpoint_id=r["checkpoint_id"], room_id=r["room_id"],
                state_snapshot=_decode_json(r["state_snapshot"]),
                created_at=_to_iso(r["created_at"]),
            ) for r in rows
        ]

    def _build_snapshot(self, room_id: str) -> dict:
        snapshot = {}
        room = self.conn.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()
        snapshot["room"] = dict(room) if room else {}
        for table in SNAPSHOT_DATA_TABLES:
            if table == "encounter_participants":
                # Linked via encounters.encounter_id — JOIN to get room-scoped participants
                rows = self.conn.execute(
                    "SELECT ep.* FROM encounter_participants ep "
                    "JOIN encounters e ON ep.encounter_id = e.encounter_id "
                    "WHERE e.room_id = %s", (room_id,)
                ).fetchall()
            else:
                rows = self.conn.execute(
                    f"SELECT * FROM {table} WHERE room_id = %s", (room_id,)
                ).fetchall()
            snapshot[table] = [dict(r) for r in rows]
        return snapshot

    def _apply_snapshot(self, room_id: str, snapshot: dict):
        for table in SNAPSHOT_CHILD_TABLES:
            try:
                if table == "encounter_participants":
                    # Delete via JOIN — participants linked through encounters
                    self.conn.execute(
                        "DELETE FROM encounter_participants WHERE encounter_id IN "
                        "(SELECT encounter_id FROM encounters WHERE room_id = %s)", (room_id,)
                    )
                else:
                    self.conn.execute(f"DELETE FROM {table} WHERE room_id = %s", (room_id,))
            except Exception as e:
                logger.warning("Failed to delete from %s: %s", table, e)

        room_data = snapshot.get("room", {})
        if room_data:
            self.conn.execute(
                "UPDATE rooms SET status = %s, scenario_id = %s, spoiler_level = %s WHERE room_id = %s",
                (room_data.get("status", "lobby"), room_data.get("scenario_id"),
                 room_data.get("spoiler_level", "standard"), room_id),
            )

        # Restore characters (needs specific columns due to schema variations)
        for char in snapshot.get("characters", []):
            cols = ["character_id", "room_id", "player_name", "player_token", "xlsx_data", "is_ready"]
            vals = [char.get(c) for c in cols]
            vals[1] = room_id  # ensure room_id
            self.conn.execute(
                "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data, is_ready) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (vals[0], room_id, vals[2], vals[3],
                 _encode_json(vals[4]), vals[5]),
            )

        # Generic restore for other tables (uses INSERT with column discovery)
        for table in SNAPSHOT_DATA_TABLES:
            if table == "characters":
                continue  # handled above
            rows = snapshot.get(table, [])
            if not rows:
                continue
            for row in rows:
                row_dict = dict(row)
                if table not in ("host_states", "room_map_state", "room_turns",
                                 "encounters", "events",
                                 "clues", "inventory", "objectives",
                                 "character_map_positions"):
                    continue
                # Use simple insert: build column list from dict keys
                # Skip sequence column for events (auto-generated)
                cols = [k for k in row_dict.keys() if k != "sequence"]
                placeholders = ", ".join(["%s"] * len(cols))
                col_names = ", ".join(cols)
                try:
                    self.conn.execute(
                        f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                        tuple(_safe_val(row_dict[k]) for k in cols),
                    )
                except Exception as e:
                    logger.debug("Failed to restore row in %s: %s", table, e)

        self.conn.commit()


def _safe_val(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=_json_default)
    return v


def _decode_json(value):
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


def _encode_json(value):
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _to_iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value
