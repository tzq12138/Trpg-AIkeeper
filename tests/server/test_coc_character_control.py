import json
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

import src.server.engine.resolution_pipeline as resolution_pipeline_module
import src.server.main as main_module
import src.server.player.router_player as router_player_module
from src.server.engine.ending_conditions import EndingDecision
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.rule_executor import RuleExecutor
from src.server.engine.state_service import StateService
from src.server.host.ws_manager import ConnectionManager
from src.server.main import app
from src.server.models import MechanicCompileResult, ResolutionResult
from src.server.player.action_service import submit_coc_background_decision
from src.server.player.router_player import _resolve_action_background
from src.server.router_auth import _hash_password
from src.server.rules.base import GameState
from src.server.rules.coc_handlers import CocSanityAdvanceHandler
from src.server.scenario.module_compiler import (
    _build_runtime_package,
    _quality_exceptions,
)


class _Dispatcher:
    def __init__(self, ws_manager=None):
        self.events = []
        self.ws_manager = ws_manager

    async def emit(self, room_id, event_type, audience, payload, character_id=None):
        self.events.append((room_id, event_type, audience, payload, character_id))


class _ConnectionRevoker:
    def __init__(self):
        self.calls = []

    async def revoke_player(self, room_id, character_id):
        self.calls.append((room_id, character_id))
        return True


class _ClosableSocket:
    def __init__(self):
        self.closed = None

    async def close(self, *, code, reason):
        self.closed = (code, reason)


class _EndpointSocket(_ClosableSocket):
    def __init__(self, connection):
        super().__init__()
        self.app = SimpleNamespace(state=SimpleNamespace(db=connection))
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, _payload):
        return None

    async def receive_text(self):
        raise WebSocketDisconnect(code=1000)


class _NonClosingConnection:
    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        return None


class _ConnectionProvider:
    def __init__(self, connection):
        self._connection = connection

    def get_connection(self):
        return _NonClosingConnection(self._connection)


class _DialogueCompiler:
    async def compile(self, _intent, _scenario, _character):
        return MechanicCompileResult(triggeredMechanic="dialogue")


class _PermanentInsanityExecutor:
    async def execute(self, intent, _compiled, character, _inventory, _scenario_assets):
        sanity_state = {
            "schema_version": 1,
            "insanity_type": "permanent",
            "phase": "permanent",
            "control": "ai_keeper",
            "archive_required": True,
            "reserve_investigator_at_safe_scene": True,
        }
        return ResolutionResult(
            actionId=intent.action_id,
            roomId=character["room_id"],
            characterId=character["character_id"],
            mechanic="sanity_check",
            isSuccess=False,
            metadata={
                "insanity_type": "permanent",
                "sanity_phase": "permanent",
            },
            mutations=[
                {"op": "replace", "path": "/character/san", "value": 0},
                {
                    "op": "add",
                    "path": "/character/status_tag",
                    "value": "permanent_insanity",
                },
                {
                    "op": "replace",
                    "path": "/character/temp_modifier/coc7_sanity",
                    "value": sanity_state,
                },
            ],
        )


class _MetadataOnlyPermanentInsanityExecutor:
    async def execute(self, intent, _compiled, character, _inventory, _scenario_assets):
        return ResolutionResult(
            actionId=intent.action_id,
            roomId=character["room_id"],
            characterId=character["character_id"],
            mechanic="sanity_check",
            isSuccess=False,
            metadata={
                "insanity_type": "permanent",
                "sanity_phase": "permanent",
            },
            mutations=[
                {
                    "op": "add",
                    "path": "/character/status_tag",
                    "value": "permanent_insanity",
                }
            ],
        )


class _PermanentThenDialogueExecutor(_PermanentInsanityExecutor):
    async def execute(self, intent, compiled, character, inventory, scenario_assets):
        result = await super().execute(
            intent,
            compiled,
            character,
            inventory,
            scenario_assets,
        )
        result.mechanic = "dialogue"
        return result


class _SuccessfulPermanentThenDialogueExecutor(_PermanentThenDialogueExecutor):
    async def execute(self, intent, compiled, character, inventory, scenario_assets):
        result = await super().execute(
            intent,
            compiled,
            character,
            inventory,
            scenario_assets,
        )
        result.is_success = True
        return result


def _verified_action_params():
    return {
        "director_plan": {
            "context_version": 0,
            "preconditions": [],
            "permissions": [],
            "state_patch": [],
            "state_patch_authority": "advisory_only",
        }
    }


def _insert_background_decision_fixture(test_db):
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title) "
        "VALUES ('scenario-background', 'Background Scenario')"
    )
    test_db.execute(
        "INSERT INTO scenario_versions "
        "(scenario_version_id, scenario_id, version_number, status, created_by) "
        "VALUES ('version-background', 'scenario-background', 1, 'published', 'test')"
    )
    runtime_package = {
        "rule_triggers": [
            {
                "condition": {"$action": "dialogue"},
                "mechanics": [
                    {
                        "type": "sanity_advance",
                        "params": {
                            "event": "bout_elapsed",
                            "backgroundChangeProposal": {
                                "changeId": "forced-betrayal",
                                "summary": "永久强迫调查员伤害同伴",
                                "riskLevel": "high",
                                "forcesHarm": True,
                            },
                        },
                    }
                ],
            }
        ]
    }
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) VALUES "
        "('package-background', 'version-background', 1, 'ready', 'background', %s, 'test')",
        (json.dumps(runtime_package, ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO rooms "
        "(room_id, owner_token, player_experience_version, scenario_id, "
        "scenario_version_id, runtime_package_version_id) VALUES "
        "('room-background', 'owner-background', 'v1', 'scenario-background', "
        "'version-background', 'package-background')"
    )
    for character_id, token in (
        ("char-background", "token-background"),
        ("char-independent", "token-independent"),
    ):
        test_db.execute(
            "INSERT INTO characters "
            "(character_id, room_id, player_name, player_token, xlsx_data, status) "
            "VALUES (%s, 'room-background', %s, %s, %s, 'joined')",
            (
                character_id,
                character_id,
                token,
                json.dumps(
                    {
                        "hp": 10,
                        "max_hp": 10,
                        "san": 50,
                        "max_san": 50,
                        "mp": 10,
                        "max_mp": 10,
                        "luck": 40,
                    }
                ),
            ),
        )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, scene_variables) "
        "VALUES ('room-background', 'library', %s)",
        (json.dumps({"in_game_minutes": 100}),),
    )
    params = json.dumps(_verified_action_params(), ensure_ascii=False)
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, draft_id, idempotency_key, intent_type, "
        "declared_intent, params, status) VALUES "
        "('action-background', 'room-background', 'char-background', 'draft-background', "
        "'confirm-background', 'dialogue', '结束疯狂发作', %s, 'queued'), "
        "('action-independent', 'room-background', 'char-independent', 'draft-independent', "
        "'confirm-independent', 'dialogue', '整理自己的笔记', %s, 'queued')",
        (params, params),
    )
    state_service = StateService(test_db)
    state_service.initialize_character_state("char-background", "room-background")
    state_service.initialize_character_state("char-independent", "room-background")
    test_db.execute(
        "UPDATE character_runtime_state SET status_tags = %s, temp_modifiers = %s "
        "WHERE room_id = 'room-background' AND character_id = 'char-background'",
        (
            json.dumps(["temporary_insanity"]),
            json.dumps({"coc7_sanity": _temporary_bout_state()}),
        ),
    )
    test_db.commit()
    return state_service


