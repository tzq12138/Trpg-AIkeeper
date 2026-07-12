import asyncio

import pytest

from src.server.host.ws_manager import ConnectionManager
from src.server.models import EngineEvent


class _HangingWebSocket:
    async def send_text(self, _payload: str):
        await asyncio.Event().wait()


class _RecordingWebSocket:
    def __init__(self):
        self.messages = []

    async def send_text(self, payload: str):
        self.messages.append(payload)


class _ClosableWebSocket(_RecordingWebSocket):
    def __init__(self):
        super().__init__()
        self.closed = asyncio.Event()

    async def close(self, **_kwargs):
        self.closed.set()


@pytest.mark.asyncio
async def test_broadcast_drops_hanging_connection_without_blocking_healthy_player(monkeypatch):
    import src.server.host.ws_manager as ws_module

    monkeypatch.setattr(ws_module, "WS_SEND_TIMEOUT_SECONDS", 0.01, raising=False)
    manager = ConnectionManager()
    hanging = _HangingWebSocket()
    healthy = _RecordingWebSocket()
    manager._connections["room-1"] = {
        "player:stale": hanging,
        "player:healthy": healthy,
    }
    event = EngineEvent(
        roomId="room-1",
        type="s2c_ai_stage_changed",
        roomSequence=1,
        audience="player",
        payload={"stage": "retrieving"},
    )

    await asyncio.wait_for(manager.broadcast_to_room("room-1", event), timeout=0.1)

    assert len(healthy.messages) == 1
    assert "player:stale" not in manager._connections["room-1"]
    assert "player:healthy" in manager._connections["room-1"]


@pytest.mark.asyncio
async def test_register_accepted_closes_replaced_socket():
    manager = ConnectionManager()
    old = _ClosableWebSocket()
    new = _ClosableWebSocket()
    manager._connections["room-1"] = {"player:one": old}

    manager.register_accepted(new, "room-1", "player:one")
    await asyncio.wait_for(old.closed.wait(), timeout=0.1)

    assert manager._connections["room-1"]["player:one"] is new
