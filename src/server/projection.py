import json
from typing import Any

from .models import EngineEvent
from .ws_manager import manager as default_ws_manager


class ProjectionBuilder:
    def build(self, event: EngineEvent) -> list[EngineEvent]:
        projections = []
        if event.audience == "host":
            projections.append(event)
        elif event.audience == "player":
            projections.append(event)
        elif event.audience == "party":
            projections.append(event.model_copy(update={"audience": "host"}))
            projections.append(event.model_copy(update={"audience": "player"}))
        elif event.audience == "system":
            projections.append(event)
        return projections


class ProjectionDispatcher:
    def __init__(self, conn, ws_manager=default_ws_manager):
        self.conn = conn
        self.ws_manager = ws_manager

    async def emit(
        self,
        room_id: str,
        event_type: str,
        audience: str,
        payload: dict[str, Any],
        character_id: str | None = None,
    ):
        self.conn.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s)",
            (room_id, event_type, audience, json.dumps(payload, ensure_ascii=False)),
        )
        self.conn.commit()

        event = EngineEvent(
            roomId=room_id,
            type=event_type,
            audience=audience,
            payload=payload,
        )
        if audience == "player" and character_id:
            await self.ws_manager.send_event(room_id, f"player:{character_id}", event)
            return
        await self.ws_manager.broadcast_to_room(room_id, event)
