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


@pytest.mark.asyncio
async def test_timeout_scan_skips_retired_rooms_without_writing_absence_actions(
    monkeypatch, test_db
):
    from src.server import turn_timeout_worker

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status, rule_source_status, rule_source_reason) "
        "VALUES ('retired-timeout-room', 'owner', 'active', 'rule_source_retired', "
        "'local_test_rule_version')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('retired-timeout-character', 'retired-timeout-room', 'Player', 'token', 'ready')"
    )
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('retired-timeout-encounter', 'retired-timeout-room', 'combat', 'active', 1)"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id, started_at) "
        "VALUES ('retired-timeout-turn', 'retired-timeout-room', 1, 'collecting', 'combat', "
        "'retired-timeout-encounter', NOW() - INTERVAL '2 minutes')"
    )
    test_db.commit()

    scheduled = []

    async def fake_settle(app, room_id, turn_id):
        scheduled.append((app, room_id, turn_id))

    monkeypatch.setattr(turn_timeout_worker, "_settle_turn_background", fake_settle)
    app = SimpleNamespace(state=SimpleNamespace(db=test_db, pg_db=None))

    assert await turn_timeout_worker.apply_expired_turns_once(app) == []
    await asyncio.sleep(0)
    assert scheduled == []
    assert test_db.execute(
        "SELECT status FROM room_turns WHERE turn_id = 'retired-timeout-turn'"
    ).fetchone()["status"] == "collecting"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM actions WHERE turn_id = 'retired-timeout-turn'"
    ).fetchone()["count"] == 0


@pytest.mark.asyncio
async def test_background_settlement_skips_a_retired_room_before_claiming_turn(test_db):
    from src.server.player.router_player import _settle_turn_background

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status, rule_source_status, rule_source_reason) "
        "VALUES ('retired-settlement-room', 'owner', 'active', 'rule_source_retired', "
        "'local_test_rule_version')"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status) "
        "VALUES ('retired-settlement-turn', 'retired-settlement-room', 1, 'collecting')"
    )
    test_db.commit()

    app = SimpleNamespace(state=SimpleNamespace(db=test_db, pg_db=None))
    await _settle_turn_background(app, "retired-settlement-room", "retired-settlement-turn")

    assert test_db.execute(
        "SELECT status FROM room_turns WHERE turn_id = 'retired-settlement-turn'"
    ).fetchone()["status"] == "collecting"


@pytest.mark.asyncio
async def test_background_settlement_stops_when_room_retires_after_claim(
    monkeypatch,
    test_db,
):
    from src.server import turn_manager
    from src.server.player.router_player import _settle_turn_background

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('retired-after-claim-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('retired-after-claim-character', 'retired-after-claim-room', 'Player', 'token', 'ready')"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status) "
        "VALUES ('retired-after-claim-turn', 'retired-after-claim-room', 1, 'collecting')"
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, turn_id, intent_type, declared_intent, status) "
        "VALUES ('retired-after-claim-action', 'retired-after-claim-room', "
        "'retired-after-claim-character', 'retired-after-claim-turn', 'dialogue', 'Wait.', 'queued')"
    )
    test_db.commit()

    base_manager = turn_manager.TurnManager

    class RetiringAfterClaimTurnManager(base_manager):
        def mark_resolving(self, turn_id):
            claimed = super().mark_resolving(turn_id)
            if claimed:
                test_db.execute(
                    "UPDATE rooms SET rule_source_status = 'rule_source_retired', "
                    "rule_source_reason = 'local_test_rule_version' "
                    "WHERE room_id = 'retired-after-claim-room'"
                )
                test_db.commit()
            return claimed

    monkeypatch.setattr(turn_manager, "TurnManager", RetiringAfterClaimTurnManager)

    class Pipeline:
        async def resolve_action(self, _action_id):
            from src.server.rule_source_lifecycle import RuleSourceRetiredError

            raise RuleSourceRetiredError("local_test_rule_version")

    emitted = []

    class Dispatcher:
        async def emit(self, *args, **kwargs):
            emitted.append((args, kwargs))

    app = SimpleNamespace(
        state=SimpleNamespace(
            db=test_db,
            pg_db=None,
            pipeline=Pipeline(),
            dispatcher=Dispatcher(),
        )
    )
    await _settle_turn_background(
        app,
        "retired-after-claim-room",
        "retired-after-claim-turn",
    )

    assert test_db.execute(
        "SELECT status FROM room_turns WHERE turn_id = 'retired-after-claim-turn'"
    ).fetchone()["status"] == "resolving"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM room_turns WHERE room_id = 'retired-after-claim-room'"
    ).fetchone()["count"] == 1
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'retired-after-claim-action'"
    ).fetchone()["status"] == "queued"
    assert emitted == []


@pytest.mark.asyncio
async def test_background_settlement_stops_when_room_retires_after_last_action_resolution(
    test_db,
):
    from src.server.player.router_player import _settle_turn_background

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) "
        "VALUES ('retired-after-resolution-room', 'owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
        "VALUES ('retired-after-resolution-character', 'retired-after-resolution-room', "
        "'Player', 'token', 'ready')"
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status) "
        "VALUES ('retired-after-resolution-turn', 'retired-after-resolution-room', 1, 'collecting')"
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, turn_id, intent_type, declared_intent, status) "
        "VALUES ('retired-after-resolution-action', 'retired-after-resolution-room', "
        "'retired-after-resolution-character', 'retired-after-resolution-turn', "
        "'dialogue', 'Wait.', 'queued')"
    )
    test_db.commit()

    class RetiringPipeline:
        async def resolve_action(self, action_id):
            test_db.execute(
                "UPDATE actions SET status = 'completed' WHERE action_id = %s",
                (action_id,),
            )
            test_db.execute(
                "UPDATE rooms SET rule_source_status = 'rule_source_retired', "
                "rule_source_reason = 'local_test_rule_version' "
                "WHERE room_id = 'retired-after-resolution-room'"
            )
            test_db.commit()
            return {"status": "completed", "action_id": action_id}

    emitted = []

    class Dispatcher:
        async def emit(self, *args, **kwargs):
            emitted.append((args, kwargs))

    app = SimpleNamespace(
        state=SimpleNamespace(
            db=test_db,
            pg_db=None,
            pipeline=RetiringPipeline(),
            dispatcher=Dispatcher(),
        )
    )
    await _settle_turn_background(
        app,
        "retired-after-resolution-room",
        "retired-after-resolution-turn",
    )

    assert test_db.execute(
        "SELECT status FROM room_turns WHERE turn_id = 'retired-after-resolution-turn'"
    ).fetchone()["status"] == "resolving"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM room_turns WHERE room_id = 'retired-after-resolution-room'"
    ).fetchone()["count"] == 1
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'retired-after-resolution-action'"
    ).fetchone()["status"] == "completed"
    assert emitted == []
