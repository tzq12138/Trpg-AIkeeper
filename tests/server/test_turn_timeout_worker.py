import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_competing_turn_settlement_releases_dedicated_pg_connection(monkeypatch):
    from src.server import turn_manager
    from src.server.player import router_player

    class _DedicatedConnection:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class _DedicatedDatabase:
        def __init__(self, connection):
            self.connection = connection

        def get_connection(self):
            return self.connection

    class _AlreadyResolvingTurnManager:
        def __init__(self, _connection):
            pass

        def mark_resolving(self, _turn_id):
            return False

    connection = _DedicatedConnection()
    monkeypatch.setattr(turn_manager, "TurnManager", _AlreadyResolvingTurnManager)
    app = SimpleNamespace(
        state=SimpleNamespace(pg_db=_DedicatedDatabase(connection), db=None)
    )

    await router_player._settle_turn_background(app, "room", "turn")

    assert connection.closed is True


@pytest.mark.asyncio
async def test_timeout_scan_applies_absence_policy_and_schedules_settlement(monkeypatch, test_db):
    from src.server import turn_timeout_worker

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('timeout-worker-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('timeout-worker-character', 'timeout-worker-room', 'Player', 'token', 'ready')"
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('timeout-worker-encounter', 'timeout-worker-room', 'combat', 'active', 1)"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id, started_at) "
        "VALUES ('timeout-worker-turn', 'timeout-worker-room', 1, 'collecting', 'combat', "
        "'timeout-worker-encounter', NOW() - INTERVAL '2 minutes')"
    )
    test_db.commit()

    scheduled = []

    async def fake_settle(app, room_id, turn_id):
        scheduled.append((app, room_id, turn_id))

    monkeypatch.setattr(turn_timeout_worker, "_settle_turn_background", fake_settle)
    app = SimpleNamespace(state=SimpleNamespace(db=test_db, pg_db=None))

    applied = await turn_timeout_worker.apply_expired_turns_once(app)
    await asyncio.sleep(0)

    assert applied == [{
        'room_id': 'timeout-worker-room',
        'turn_id': 'timeout-worker-turn',
        'character_ids': ['timeout-worker-character'],
    }]
    assert scheduled == [(app, 'timeout-worker-room', 'timeout-worker-turn')]
