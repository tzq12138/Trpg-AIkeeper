from types import SimpleNamespace

from src.server.player.router_actions_v2 import _schedule_action_resolution


class _Rows:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def execute(self, _sql, _params):
        return _Rows({"turn_id": None, "room_status": "active", "room_id": "room-1"})


class _Batcher:
    def __init__(self):
        self.calls = []

    def schedule(self, room_id, flush):
        self.calls.append((room_id, flush))
        return True


def test_non_turn_action_uses_room_batcher_instead_of_immediate_worker():
    batcher = _Batcher()
    app = SimpleNamespace(state=SimpleNamespace(
        pipeline=object(),
        pg_db=None,
        action_batcher=batcher,
    ))

    _schedule_action_resolution(app, _Conn(), "action-1")

    assert len(batcher.calls) == 1
    assert batcher.calls[0][0] == "room-1"
