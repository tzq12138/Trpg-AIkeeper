from src.server.db_adapter import SCHEMA_SQL
from src.server.db_pg import SCHEMA_SQL as SECONDARY_SCHEMA_SQL
from tests.server.conftest import create_room, setup_auth_test_data


V2_ACTION_TABLES = {
    "action_drafts",
    "action_draft_revisions",
    "action_status_events",
    "action_review_requests",
    "compensation_transactions",
    "room_player_settings",
}


def test_v2_action_tables_are_initialized(test_db):
    rows = test_db.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = ANY(%s)",
        (list(V2_ACTION_TABLES),),
    ).fetchall()

    assert {row["table_name"] for row in rows} == V2_ACTION_TABLES


def test_both_postgres_initializers_share_the_same_schema_source():
    assert SECONDARY_SCHEMA_SQL == SCHEMA_SQL


def test_new_rooms_default_to_player_experience_v2(client, test_db):
    setup_auth_test_data(test_db)

    room_id = create_room(client)["room_id"]
    room = test_db.execute(
        "SELECT player_experience_version, action_pacing_preset, action_timing, "
        "draft_analysis_enabled FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()

    assert room["player_experience_version"] == "v2"
    assert room["action_pacing_preset"] == "standard"
    assert room["action_timing"] == {
        "input_hint_seconds": 60,
        "receipt_seconds": 5,
        "preview_seconds": 30,
        "resolution_seconds": 180,
    }
    assert room["draft_analysis_enabled"] is True


def test_schema_migration_keeps_existing_rooms_on_v1(test_db):
    test_db.execute("ALTER TABLE rooms DROP COLUMN player_experience_version")
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) VALUES ('legacy-room', 'legacy-token')"
    )

    test_db.executescript(SCHEMA_SQL)

    legacy = test_db.execute(
        "SELECT player_experience_version FROM rooms WHERE room_id = 'legacy-room'"
    ).fetchone()
    assert legacy["player_experience_version"] == "v1"

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) VALUES ('new-room', 'new-token')"
    )
    current = test_db.execute(
        "SELECT player_experience_version FROM rooms WHERE room_id = 'new-room'"
    ).fetchone()
    assert current["player_experience_version"] == "v2"
