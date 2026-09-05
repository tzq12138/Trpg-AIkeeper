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
    create_account(test_db, "acc-player-3", "testplayer3", "player")
    create_account(test_db, "acc-player-4", "testplayer4", "player")
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, is_base, license_type, created_by, status) "
        "VALUES ('coc7-base', 'CoC7', 'coc7', 'coc7', TRUE, 'open', 'test', 'published')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions "
        "(rule_set_version_id, rule_set_id, version_number, status, runtime_eligible, created_by) "
        "VALUES ('coc7-base-v1', 'coc7-base', 1, 'published', TRUE, 'test')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) "
        "VALUES ('coc7-base-v1', 'ready')"
    )
    test_db.commit()
    tokens = {
        "admin": login(client, "admin"),
        "player_1": login(client, "testplayer"),
        "player_2": login(client, "testplayer2"),
        "player_3": login(client, "testplayer3"),
        "player_4": login(client, "testplayer4"),
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
    for ordinal, player_key in enumerate(
        ("player_1", "player_2", "player_3", "player_4")
    ):
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
        headers = {"X-Room-Token": character["player_token"]}
        for step in (
            "character_rules",
            "safety",
            "ai_host",
            "private_data",
            "connection",
        ):
            confirmation = {"confirmed": True}
            if step == "safety":
                confirmation["contract_hash"] = room["risk_contract_hash"]
            confirmed = client.post(
                f"/api/player/session-zero/{step}",
                headers=headers,
                json=confirmation,
            )
            assert confirmed.status_code == 200, confirmed.text
        ready = client.post(
            "/api/player/intent",
            headers=headers,
            json={
                "action_id": f"glass-ready-{character['character_id']}",
                "intent_type": "ready_toggle",
                "declared_intent": "准备就绪",
            },
        )
        assert ready.status_code == 202, ready.text
    started = client.post(
        f"/api/rooms/{room['room_id']}/start",
        headers={"X-Owner-Token": room["owner_token"]},
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
    extra_params=None,
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
    params.update(extra_params or {})
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


def test_ai_only_owner_end_is_an_aborted_termination_not_an_authored_ending(
    client,
    test_db,
    monkeypatch,
):
    """The room owner may terminate an AI-only run, but may not author its ending."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, _players, _state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )

    response = client.post(
        f"/api/rooms/{room['room_id']}/end",
        headers={"X-Owner-Token": room["owner_token"]},
        json={
            "ending_type": "victory",
            "ending_name": "房主指定的胜利",
            "summary": "不应由房主写入的结局文本",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ending_type"] == "aborted"
    assert payload["ending_status"] == "aborted"
    assert payload["ending_id"] is None
    assert payload["termination_reason"] == "owner_terminated"
    room_row = test_db.execute(
        "SELECT status, runtime_status, campaign_lifecycle_status, ending_status, "
        "termination_reason, ending_id FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["status"] == "completed"
    assert room_row["runtime_status"] == "ended"
    assert room_row["campaign_lifecycle_status"] == "finalized"
    assert room_row["ending_status"] == "aborted"
    assert room_row["termination_reason"] == "owner_terminated"
    assert room_row["ending_id"] is None
    archive = test_db.execute(
        "SELECT ending_type, summary FROM campaign_archives WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert archive["ending_type"] == "aborted"
    assert "房主指定的胜利" not in archive["summary"]


def test_ai_only_admin_state_patches_are_rejected_before_mutation(
    client,
    test_db,
    monkeypatch,
):
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, _state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    admin_headers = {"Authorization": f"Bearer {tokens['admin']}"}
    character_id = players[0]["character_id"]
    before = test_db.execute(
        "SELECT rooms.status AS room_status, xlsx_data FROM rooms LEFT JOIN characters "
        "ON characters.room_id = rooms.room_id "
        "WHERE rooms.room_id = %s AND characters.character_id = %s",
        (room["room_id"], character_id),
    ).fetchone()

    room_response = client.patch(
        f"/api/admin/rooms/{room['room_id']}",
        headers=admin_headers,
        json={"status": "completed"},
    )
    assert room_response.status_code == 409, room_response.text
    assert room_response.json()["detail"]["code"] == "AI_ONLY_ADMIN_STATE_PATCH_FORBIDDEN"
    character_response = client.patch(
        f"/api/admin/characters/{character_id}",
        headers=admin_headers,
        json={"hp": 1, "is_ready": False},
    )
    assert character_response.status_code == 409, character_response.text
    assert character_response.json()["detail"]["code"] == "AI_ONLY_ADMIN_STATE_PATCH_FORBIDDEN"
    after = test_db.execute(
        "SELECT rooms.status AS room_status, xlsx_data FROM rooms LEFT JOIN characters "
        "ON characters.room_id = rooms.room_id "
        "WHERE rooms.room_id = %s AND characters.character_id = %s",
        (room["room_id"], character_id),
    ).fetchone()
    assert after["room_status"] == before["room_status"] == "active"
    assert after["xlsx_data"] == before["xlsx_data"]


def test_ai_only_force_start_cannot_bypass_session_zero_or_readiness(
    client,
    test_db,
    monkeypatch,
):
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, _templates = _install_glass_rain(client, test_db)
    created = client.post(
        "/api/rooms",
        headers={"Authorization": f"Bearer {tokens['admin']}"},
        json={"scenario_id": installed["scenarioId"]},
    )
    assert created.status_code == 200, created.text
    room = created.json()

    response = client.post(
        f"/api/rooms/{room['room_id']}/start",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"force_start": True, "reason": "跳过准备", "confirm": True},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "AI_ONLY_SESSION_ZERO_INCOMPLETE"
    room_row = test_db.execute(
        "SELECT status, runtime_status FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["status"] == "lobby"
    assert room_row["runtime_status"] == "lobby"


def test_ai_only_session_zero_freezes_mode_and_room_version_bundle(
    client,
    test_db,
    monkeypatch,
):
    """A started AI-only room must keep its chosen mode and complete version set."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, _players, _state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )

    mode_change = client.patch(
        f"/api/rooms/{room['room_id']}/session-mode",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"session_mode": "assisted"},
    )

    assert mode_change.status_code == 409, mode_change.text
    assert mode_change.json()["detail"]["code"] == "session_mode_frozen"
    room_row = test_db.execute(
        "SELECT session_mode, session_mode_frozen_at, session_mode_frozen_reason, "
        "version_bundle, version_bundle_hash, version_bundle_locked_at "
        "FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["session_mode"] == "ai_only"
    assert room_row["session_mode_frozen_at"] is not None
    assert room_row["session_mode_frozen_reason"] == "session_zero_completed"
    assert room_row["version_bundle_locked_at"] is not None
    assert len(room_row["version_bundle_hash"]) == 64
    bundle = room_row["version_bundle"]
    if isinstance(bundle, str):
        bundle = json.loads(bundle)
    assert set(bundle) >= {
        "runtime_package_version_id",
        "rule_version_id",
        "prompt_bundle_version",
        "scenario_package_hash",
        "ai_policy_version",
    }
    assert bundle["runtime_package_version_id"] == room["runtime_package_version_id"]
    assert bundle["rule_version_id"] == "coc7-base-v1"
    assert bundle["scenario_package_hash"]
    assert bundle["prompt_bundle_version"]
    assert bundle["ai_policy_version"]
    event = test_db.execute(
        "SELECT payload FROM events WHERE room_id = %s "
        "AND event_type = 's2c_session_mode_frozen' ORDER BY sequence DESC LIMIT 1",
        (room["room_id"],),
    ).fetchone()
    assert event is not None
    payload = event["payload"] if isinstance(event["payload"], dict) else json.loads(event["payload"])
    assert payload["reason"] == "session_zero_completed"


def test_ai_only_frozen_contract_blocks_scenario_and_status_rewrites(
    client,
    test_db,
    monkeypatch,
):
    """A paused/active AI-only run cannot be rebound or state-patched generically."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, _players, _state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    headers = {"X-Owner-Token": room["owner_token"]}

    generic_scenario = client.patch(
        f"/api/rooms/{room['room_id']}",
        headers=headers,
        json={"scenario_id": installed["scenarioId"]},
    )
    dedicated_scenario = client.patch(
        f"/api/rooms/{room['room_id']}/scenario",
        headers=headers,
        json={"scenario_id": installed["scenarioId"]},
    )
    status_patch = client.patch(
        f"/api/rooms/{room['room_id']}",
        headers=headers,
        json={"status": "paused"},
    )

    for response in (generic_scenario, dedicated_scenario):
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "runtime_contract_frozen"
    assert status_patch.status_code == 409, status_patch.text
    assert status_patch.json()["detail"]["code"] == "ai_only_runtime_state_patch_forbidden"
    room_row = test_db.execute(
        "SELECT status, scenario_id, runtime_package_version_id FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["status"] == "active"
    assert room_row["scenario_id"] == installed["scenarioId"]
    assert room_row["runtime_package_version_id"] == room["runtime_package_version_id"]


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
    extra_params=None,
):
    action_id = _insert_v2_action(
        test_db,
        room_id=room_id,
        character_id=character_id,
        intent_type=intent_type,
        declared_intent=declared_intent,
        from_scene=from_scene,
        target_scene=target_scene,
        extra_params=extra_params,
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
async def test_ai_only_resolution_trace_carries_the_locked_room_version_bundle(
    client,
    test_db,
    monkeypatch,
):
    """Every authoritative action remains attributable to its frozen versions."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )

    action_id, result = await _resolve(
        test_db,
        state_service,
        _RecordingDispatcher(),
        room_id=room["room_id"],
        character_id=players[0]["character_id"],
        intent_type="dialogue",
        declared_intent="我向门卫询问展厅关闭的原因。",
    )

    assert result["status"] == "completed"
    row = test_db.execute(
        "SELECT trace FROM resolution_traces WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    trace = row["trace"] if isinstance(row["trace"], dict) else json.loads(row["trace"])
    room_row = test_db.execute(
        "SELECT version_bundle, version_bundle_hash FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    bundle = room_row["version_bundle"]
    if isinstance(bundle, str):
        bundle = json.loads(bundle)
    assert trace["version_bundle"] == bundle
    assert trace["version_bundle_hash"] == room_row["version_bundle_hash"]


def test_ai_only_soft_pause_is_durable_and_blocks_new_game_actions(
    client,
    test_db,
    monkeypatch,
):
    """Owner soft pause stops new inputs at a durable between-action boundary."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, _state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )

    paused = client.post(
        f"/api/host/{room['room_id']}/pause",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"mode": "soft_pause", "reason": "房主需要短暂休息"},
    )

    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused_by_owner"
    room_row = test_db.execute(
        "SELECT runtime_status, pause_mode, pause_cursor, pause_reason "
        "FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["runtime_status"] == "paused_by_owner"
    assert room_row["pause_mode"] == "soft_pause"
    assert room_row["pause_cursor"] == "between_actions"
    assert room_row["pause_reason"] == "房主需要短暂休息"
    blocked = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": players[0]["player_token"]},
        json={
            "actionId": "soft-pause-blocked",
            "rawText": "我继续检查展厅入口。",
            "inputMode": "action",
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "room_paused_by_owner"
    resumed = client.post(
        f"/api/host/{room['room_id']}/resume",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"reason": "继续游戏"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "running"
    accepted = client.post(
        "/api/player/action-submissions",
        headers={"X-Room-Token": players[0]["player_token"]},
        json={
            "actionId": "soft-pause-resumed",
            "rawText": "我继续检查展厅入口。",
            "inputMode": "action",
        },
    )
    assert accepted.status_code == 201, accepted.text


@pytest.mark.asyncio
async def test_ai_only_pause_leaves_preexisting_queued_action_unresolved(
    client,
    test_db,
    monkeypatch,
):
    """A queued action cannot cross the pre-roll boundary while an owner pause holds."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    action_id = _insert_v2_action(
        test_db,
        room_id=room["room_id"],
        character_id=players[0]["character_id"],
        intent_type="dialogue",
        declared_intent="我向门卫询问展厅关闭的原因。",
    )
    paused = client.post(
        f"/api/host/{room['room_id']}/pause",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"mode": "emergency_pause", "reason": "立刻停止"},
    )
    assert paused.status_code == 200, paused.text

    result = await ResolutionPipeline(
        conn=test_db,
        compiler=_GoldenFlowCompiler(),
        gateway=_FailingNarratorGateway(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
        host_connection_checker=lambda _room_id: False,
    ).resolve_action(action_id)

    assert result["status"] == "paused_by_owner"
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (action_id,),
    ).fetchone()
    assert action["status"] == "queued"


def test_ai_only_resume_reschedules_queued_actions(
    client,
    test_db,
    monkeypatch,
):
    """Resuming an owner pause hands preserved queued work back to automatic scheduling."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, _state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    action_id = _insert_v2_action(
        test_db,
        room_id=room["room_id"],
        character_id=players[0]["character_id"],
        intent_type="dialogue",
        declared_intent="我等待恢复后继续调查。",
    )
    paused = client.post(
        f"/api/host/{room['room_id']}/pause",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"mode": "soft_pause", "reason": "短暂暂停"},
    )
    assert paused.status_code == 200, paused.text

    scheduled: list[tuple[str, list[str]]] = []

    async def fake_resume_scheduler(_request, scheduled_room_id):
        scheduled.append((scheduled_room_id, [action_id]))
        return [action_id]

    monkeypatch.setattr(
        "src.server.host.router_host._resume_queued_actions",
        fake_resume_scheduler,
        raising=False,
    )
    resumed = client.post(
        f"/api/host/{room['room_id']}/resume",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"reason": "继续调查"},
    )

    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["resumed_action_ids"] == [action_id]
    assert scheduled == [(room["room_id"], [action_id])]


@pytest.mark.asyncio
async def test_ai_only_emergency_pause_requeues_an_action_before_any_roll(
    client,
    test_db,
    monkeypatch,
):
    """A pause requested while resolving stops at pre-roll and resumes safely."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    action_id = _insert_v2_action(
        test_db,
        room_id=room["room_id"],
        character_id=players[0]["character_id"],
        intent_type="dialogue",
        declared_intent="我询问门卫昨晚发生了什么。",
    )

    class _PauseBeforeRuleExecutionCompiler:
        async def compile(self, intent, scenario, character):
            from src.server.engine.room_pause import request_owner_pause

            with test_db.transaction() as tx:
                request_owner_pause(
                    tx,
                    room["room_id"],
                    mode="emergency_pause",
                    actor_id="acc-admin",
                    reason="演练紧急暂停",
                )
            return MechanicCompileResult(triggeredMechanic="dialogue")

    paused = await ResolutionPipeline(
        conn=test_db,
        compiler=_PauseBeforeRuleExecutionCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
        host_connection_checker=lambda _room_id: False,
    ).resolve_action(action_id)

    assert paused == {"status": "paused_by_owner", "action_id": action_id}
    action = test_db.execute(
        "SELECT status, receipt FROM actions WHERE action_id = %s", (action_id,)
    ).fetchone()
    assert action["status"] == "queued"
    assert action["receipt"] is None
    room_row = test_db.execute(
        "SELECT runtime_status, pause_mode, pause_cursor FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert dict(room_row) == {
        "runtime_status": "paused_by_owner",
        "pause_mode": "emergency_pause",
        "pause_cursor": "pre_roll",
    }

    resumed = client.post(
        f"/api/host/{room['room_id']}/resume",
        headers={"X-Owner-Token": room["owner_token"]},
        json={"reason": "继续演练"},
    )
    assert resumed.status_code == 200, resumed.text
    completed = await ResolutionPipeline(
        conn=test_db,
        compiler=_GoldenFlowCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=state_service,
        host_connection_checker=lambda _room_id: False,
    ).resolve_action(action_id)
    assert completed["status"] == "completed"


@pytest.mark.asyncio
async def test_ai_only_pause_requested_after_resolution_settles_post_projection(
    client,
    test_db,
    monkeypatch,
):
    """A late pause preserves this completed action then records its boundary."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    action_id = _insert_v2_action(
        test_db,
        room_id=room["room_id"],
        character_id=players[0]["character_id"],
        intent_type="move",
        declared_intent="前往兰花展厅。",
        from_scene="glass-gate",
        target_scene="orchid-hall",
    )
    from src.server.engine.room_pause import request_owner_pause

    class _PauseAfterStateService(StateService):
        def apply_change(self, *args, transaction=None, **kwargs):
            result = super().apply_change(*args, transaction=transaction, **kwargs)
            request_owner_pause(
                transaction or self.conn,
                room["room_id"],
                mode="soft_pause",
                actor_id="acc-admin",
                reason="在状态提交后暂停",
            )
            return result

    pipeline = ResolutionPipeline(
        conn=test_db,
        compiler=_GoldenFlowCompiler(),
        dispatcher=_RecordingDispatcher(),
        state_service=_PauseAfterStateService(test_db),
        host_connection_checker=lambda _room_id: False,
    )
    result = await pipeline.resolve_action(action_id)

    assert result["status"] == "completed"
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s", (action_id,)
    ).fetchone()
    assert action["status"] == "completed"
    room_row = test_db.execute(
        "SELECT runtime_status, pause_mode, pause_cursor FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert dict(room_row) == {
        "runtime_status": "paused_by_owner",
        "pause_mode": "soft_pause",
        "pause_cursor": "post_projection",
    }


def test_ai_only_system_recovery_uses_a_generated_verified_proposal(
    client,
    test_db,
    monkeypatch,
):
    """Owner can confirm a system proposal, never select a checkpoint to restore."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, _state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    from src.server.events.event_log import EventLog

    checkpoint = EventLog(test_db).create_checkpoint(
        room["room_id"],
        checkpoint_id="system-recovery-source",
        reason="known-good-state",
    )
    before = test_db.execute(
        "SELECT hp, san FROM character_runtime_state "
        "WHERE room_id = %s AND character_id = %s",
        (room["room_id"], players[0]["character_id"]),
    ).fetchone()
    test_db.execute(
        "UPDATE rooms SET runtime_status = 'paused_system', "
        "integrity_status = 'read_only_recovery', "
        "integrity_reason = 'checkpoint_hash_mismatch' WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()
    headers = {"X-Owner-Token": room["owner_token"]}

    proposed = client.post(
        f"/api/rooms/{room['room_id']}/recovery/proposals",
        headers=headers,
    )

    assert proposed.status_code == 201, proposed.text
    proposal = proposed.json()["proposal"]
    assert proposal["source_checkpoint_id"] == checkpoint.checkpoint_id
    assert proposal["source_state_version"] == proposal["target_state_version"]
    assert set(proposal) >= {
        "proposal_id",
        "room_id",
        "transactions_to_replay",
        "roll_receipts_to_reuse",
        "reveal_transactions_to_replay",
        "projection_events_to_replay",
        "integrity_checks",
        "proposal_hash",
        "expires_at",
    }
    dry_run = client.post(
        f"/api/rooms/{room['room_id']}/recovery/proposals/{proposal['proposal_id']}/dry-run",
        headers=headers,
    )
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["status"] == "dry_run_verified"
    executed = client.post(
        f"/api/rooms/{room['room_id']}/recovery/proposals/{proposal['proposal_id']}/execute",
        headers=headers,
        json={"confirm": True},
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "running"
    after = test_db.execute(
        "SELECT hp, san FROM character_runtime_state "
        "WHERE room_id = %s AND character_id = %s",
        (room["room_id"], players[0]["character_id"]),
    ).fetchone()
    assert dict(after) == dict(before)
    restored = test_db.execute(
        "SELECT runtime_status, integrity_status FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert restored["runtime_status"] == "running"
    assert restored["integrity_status"] == "healthy"


def test_ai_only_system_recovery_refuses_unprovable_intervening_state(
    client,
    test_db,
    monkeypatch,
):
    """A checkpoint is never an Owner-selected rollback when replay is unprovable."""
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, _players, _state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    from src.server.events.event_log import EventLog

    checkpoint = EventLog(test_db).create_checkpoint(
        room["room_id"],
        checkpoint_id="system-recovery-unprovable-source",
        reason="known-good-state",
    )
    test_db.execute(
        "UPDATE rooms SET state_version = state_version + 1, "
        "runtime_status = 'paused_system', integrity_status = 'read_only_recovery' "
        "WHERE room_id = %s",
        (room["room_id"],),
    )
    test_db.commit()

    response = client.post(
        f"/api/rooms/{room['room_id']}/recovery/proposals",
        headers={"X-Owner-Token": room["owner_token"]},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "no_safe_recovery"
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM runtime_recovery_proposals "
        "WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()["count"] == 0
    room_row = test_db.execute(
        "SELECT runtime_status, state_version FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    assert room_row["runtime_status"] == "paused_system"
    assert room_row["state_version"] == checkpoint.state_version + 1


@pytest.mark.asyncio
async def test_glass_rain_v2_ai_only_success_mixed_and_safe_abort_flows(
    client,
    test_db,
    monkeypatch,
):
    # This flow test uses a compact CoC7 fixture; the authoritative 380-page
    # source is covered by the lifecycle tests, so pin the fixture explicitly.
    monkeypatch.setattr(
        "src.server.rule_source_lifecycle.current_authoritative_base_version",
        lambda _conn: "coc7-base-v1",
    )
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

    def reject_post_ending_prepared_write(*_args, **_kwargs):
        raise AssertionError("结局提交后不应再处理预备反应状态")

    monkeypatch.setattr(
        "src.server.engine.prepared_rule_actions.complete_triggered_prepared_reaction",
        reject_post_ending_prepared_write,
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
    assert cistern_result["status"] == "completed", cistern_result
    sanity = test_db.execute(
        "SELECT san, temp_modifiers FROM character_runtime_state "
        "WHERE room_id = %s AND character_id = %s",
        (success_room["room_id"], success_actor["character_id"]),
    ).fetchone()
    assert sanity["san"] == start_san - 4
    assert sanity["temp_modifiers"]["coc7_sanity"]["day_key"] == "glass-rain-night-1"

    pending_after_ending_action = _insert_v2_action(
        test_db,
        room_id=success_room["room_id"],
        character_id=success_actor["character_id"],
        intent_type="dialogue",
        declared_intent="等待结局后的下一步行动",
    )
    _, success_ending = await _resolve(
        test_db,
        success_state,
        dispatcher,
        room_id=success_room["room_id"],
        character_id=success_actor["character_id"],
        intent_type="dialogue",
        declared_intent="收听维护无线电并确认停机顺序",
        extra_params={"preparedReaction": True},
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
    assert test_db.execute(
        "SELECT status FROM actions WHERE action_id = %s",
        (pending_after_ending_action,),
    ).fetchone()["status"] == "canceled"
    assert test_db.execute(
        "SELECT metadata FROM action_status_events "
        "WHERE action_id = %s AND status = 'canceled'",
        (pending_after_ending_action,),
    ).fetchone()["metadata"]["reason_code"] == "campaign_ended"
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

    traces = test_db.execute(
        "SELECT status, trace FROM resolution_traces "
        "WHERE room_id IN (%s, %s) ORDER BY created_at",
        (success_room["room_id"], mixed_room["room_id"]),
    ).fetchall()
    assert traces
    assert any(row["status"] == "completed" for row in traces)
    completed_trace = next(row["trace"] for row in traces if row["status"] == "completed")
    assert {
        "input_received",
        "resolution_returned",
        "finalized",
    } <= {phase["name"] for phase in completed_trace["phases"]}
