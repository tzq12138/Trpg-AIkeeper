import json
import uuid

import pytest

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.state_service import StateService
from src.server.models import MechanicCompileResult
from tests.server.conftest import (
    create_account,
    login,
    setup_auth_test_data,
)


class _GoldenFlowCompiler:
    async def compile(self, intent, _scenario, _character):
        return MechanicCompileResult(
            triggeredMechanic="move" if intent.intent_type == "move" else "dialogue"
        )


class _FailingNarratorGateway:
    async def narrate_action(self, *_args, **_kwargs):
        raise RuntimeError("simulated narrator outage")


class _RecordingDispatcher:
    def __init__(self):
        self.events = []

    async def emit(
        self,
        room_id,
        event_type,
        audience,
        payload,
        character_id=None,
    ):
        self.events.append(
            (room_id, event_type, audience, payload, character_id)
        )


def _install_glass_rain(client, test_db):
    setup_auth_test_data(test_db)
    create_account(test_db, "acc-player-2", "testplayer2", "player")
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, license_type, created_by, status) "
        "VALUES ('coc7-base', 'CoC7', 'coc7', 'coc7', 'open', 'test', 'published')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions "
        "(rule_set_version_id, rule_set_id, version_number, status, created_by) "
        "VALUES ('coc7-base-v1', 'coc7-base', 1, 'published', 'test')"
    )
    test_db.commit()
    tokens = {
        "admin": login(client, "admin"),
        "player_1": login(client, "testplayer"),
        "player_2": login(client, "testplayer2"),
    }
    installed = client.post(
        "/api/admin/golden-modules/golden-team-glass-rain/install",
        headers={"Authorization": f"Bearer {tokens['admin']}"},
    )
    assert installed.status_code == 201, installed.text
    payload = installed.json()
    assert payload["runtimePackage"]["gate_status"] == "ready"
    templates = test_db.execute(
        "SELECT template_id FROM character_templates "
        "WHERE scenario_id = %s ORDER BY template_id",
        (payload["scenarioId"],),
    ).fetchall()
    return payload, tokens, [row["template_id"] for row in templates]


def _create_started_room(client, test_db, installed, tokens, templates):
    created = client.post(
        "/api/rooms",
        headers={"Authorization": f"Bearer {tokens['admin']}"},
        json={"scenario_id": installed["scenarioId"]},
    )
    assert created.status_code == 200, created.text
    room = created.json()
    joined = []
    for ordinal, player_key in enumerate(("player_1", "player_2")):
        response = client.post(
            f"/api/player/rooms/{room['room_id']}/join-with-character",
            headers={"Authorization": f"Bearer {tokens[player_key]}"},
            data={
                "player_name": f"Player {ordinal + 1}",
                "template_id": templates[ordinal],
            },
        )
        assert response.status_code == 200, response.text
        joined.append(response.json())
    state_service = StateService(test_db)
    for character in joined:
        state_service.initialize_character_state(
            character["character_id"],
            room["room_id"],
        )
    started = client.post(
        f"/api/rooms/{room['room_id']}/start",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "force_start": True,
            "confirm": True,
            "reason": "golden-flow integration test",
        },
    )
    assert started.status_code == 200, started.text
    return room, joined, state_service


def _runtime_package(test_db, room_id):
    row = test_db.execute(
        "SELECT packages.runtime_package "
        "FROM rooms "
        "JOIN runtime_package_versions AS packages "
        "ON packages.runtime_package_version_id = rooms.runtime_package_version_id "
        "WHERE rooms.room_id = %s",
        (room_id,),
    ).fetchone()
    return row["runtime_package"]