@pytest.mark.asyncio
async def test_background_decision_uses_owner_bound_action_chain_without_blocking_others(
    client,
    test_db,
    monkeypatch,
):
    monkeypatch.setattr(app.state, "pg_db", None, raising=False)
    monkeypatch.setattr(app.state, "pipeline", None, raising=False)
    state_service = _insert_background_decision_fixture(test_db)
    dispatcher = _Dispatcher()
    pipeline = ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=dispatcher,
        rule_executor=RuleExecutor(),
        state_service=state_service,
    )

    pending = await pipeline.resolve_action("action-background")

    assert pending["status"] == "awaiting_player_choice"
    unchanged = state_service.get_runtime_state("char-background", "room-background")
    assert unchanged["temp_modifiers"]["coc7_sanity"]["phase"] == "bout"
    assert "永久强迫调查员伤害同伴" not in str(pending)

    independent = await ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=dispatcher,
        state_service=state_service,
    ).resolve_action("action-independent")
    assert independent["status"] == "completed"

    not_owner = client.post(
        "/api/player/actions/action-background/background-change",
        headers={
            "X-Room-Token": "token-independent",
            "Idempotency-Key": "background-reject",
        },
        json={"decision": "reject"},
    )
    accepted = client.post(
        "/api/player/actions/action-background/background-change",
        headers={
            "X-Room-Token": "token-background",
            "Idempotency-Key": "background-reject",
        },
        json={"decision": "reject"},
    )

    assert not_owner.status_code == 404
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "awaiting_player_choice"

    completed = await pipeline.resolve_action("action-background")

    assert completed["status"] == "completed"
    runtime = state_service.get_runtime_state("char-background", "room-background")
    sanity = runtime["temp_modifiers"]["coc7_sanity"]
    assert sanity["phase"] == "underlying"
    assert sanity["underlying_ends_at_minute"] == 220
    assert sanity["background_change"] == {
        "change_id": "engine-safe-no-change",
        "summary": "玩家拒绝了背景变化；核心背景与关系保持不变。",
        "selection_source": "engine_safe_rejection",
    }
    action = test_db.execute(
        "SELECT status, result, params FROM actions WHERE action_id = 'action-background'"
    ).fetchone()
    assert action["status"] == "completed"
    assert "永久强迫调查员伤害同伴" not in str(action["result"])
    assert action["params"]["sanity_background_progress"]["decision"] == "reject"
    assert any(
        event[1] == "s2c_action_choice_requested"
        and event[3].get("kind") == "coc_background_change"
        for event in dispatcher.events
    )


@pytest.mark.asyncio
async def test_production_background_worker_persists_submitted_background_decision(
    test_db,
    monkeypatch,
):
    state_service = _insert_background_decision_fixture(test_db)
    initial = ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        state_service=state_service,
    )
    assert (await initial.resolve_action("action-background"))["status"] == (
        "awaiting_player_choice"
    )
    submit_coc_background_decision(
        test_db,
        "char-background",
        "action-background",
        "reject",
        "worker-background-reject",
    )
    monkeypatch.setattr(
        app.state,
        "pg_db",
        _ConnectionProvider(test_db),
        raising=False,
    )
    monkeypatch.setattr(app.state, "compiler", _DialogueCompiler(), raising=False)

    await _resolve_action_background(app, "action-background")

    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'action-background'"
    ).fetchone()
    runtime = state_service.get_runtime_state("char-background", "room-background")
    assert action["status"] == "completed", json.dumps(
        action["result"], ensure_ascii=False, indent=2
    )
    assert runtime["temp_modifiers"]["coc7_sanity"]["background_change"][
        "selection_source"
    ] == "engine_safe_rejection"


@pytest.mark.asyncio
async def test_background_resolver_forwards_configured_gateway_to_pipeline(
    test_db,
    monkeypatch,
):
    captured = {}

    class CapturingPipeline:
        def __init__(self, _conn, *, gateway=None, **_kwargs):
            captured["gateway"] = gateway

        async def resolve_action(self, action_id):
            captured["action_id"] = action_id
            return {"status": "completed"}

    configured_gateway = object()
    monkeypatch.setattr(
        app.state,
        "pg_db",
        _ConnectionProvider(test_db),
        raising=False,
    )
    monkeypatch.setattr(app.state, "gateway", configured_gateway, raising=False)
    monkeypatch.setattr(
        router_player_module,
        "ResolutionPipeline",
        CapturingPipeline,
    )

    await _resolve_action_background(app, "action-gateway-forwarding")

    assert captured["action_id"] == "action-gateway-forwarding"
    assert captured["gateway"] is configured_gateway


