import json
import pytest
from src.server.campaign_archive import CampaignArchive
from src.server.models import CampaignArchiveQuery


@pytest.fixture
def campaign_archive(test_db):
    return CampaignArchive(test_db)


def _seed_full_room(conn):
    conn.execute(
        "INSERT INTO rooms (room_id, owner_token, status, started_at) "
        "VALUES ('room-1', 'token-owner', 'active', datetime('now', '-1 hour'))"
    )
    conn.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-1', 'room-1', 'Alice', 'token-1')"
    )
    conn.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-2', 'room-1', 'Bob', 'token-2')"
    )
    conn.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES "
        "('room-1', 's2c_chat_stream', 'party', '{\"text\": \"game started\"}')"
    )
    conn.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES "
        "('room-1', 's2c_reveal_transaction', 'party', '{\"text\": \"a clue found\"}')"
    )
    conn.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES "
        "('room-1', 's2c_campaign_ended', 'party', '{\"ending_type\": \"victory\", \"text\": \"you won\"}')"
    )
    conn.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-1', 'room-1', 'char-1', 'dialogue', 'I look around', 'resolved')"
    )
    conn.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-2', 'room-1', 'char-2', 'skill_check', 'search', 'resolved')"
    )
    conn.commit()


def test_generate_ending(campaign_archive, test_db):
    _seed_full_room(test_db)

    ending = campaign_archive.generate_ending("room-1")
    assert ending.ending_type == "victory"
    assert "Alice" in ending.summary or "Bob" in ending.summary
    assert len(ending.character_arcs) == 2


def test_generate_ending_marks_room_completed(campaign_archive, test_db):
    _seed_full_room(test_db)

    campaign_archive.generate_ending("room-1")

    room = test_db.execute("SELECT status FROM rooms WHERE room_id = 'room-1'").fetchone()
    assert room["status"] == "completed"


def test_generate_ending_saves_archive(campaign_archive, test_db):
    _seed_full_room(test_db)

    campaign_archive.generate_ending("room-1")

    archive = test_db.execute(
        "SELECT * FROM campaign_archives WHERE room_id = 'room-1'"
    ).fetchone()
    assert archive is not None
    assert archive["ending_type"] == "victory"


def test_get_campaign_summary(campaign_archive, test_db):
    _seed_full_room(test_db)

    summary = campaign_archive.get_campaign_summary("room-1")
    assert summary.room_id == "room-1"
    assert summary.total_actions == 2
    assert summary.duration_seconds > 0
    assert len(summary.key_events) > 0


def test_get_campaign_summary_with_ending(campaign_archive, test_db):
    _seed_full_room(test_db)
    campaign_archive.generate_ending("room-1")

    summary = campaign_archive.get_campaign_summary("room-1")
    assert summary.ending is not None
    assert summary.ending.ending_type == "victory"


def test_get_campaign_summary_nonexistent(campaign_archive, test_db):
    with pytest.raises(ValueError, match="not found"):
        campaign_archive.get_campaign_summary("room-999")


def test_query_archive_by_event_type(campaign_archive, test_db):
    _seed_full_room(test_db)

    filters = CampaignArchiveQuery(action_type="s2c_reveal_transaction")
    results = campaign_archive.query_archive("room-1", filters)
    assert len(results) == 1
    assert results[0].event_type == "s2c_reveal_transaction"


def test_query_archive_by_character(campaign_archive, test_db):
    _seed_full_room(test_db)

    # Add an event that contains a character reference in payload
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES "
        "('room-1', 's2c_action_queued', 'party', '{\"characterId\": \"char-1\", \"actionId\": \"act-1\"}')"
    )
    test_db.commit()

    filters = CampaignArchiveQuery(character_id="char-1")
    results = campaign_archive.query_archive("room-1", filters)
    assert len(results) == 1
    assert results[0].payload.get("characterId") == "char-1"


def test_query_archive_with_limit(campaign_archive, test_db):
    _seed_full_room(test_db)

    filters = CampaignArchiveQuery(limit=1)
    results = campaign_archive.query_archive("room-1", filters)
    assert len(results) == 1


def test_query_archive_empty_room(campaign_archive, test_db):
    _seed_full_room(test_db)

    filters = CampaignArchiveQuery()
    results = campaign_archive.query_archive("room-empty", filters)
    assert len(results) == 0