def _insert_v2_action(
    test_db,
    *,
    room_id,
    character_id,
    intent_type,
    declared_intent,
    from_scene=None,
    target_scene=None,
):
    action_id = f"glass-{uuid.uuid4().hex[:12]}"
    room = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    params = {
        "director_plan": {
            "context_version": int(room["state_version"]),
            "preconditions": [],
            "permissions": [],
            "state_patch": [],
            "state_patch_authority": "advisory_only",
        }
    }
    if intent_type == "move":
        package = _runtime_package(test_db, room_id)
        edge = next(
            edge
            for edge in package["semantic_progression_rules"]["edges"]
            if edge.get("from_scene_id") == from_scene
            and edge.get("to_scene_id") == target_scene
        )
        params.update(
            {
                "fromNodeId": from_scene,
                "targetNodeId": target_scene,
                "analysis": {
                    "semantic_progression": {
                        "validated": True,
                        "fromNodeId": from_scene,
                        "targetNodeId": target_scene,
                        "ruleCitation": edge["citation"],
                    }
                },
            }
        )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, draft_id, intent_type, "
        "declared_intent, params, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued')",
        (
            action_id,
            room_id,
            character_id,
            f"draft-{action_id}",
            intent_type,
            declared_intent,
            json.dumps(params, ensure_ascii=False),
        ),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES (%s, 'queued', '{}')",
        (action_id,),
    )
    test_db.commit()
    return action_id


async def _resolve(
    test_db,
    state_service,
    dispatcher,
    *,
    room_id,
    character_id,
    intent_type,
    declared_intent,
    from_scene=None,
    target_scene=None,
):
    action_id = _insert_v2_action(
        test_db,
        room_id=room_id,
        character_id=character_id,
        intent_type=intent_type,
        declared_intent=declared_intent,
        from_scene=from_scene,
        target_scene=target_scene,
    )
    result = await ResolutionPipeline(
        conn=test_db,
        compiler=_GoldenFlowCompiler(),
        gateway=_FailingNarratorGateway(),
        dispatcher=dispatcher,
        state_service=state_service,
        host_connection_checker=lambda _room_id: False,
    ).resolve_action(action_id)
    return action_id, result