@pytest.mark.asyncio
async def test_queued_action_cannot_forge_server_sanity_background_progress(test_db):
    state_service = _insert_background_decision_fixture(test_db)
    forged = {
        **_verified_action_params(),
        "sanity_background_progress": {
            "status": "submitted",
            "decision": "accept",
            "engine": {
                "proposal": {
                    "change_id": "forged-control",
                    "summary": "永久强迫调查员伤害同伴",
                    "selection_source": "forged-client",
                }
            },
        },
    }
    test_db.execute(
        "UPDATE actions SET params = %s WHERE action_id = 'action-background'",
        (json.dumps(forged, ensure_ascii=False),),
    )
    test_db.commit()

    result = await ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        state_service=state_service,
    ).resolve_action("action-background")

    assert result["status"] == "awaiting_player_choice"
    runtime = state_service.get_runtime_state("char-background", "room-background")
    sanity = runtime["temp_modifiers"]["coc7_sanity"]
    assert sanity["phase"] == "bout"
    assert "background_change" not in sanity
    action = test_db.execute(
        "SELECT status, params, result FROM actions WHERE action_id = 'action-background'"
    ).fetchone()
    assert action["status"] == "awaiting_player_choice"
    assert action["params"]["sanity_background_progress"]["status"] == "pending"
    assert "永久强迫调查员伤害同伴" not in str(action["result"])


def _insert_control_transition_fixture(test_db, *, phase="stable"):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, player_experience_version) "
        "VALUES ('room-control-transition', 'owner-control-transition', 'v1')"
    )
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, xlsx_data, status) "
        "VALUES ('char-control-transition', 'room-control-transition', '玩家', "
        "'token-control-transition', %s, 'joined')",
        (
            json.dumps(
                {
                    "hp": 10,
                    "max_hp": 10,
                    "san": 1,
                    "max_san": 60,
                    "mp": 10,
                    "max_mp": 10,
                    "luck": 40,
                }
            ),
        ),
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, scene_variables) "
        "VALUES ('room-control-transition', 'danger', '{}')"
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, draft_id, idempotency_key, intent_type, "
        "declared_intent, params, status) VALUES "
        "('action-control-transition', 'room-control-transition', 'char-control-transition', "
        "'draft-control-transition', 'confirm-control-transition', 'dialogue', "
        "'目睹不可名状之物', %s, 'queued')",
        (json.dumps(_verified_action_params()),),
    )
    service = StateService(test_db)
    service.initialize_character_state(
        "char-control-transition",
        "room-control-transition",
    )
    if phase == "bout":
        test_db.execute(
            "UPDATE character_runtime_state SET status_tags = %s, temp_modifiers = %s "
            "WHERE room_id = 'room-control-transition' "
            "AND character_id = 'char-control-transition'",
            (
                json.dumps(["temporary_insanity"]),
                json.dumps({"coc7_sanity": _temporary_bout_state()}),
            ),
        )
        test_db.commit()
    return service


@pytest.mark.asyncio
async def test_san_zero_atomically_restricts_original_investigator_and_revokes_player_routes(
    client,
    test_db,
):
    state_service = _insert_control_transition_fixture(test_db)
    connection_revoker = _ConnectionRevoker()

    outcome = await ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(ws_manager=connection_revoker),
        rule_executor=_PermanentThenDialogueExecutor(),
        state_service=state_service,
    ).resolve_action("action-control-transition")

    assert outcome["status"] == "completed"
    character = test_db.execute(
        "SELECT status, account_id FROM characters "
        "WHERE character_id = 'char-control-transition'"
    ).fetchone()
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'action-control-transition'"
    ).fetchone()
    completed_event = test_db.execute(
        "SELECT status FROM action_status_events "
        "WHERE action_id = 'action-control-transition' AND status = 'completed'"
    ).fetchone()
    assert character["status"] == "restricted_npc"
    assert action["status"] == "completed"
    assert completed_event["status"] == "completed"
    assert connection_revoker.calls == [
        ("room-control-transition", "char-control-transition")
    ]
    denied = client.get(
        "/api/player/character",
        headers={"X-Room-Token": "token-control-transition"},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_san_zero_state_and_control_roll_back_when_action_completion_fails(
    test_db,
    monkeypatch,
):
    state_service = _insert_control_transition_fixture(test_db)

    def fail_completion(*_args, **_kwargs):
        raise RuntimeError("injected-action-completion-failure")

    monkeypatch.setattr(
        resolution_pipeline_module,
        "complete_action",
        fail_completion,
    )

    outcome = await ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        rule_executor=_PermanentThenDialogueExecutor(),
        state_service=state_service,
    ).resolve_action("action-control-transition")

    assert outcome == {
        "status": "awaiting_host_exception",
        "action_id": "action-control-transition",
        "reason": "state_persistence_failed",
    }
    runtime = state_service.get_runtime_state(
        "char-control-transition",
        "room-control-transition",
    )
    character = test_db.execute(
        "SELECT status FROM characters WHERE character_id = 'char-control-transition'"
    ).fetchone()
    assert runtime["san"] == 1
    assert runtime["temp_modifiers"] == {}
    assert character["status"] == "joined"


