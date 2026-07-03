import pytest

from src.server.game_loop import GameLoop


class Rows:
    def __init__(self, rows=None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self):
        self.rooms = {"room-1": {"room_id": "room-1", "state_version": 0}}
        self.actions = {
            "act-1": {
                "action_id": "act-1",
                "room_id": "room-1",
                "status": "queued",
            }
        }

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        params = params or ()
        if normalized.startswith("SELECT * FROM actions WHERE room_id"):
            room_id = params[0]
            return Rows([
                action for action in self.actions.values()
                if action["room_id"] == room_id and action["status"] == "queued"
            ])
        if normalized.startswith("SELECT * FROM rooms WHERE room_id"):
            return Rows([self.rooms[params[0]]])
        if normalized.startswith("UPDATE actions SET status = 'resolving' WHERE action_id"):
            self.actions[params[0]]["status"] = "resolving"
            return Rows()
        if normalized.startswith("UPDATE rooms SET state_version = state_version + 1"):
            self.rooms[params[0]]["state_version"] += 1
            return Rows()
        raise AssertionError(f"Unhandled SQL: {normalized}")

    def commit(self):
        pass


class FakePipeline:
    def __init__(self, conn):
        self.conn = conn

    async def resolve_action(self, action_id):
        self.conn.execute(
            "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s",
            ("room-1",),
        )
        self.conn.actions[action_id]["status"] = "resolved"
        return {"status": "resolved", "action_id": action_id}


@pytest.mark.asyncio
async def test_game_loop_does_not_bump_state_version_after_pipeline_resolution():
    conn = FakeConn()
    loop = GameLoop(conn, engine=object(), pipeline=FakePipeline(conn))

    await loop.process_turn("room-1")

    assert conn.rooms["room-1"]["state_version"] == 1
