import json

from src.server.turn_manager import TurnManager


def test_ready_player_submission_settles_single_player_turn(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES ('turn-ready-room', 'owner', 'active')"
    )
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data)
        VALUES ('turn-ready-character', 'turn-ready-room', '玩家', 'token', 'ready', %s)
        """,
        (json.dumps({}),),
    )
    test_db.execute(
        """
        INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status)
        VALUES ('turn-ready-action', 'turn-ready-room', 'turn-ready-character', 'combat_action', '攻击黑熊', 'queued')
        """
    )

    turns = TurnManager(test_db)
    turns.submit_action('turn-ready-room', 'turn-ready-character', 'turn-ready-action')

    assert turns.all_submitted('turn-ready-room') is True