@pytest.mark.asyncio
async def test_san_zero_state_control_and_action_roll_back_when_ending_archive_fails(
    test_db,
    monkeypatch,
):
    state_service = _insert_control_transition_fixture(test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active' "
        "WHERE room_id = 'room-control-transition'"
    )
    test_db.commit()

    ending = EndingDecision(
        ending_id="san-zero-ending",
        ending_type="defeat",
        citation={"source": "compiled-test-ending"},
        room_status="active",
        priority=100,
        exclusive_group="campaign_ending",
    )
    monkeypatch.setattr(
        ResolutionPipeline,
        "_evaluate_verified_runtime_ending",
        lambda _self, _room_id, *, executor=None: ending,
    )

    def fail_finalization(*_args, **_kwargs):
        raise RuntimeError("injected-ending-archive-failure")

    monkeypatch.setattr(
        resolution_pipeline_module,
        "finalize_campaign",
        fail_finalization,
    )

    outcome = await ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        rule_executor=_PermanentThenDialogueExecutor(),
        state_service=state_service,
    ).resolve_action("action-control-transition")

    assert outcome == {
        "status": "awaiting_host_exception",
        "action_id": "action-control-transition",
        "reason": "state_persistence_failed",
    }
    runtime = state_service.get_runtime_state(
        "char-control-transition",
        "room-control-transition",
    )
    character = test_db.execute(
        "SELECT status FROM characters WHERE character_id = 'char-control-transition'"
    ).fetchone()
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'action-control-transition'"
    ).fetchone()
    room = test_db.execute(
        "SELECT status FROM rooms WHERE room_id = 'room-control-transition'"
    ).fetchone()
    archive = test_db.execute(
        "SELECT archive_id FROM campaign_archives "
        "WHERE room_id = 'room-control-transition'"
    ).fetchone()
    assert runtime["san"] == 1
    assert runtime["temp_modifiers"] == {}
    assert character["status"] == "joined"
    assert action["status"] == "awaiting_host_exception"
    assert room["status"] == "active"
    assert archive is None


@pytest.mark.asyncio
async def test_san_zero_atomically_completes_verified_ending(test_db, monkeypatch):
    state_service = _insert_control_transition_fixture(test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active' "
        "WHERE room_id = 'room-control-transition'"
    )
    test_db.commit()

    ending = EndingDecision(
        ending_id="san-zero-ending",
        ending_type="defeat",
        citation={"source": "compiled-test-ending"},
        room_status="active",
        priority=100,
        exclusive_group="campaign_ending",
    )
    monkeypatch.setattr(
        ResolutionPipeline,
        "_evaluate_verified_runtime_ending",
        lambda _self, _room_id, *, executor=None: ending,
    )

    outcome = await ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        rule_executor=_PermanentThenDialogueExecutor(),
        state_service=state_service,
    ).resolve_action("action-control-transition")

    assert outcome["status"] == "completed"
    character = test_db.execute(
        "SELECT status FROM characters WHERE character_id = 'char-control-transition'"
    ).fetchone()
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'action-control-transition'"
    ).fetchone()
    room = test_db.execute(
        "SELECT status FROM rooms WHERE room_id = 'room-control-transition'"
    ).fetchone()
    archive = test_db.execute(
        "SELECT ending_type FROM campaign_archives "
        "WHERE room_id = 'room-control-transition'"
    ).fetchone()
    assert character["status"] == "restricted_npc"
    assert action["status"] == "completed"
    assert room["status"] == "completed"
    assert archive["ending_type"] == "defeat"


@pytest.mark.asyncio
async def test_san_named_clue_and_action_roll_back_when_triggered_ending_fails(
    test_db,
    monkeypatch,
):
    state_service = _insert_control_transition_fixture(test_db)
    test_db.execute(
        "UPDATE rooms SET status = 'active' "
        "WHERE room_id = 'room-control-transition'"
    )
    test_db.commit()

    ending = EndingDecision(
        ending_id="clue-ending",
        ending_type="defeat",
        citation={"source": "compiled-test-ending"},
        room_status="active",
        priority=100,
        exclusive_group="campaign_ending",
    )

    async def persist_trigger_clue(
        _pipeline,
        action,
        _intent,
        *,
        executor=None,
        publish=True,
    ):
        worker = executor or test_db
        worker.execute(
            "INSERT INTO clues "
            "(clue_id, room_id, character_id, text, source, is_private) "
            "VALUES ('san-ending-clue', %s, %s, 'ending clue', "
            "'runtime:san-ending-clue', TRUE)",
            (action["room_id"], action["character_id"]),
        )
        return [
            {
                "canonicalId": "san-ending-clue",
                "clueId": "san-ending-clue",
                "name": "ending clue",
            }
        ]

    def ending_after_clue(_pipeline, _room_id, *, executor=None):
        worker = executor or test_db
        clue = worker.execute(
            "SELECT 1 FROM clues WHERE clue_id = 'san-ending-clue'"
        ).fetchone()
        return ending if clue else None

    monkeypatch.setattr(
        ResolutionPipeline,
        "_persist_named_runtime_clues",
        persist_trigger_clue,
    )
    monkeypatch.setattr(
        ResolutionPipeline,
        "_evaluate_verified_runtime_ending",
        ending_after_clue,
    )

    def fail_finalization(*_args, **_kwargs):
        raise RuntimeError("injected-clue-ending-archive-failure")

    monkeypatch.setattr(
        resolution_pipeline_module,
        "finalize_campaign",
        fail_finalization,
    )

    outcome = await ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        rule_executor=_SuccessfulPermanentThenDialogueExecutor(),
        state_service=state_service,
    ).resolve_action("action-control-transition")

    assert outcome == {
        "status": "awaiting_host_exception",
        "action_id": "action-control-transition",
        "reason": "state_persistence_failed",
    }
    runtime = state_service.get_runtime_state(
        "char-control-transition",
        "room-control-transition",
    )
    character = test_db.execute(
        "SELECT status FROM characters WHERE character_id = 'char-control-transition'"
    ).fetchone()
    action = test_db.execute(
        "SELECT status FROM actions WHERE action_id = 'action-control-transition'"
    ).fetchone()
    assert runtime["san"] == 1
    assert runtime["temp_modifiers"] == {}
    assert character["status"] == "joined"
    assert action["status"] == "awaiting_host_exception"
    assert test_db.execute(
        "SELECT 1 FROM clues WHERE clue_id = 'san-ending-clue'"
    ).fetchone() is None


