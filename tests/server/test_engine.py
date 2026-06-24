from src.server.models import PlayerIntent


def test_intent_returns_accepted(engine, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) VALUES ('room-1', 'token-owner')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-1', 'room-1', 'Alice', 'token-1')"
    )
    test_db.commit()

    intent = PlayerIntent(
        action_id="act-1", intent_type="dialogue", declared_intent="I look around"
    )
    result = engine.submit_intent("room-1", "char-1", intent)
    assert result["status"] == "accepted"
    assert result["action_id"] == "act-1"


def test_intent_idempotent(engine, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) VALUES ('room-1', 'token-owner')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-1', 'room-1', 'Alice', 'token-1')"
    )
    test_db.commit()

    intent = PlayerIntent(
        action_id="act-1", intent_type="dialogue", declared_intent="I look around"
    )
    engine.submit_intent("room-1", "char-1", intent)
    result = engine.submit_intent("room-1", "char-1", intent)
    assert result["status"] == "accepted"

    count = test_db.execute(
        "SELECT COUNT(*) as c FROM actions WHERE action_id = 'act-1'"
    ).fetchone()["c"]
    assert count == 1


def test_complete_action(engine, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) VALUES ('room-1', 'token-owner')"
    )
    test_db.execute(
        "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
        "VALUES ('act-1', 'room-1', 'char-1', 'dialogue', 'test', 'queued')"
    )
    test_db.commit()

    engine.complete_action("act-1", "resolved", "You see a dark room")
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'act-1'"
    ).fetchone()
    assert action["status"] == "resolved"
    assert action["result"] == "You see a dark room"


def test_conflict_detection(engine, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, state_version) VALUES ('room-1', 'token-owner', 5)"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-1', 'room-1', 'Alice', 'token-1')"
    )
    test_db.commit()

    intent = PlayerIntent(
        action_id="act-1", intent_type="dialogue", declared_intent="I look around",
        base_state_version=3,
    )
    result = engine.submit_intent("room-1", "char-1", intent)
    assert result["status"] == "conflict"
    assert result["current_version"] == 5


def test_conflict_detection_matching_version(engine, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, state_version) VALUES ('room-1', 'token-owner', 5)"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-1', 'room-1', 'Alice', 'token-1')"
    )
    test_db.commit()

    intent = PlayerIntent(
        action_id="act-1", intent_type="dialogue", declared_intent="I look around",
        base_state_version=5,
    )
    result = engine.submit_intent("room-1", "char-1", intent)
    assert result["status"] == "accepted"


def test_conflict_detection_zero_version_bypasses(engine, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, state_version) VALUES ('room-1', 'token-owner', 5)"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) "
        "VALUES ('char-1', 'room-1', 'Alice', 'token-1')"
    )
    test_db.commit()

    intent = PlayerIntent(
        action_id="act-1", intent_type="dialogue", declared_intent="I look around",
        base_state_version=0,
    )
    result = engine.submit_intent("room-1", "char-1", intent)
    assert result["status"] == "accepted"


def test_ready_toggle(engine, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) VALUES ('room-1', 'token-owner')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready) "
        "VALUES ('char-1', 'room-1', 'Alice', 'token-1', 0)"
    )
    test_db.commit()

    intent = PlayerIntent(
        action_id="act-ready", intent_type="ready_toggle", declared_intent=""
    )
    result = engine.submit_intent("room-1", "char-1", intent)
    assert result["status"] == "accepted"
    assert result["is_ready"] is True

    char = test_db.execute(
        "SELECT is_ready FROM characters WHERE character_id = 'char-1'"
    ).fetchone()
    assert char["is_ready"] == 1


def test_ready_toggle_off(engine, test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) VALUES ('room-1', 'token-owner')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready) "
        "VALUES ('char-1', 'room-1', 'Alice', 'token-1', 1)"
    )
    test_db.commit()

    intent = PlayerIntent(
        action_id="act-ready", intent_type="ready_toggle", declared_intent=""
    )
    result = engine.submit_intent("room-1", "char-1", intent)
    assert result["status"] == "accepted"
    assert result["is_ready"] is False
