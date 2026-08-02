import json
import pytest
from src.server.events.event_log import EventLog


@pytest.fixture
def event_log(test_db):
    return EventLog(test_db)


def _seed_room_and_chars(conn):
    conn.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('room-1', 'token-owner', 'active')"
    )
    conn.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-1', 'room-1', 'Alice', 'token-1')"
    )
    conn.commit()


def test_log_event_and_retrieve(event_log, test_db):
    _seed_room_and_chars(test_db)

    seq = event_log.log_event("room-1", "s2c_chat_stream", "party", {"text": "hello"})
    assert seq >= 1

    events = event_log.get_events("room-1")
    assert len(events) == 1
    assert events[0].sequence == seq
    assert events[0].event_type == "s2c_chat_stream"
    assert events[0].payload == {"text": "hello"}


def test_get_events_pagination(event_log, test_db):
    _seed_room_and_chars(test_db)

    for i in range(5):
        event_log.log_event("room-1", "s2c_chat_stream", "party", {"i": i})

    page1 = event_log.get_events("room-1", since_sequence=0, limit=2)
    assert len(page1) == 2
    assert page1[0].sequence < page1[1].sequence

    page2 = event_log.get_events("room-1", since_sequence=page1[-1].sequence, limit=2)
    assert len(page2) == 2
    assert page2[0].sequence > page1[-1].sequence


def test_get_public_events_filters_private(event_log, test_db):
    _seed_room_and_chars(test_db)

    event_log.log_event("room-1", "s2c_chat_stream", "party", {"text": "public"})
    event_log.log_event("room-1", "s2c_private_notice", "player", {"text": "secret"})
    event_log.log_event("room-1", "s2c_public_observation", "party", {"text": "visible"})

    public = event_log.get_public_events("room-1")
    assert len(public) == 2
    assert all(e.audience != "player" for e in public)

    # Verify host events are also excluded
    event_log.log_event("room-1", "s2c_host_snapshot", "host", {"data": "secret"})
    public2 = event_log.get_public_events("room-1")
    assert all(e.audience != "host" for e in public2), "Host events must not leak to public"


def test_checkpoint_create_and_list(event_log, test_db):
    _seed_room_and_chars(test_db)

    cp = event_log.create_checkpoint("room-1", "cp-1")
    assert cp.checkpoint_id == "cp-1"
    assert cp.room_id == "room-1"
    assert "room" in cp.state_snapshot

    cps = event_log.list_checkpoints("room-1")
    assert len(cps) == 1
    assert cps[0].checkpoint_id == "cp-1"


def test_checkpoint_restore_keeps_append_only_events(event_log, test_db):
    _seed_room_and_chars(test_db)
    event_log.log_event("room-1", "s2c_chat_stream", "party", {"text": "before"})

    event_log.create_checkpoint("room-1", "cp-1")

    event_log.log_event("room-1", "s2c_chat_stream", "party", {"text": "after"})
    # create_checkpoint also logs a s2c_checkpoint_created event, so 3 events total
    events_before = event_log.get_events("room-1")
    assert len(events_before) == 3

    event_log.restore_checkpoint("room-1", "cp-1")

    events_after = event_log.get_events("room-1")
    assert len(events_after) == 3
    assert [event.payload.get("text") for event in events_after] == [
        "before",
        None,
        "after",
    ]


def test_checkpoint_restore_nonexistent(event_log, test_db):
    _seed_room_and_chars(test_db)

    with pytest.raises(ValueError, match="not found"):
        event_log.restore_checkpoint("room-1", "cp-999")


def test_checkpoint_restores_character_runtime_without_restoring_credentials(event_log, test_db):
    _seed_room_and_chars(test_db)

    event_log.create_checkpoint("room-1", "cp-1")

    test_db.execute(
        "UPDATE characters SET status = 'left', player_token = 'rotated-token' "
        "WHERE character_id = 'char-1'"
    )
    test_db.commit()

    event_log.restore_checkpoint("room-1", "cp-1")

    char = test_db.execute(
        "SELECT status, player_token FROM characters WHERE character_id = 'char-1'"
    ).fetchone()
    assert char["status"] == "joined"
    assert char["player_token"] == "rotated-token"