@pytest.mark.asyncio
async def test_connection_manager_removes_and_closes_revoked_player_socket():
    manager = ConnectionManager()
    socket = _ClosableSocket()
    manager.register_accepted(
        socket,
        "room-control-transition",
        "player:char-control-transition",
    )

    revoked = await manager.revoke_player(
        "room-control-transition",
        "char-control-transition",
    )

    assert revoked is True
    assert manager.is_connected(
        "room-control-transition",
        "player:char-control-transition",
    ) is False
    assert socket.closed == (4003, "character_control_revoked")


@pytest.mark.asyncio
async def test_player_ws_rechecks_control_after_connection_registration(
    test_db,
    monkeypatch,
):
    _insert_control_transition_fixture(test_db)
    socket = _EndpointSocket(test_db)
    original_connect = main_module.ws_manager.connect

    async def connect_then_restrict(websocket, room_id, connection_id):
        await original_connect(websocket, room_id, connection_id)
        test_db.execute(
            "UPDATE characters SET status = 'restricted_npc' "
            "WHERE character_id = 'char-control-transition'"
        )
        test_db.commit()

    monkeypatch.setattr(main_module.ws_manager, "connect", connect_then_restrict)

    await main_module.player_ws_endpoint(
        socket,
        "room-control-transition",
        "token-control-transition",
    )

    assert socket.accepted is True
    assert socket.closed == (4003, "character_control_revoked")
    assert not main_module.ws_manager.is_connected(
        "room-control-transition",
        "player:char-control-transition",
    )


@pytest.mark.asyncio
async def test_player_ws_removes_connection_when_room_retires_during_revalidation(
    test_db,
    monkeypatch,
):
    _insert_control_transition_fixture(test_db)
    socket = _EndpointSocket(test_db)
    original_connect = main_module.ws_manager.connect

    async def connect_then_retire(websocket, room_id, connection_id):
        await original_connect(websocket, room_id, connection_id)
        test_db.execute(
            "UPDATE rooms SET rule_source_status = 'rule_source_retired', "
            "rule_source_reason = 'local_test_rule_version' "
            "WHERE room_id = 'room-control-transition'"
        )
        test_db.commit()

    monkeypatch.setattr(main_module.ws_manager, "connect", connect_then_retire)

    await main_module.player_ws_endpoint(
        socket,
        "room-control-transition",
        "token-control-transition",
    )

    assert socket.accepted is True
    assert socket.closed == (4009, "rule_source_retired")
    assert not main_module.ws_manager.is_connected(
        "room-control-transition",
        "player:char-control-transition",
    )


@pytest.mark.asyncio
async def test_permanent_metadata_without_authoritative_zero_san_does_not_revoke_control(
    test_db,
):
    state_service = _insert_control_transition_fixture(test_db)

    outcome = await ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        rule_executor=_MetadataOnlyPermanentInsanityExecutor(),
        state_service=state_service,
    ).resolve_action("action-control-transition")

    assert outcome["status"] == "completed"
    runtime = state_service.get_runtime_state(
        "char-control-transition",
        "room-control-transition",
    )
    character = test_db.execute(
        "SELECT status FROM characters WHERE character_id = 'char-control-transition'"
    ).fetchone()
    assert runtime["san"] == 1
    assert character["status"] == "joined"


@pytest.mark.asyncio
async def test_player_action_is_rejected_while_ai_controls_an_active_bout(test_db):
    state_service = _insert_control_transition_fixture(test_db, phase="bout")

    outcome = await ResolutionPipeline(
        test_db,
        compiler=_DialogueCompiler(),
        dispatcher=_Dispatcher(),
        state_service=state_service,
    ).resolve_action("action-control-transition")

    assert outcome == {
        "status": "rejected",
        "action_id": "action-control-transition",
        "reason": "investigator_not_player_controlled",
    }


def _insert_replacement_fixture(test_db):
    test_db.execute(
        "INSERT INTO accounts (account_id, username, password_hash, role) "
        "VALUES ('account-replacement', 'replacement-player', %s, 'player')",
        (_hash_password("test123"),),
    )
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, publish_status) "
        "VALUES ('scenario-replacement', 'Replacement Scenario', 'published')"
    )
    test_db.execute(
        "INSERT INTO scenario_versions "
        "(scenario_version_id, scenario_id, version_number, status, created_by) "
        "VALUES ('version-replacement', 'scenario-replacement', 1, 'published', 'test')"
    )
    package = {
        "character_control": {
            "safe_replacement_scene_ids": ["safe-lobby"],
            "recovery_nodes": [],
        },
        "character_and_items": {
            "templates": [
                {"template_id": "template-reserve", "name": "备用调查员"}
            ]
        },
    }
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, "
        "gate_status, input_checksum, runtime_package, created_by) VALUES "
        "('package-replacement', 'version-replacement', 1, 'ready', 'replacement', %s, 'test')",
        (json.dumps(package, ensure_ascii=False),),
    )
    test_db.execute(
        "INSERT INTO rooms "
        "(room_id, owner_token, status, scenario_id, scenario_version_id, "
        "runtime_package_version_id, player_experience_version) VALUES "
        "('room-replacement', 'owner-replacement', 'active', 'scenario-replacement', "
        "'version-replacement', 'package-replacement', 'v2')"
    )
    test_db.execute(
        "INSERT INTO character_templates "
        "(template_id, scenario_id, name, occupation, background, attributes, skills, backstory) "
        "VALUES ('template-reserve', 'scenario-replacement', '艾达', '记者', '公开背景', "
        "%s, %s, %s)",
        (
            json.dumps({"con": 50, "siz": 50, "pow": 60, "luck": 55}),
            json.dumps({"侦查": 65}),
            json.dumps({"public_history": "来自报社"}, ensure_ascii=False),
        ),
    )
    test_db.execute(
        "INSERT INTO characters "
        "(character_id, room_id, player_name, player_token, xlsx_data, account_id, "
        "status, is_ready) VALUES "
        "('char-original', 'room-replacement', '玩家', 'token-original', %s, "
        "'account-replacement', 'restricted_npc', FALSE)",
        (
            json.dumps(
                {
                    "name": "原调查员",
                    "private_memory": "只有原调查员知道的秘密",
                    "hp": 3,
                    "max_hp": 10,
                    "san": 0,
                    "max_san": 60,
                    "mp": 0,
                    "max_mp": 10,
                    "luck": 1,
                },
                ensure_ascii=False,
            ),
        ),
    )
    test_db.execute(
        "INSERT INTO character_runtime_state "
        "(character_id, room_id, hp, hp_max, san, san_max, mp, mp_max, luck, "
        "status_tags, temp_modifiers, visibility, version) VALUES "
        "('char-original', 'room-replacement', 3, 10, 0, 60, 0, 10, 1, %s, %s, "
        "'visible', 7)",
        (
            json.dumps(["permanent_insanity"]),
            json.dumps(
                {
                    "coc7_sanity": {
                        "insanity_type": "permanent",
                        "phase": "permanent",
                        "control": "ai_keeper",
                    },
                    "private_state": "do-not-copy",
                }
            ),
        ),
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, scene_variables) "
        "VALUES ('room-replacement', 'danger', '{}')"
    )
    test_db.commit()


