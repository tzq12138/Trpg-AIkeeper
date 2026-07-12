import json

import pytest

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.models import MechanicCompileResult, PlayerIntent, ResolutionResult
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
                    "target_node_ids": ["3"],
                    "citation": {"page_number": 2},
                },
                {
                    "node_id": "3",
                    "title": "条目 3",
                    "text": "黑熊的敏捷为58，生命值为20。它会用爪击攻击，战斗持续三轮。",
                    "target_node_ids": ["4"],
                    "citation": {"page_number": 3},
                },
                {
                    "node_id": "4",
                    "title": "条目 4",
                    "text": "你成功逃离危险。\n【剧终】",
                    "target_node_ids": [],
                    "citation": {"page_number": 4},
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
            json.dumps(
                {
                    "fromNodeId": "1",
                    "targetNodeId": "2",
                    "director_plan": {
                        "context_version": 0,
                        "preconditions": [],
                        "permissions": [],
                        "state_patch": [],
                        "state_patch_authority": "advisory_only",
                    },
                },
                ensure_ascii=False,
            ),
        ),
    )
    dispatcher = _RecordingDispatcher()
    result = await ResolutionPipeline(
        test_db, compiler=_AutoSuccessCompiler(), dispatcher=dispatcher
    ).resolve_action("solo-runtime-action")

    assert result["status"] == "completed"
    assert "长途车。" in result["result"]["narrative"]
    assert "转到条目 3" in result["result"]["narrative"]
    assert "你准备怎么做" in result["result"]["narrative"]
    assert SoloAdventureRuntime(test_db).current(room_id)["node_id"] == "2"
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'solo-runtime-action'"
    ).fetchone()
    assert action["status"] == "completed"
    assert action["result"]["metadata"]["solo_adventure_transition"]["target_node_id"] == "2"
    assert any(event[1] == "s2c_scene_sync" for event in dispatcher.events)


def test_player_map_projects_text_scene_without_raw_solo_targets(client, test_db):
    from src.server.router_map import _sanitize_player_scene_text

    assert _sanitize_player_scene_text("车站。转到263。") == "车站。"
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
    assert scene["name"] == "当前场景"
    assert "条目 1" not in response.text
    assert "soloAdventure" not in scene
    assert "target_node_ids" not in response.text
    assert "source_ref" not in response.text
    assert "长途车" not in response.text


def test_player_map_uses_semantic_projection_when_image_map_is_active(client, test_db):
    from src.server.map_persistence import init_room_map_state, set_character_position

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-image-map-character', %s, '玩家', 'solo-image-map-token', %s)
        """,
        (room_id, json.dumps({})),
    )
    test_db.execute(
        "INSERT INTO scenario_maps "
        "(map_id, scenario_id, status, map_type, base_asset, nodes, edges) "
        "VALUES ('solo-image-map', 'solo-runtime-scenario', 'confirmed', 'image', %s, %s, %s)",
        (
            json.dumps({"assetId": "solo-map-image"}),
            json.dumps([{"nodeId": "station", "name": "车站", "isStart": True}]),
            json.dumps([]),
        ),
    )
    test_db.commit()
    init_room_map_state(test_db, room_id, "solo-image-map")
    set_character_position(test_db, "solo-image-map-character", room_id, "station")

    response = client.get(
        f"/api/maps/{room_id}", headers={"X-Room-Token": "solo-image-map-token"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mapType"] == "image"
    assert "knownLocations" in payload
    assert "knownConnections" in payload
    assert "partyPosition" in payload
    assert "fogOfWar" in payload
    assert "soloAdventure" not in response.text
    assert "targetNodeId" not in response.text
    assert "cluesAvailable" not in response.text


def test_v2_map_move_returns_410_use_action_draft(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-move-character', %s, '玩家', 'solo-move-token', %s)
        """,
        (room_id, json.dumps({})),
    )

    response = client.post(
        f"/api/map/{room_id}/move",
        headers={"X-Room-Token": "solo-move-token"},
        json={"fromNodeId": "1", "targetNodeId": "2"},
    )

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "use_action_draft"


def test_shared_contract_models_use_redacted_citations():
    from pydantic import ValidationError
    from src.server.models import (
        ActionDraftDTO,
        AiStageProgress,
        HostDirectorSnapshotDTO,
        NarrationResultDTO,
        RedactedCitation,
        RuleExplanationDTO,
        SemanticMapProjectionDTO,
    )

    citation = RedactedCitation(label="场景依据", page=2, scene="车站")
    assert citation.model_dump() == {
        "label": "场景依据",
        "page": 2,
        "scene": "车站",
        "verified": True,
    }
    with pytest.raises(ValidationError):
        RedactedCitation(label="泄露", source_ref="secret.pdf#page=2")

    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="检查窗户",
        understanding_summary="你想检查窗户。",
        risk="low",
        citations=[citation],
        analysis_source="local_fallback",
    )
    assert draft.citations[0].label == "场景依据"

    rule = RuleExplanationDTO(rule_set_version="coc7-v1", citations=[citation])
    assert rule.citations[0].page == 2

    narration = NarrationResultDTO(
        action_id="a1",
        context_version=1,
        director_plan_digest="digest",
        narrative_text="雾变浓了。",
        environment_changes=["灯暗了"],
        interactable_objects=["窗户"],
        open_question="你怎么做？",
        fact_refs={
            "narrative_text": ["fact-1"],
            "environment_changes": ["fact-2"],
            "interactable_objects": ["fact-3"],
            "open_question": ["fact-4"],
        },
        redacted_citations=[citation],
        style_pack_version="v1",
        provider_source="local_fallback",
    )
    assert narration.redacted_citations[0].scene == "车站"

    stage = AiStageProgress(stage="validating_rules", status="active")
    assert stage.stage == "validating_rules"

    projection = SemanticMapProjectionDTO(
        room_id="room-1",
        known_locations=[{"nodeId": "station", "label": "车站"}],
        known_connections=[],
        party_position={"nodeId": "station", "label": "车站"},
        fog_of_war=[],
    )
    assert projection.model_dump(by_alias=True)["knownLocations"][0]["label"] == "车站"

    snapshot = HostDirectorSnapshotDTO(
        current_scene="车站",
        confirmed_facts=["灯亮着"],
        pending_triggers=[],
        ai_evidence=[citation],
        stage="completed",
        risks=[],
        exception_queue=[],
    )
    assert snapshot.ai_evidence[0].label == "场景依据"


