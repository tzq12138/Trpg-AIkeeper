import json

import pytest

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.models import MechanicCompileResult
from src.server.scenario.content_projection import ContentProjectionService
from src.server.scenario.solo_runtime import SoloAdventureRuntime, SoloTransitionError


def _setup_solo_room(conn) -> tuple[str, str]:
    scenario_id = "solo-runtime-scenario"
    scenario_version_id = "solo-runtime-version"
    room_id = "solo-runtime-room"
    graph = {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": "车站。",
                    "target_node_ids": ["2"],
                    "citation": {"page_number": 1},
                },
                {
                    "node_id": "2",
                    "title": "条目 2",
                    "text": "长途车。",
                    "target_node_ids": [],
                    "citation": {"page_number": 2},
                },
            ],
        }
    }
    conn.execute(
        "INSERT INTO scenarios (scenario_id, title, knowledge_graph) VALUES (%s, %s, %s)",
        (scenario_id, "运行时测试", json.dumps(graph)),
    )
    conn.execute(
        """
        INSERT INTO scenario_versions (
            scenario_version_id, scenario_id, version_number, status,
            knowledge_graph, quality_report, prep_package, created_by
        ) VALUES (%s, %s, 1, 'published', %s, %s, %s, 'test-admin')
        """,
        (scenario_version_id, scenario_id, json.dumps(graph), json.dumps({}), json.dumps({})),
    )
    conn.execute(
        "INSERT INTO rooms (room_id, scenario_id, scenario_version_id, owner_token) "
        "VALUES (%s, %s, %s, 'owner-token')",
        (room_id, scenario_id, scenario_version_id),
    )
    ContentProjectionService(conn).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    return room_id, scenario_version_id


def test_runtime_initializes_root_and_applies_explicit_transition(test_db):
    room_id, scenario_version_id = _setup_solo_room(test_db)
    runtime = SoloAdventureRuntime(test_db)

    initial = runtime.current(room_id)
    result = runtime.transition(room_id, from_node_id="1", target_node_id="2")
    current = runtime.current(room_id)

    assert initial["node_id"] == "1"
    assert initial["scenario_version_id"] == scenario_version_id
    assert result["from_node_id"] == "1"
    assert result["target_node_id"] == "2"
    assert result["citation"]["page_number"] == 1
    assert current["node_id"] == "2"
    state = test_db.execute(
        "SELECT current_scene, visited_scenes FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert state["current_scene"] == "solo:2"
    assert state["visited_scenes"] == ["solo:1", "solo:2"]


def test_runtime_rejects_stale_or_non_explicit_transition(test_db):
    room_id, _ = _setup_solo_room(test_db)
    runtime = SoloAdventureRuntime(test_db)

    with pytest.raises(SoloTransitionError, match="solo_transition_not_allowed"):
        runtime.transition(room_id, from_node_id="1", target_node_id="9")
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    with pytest.raises(SoloTransitionError, match="solo_transition_stale"):
        runtime.transition(room_id, from_node_id="1", target_node_id="2")


class _AutoSuccessCompiler:
    async def compile(self, *_args, **_kwargs):
        return MechanicCompileResult(triggeredMechanic="auto_success")


class _RecordingDispatcher:
    def __init__(self):
        self.events = []

    async def emit(self, room_id, event_type, audience, payload, character_id=None):
        self.events.append((room_id, event_type, audience, payload, character_id))


@pytest.mark.asyncio
async def test_confirmed_move_commits_solo_transition_with_action_completion(test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-runtime-character', %s, '玩家', 'solo-runtime-token', %s)
        """,
        (room_id, json.dumps({"skills": {}})),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, intent_type, declared_intent,
            params, status, draft_id, idempotency_key
        ) VALUES (%s, %s, %s, 'move', '我转到条目 2', %s, 'queued', 'solo-draft', 'solo-key')
        """,
        (
            "solo-runtime-action",
            room_id,
            "solo-runtime-character",
            json.dumps({"fromNodeId": "1", "targetNodeId": "2"}),
        ),
    )
    dispatcher = _RecordingDispatcher()
    result = await ResolutionPipeline(
        test_db, compiler=_AutoSuccessCompiler(), dispatcher=dispatcher
    ).resolve_action("solo-runtime-action")

    assert result["status"] == "completed"
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "2"
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'solo-runtime-action'"
    ).fetchone()
    assert action["status"] == "completed"
    assert action["result"]["metadata"]["solo_adventure_transition"]["target_node_id"] == "2"
    assert any(event[1] == "s2c_scene_sync" for event in dispatcher.events)


def test_player_map_projects_only_current_solo_node_and_choices(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-map-character', %s, '玩家', 'solo-map-token', %s)
        """,
        (room_id, json.dumps({})),
    )

    response = client.get(
        f"/api/maps/{room_id}", headers={"X-Room-Token": "solo-map-token"}
    )

    assert response.status_code == 200
    scene = response.json()["textScene"]
    assert scene["name"] == "条目 1"
    assert scene["soloAdventure"]["nodeId"] == "1"
    assert scene["soloAdventure"]["choices"] == [{"nodeId": "2", "label": "转到条目 2"}]
    assert "长途车" not in response.text


def test_reconnect_restores_solo_scene_snapshot(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-reconnect-character', %s, '玩家', 'solo-reconnect-token', %s)
        """,
        (room_id, json.dumps({})),
    )
    SoloAdventureRuntime(test_db).transition(
        room_id, from_node_id="1", target_node_id="2"
    )

    response = client.get(
        "/api/player/reconnect", headers={"X-Room-Token": "solo-reconnect-token"}
    )

    assert response.status_code == 200
    assert response.json()["sceneState"] == {
        "currentScene": "solo:2",
        "visitedScenes": ["solo:1", "solo:2"],
        "version": 1,
    }