def test_replacement_requires_compiled_safe_scene_and_creates_fresh_room_run_entity(
    client,
    test_db,
    monkeypatch,
):
    _insert_replacement_fixture(test_db)
    monkeypatch.setattr(app.state, "state_service", StateService(test_db), raising=False)
    headers = {
        "X-Room-Token": "token-original",
        "Idempotency-Key": "replacement-transition-1",
    }

    unsafe = client.post(
        "/api/player/characters/char-original/replacement",
        headers=headers,
        json={"templateId": "template-reserve"},
    )
    assert unsafe.status_code == 409
    assert unsafe.json()["detail"]["code"] == "replacement_scene_not_safe"
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'safe-lobby' "
        "WHERE room_id = 'room-replacement'"
    )
    test_db.execute(
        "UPDATE rooms SET integrity_status = 'read_only_recovery' "
        "WHERE room_id = 'room-replacement'"
    )
    test_db.commit()

    unhealthy = client.post(
        "/api/player/characters/char-original/replacement",
        headers=headers,
        json={"templateId": "template-reserve"},
    )
    assert unhealthy.status_code == 409
    assert unhealthy.json()["detail"]["code"] == "replacement_room_not_healthy"
    test_db.execute(
        "UPDATE rooms SET integrity_status = 'healthy' "
        "WHERE room_id = 'room-replacement'"
    )
    test_db.commit()

    response = client.post(
        "/api/player/characters/char-original/replacement",
        headers=headers,
        json={"templateId": "template-reserve"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["character_id"] != "char-original"
    assert payload["player_token"] != "token-original"
    assert payload["status"] == "ready"
    original = test_db.execute(
        "SELECT status, account_id, player_token FROM characters "
        "WHERE character_id = 'char-original'"
    ).fetchone()
    replacement = test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s",
        (payload["character_id"],),
    ).fetchone()
    assert original["status"] == "restricted_npc"
    assert original["account_id"] is None
    assert original["player_token"] != "token-original"
    assert replacement["room_id"] == "room-replacement"
    assert replacement["account_id"] == "account-replacement"
    assert replacement["player_token"] == payload["player_token"]
    assert replacement["xlsx_data"]["source"] == {
        "type": "template",
        "template_id": "template-reserve",
    }
    assert "private_memory" not in replacement["xlsx_data"]
    replacement_runtime = test_db.execute(
        "SELECT status_tags, temp_modifiers, version FROM character_runtime_state "
        "WHERE room_id = 'room-replacement' AND character_id = %s",
        (payload["character_id"],),
    ).fetchone()
    assert replacement_runtime["status_tags"] == []
    assert replacement_runtime["temp_modifiers"] == {}
    assert replacement_runtime["version"] == 1
    assert client.get("/api/player/character", headers=headers).status_code == 403
    assert client.get(
        "/api/player/character",
        headers={"X-Room-Token": payload["player_token"]},
    ).status_code == 200

    replay = client.post(
        "/api/player/characters/char-original/replacement",
        headers=headers,
        json={"templateId": "template-reserve"},
    )
    assert replay.status_code == 200
    assert replay.json() == payload
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM characters WHERE room_id = 'room-replacement'"
    ).fetchone()["count"] == 2
    unauthorized_replay = client.post(
        "/api/player/characters/char-original/replacement",
        headers={
            "X-Room-Token": "wrong-original-token",
            "Idempotency-Key": "replacement-transition-1",
        },
        json={"templateId": "template-reserve"},
    )
    assert unauthorized_replay.status_code == 403
    conflicting_retry = client.post(
        "/api/player/characters/char-original/replacement",
        headers={
            "X-Room-Token": "token-original",
            "Idempotency-Key": "replacement-transition-2",
        },
        json={"templateId": "template-reserve"},
    )
    assert conflicting_retry.status_code == 409
    assert conflicting_retry.json()["detail"]["code"] == "replacement_already_completed"


def test_replacement_rejects_a_retired_room_before_idempotent_replay(client, test_db):
    _insert_replacement_fixture(test_db)
    test_db.execute(
        "UPDATE rooms SET rule_source_status = 'rule_source_retired', "
        "rule_source_reason = 'local_test_rule_version' "
        "WHERE room_id = 'room-replacement'"
    )
    test_db.commit()

    response = client.post(
        "/api/player/characters/char-original/replacement",
        headers={
            "X-Room-Token": "token-original",
            "Idempotency-Key": "retired-replacement",
        },
        json={"templateId": "template-reserve"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "code": "rule_source_retired",
        "reason": "local_test_rule_version",
    }
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM characters WHERE room_id = 'room-replacement'"
    ).fetchone()["count"] == 1


