import pytest

from src.server.engine.projection import ProjectionDispatcher


class Rows:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConn:
    def __init__(self):
        self.committed = False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT state_version FROM rooms"):
            return Rows({"state_version": 4})
        if normalized.startswith("INSERT INTO events"):
            return Rows({"sequence": 7})
        raise AssertionError(f"Unhandled SQL: {normalized}")

    def commit(self):
        self.committed = True


class FakeWsManager:
    def __init__(self):
        self.broadcasts = []
        self.direct = []

    async def broadcast_to_room(self, room_id, event):
        self.broadcasts.append((room_id, event))

    async def send_event(self, room_id, target, event):
        self.direct.append((room_id, target, event))


@pytest.mark.asyncio
async def test_dispatcher_sends_live_event_with_persisted_room_sequence():
    conn = FakeConn()
    ws = FakeWsManager()
    dispatcher = ProjectionDispatcher(conn, ws_manager=ws)

    await dispatcher.emit("room-1", "s2c_public_observation", "party", {"text": "ok"})

    assert conn.committed is True
    assert ws.broadcasts[0][1].room_sequence == 7
