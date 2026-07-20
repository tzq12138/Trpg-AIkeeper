import json

from tests.server.conftest import create_room, setup_auth_test_data


def _ending_conditions():
    return [{
        "ending_id": "escape",
        "type": "victory",
        "citation": {"source_ref": "page:8", "page_number": 8},
        "completion_conditions": {
            "entered_scenes": ["harbor"],
            "event_types": ["s2c_clue_discovered"],
            "room_status": "active",
        },
    }]


def test_evaluate_ending_requires_all_declared_persisted_facts(client, test_db):
    from src.server.engine.ending_conditions import evaluate_ending_conditions

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, version) "
        "VALUES (%s, 'lobby', '[\"lobby\"]', 1) "
        "ON CONFLICT (room_id) DO UPDATE SET current_scene = EXCLUDED.current_scene, "
        "visited_scenes = EXCLUDED.visited_scenes",
        (room_id,),
    )
    test_db.commit()

    assert evaluate_ending_conditions(test_db, room_id, _ending_conditions()) is None

    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'harbor', visited_scenes = '[\"lobby\", \"harbor\"]' "
        "WHERE room_id = %s",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'party', %s)",
        (room_id, "s2c_clue_discovered", json.dumps({"clue_id": "black-key"})),
    )
    test_db.commit()

    decision = evaluate_ending_conditions(test_db, room_id, _ending_conditions())

    assert decision is not None
    assert decision.ending_id == "escape"
    assert decision.ending_type == "victory"
    assert decision.citation == {"source_ref": "page:8", "page_number": 8}


def test_evaluate_ending_rejects_ambiguous_or_invalid_conditions(client, test_db):
    from src.server.engine.ending_conditions import evaluate_ending_conditions

    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    test_db.commit()
    matching = {
        "ending_id": "first",
        "type": "mixed",
        "citation": {"source_ref": "page:1"},
        "completion_conditions": {"room_status": "active"},
    }

    assert evaluate_ending_conditions(
        test_db,
        room_id,
        [matching, {**matching, "ending_id": "second"}],
    ) is None
    assert evaluate_ending_conditions(
        test_db,
        room_id,
        [{**matching, "completion_conditions": {"invented": True}}],
    ) is None