def test_restricted_npc_token_cannot_use_player_routes_or_restore_session(
    client,
    test_db,
):
    _insert_replacement_fixture(test_db)
    token_headers = {"X-Room-Token": "token-original"}

    assert client.get("/api/player/reconnect", headers=token_headers).status_code == 403
    assert client.post(
        "/api/player/team-message",
        headers=token_headers,
        json={"text": "仍以原角色发言"},
    ).status_code == 403
    assert client.get("/api/player/archive", headers=token_headers).status_code == 403
    with pytest.raises(WebSocketDisconnect) as disconnected:
        with client.websocket_connect(
            "/ws?room=room-replacement&role=player&token=token-original"
        ) as websocket:
            websocket.receive_text()
    assert disconnected.value.code == 4003

    login_response = client.post(
        "/api/auth/login",
        json={"username": "replacement-player", "password": "test123"},
    )
    assert login_response.status_code == 200
    account_headers = {
        **token_headers,
        "Authorization": f"Bearer {login_response.json()['token']}",
    }
    copied = client.post(
        "/api/player/rooms/room-replacement/join-with-character",
        headers=account_headers,
        data={
            "player_name": "绕过替补",
            "copy_character_id": "char-original",
        },
    )
    assert copied.status_code == 409
    assert copied.json()["detail"]["code"] == "character_copy_source_unavailable"
    restored = client.post(
        "/api/player/characters/char-original/restore-session",
        headers=account_headers,
    )
    assert restored.status_code == 409
    assert restored.json()["detail"]["code"] == "character_session_not_restorable"


def _sanity_state(result):
    return next(
        mutation["value"]
        for mutation in result.mutations
        if mutation["path"] == "/character/temp_modifier/coc7_sanity"
    )


def _temporary_underlying_state():
    return {
        "schema_version": 1,
        "insanity_type": "temporary",
        "phase": "underlying",
        "control": "player",
        "underlying_duration": {"value": 2, "unit": "hours"},
        "underlying_started_at_minute": 100,
        "underlying_ends_at_minute": 220,
    }


def _temporary_bout_state():
    return {
        "schema_version": 1,
        "insanity_type": "temporary",
        "phase": "bout",
        "control": "ai_keeper",
        "underlying_duration": {"value": 2, "unit": "hours"},
    }


@pytest.mark.asyncio
async def test_background_change_is_only_proposed_until_owning_player_decides():
    current = _temporary_bout_state()

    result = await CocSanityAdvanceHandler().execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {
            "event": "bout_elapsed",
            "backgroundChangeProposal": {
                "changeId": "forced-betrayal",
                "summary": "永久强迫调查员伤害同伴",
                "riskLevel": "high",
                "forcesHarm": True,
            },
            "_runtime_scene": {"in_game_minutes": 100},
        },
    )

    state = _sanity_state(result)
    proposal = result.metadata["background_change"]
    assert state["background_change_pending_player_confirmation"] is True
    assert "background_change" not in state
    assert proposal["status"] == "pending"
    assert proposal["allowed_decisions"] == ["accept", "reject"]
    assert proposal["proposal"] == {
        "change_id": "engine-safe-behavioral-note",
        "summary": "调查员在压力后变得更谨慎，但核心背景与关系保持不变。",
        "selection_source": "engine_safe_fallback",
    }
    assert proposal["proposal_audit"]["engine_validation"] == {
        "status": "rejected",
        "reason_code": "unsafe_background_change",
    }
    assert "永久强迫调查员伤害同伴" not in str(result.metadata)
    assert "永久强迫调查员伤害同伴" not in str(result.mutations)


@pytest.mark.asyncio
async def test_rejecting_background_change_commits_engine_safe_alternative_only_after_decision():
    current = _temporary_bout_state()
    handler = CocSanityAdvanceHandler()
    proposed = await handler.execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {
            "event": "bout_elapsed",
            "backgroundChangeProposal": {
                "changeId": "withdrawn",
                "summary": "调查员暂时更不愿独自行动。",
                "riskLevel": "low",
            },
            "_runtime_scene": {"in_game_minutes": 100},
        },
    )

    resolved = await handler.execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {
            "event": "bout_elapsed",
            "_runtime_scene": {"in_game_minutes": 100},
            "_sanity_background": {
                "status": "submitted",
                "decision": "reject",
                "engine": proposed.metadata["background_change"]["_engine"],
            },
        },
    )

    state = _sanity_state(resolved)
    assert state["background_change_pending_player_confirmation"] is False
    assert state["background_change_confirmed"] is False
    assert state["background_change"] == {
        "change_id": "engine-safe-no-change",
        "summary": "玩家拒绝了背景变化；核心背景与关系保持不变。",
        "selection_source": "engine_safe_rejection",
    }
    assert resolved.metadata["background_change"] == {
        "status": "resolved",
        "decision": "reject",
        "applied": state["background_change"],
    }


@pytest.mark.asyncio
async def test_legacy_background_confirmed_event_cannot_bypass_owner_decision_chain():
    current = {
        **_temporary_underlying_state(),
        "background_change_pending_player_confirmation": True,
    }

    result = await CocSanityAdvanceHandler().execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {"event": "background_confirmed"},
    )

    assert result.is_success is False
    assert result.metadata["reason_code"] == "player_background_decision_required"
    assert result.mutations == []


@pytest.mark.asyncio
async def test_temporary_insanity_ends_only_when_authoritative_game_time_reaches_deadline():
    handler = CocSanityAdvanceHandler()
    current = _temporary_underlying_state()

    early = await handler.execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {
            "event": "time_advanced",
            "inGameMinute": 999999,
            "_runtime_scene": {"in_game_minutes": 219},
        },
    )
    due = await handler.execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {
            "event": "time_advanced",
            "_runtime_scene": {"in_game_minutes": 220},
        },
    )

    assert early.is_success is False
    assert early.metadata["reason_code"] == "temporary_insanity_time_remaining"
    assert early.mutations == []
    assert _sanity_state(due)["insanity_type"] == "none"
    assert due.metadata["recovered_at_game_minute"] == 220


