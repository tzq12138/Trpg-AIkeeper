from typing import Callable
from .models import EngineEvent


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}

    def subscribe(self, room_id: str, callback: Callable[[EngineEvent], None]):
        self._subscribers.setdefault(room_id, []).append(callback)

    def unsubscribe(self, room_id: str, callback: Callable):
        if room_id in self._subscribers:
            self._subscribers[room_id] = [
                c for c in self._subscribers[room_id] if c is not callback
            ]

    def publish(self, event: EngineEvent):
        for callback in self._subscribers.get(event.room_id, []):
            callback(event)
