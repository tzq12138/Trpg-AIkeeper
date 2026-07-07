"""Turn-based scene round manager — collecting → resolving → resolved cycle."""
import json
import uuid
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TurnManager:
    def __init__(self, conn):
        self.conn = conn

    def ensure_current_turn(self, room_id: str) -> dict:
        """Get or create the current collecting turn for a room."""
        turn = self.conn.execute(
            "SELECT * FROM room_turns WHERE room_id = %s AND status = 'collecting' ORDER BY turn_index DESC LIMIT 1",
            (room_id,)
        ).fetchone()
        if turn:
            return dict(turn)
        return self._create_turn(room_id)

    def _create_turn(self, room_id: str) -> dict:
        max_idx = self.conn.execute(
            "SELECT COALESCE(MAX(turn_index), 0) as max_idx FROM room_turns WHERE room_id = %s",
            (room_id,)
        ).fetchone()["max_idx"]
        turn_id = str(uuid.uuid4())[:8]
        new_idx = max_idx + 1
        self.conn.execute(
            "INSERT INTO room_turns (turn_id, room_id, turn_index, status) VALUES (%s, %s, %s, 'collecting')",
            (turn_id, room_id, new_idx),
        )
        self.conn.commit()
        logger.info("create_turn: room=%s turn=%s index=%s", room_id, turn_id, new_idx)
        return {"turn_id": turn_id, "room_id": room_id, "turn_index": new_idx, "status": "collecting"}

    def submit_action(self, room_id: str, character_id: str, action_id: str) -> dict:
        """Submit an action to the current turn. Returns action status."""
        turn = self.ensure_current_turn(room_id)
        # Check duplicate — same character can't submit twice in same turn
        existing = self.conn.execute(
            "SELECT action_id FROM actions WHERE turn_id = %s AND character_id = %s AND status != 'rejected'",
            (turn["turn_id"], character_id),
        ).fetchone()
        if existing:
            return {"status": "duplicate", "turn_id": turn["turn_id"], "turn_index": turn["turn_index"],
                    "message": "Already submitted this turn"}
        self.conn.execute(
            "UPDATE actions SET turn_id = %s WHERE action_id = %s",
            (turn["turn_id"], action_id),
        )
        self.conn.commit()
        return {"status": "queued", "turn_id": turn["turn_id"], "turn_index": turn["turn_index"]}

    def get_turn_snapshot(self, room_id: str) -> dict:
        """Return current turn state with per-character submission status."""
        turn = self.ensure_current_turn(room_id)
        chars = self.conn.execute(
            "SELECT character_id, player_name, xlsx_data, status FROM characters "
            "WHERE room_id = %s AND status = 'joined'",
            (room_id,)
        ).fetchall()
        submitted = set()
        turn_actions = self.conn.execute(
            "SELECT character_id, action_id, intent_type, declared_intent FROM actions WHERE turn_id = %s",
            (turn["turn_id"],)
        ).fetchall()
        for a in turn_actions:
            submitted.add(a["character_id"])

        players = []
        for c in chars:
            xlsx = _json_val(c.get("xlsx_data")) or {}
            players.append({
                "character_id": c["character_id"],
                "player_name": c["player_name"],
                "investigator_name": xlsx.get("name", ""),
                "submitted": c["character_id"] in submitted,
                "status": c.get("status", "joined"),
            })

        return {
            "turn_id": turn["turn_id"],
            "turn_index": turn["turn_index"],
            "status": turn["status"],
            "players": players,
            "all_submitted": all(p["submitted"] for p in players),
            "actions": [dict(a) for a in turn_actions],
        }

    def all_submitted(self, room_id: str) -> bool:
        """Check if all active players have submitted for the current turn."""
        snap = self.get_turn_snapshot(room_id)
        return snap["all_submitted"] and len(snap["players"]) > 0

    def skip_character(self, room_id: str, turn_id: str, character_id: str, reason: str = ""):
        """Generate a placeholder action so a skipped player doesn't block settlement. Requires reason."""
        turn = self.conn.execute(
            "SELECT * FROM room_turns WHERE turn_id = %s AND room_id = %s", (turn_id, room_id)
        ).fetchone()
        if not turn:
            return {"status": "not_found"}
        action_id = str(uuid.uuid4())[:12]
        declared = f"本回合跳过: {reason}" if reason else "本回合跳过"
        self.conn.execute(
            "INSERT INTO actions (action_id, room_id, character_id, turn_id, intent_type, declared_intent, status) "
            "VALUES (%s, %s, %s, %s, 'system_skip', %s, 'resolved')",
            (action_id, room_id, character_id, turn_id, declared),
        )
        self.conn.commit()
        return {"status": "skipped", "action_id": action_id, "reason": reason}

    def mark_resolving(self, turn_id: str) -> bool:
        """Atomically transition collecting → resolving. Returns True if this caller won the race."""
        cursor = self.conn.execute(
            "UPDATE room_turns SET status = 'resolving' WHERE turn_id = %s AND status = 'collecting'",
            (turn_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def mark_resolved(self, turn_id: str, summary: str = ""):
        self.conn.execute(
            "UPDATE room_turns SET status = 'resolved', resolved_at = NOW(), summary = %s WHERE turn_id = %s",
            (summary, turn_id),
        )
        self.conn.commit()

    def mark_blocked(self, turn_id: str):
        self.conn.execute(
            "UPDATE room_turns SET status = 'blocked' WHERE turn_id = %s", (turn_id,)
        )
        self.conn.commit()

    def get_pending_actions(self, turn_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM actions WHERE turn_id = %s AND status = 'queued' ORDER BY created_at",
            (turn_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def _json_val(value):
    if value is None: return None
    if isinstance(value, (dict, list)): return value
    if isinstance(value, str):
        try: return json.loads(value)
        except json.JSONDecodeError: return None
    return value