def test_natural_language_progression_resolves_the_only_visible_solo_choice(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        """
        INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data)
        VALUES ('solo-natural-character', %s, '玩家', 'solo-natural-token', %s)
        """,
        (room_id, json.dumps({})),
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = None
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "solo-natural-token"},
            json={"declared_intent": "车来了，我提起行李上车，继续出发。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["intent_type"] == "move"
    assert draft["params"] == {"fromNodeId": "1", "targetNodeId": "2"}
    assert draft["movement_target"] == "下一场景"
    assert "条目 2" not in response.text
    assert draft["confirmation_requirements"] == ["movement", "state_change"]


@pytest.mark.asyncio
async def test_solo_bear_scene_bootstraps_an_active_encounter_without_host(test_db):
    from src.server.encounter_persistence import get_encounter, get_participants

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-combat-character', %s, '玩家', 'solo-combat-token', %s)",
        (
            room_id,
            json.dumps({
                "name": "调查员",
                "hp": 10,
                "max_hp": 10,
                "san": 60,
                "max_san": 60,
                "attributes": {"dex": 65},
                "skills": {"格斗（斗殴）": 40},
            }, ensure_ascii=False),
        ),
    )
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    runtime.transition(room_id, from_node_id="2", target_node_id="3")
    intent = PlayerIntent(
        intent_type="combat_action",
        declared_intent="我用小刀攻击黑熊",
        params={},
    )
    error = await ResolutionPipeline(test_db)._validate_encounter_action(
        {"room_id": room_id, "character_id": "solo-combat-character"},
        intent,
    )

    assert error is None
    encounter = get_encounter(test_db, intent.params["encounterId"])
    assert encounter["status"] == "active"
    participants = get_participants(test_db, encounter["encounter_id"])
    enemy = next(item for item in participants if item["side"] == "enemy")
    assert enemy["display_name"] == "黑熊"
    assert enemy["hp"] == 20
    assert intent.params["targetId"] == enemy["character_id"]
    assert intent.params["actionKind"] == "attack"


@pytest.mark.asyncio
async def test_encounter_damage_mutation_updates_the_target_not_the_actor(test_db):
    from src.server.encounter_persistence import (
        add_participant,
        create_encounter,
        get_participant,
    )

    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('solo-damage-character', %s, '玩家', 'solo-damage-token', %s)",
        (room_id, json.dumps({"hp": 10, "max_hp": 10})),
    )
    create_encounter(test_db, "solo-damage-encounter", room_id, status="active")
    add_participant(
        test_db, "solo-damage-encounter", "solo-damage-character",
        side="player", hp=10, hp_max=10,
    )
    add_participant(
        test_db, "solo-damage-encounter", "npc:bear",
        side="enemy", hp=20, hp_max=20, display_name="黑熊",
    )
    resolution = ResolutionResult(
        actionId="combat-action",
        roomId=room_id,
        characterId="solo-damage-character",
        mechanic="combat_attack",
        isSuccess=True,
        mutations=[{
            "op": "replace",
            "path": "/encounter/solo-damage-encounter/participants/npc:bear/hp_delta",
            "value": -4,
        }],
    )
    await ResolutionPipeline(test_db)._apply_encounter_result(
        {"room_id": room_id, "character_id": "solo-damage-character"},
        PlayerIntent(
            intent_type="combat_action",
            params={"encounterId": "solo-damage-encounter"},
        ),
        resolution,
    )

    assert get_participant(test_db, "solo-damage-encounter", "npc:bear")["hp"] == 16
    assert get_participant(
        test_db, "solo-damage-encounter", "solo-damage-character"
    )["hp"] == 10


def test_solo_ending_transition_completes_the_room(test_db):
    from src.server.encounter_persistence import create_encounter

    room_id, _ = _setup_solo_room(test_db)
    create_encounter(test_db, "ending-encounter", room_id, status="active")
    runtime = SoloAdventureRuntime(test_db)
    runtime.transition(room_id, from_node_id="1", target_node_id="2")
    runtime.transition(room_id, from_node_id="2", target_node_id="3")

    result = runtime.transition(room_id, from_node_id="3", target_node_id="4")

    room = test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    encounter = test_db.execute(
        "SELECT status FROM encounters WHERE encounter_id = 'ending-encounter'"
    ).fetchone()
    assert result["is_ending"] is True
    assert room["status"] == "completed"
    assert encounter["status"] == "resolved"


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
