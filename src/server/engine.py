import json
from datetime import datetime, timezone
from .models import PlayerIntent


class Engine:
    def __init__(self, conn):
        self.conn = conn

    def submit_intent(self, room_id: str, character_id: str, intent: PlayerIntent) -> dict:
        existing = self.conn.execute(
            "SELECT status FROM actions WHERE action_id = %s", (intent.action_id,)
        ).fetchone()
        if existing:
            return {"status": "accepted", "action_id": intent.action_id}

        room = self.conn.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)
        ).fetchone()
        current_version = room["state_version"] if room else 0
        if intent.base_state_version != 0 and intent.base_state_version != current_version:
            return {"status": "conflict", "current_version": current_version}

        if intent.intent_type == "ready_toggle":
            self.conn.execute(
                "UPDATE characters SET is_ready = NOT is_ready WHERE character_id = %s",
                (character_id,),
            )
            char = self.conn.execute(
                "SELECT is_ready FROM characters WHERE character_id = %s", (character_id,)
            ).fetchone()
            self.conn.execute(
                "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'player', %s)",
                (room_id, "s2c_ready_toggled", json.dumps({"character_id": character_id, "is_ready": bool(char["is_ready"])})),
            )
            self.conn.commit()
            return {"status": "accepted", "action_id": intent.action_id, "is_ready": bool(char["is_ready"])}

        self.conn.execute(
            "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, params, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'queued')",
            (
                intent.action_id,
                room_id,
                character_id,
                intent.intent_type,
                intent.declared_intent,
                json.dumps(intent.params, ensure_ascii=False),
            ),
        )
        self.conn.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'player', %s)",
            (room_id, "s2c_action_queued", json.dumps({"actionId": intent.action_id})),
        )
        self.conn.execute(
            "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s",
            (room_id,),
        )
        self.conn.commit()
        return {"status": "accepted", "action_id": intent.action_id}

    def bump_state_version(self, room_id: str) -> dict:
        room = self.conn.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)
        ).fetchone()
        base = room["state_version"] if room else 0
        self.conn.execute(
            "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s",
            (room_id,),
        )
        self.conn.commit()
        return {"baseStateVersion": base, "nextStateVersion": base + 1}

    def get_state_version(self, room_id: str) -> int:
        room = self.conn.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)
        ).fetchone()
        return room["state_version"] if room else 0

    def complete_action(
        self,
        action_id: str,
        status: str,
        result: str | None = None,
        host_transaction_active: bool = False,
    ) -> list[dict]:
        self.conn.execute(
            "UPDATE actions SET status = %s, result = %s, completed_at = %s WHERE action_id = %s",
            (
                status,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                datetime.now(timezone.utc).isoformat(),
                action_id,
            ),
        )
        action = self.conn.execute(
            "SELECT room_id, character_id FROM actions WHERE action_id = %s", (action_id,)
        ).fetchone()
        delayed: list[dict] = []
        if action:
            player_payload = {"actionId": action_id, "status": status}
            if host_transaction_active:
                player_payload["delayed_delivery"] = True
                delayed.append({
                    "room_id": action["room_id"],
                    "character_id": action["character_id"],
                    "event_type": "s2c_action_completed",
                    "audience": "player",
                    "payload": player_payload,
                })
            else:
                self.conn.execute(
                    "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'player', %s)",
                    (action["room_id"], "s2c_action_completed", json.dumps(player_payload)),
                )
        self.conn.commit()
        return delayed
