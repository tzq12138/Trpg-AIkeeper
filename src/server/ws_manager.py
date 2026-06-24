import json
from fastapi import WebSocket
from .models import EngineEvent

FULL_SNAPSHOT_THRESHOLD = 100


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, dict[str, WebSocket]] = {}
        self._last_sequence: dict[str, dict[str, int]] = {}

    async def connect(self, websocket: WebSocket, room_id: str, connection_id: str):
        await websocket.accept()
        self._connections.setdefault(room_id, {})[connection_id] = websocket

    def disconnect(self, room_id: str, connection_id: str):
        if room_id in self._connections:
            self._connections[room_id].pop(connection_id, None)

    async def send_event(self, room_id: str, connection_id: str, event: EngineEvent):
        ws = self._connections.get(room_id, {}).get(connection_id)
        if ws:
            await ws.send_text(event.model_dump_json(by_alias=True))

    async def broadcast_to_room(self, room_id: str, event: EngineEvent):
        for conn_id, ws in self._connections.get(room_id, {}).items():
            if event.audience == "party":
                await ws.send_text(event.model_dump_json(by_alias=True))
            elif event.audience == "host" and conn_id == "host":
                await ws.send_text(event.model_dump_json(by_alias=True))
            elif event.audience == "player" and conn_id.startswith("player:"):
                await ws.send_text(event.model_dump_json(by_alias=True))

    def update_last_sequence(self, room_id: str, connection_id: str, sequence: int):
        self._last_sequence.setdefault(room_id, {})[connection_id] = sequence

    def get_last_sequence(self, room_id: str, connection_id: str) -> int:
        return self._last_sequence.get(room_id, {}).get(connection_id, 0)

    def reconnect(self, conn, room_id: str, character_id: str, last_sequence: int) -> dict:
        char_row = conn.execute(
            "SELECT * FROM characters WHERE character_id = %s", (character_id,)
        ).fetchone()
        if not char_row:
            return {"needs_snapshot": True, "reason": "character_not_found"}

        current_max = conn.execute(
            "SELECT MAX(sequence) as max_seq FROM events WHERE room_id = %s", (room_id,)
        ).fetchone()
        max_seq = current_max["max_seq"] or 0

        missed = max_seq - last_sequence

        if missed > FULL_SNAPSHOT_THRESHOLD or last_sequence == 0:
            return {"needs_snapshot": True, "reason": "too_many_missed"}

        rows = conn.execute(
            "SELECT sequence, event_type, audience, payload, issued_at FROM events "
            "WHERE room_id = %s AND sequence > %s ORDER BY sequence ASC",
            (room_id, last_sequence),
        ).fetchall()

        pending = conn.execute(
            "SELECT action_id, intent_type, declared_intent, status, result, created_at "
            "FROM actions WHERE room_id = %s AND character_id = %s AND status IN ('queued', 'batched', 'resolving')",
            (room_id, character_id),
        ).fetchall()

        events = [dict(r) for r in rows]
        pending_actions = [dict(r) for r in pending]

        return {
            "needs_snapshot": False,
            "events": events,
            "pending_actions": pending_actions,
            "last_sequence": max_seq,
        }


manager = ConnectionManager()