@pytest.mark.asyncio
async def test_glass_rain_v2_ai_only_success_mixed_and_safe_abort_flows(
    client,
    test_db,
    monkeypatch,
):
    installed, tokens, templates = _install_glass_rain(client, test_db)
    runtime = installed["runtimePackage"]["runtime_package"]
    assert runtime["runtime_policy"]["state_scope"] == "room_run"
    assert runtime["runtime_policy"]["fresh_state_on_new_room"] is True
    assert {
        ending["type"] for ending in runtime["ending_conditions"]
    } >= {"victory", "mixed", "safe_abort"}

    monkeypatch.setattr(
        "src.server.rules.coc_handlers.secure_randint",
        lambda low, high, test_rng=None: high,
    )

    success_room, success_players, success_state = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    success_actor = success_players[0]
    dispatcher = _RecordingDispatcher()
    start_san = test_db.execute(
        "SELECT san FROM character_runtime_state "
        "WHERE room_id = %s AND character_id = %s",
        (success_room["room_id"], success_actor["character_id"]),
    ).fetchone()["san"]

    _, moved = await _resolve(
        test_db,
        success_state,
        dispatcher,
        room_id=success_room["room_id"],
        character_id=success_actor["character_id"],
        intent_type="move",
        declared_intent="前往兰花展厅",
        from_scene="glass-gate",
        target_scene="orchid-hall",
    )
    assert moved["status"] == "completed"

    pause = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": success_actor["player_token"]},
        json={
            "actionId": "glass-success-pause",
            "rawText": "暂停一下",
            "inputMode": "safety",
        },
    )
    assert pause.status_code == 201
    paused_action_id = _insert_v2_action(
        test_db,
        room_id=success_room["room_id"],
        character_id=success_actor["character_id"],
        intent_type="move",
        declared_intent="前往地下蓄水池",
        from_scene="orchid-hall",
        target_scene="cistern",
    )
    paused_result = await ResolutionPipeline(
        conn=test_db,
        compiler=_GoldenFlowCompiler(),
        dispatcher=dispatcher,
        state_service=success_state,
        host_connection_checker=lambda _room_id: False,
    ).resolve_action(paused_action_id)
    assert paused_result == {
        "status": "safety_paused",
        "action_id": paused_action_id,
    }
    resumed = client.post(
        "/api/player/safety-pauses/glass-success-pause/resume",
        headers={"X-Room-Token": success_actor["player_token"]},
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"

    cistern_result = await ResolutionPipeline(
        conn=test_db,
        compiler=_GoldenFlowCompiler(),
        gateway=_FailingNarratorGateway(),
        dispatcher=dispatcher,
        state_service=success_state,
        host_connection_checker=lambda _room_id: False,
    ).resolve_action(paused_action_id)
    assert cistern_result["status"] == "completed"
    sanity = test_db.execute(
        "SELECT san, temp_modifiers FROM character_runtime_state "
        "WHERE room_id = %s AND character_id = %s",
        (success_room["room_id"], success_actor["character_id"]),
    ).fetchone()
    assert sanity["san"] == start_san - 4
    assert sanity["temp_modifiers"]["coc7_sanity"]["day_key"] == "glass-rain-night-1"

    _, success_ending = await _resolve(
        test_db,
        success_state,
        dispatcher,
        room_id=success_room["room_id"],
        character_id=success_actor["character_id"],
        intent_type="dialogue",
        declared_intent="收听维护无线电并确认停机顺序",
    )
    assert success_ending["status"] == "completed"
    assert success_ending["result"]["metadata"]["verified_ending"][
        "ending_type"
    ] == "victory"
    success_archive = test_db.execute(
        "SELECT ending_type, character_arcs FROM campaign_archives "
        "WHERE room_id = %s",
        (success_room["room_id"],),
    ).fetchone()
    assert success_archive["ending_type"] == "victory"
    actor_arc = next(
        arc
        for arc in success_archive["character_arcs"]
        if arc["character_id"] == success_actor["character_id"]
    )
    assert actor_arc["final_san"] == start_san - 4

    mixed_room, mixed_players, mixed_state = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    mixed_actor = mixed_players[0]
    fresh_san = test_db.execute(
        "SELECT san, temp_modifiers FROM character_runtime_state "
        "WHERE room_id = %s AND character_id = %s",
        (mixed_room["room_id"], mixed_actor["character_id"]),
    ).fetchone()
    assert fresh_san["san"] == start_san
    assert fresh_san["temp_modifiers"] == {}

    _, control_move = await _resolve(
        test_db,
        mixed_state,
        dispatcher,
        room_id=mixed_room["room_id"],
        character_id=mixed_actor["character_id"],
        intent_type="move",
        declared_intent="前往灌溉控制室",
        from_scene="glass-gate",
        target_scene="control-room",
    )
    assert control_move["status"] == "completed"
    _, clue_result = await _resolve(
        test_db,
        mixed_state,
        dispatcher,
        room_id=mixed_room["room_id"],
        character_id=mixed_actor["character_id"],
        intent_type="dialogue",
        declared_intent="检查重启日志",
    )
    assert clue_result["status"] == "completed"
    _, mixed_ending = await _resolve(
        test_db,
        mixed_state,
        dispatcher,
        room_id=mixed_room["room_id"],
        character_id=mixed_actor["character_id"],
        intent_type="move",
        declared_intent="前往地下蓄水池",
        from_scene="control-room",
        target_scene="cistern",
    )
    assert mixed_ending["status"] == "completed"
    assert mixed_ending["result"]["metadata"]["verified_ending"][
        "ending_type"
    ] == "mixed"

    abort_room, abort_players, _ = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    abort_actor = abort_players[0]
    abort_pause = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": abort_actor["player_token"]},
        json={
            "actionId": "glass-abort-pause",
            "rawText": "我希望安全结束本次游戏",
            "inputMode": "safety",
        },
    )
    assert abort_pause.status_code == 201
    ended = client.post(
        f"/api/host/{abort_room['room_id']}/safety/end-session",
        headers={"X-Owner-Token": abort_room["owner_token"]},
    )
    assert ended.status_code == 200
    assert ended.json()["endingType"] == "safe_abort"
    abort_archive = test_db.execute(
        "SELECT ending_type FROM campaign_archives WHERE room_id = %s",
        (abort_room["room_id"],),
    ).fetchone()
    assert abort_archive["ending_type"] == "safe_abort"

    awaiting_host = test_db.execute(
        "SELECT COUNT(*) AS count FROM action_status_events "
        "WHERE status = 'awaiting_host_exception'"
    ).fetchone()
    assert awaiting_host["count"] == 0
