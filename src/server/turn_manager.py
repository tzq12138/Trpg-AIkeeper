"""Turn-based scene round manager — collecting → resolving → resolved cycle."""
import json
import uuid
import logging
from datetime import datetime, timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


class TurnManager:
    def __init__(self, conn):
        self.conn = conn

    def ensure_current_turn(self, room_id: str) -> dict:
        """Get or create the current collecting turn for a room."""
        encounter = self.conn.execute(
            "SELECT encounter_id FROM encounters "
            "WHERE room_id = %s AND type = 'combat' AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            (room_id,),
        ).fetchone()
        if encounter:
            turn = self.conn.execute(
                "SELECT * FROM room_turns WHERE room_id = %s "
                "AND status IN ('collecting', 'resolving', 'blocked') "
                "AND mode = 'combat' AND encounter_id = %s "
                "ORDER BY turn_index DESC LIMIT 1",
                (room_id, encounter["encounter_id"]),
            ).fetchone()
        else:
            turn = self.conn.execute(
                "SELECT * FROM room_turns WHERE room_id = %s AND status IN ('collecting', 'resolving', 'blocked') "
                "ORDER BY turn_index DESC LIMIT 1",
                (room_id,),
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
        room = self.conn.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s",
            (room_id,),
        ).fetchone()
        encounter = self.conn.execute(
            "SELECT encounter_id, current_round FROM encounters "
            "WHERE room_id = %s AND type = 'combat' AND status = 'active' "
            "ORDER BY created_at DESC LIMIT 1",
            (room_id,),
        ).fetchone()
        mode = "combat" if encounter else "scene"
        encounter_id = encounter["encounter_id"] if encounter else None
        encounter_round = int(encounter["current_round"] or 0) if encounter else 0
        if encounter and encounter_round <= 0:
            encounter_round = 1
            self.conn.execute(
                "UPDATE encounters SET current_round = %s WHERE encounter_id = %s",
                (encounter_round, encounter_id),
            )
        self.conn.execute(
            "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id, base_state_version) "
            "VALUES (%s, %s, %s, 'collecting', %s, %s, %s)",
            (turn_id, room_id, new_idx, mode, encounter_id, int(room["state_version"]) if room else 0),
        )
        self.conn.commit()
        logger.info("create_turn: room=%s turn=%s index=%s", room_id, turn_id, new_idx)
        return {
            "turn_id": turn_id,
            "room_id": room_id,
            "turn_index": new_idx,
            "status": "collecting",
            "mode": mode,
            "encounter_id": encounter_id,
            "encounter_round": encounter_round if encounter else None,
        }

    def submit_action(self, room_id: str, character_id: str, action_id: str) -> dict:
        """Submit an action to the current turn. Returns action status."""
        turn = self.ensure_current_turn(room_id)
        # Check duplicate — same character can't submit twice in same turn
        existing = self.conn.execute(
            "SELECT action_id FROM actions WHERE turn_id = %s AND character_id = %s "
            "AND status NOT IN ('rejected', 'canceled', 'timeout')",
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
            "WHERE room_id = %s AND status IN ('joined', 'ready')",
            (room_id,)
        ).fetchall()
        submitted = set()
        turn_actions = self.conn.execute(
            "SELECT character_id, action_id, intent_type, declared_intent FROM actions "
            "WHERE turn_id = %s AND status NOT IN ('rejected', 'canceled', 'timeout')",
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
            "mode": turn.get("mode") or "scene",
            "phase": self._phase_for_turn(turn),
            "encounter_id": turn.get("encounter_id"),
            "encounter_round": self._encounter_round(turn.get("encounter_id")),
            "players": players,
            "all_submitted": all(p["submitted"] for p in players),
            "actions": [dict(a) for a in turn_actions],
        }

    def _phase_for_turn(self, turn: dict) -> str:
        if (turn.get("mode") or "scene") != "combat":
            return turn["status"]
        return {
            "collecting": "declaration",
            "resolving": "resolution",
            "resolved": "summary",
            "blocked": "blocked",
        }.get(turn["status"], turn["status"])

    def _encounter_round(self, encounter_id: str | None) -> int | None:
        if not encounter_id:
            return None
        encounter = self.conn.execute(
            "SELECT current_round FROM encounters WHERE encounter_id = %s",
            (encounter_id,),
        ).fetchone()
        return int(encounter["current_round"] or 0) if encounter else None

    def all_submitted(self, room_id: str) -> bool:
        """Check if all active players have submitted for the current turn."""
        snap = self.get_turn_snapshot(room_id)
        return snap["all_submitted"] and len(snap["players"]) > 0

    def skip_character(self, room_id: str, turn_id: str, character_id: str, policy: str = "idle"):
        """Generate a documented absent-policy placeholder without choosing player tactics."""
        turn = self.conn.execute(
            "SELECT * FROM room_turns WHERE turn_id = %s AND room_id = %s", (turn_id, room_id)
        ).fetchone()
        if not turn:
            return {"status": "not_found"}
        if policy not in {"idle", "maintain_existing"}:
            return {"status": "invalid_policy"}
        existing = self.conn.execute(
            "SELECT action_id FROM actions WHERE turn_id = %s AND character_id = %s "
            "AND status NOT IN ('rejected', 'canceled', 'timeout')",
            (turn_id, character_id),
        ).fetchone()
        if existing:
            return {"status": "already_submitted", "action_id": existing["action_id"]}
        action_id = str(uuid.uuid4())[:12]
        declared = f"本回合跳过: {policy}"
        self.conn.execute(
            "INSERT INTO actions (action_id, room_id, character_id, turn_id, intent_type, declared_intent, status) "
            "VALUES (%s, %s, %s, %s, 'system_skip', %s, 'resolved')",
            (action_id, room_id, character_id, turn_id, declared),
        )
        self.conn.commit()
        return {"status": "skipped", "action_id": action_id, "policy": policy}

    def apply_expired_absence_policies(
        self,
        room_id: str | None = None,
        now: datetime | None = None,
    ) -> list[dict]:
        """Submit documented absence policies for expired combat declaration windows."""
        now = now or datetime.now(timezone.utc)
        conditions = ["turns.status = 'collecting'", "turns.mode = 'combat'"]
        params: list[str] = []
        if room_id:
            conditions.append("turns.room_id = %s")
            params.append(room_id)
        rows = self.conn.execute(
            "SELECT turns.*, rooms.action_timing FROM room_turns AS turns "
            "JOIN rooms ON rooms.room_id = turns.room_id WHERE " + " AND ".join(conditions),
            tuple(params),
        ).fetchall()
        applied = []
        for row in rows:
            turn = dict(row)
            if not _turn_window_expired(turn, now):
                continue
            characters = self.conn.execute(
                "SELECT character_id FROM characters WHERE room_id = %s AND status IN ('joined', 'ready') "
                "ORDER BY character_id",
                (turn["room_id"],),
            ).fetchall()
            submitted_rows = self.conn.execute(
                "SELECT character_id FROM actions WHERE turn_id = %s "
                "AND status NOT IN ('rejected', 'canceled', 'timeout')",
                (turn["turn_id"],),
            ).fetchall()
            submitted = {str(item["character_id"]) for item in submitted_rows}
            character_ids = []
            for character in characters:
                character_id = str(character["character_id"])
                if character_id in submitted:
                    continue
                setting = self.conn.execute(
                    "SELECT absent_policy FROM room_player_settings "
                    "WHERE room_id = %s AND character_id = %s",
                    (turn["room_id"], character_id),
                ).fetchone()
                policy = str(setting["absent_policy"]) if setting else "idle"
                result = self.skip_character(
                    turn["room_id"],
                    turn["turn_id"],
                    character_id,
                    policy,
                )
                if result.get("status") == "skipped":
                    character_ids.append(character_id)
            if character_ids:
                applied.append(
                    {
                        "room_id": turn["room_id"],
                        "turn_id": turn["turn_id"],
                        "character_ids": character_ids,
                    }
                )
        return applied

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
            "SELECT * FROM actions WHERE turn_id = %s AND status IN ('queued', 'batched') ORDER BY created_at",
            (turn_id,)
        ).fetchall()
        actions = [dict(row) for row in rows]
        turn = self.conn.execute(
            "SELECT mode, combat_plan FROM room_turns WHERE turn_id = %s",
            (turn_id,),
        ).fetchone()
        if not turn or (turn.get("mode") or "scene") != "combat":
            return actions
        plan = _json_val(turn.get("combat_plan")) or {}
        ordered_ids = [
            step.get("action_id")
            for step in plan.get("steps", [])
            if isinstance(step, dict) and step.get("action_id")
        ]
        position = {action_id: index for index, action_id in enumerate(ordered_ids)}
        return sorted(actions, key=lambda action: (position.get(action["action_id"], len(position)), action["action_id"]))

    def plan_combat_round(self, turn_id: str) -> dict | None:
        turn_row = self.conn.execute(
            "SELECT * FROM room_turns WHERE turn_id = %s",
            (turn_id,),
        ).fetchone()
        if not turn_row:
            return None
        turn = dict(turn_row)
        if (turn.get("mode") or "scene") != "combat" or not turn.get("encounter_id"):
            return None
        rows = self.conn.execute(
            "SELECT a.*, COALESCE(ep.dex, 0) AS dex, c.player_name "
            "FROM actions a LEFT JOIN encounter_participants ep "
            "ON ep.encounter_id = %s AND ep.character_id = a.character_id "
            "LEFT JOIN characters c ON c.character_id = a.character_id "
            "WHERE a.turn_id = %s AND (a.status IN ('queued', 'batched') OR a.intent_type = 'system_skip')",
            (turn["encounter_id"], turn_id),
        ).fetchall()
        prepared_rows = self.conn.execute(
            "SELECT prepared.action_id, prepared.character_id, prepared.trigger_kind, prepared.reaction_kind, "
            "characters.player_name FROM prepared_rule_actions AS prepared "
            "JOIN encounter_participants AS participants "
            "ON participants.encounter_id = %s AND participants.character_id = prepared.character_id "
            "LEFT JOIN characters ON characters.character_id = prepared.character_id "
            "WHERE prepared.room_id = %s AND prepared.status = 'armed' "
            "AND prepared.expires_at > NOW() ORDER BY prepared.created_at, prepared.action_id",
            (turn["encounter_id"], turn["room_id"]),
        ).fetchall()
        from .combat_round_planner import build_combat_round_plan

        plan = build_combat_round_plan(
            turn_id=turn_id,
            encounter_id=turn["encounter_id"],
            round_number=self._encounter_round(turn["encounter_id"]) or 1,
            actions=[dict(row) for row in rows],
            prepared_actions=[dict(row) for row in prepared_rows],
        )
        self.save_combat_plan(turn_id, plan)
        return plan

    def save_combat_plan(self, turn_id: str, plan: dict) -> None:
        self.conn.execute(
            "UPDATE room_turns SET combat_plan = %s WHERE turn_id = %s",
            (json.dumps(plan, ensure_ascii=False), turn_id),
        )
        self.conn.commit()

    def save_combat_summary(self, turn_id: str, summary: dict) -> None:
        self.conn.execute(
            "UPDATE room_turns SET combat_summary = %s WHERE turn_id = %s",
            (json.dumps(summary, ensure_ascii=False), turn_id),
        )
        self.conn.commit()

    def advance_combat_round_if_ready(self, turn_id: str) -> bool:
        turn = self.conn.execute(
            "SELECT encounter_id FROM room_turns WHERE turn_id = %s AND mode = 'combat'",
            (turn_id,),
        ).fetchone()
        if not turn or not turn.get("encounter_id"):
            return True
        encounter_id = turn["encounter_id"]
        pending = self.conn.execute(
            "SELECT reaction_id FROM encounter_pending_reactions "
            "WHERE encounter_id = %s AND status = 'pending' LIMIT 1",
            (encounter_id,),
        ).fetchone()
        if pending:
            return False
        encounter = self.conn.execute(
            "SELECT status, current_round FROM encounters WHERE encounter_id = %s",
            (encounter_id,),
        ).fetchone()
        if not encounter or encounter.get("status") != "active":
            return True
        self.conn.execute(
            "UPDATE encounters SET current_round = %s WHERE encounter_id = %s",
            (int(encounter.get("current_round") or 0) + 1, encounter_id),
        )
        self.conn.execute(
            "UPDATE encounter_participants SET acted_this_round = FALSE WHERE encounter_id = %s",
            (encounter_id,),
        )
        self.conn.commit()
        return True


def _json_val(value):
    if value is None: return None
    if isinstance(value, (dict, list)): return value
    if isinstance(value, str):
        try: return json.loads(value)
        except json.JSONDecodeError: return None
    return value


def _turn_window_expired(turn: dict, now: datetime) -> bool:
    started_at = turn.get("started_at")
    if not isinstance(started_at, datetime):
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    timing = _json_val(turn.get("action_timing")) or {}
    try:
        timeout_seconds = max(1, int(timing.get("input_hint_seconds", 60)))
    except (AttributeError, TypeError, ValueError):
        timeout_seconds = 60
    return now >= started_at + timedelta(seconds=timeout_seconds)
    return value