@pytest.mark.asyncio
async def test_bout_completion_anchors_temporary_insanity_to_authoritative_game_time():
    current = {
        "schema_version": 1,
        "insanity_type": "temporary",
        "phase": "bout",
        "control": "ai_keeper",
        "underlying_duration": {"value": 2, "unit": "hours"},
    }

    result = await CocSanityAdvanceHandler().execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {
            "event": "bout_elapsed",
            "inGameMinute": 999999,
            "_runtime_scene": {"in_game_minutes": 100},
        },
    )

    state = _sanity_state(result)
    assert state["underlying_started_at_minute"] == 100
    assert state["underlying_ends_at_minute"] == 220


@pytest.mark.asyncio
async def test_bout_completion_without_authoritative_game_time_keeps_temporary_bout():
    current = _temporary_bout_state()

    result = await CocSanityAdvanceHandler().execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {"event": "bout_elapsed"},
    )

    assert result.is_success is False
    assert result.metadata["reason_code"] == "authoritative_game_time_required"
    assert result.mutations == []
    assert current["phase"] == "bout"


@pytest.mark.asyncio
async def test_retriggered_bout_does_not_extend_existing_temporary_insanity_deadline():
    current = {
        **_temporary_bout_state(),
        "retriggered": True,
        "underlying_started_at_minute": 100,
        "underlying_ends_at_minute": 220,
    }

    result = await CocSanityAdvanceHandler().execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {
            "event": "bout_elapsed",
            "_runtime_scene": {"in_game_minutes": 160},
        },
    )

    state = _sanity_state(result)
    assert state["underlying_started_at_minute"] == 100
    assert state["underlying_ends_at_minute"] == 220


@pytest.mark.asyncio
async def test_indefinite_insanity_rejects_forged_recovery_and_accepts_compiled_cited_node():
    current = {
        "schema_version": 1,
        "insanity_type": "indefinite",
        "phase": "underlying",
        "control": "player",
        "underlying_duration": {"value": None, "unit": "until_recovery"},
    }
    state = GameState(character={"temp_modifiers": {"coc7_sanity": current}})
    handler = CocSanityAdvanceHandler()

    forged = await handler.execute(
        state,
        {
            "event": "recovered",
            "recoveryNodeId": "clinic-care",
            "ruleCitation": {"source_ref": "forged"},
            "_runtime_scene": {"current_scene": "clinic"},
        },
    )
    compiled = await handler.execute(
        state,
        {
            "event": "recovered",
            "recoveryNodeId": "clinic-care",
            "_runtime_scene": {"current_scene": "clinic"},
            "_runtime_character_control": {
                "recovery_nodes": [
                    {
                        "node_id": "clinic-care",
                        "scene_id": "clinic",
                        "citation": {
                            "source_part_id": "part-clinic",
                            "source_ref": "module#part-clinic",
                        },
                    }
                ]
            },
        },
    )

    assert forged.is_success is False
    assert forged.metadata["reason_code"] == "compiled_recovery_node_required"
    assert forged.mutations == []
    assert compiled.is_success is True
    assert _sanity_state(compiled)["insanity_type"] == "none"
    assert compiled.metadata["recovery_node"] == {
        "node_id": "clinic-care",
        "scene_id": "clinic",
        "citation": {
            "source_part_id": "part-clinic",
            "source_ref": "module#part-clinic",
        },
    }


@pytest.mark.asyncio
async def test_permanent_insanity_cannot_be_recovered_in_m0():
    current = {
        "schema_version": 1,
        "insanity_type": "permanent",
        "phase": "permanent",
        "control": "ai_keeper",
    }

    result = await CocSanityAdvanceHandler().execute(
        GameState(character={"temp_modifiers": {"coc7_sanity": current}}),
        {
            "event": "recovered",
            "recoveryNodeId": "clinic-care",
            "_runtime_scene": {"current_scene": "clinic"},
            "_runtime_character_control": {
                "recovery_nodes": [
                    {
                        "node_id": "clinic-care",
                        "scene_id": "clinic",
                        "citation": {"source_ref": "module#part-clinic"},
                    }
                ]
            },
        },
    )

    assert result.is_success is False
    assert result.metadata["reason_code"] == "permanent_insanity_not_recoverable"
    assert result.mutations == []


def _compiler_graph():
    citation = {
        "source_part_id": "part-clinic",
        "source_ref": "module#part-clinic",
    }
    return {
        "scenes": [
            {"scene_id": "lobby", "name": "Lobby", "citation": citation},
            {"scene_id": "clinic", "name": "Clinic", "citation": citation},
        ],
        "character_control": {
            "safe_replacement_scene_ids": ["lobby"],
            "recovery_nodes": [
                {
                    "node_id": "clinic-care",
                    "scene_id": "clinic",
                    "citation": citation,
                }
            ],
        },
    }


def _compile_package(graph):
    return _build_runtime_package(
        {"scenario_version_id": "version-control", "scenario_title": "Control"},
        graph,
        {},
        [],
        [],
        [],
        [{"template_id": "replacement-template", "name": "Reserve"}],
    )


def _quality_issues(graph):
    return _quality_exceptions(
        graph,
        [],
        [],
        [],
        {},
        [],
        [{"template_id": "replacement-template", "name": "Reserve"}],
    )


def test_runtime_package_compiles_safe_replacement_scenes_and_cited_recovery_nodes():
    graph = _compiler_graph()

    package = _compile_package(graph)

    assert package["character_control"] == graph["character_control"]
    assert not any(
        issue["code"].startswith("invalid_character_control")
        for issue in _quality_issues(graph)
    )


def test_runtime_package_blocks_uncited_or_unknown_character_control_nodes():
    graph = _compiler_graph()
    graph["character_control"]["safe_replacement_scene_ids"].append("missing-scene")
    graph["character_control"]["recovery_nodes"][0].pop("citation")

    issues = _quality_issues(graph)

    assert {
        (issue["code"], issue["target_key"])
        for issue in issues
        if issue["code"].startswith("invalid_character_control")
    } == {
        ("invalid_character_control_safe_scene", "missing-scene"),
        ("invalid_character_control_recovery_citation", "clinic-care"),
    }
    assert all(
        issue["waivable"] is False
        for issue in issues
        if issue["code"].startswith("invalid_character_control")
    )
