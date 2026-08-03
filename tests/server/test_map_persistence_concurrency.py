from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event, local

from src.server.db_adapter import PgConnection, PgCursorWrapper
from src.server.engine.state_service import StateService
from src.server.map_persistence import mark_node_explored
from src.server.models import StateChangeSet
from tests.server.conftest import create_scenario, setup_auth_test_data


def test_concurrent_exploration_merges_room_map_state_without_lost_updates(
    test_db,
    monkeypatch,
):
    setup_auth_test_data(test_db)
    create_scenario(test_db, "map-lock-scenario", "Map Lock")
    test_db.execute(
        "INSERT INTO scenario_maps "
        "(map_id, scenario_id, status, nodes, edges) "
        "VALUES ('map-lock-map', 'map-lock-scenario', 'confirmed', '[]', '[]')"
    )
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, scenario_id) "
        "VALUES ('map-lock-room', 'map-lock-owner', 'map-lock-scenario')"
    )
    test_db.execute(
        "INSERT INTO room_map_state (room_id, map_id, explored_nodes) "
        "VALUES ('map-lock-room', 'map-lock-map', '[]')"
    )
    test_db.commit()

    first_read = Event()
    release_first = Event()
    writer_context = local()
    original_execute = PgCursorWrapper.execute

    def delayed_first_read(cursor, sql, params=None):
        result = original_execute(cursor, sql, params)
        if (
            getattr(writer_context, "writer", "") == "first"
            and "SELECT * FROM room_map_state WHERE room_id = %s" in sql
        ):
            first_read.set()
            release_first.wait(timeout=5)
        return result

    monkeypatch.setattr(PgCursorWrapper, "execute", delayed_first_read)

    def explore(writer: str, node_id: str):
        conn = PgConnection(test_db._pool)
        writer_context.writer = writer
        try:
            mark_node_explored(conn, "map-lock-room", node_id)
        finally:
            conn.close()

    second_blocked = False
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(explore, "first", "node-a")
        assert first_read.wait(timeout=2)
        second = executor.submit(explore, "second", "node-b")
        try:
            second.result(timeout=0.25)
        except TimeoutError:
            second_blocked = True
        finally:
            release_first.set()
        first.result(timeout=3)
        second.result(timeout=3)

    explored = test_db.execute(
        "SELECT explored_nodes FROM room_map_state WHERE room_id = 'map-lock-room'"
    ).fetchone()["explored_nodes"]
    assert second_blocked is True
    assert set(explored) == {"node-a", "node-b"}


def test_state_service_map_changes_reuse_the_caller_transaction(test_db):
    setup_auth_test_data(test_db)
    create_scenario(test_db, "map-state-scenario", "Map State")
    test_db.execute(
        "INSERT INTO scenario_maps "
        "(map_id, scenario_id, status, nodes, edges) "
        "VALUES ('map-state-map', 'map-state-scenario', 'confirmed', '[]', '[]')"
    )
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, scenario_id) "
        "VALUES ('map-state-room', 'map-state-owner', 'map-state-scenario')"
    )
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token) "
        "VALUES ('map-state-character', 'map-state-room', '玩家', 'map-state-token')"
    )
    test_db.execute(
        "INSERT INTO room_map_state (room_id, map_id, explored_nodes) "
        "VALUES ('map-state-room', 'map-state-map', '[]')"
    )
    test_db.commit()

    StateService(test_db).apply_change(
        "map-state-room",
        {"character_id": "map-state-character", "action_id": "map-state-action"},
        StateChangeSet(
            mapChanges={
                "nodeExplored": "library",
                "positionSet": {"map-state-character": "library"},
            }
        ),
        reason="move",
    )

    assert test_db.execute(
        "SELECT explored_nodes FROM room_map_state WHERE room_id = 'map-state-room'"
    ).fetchone()["explored_nodes"] == ["library"]
    assert test_db.execute(
        "SELECT node_id FROM character_map_positions "
        "WHERE character_id = 'map-state-character' AND room_id = 'map-state-room'"
    ).fetchone()["node_id"] == "library"
