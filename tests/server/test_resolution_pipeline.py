import json
import random
from contextlib import contextmanager

import pytest

from src.server.ai.contracts import KpResponse, NarrativePayload
from src.server.ai.mechanic_compiler import MechanicCompiler
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.models import MechanicCompileResult, PlayerIntent, ResolutionResult


class Rows:
    def __init__(self, rows=None, *, rowcount=None):
        self.rows = rows or []
        self.rowcount = len(self.rows) if rowcount is None else rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self):
        self.rooms = {
            "room-1": {
                "room_id": "room-1",
                "scenario_id": None,
                "state_version": 0,
            }
        }
        self.characters = {
            "char-1": {
                "character_id": "char-1",
                "room_id": "room-1",
                "player_name": "Alice",
                "xlsx_data": {"skills": {"侦查": 60}, "hp": 10, "san": 50, "luck": 40},
            }
        }
        self.actions = {
            "act-1": {
                "action_id": "act-1",
                "room_id": "room-1",
                "character_id": "char-1",
                "intent_type": "dialogue",
                "declared_intent": "我侦查房间",
                "status": "queued",
                "result": None,
            }
        }
        self.inventory = []
        self.scenarios = {}
        self.events = []
        self.resolution_bundles = []
        self.last_insert_params = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        params = params or ()
        if normalized.startswith(
            "SELECT rule_source_status, rule_source_reason FROM rooms WHERE room_id"
        ):
            room = self.rooms.get(params[0])
            if not room:
                return Rows()
            return Rows([{
                "rule_source_status": room.get("rule_source_status"),
                "rule_source_reason": room.get("rule_source_reason"),
            }])
        if normalized.startswith("SELECT * FROM actions WHERE action_id"):
            return Rows([self.actions[params[0]]] if params[0] in self.actions else [])
        if normalized.startswith("SELECT * FROM actions WHERE room_id"):
            room_id, status = params
            return Rows([
                a for a in self.actions.values()
                if a["room_id"] == room_id and a["status"] == status
            ])
        if normalized.startswith("UPDATE actions SET status = %s WHERE action_id = %s AND status = %s RETURNING"):
            status, action_id, expected_status = params
            action = self.actions.get(action_id)
            if not action or action["status"] != expected_status:
                return Rows()
            action["status"] = status
            return Rows([action])
        if normalized.startswith("UPDATE actions SET status = %s WHERE action_id"):
            status, action_id = params
            self.actions[action_id]["status"] = status
            return Rows()
        if normalized.startswith("UPDATE actions SET status = %s, result = %s, completed_at"):
            status, result, _completed_at, action_id = params
            self.actions[action_id]["status"] = status
            self.actions[action_id]["result"] = json.loads(result) if isinstance(result, str) else result
            return Rows()
        if normalized.startswith("SELECT * FROM characters WHERE character_id"):
            return Rows([self.characters[params[0]]] if params[0] in self.characters else [])
        if normalized.startswith("SELECT * FROM rooms WHERE room_id"):
            return Rows([self.rooms[params[0]]] if params[0] in self.rooms else [])
        if normalized.startswith(
            "SELECT scenario_version_id, runtime_package_version_id FROM rooms WHERE room_id"
        ):
            return Rows([self.rooms[params[0]]] if params[0] in self.rooms else [])
        if normalized.startswith("SELECT state_version") and "FROM rooms WHERE room_id" in normalized:
            return Rows([self.rooms[params[0]]] if params[0] in self.rooms else [])
        if normalized.startswith("SELECT * FROM scenarios WHERE scenario_id"):
            return Rows([self.scenarios[params[0]]] if params[0] in self.scenarios else [])
        if normalized.startswith("SELECT * FROM inventory WHERE character_id"):
            return Rows([i for i in self.inventory if i["character_id"] == params[0]])
        if normalized.startswith("UPDATE rooms SET state_version = state_version + 1"):
            self.rooms[params[0]]["state_version"] += 1
            return Rows([{"state_version": self.rooms[params[0]]["state_version"]}])
        if normalized.startswith("INSERT INTO events"):
            room_id, event_type, audience, payload = params
            self.events.append({
                "room_id": room_id,
                "event_type": event_type,
                "audience": audience,
                "payload": json.loads(payload) if isinstance(payload, str) else payload,
            })
            return Rows([{"sequence": len(self.events)}])
        if normalized.startswith("INSERT INTO resolution_bundles"):
            (
                action_id,
                room_id,
                character_id,
                canonical_result,
                rule_explanation,
                actor_projection,
                stage_projection,
                host_console,
                release_status,
            ) = params
            self.resolution_bundles.append({
                "action_id": action_id,
                "room_id": room_id,
                "character_id": character_id,
                "status": canonical_result.get("status", "resolved") if isinstance(canonical_result, dict) else "resolved",
                "bundle": {
                    "authoritative_result": json.loads(canonical_result) if isinstance(canonical_result, str) else canonical_result,
                    "rule_explanation": json.loads(rule_explanation) if isinstance(rule_explanation, str) else rule_explanation,
                    "player_projection": json.loads(actor_projection) if isinstance(actor_projection, str) else actor_projection,
                    "party_projection": json.loads(stage_projection) if isinstance(stage_projection, str) else stage_projection,
                    "host_projection": json.loads(host_console) if isinstance(host_console, str) else host_console,
                    "release_status": release_status,
                },
            })
            return Rows()
        if normalized.startswith("UPDATE resolution_bundles SET actor_projection"):
            actor_projection, stage_projection, host_console, release_status, action_id = params
            for saved in self.resolution_bundles:
                if saved["action_id"] == action_id:
                    saved["bundle"]["player_projection"] = json.loads(actor_projection) if isinstance(actor_projection, str) else actor_projection
                    saved["bundle"]["party_projection"] = json.loads(stage_projection) if isinstance(stage_projection, str) else stage_projection
                    saved["bundle"]["host_projection"] = json.loads(host_console) if isinstance(host_console, str) else host_console
                    saved["bundle"]["release_status"] = release_status
                    break
            return Rows()
        if normalized.startswith("UPDATE resolution_bundles SET release_status = %s WHERE action_id"):
            release_status, action_id = params
            for saved in self.resolution_bundles:
                if saved["action_id"] == action_id:
                    saved["bundle"]["release_status"] = release_status
                    break
            return Rows()
        if normalized.startswith("SELECT actor_projection, stage_projection, host_console, release_status FROM resolution_bundles"):
            for saved in self.resolution_bundles:
                if saved["action_id"] == params[0]:
                    bundle = saved["bundle"]
                    return Rows([{
                        "actor_projection": json.dumps(bundle["player_projection"], ensure_ascii=False),
                        "stage_projection": json.dumps(bundle["party_projection"], ensure_ascii=False),
                        "host_console": json.dumps(bundle["host_projection"], ensure_ascii=False),
                        "release_status": bundle["release_status"],
                    }])
            return Rows()
        if normalized.startswith("SELECT status FROM rooms WHERE room_id"):
            return Rows([self.rooms.get(params[0])])
        if normalized.startswith("SELECT 1 FROM player_action_submissions"):
            return Rows([])
        if normalized.startswith("SELECT COUNT(*) AS count FROM action_consents"):
            return Rows([{"count": 0}])
        if normalized.startswith("SELECT d.decision_audit_required FROM actions"):
            return Rows([{"decision_audit_required": False}])
        if normalized.startswith("UPDATE ai_call_logs SET"):
            return Rows(rowcount=0)
        if normalized.startswith("SELECT * FROM character_runtime_state WHERE character_id"):
            return Rows([])  # No existing runtime state
        if normalized.startswith("INSERT INTO character_runtime_state"):
            self.last_insert_params = params
            return Rows()
        if normalized.startswith("UPDATE character_runtime_state"):
            return Rows()
        raise AssertionError(f"Unhandled SQL: {normalized}")

    def commit(self):
        pass

    @contextmanager
    def transaction(self):
        yield self


class FakeDispatcher:
    def __init__(self):
        self.events = []

    async def emit(self, room_id, event_type, audience, payload, character_id=None):
        self.events.append((room_id, event_type, audience, payload, character_id))


class FailingProjectionDispatcher(FakeDispatcher):
    def __init__(self):
        super().__init__()
        self.fail_public_projection = True

    async def emit(self, room_id, event_type, audience, payload, character_id=None):
        if self.fail_public_projection and event_type == "s2c_public_observation":
            raise RuntimeError("projection unavailable")
        await super().emit(room_id, event_type, audience, payload, character_id)


class FakeStateService:
    """StateService stub that bumps version for testing."""
    def __init__(self):
        self.changes = []

    def apply_change(self, room_id, actor, changes, reason=""):
        # Simulate what real StateService does: bump room version
        self.changes.append({"room_id": room_id, "changes": changes, "reason": reason})
        return {"room_id": room_id, "state_version": 1, "applied": {}, "events": []}


class GatewayReturningNarrativePayload:
    async def generate_narrative(self, context, room_id=None):
        return NarrativePayload(public="窗外的风掠过木板缝隙，带来一阵短促的呜咽。")


class GatewayReturningKpResponse:
    async def generate_narrative(self, context, room_id=None):
        return KpResponse(
            narrative=NarrativePayload(public="你的话音刚落，屋里忽然安静得能听见墙后细碎的摩擦声。")
        )


class FailingRuleExecutor:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("handler failed with SECRET_RULE_INPUT")


class CompositeRuleExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, intent, _compiled, character, _inventory, _scenario_assets):
        self.calls.append(intent.declared_intent)
        return ResolutionResult(
            actionId=intent.action_id,
            roomId=character["room_id"],
            characterId=character["character_id"],
            mechanic=intent.intent_type,
            isSuccess=intent.params.get("expected_success", True),
        )


class CharacterAndEncounterMutationRuleExecutor:
    async def execute(self, intent, _compiled, character, _inventory, _scenario_assets):
        return ResolutionResult(
            actionId=intent.action_id,
            roomId=character["room_id"],
            characterId=character["character_id"],
            mechanic="combat_attack",
            isSuccess=True,
            mutations=[
                {"op": "replace", "path": "/character/luck", "value": 39},
                {
                    "op": "replace",
                    "path": "/encounter/enc-1/participants/npc:hidden/hp_delta",
                    "value": -3,
                },
            ],
        )


@pytest.mark.asyncio
async def test_pipeline_resolves_queued_action_and_projects_events():
    random.seed(0)
    conn = FakeConn()
    dispatcher = FakeDispatcher()
    state_svc = FakeStateService()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=dispatcher,
        state_service=state_svc,
    )

    result = await pipeline.resolve_action("act-1")

    assert result["status"] == "resolved"
    assert conn.actions["act-1"]["status"] == "resolved"
    # State version is NOT directly bumped by pipeline anymore (StateService owns it)
    # The pipeline only bumps via StateService when mutations exist
    assert conn.actions["act-1"]["result"]["mechanic"] == "skill_check"
    assert len(conn.resolution_bundles) == 1
    bundle = conn.resolution_bundles[0]
    assert bundle["action_id"] == "act-1"
    assert bundle["status"] == "resolved"
    assert bundle["bundle"]["authoritative_result"]["actionId"] == "act-1"
    assert bundle["bundle"]["player_projection"]["actionId"] == "act-1"
    assert bundle["bundle"]["party_projection"]["narrativeText"]
    event_types = [event[1] for event in dispatcher.events]
    assert "s2c_reveal_transaction" in event_types
    assert "s2c_action_completed" in event_types


@pytest.mark.asyncio
async def test_pipeline_resolves_batched_action():
    conn = FakeConn()
    conn.actions["act-1"]["status"] = "batched"

    result = await ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=FakeDispatcher(),
    ).resolve_action("act-1")

    assert result["status"] == "resolved"
    assert conn.actions["act-1"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_pipeline_never_sends_encounter_mutations_to_state_service():
    conn = FakeConn()
    dispatcher = FakeDispatcher()
    state_svc = FakeStateService()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=dispatcher,
        rule_executor=CharacterAndEncounterMutationRuleExecutor(),
        state_service=state_svc,
    )

    result = await pipeline.resolve_action("act-1")

    assert result["status"] == "resolved"
    changes = state_svc.changes[0]["changes"].model_dump(by_alias=True)
    assert changes["characterMutations"] == [
        {
            "characterId": "char-1",
            "mutations": [{"op": "replace", "path": "/character/luck", "value": 39}],
            "permanent": False,
        }
    ]


@pytest.mark.asyncio
async def test_projection_failure_keeps_resolution_complete_and_replays_saved_bundle_only():
    conn = FakeConn()
    dispatcher = FailingProjectionDispatcher()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=dispatcher,
    )

    result = await pipeline.resolve_action("act-1")

    assert result["status"] == "resolved"
    assert conn.actions["act-1"]["status"] == "resolved"
    assert conn.resolution_bundles[0]["bundle"]["release_status"] == "projection_pending"

    dispatcher.fail_public_projection = False
    replayed = await pipeline.replay_projection("act-1")

    assert replayed == {"status": "replayed", "action_id": "act-1"}
    assert conn.actions["act-1"]["status"] == "resolved"
    assert conn.resolution_bundles[0]["bundle"]["release_status"] == "released"
    assert any(event[1] == "s2c_action_completed" for event in dispatcher.events)


@pytest.mark.asyncio
async def test_pipeline_includes_skill_check_result_in_action_completed_projection():
    random.seed(0)
    conn = FakeConn()
    conn.characters["char-1"]["xlsx_data"]["skills"] = {"Spot": 60}
    conn.actions["act-1"].update({
        "intent_type": "skill_check",
        "declared_intent": "roll Spot",
        "params": json.dumps({"skillName": "Spot"}),
    })
    dispatcher = FakeDispatcher()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=dispatcher,
    )

    await pipeline.resolve_action("act-1")

    completed = [
        event for event in dispatcher.events
        if event[1] == "s2c_action_completed" and event[3]["status"] == "resolved"
    ][0]
    payload = completed[3]
    assert payload["skill_name"] == "Spot"
    assert payload["skillName"] == "Spot"
    assert payload["target"] == 60
    assert isinstance(payload["roll"], int)
    assert "level" in payload
    assert "success" in payload


@pytest.mark.asyncio
async def test_pipeline_rejects_when_rule_handler_fails_without_partial_projection(caplog):
    conn = FakeConn()
    dispatcher = FakeDispatcher()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=dispatcher,
        rule_executor=FailingRuleExecutor(),
    )

    result = await pipeline.resolve_action("act-1")

    assert result["status"] == "rejected"
    assert conn.actions["act-1"]["status"] == "rejected"
    assert result["reason"] == "resolution_failed"
    assert conn.actions["act-1"]["result"]["reason"] == "resolution_failed"
    assert "SECRET_RULE_INPUT" not in json.dumps(
        {"result": result, "action": conn.actions["act-1"], "events": dispatcher.events}
    )
    assert "SECRET_RULE_INPUT" not in caplog.text
    event_types = [event[1] for event in dispatcher.events]
    assert event_types == ["s2c_action_completed"]


@pytest.mark.asyncio
async def test_composite_action_cancels_its_second_stage_after_first_stage_failure():
    conn = FakeConn()
    conn.actions["act-1"]["params"] = json.dumps({
        "composite_steps": [
            {
                "step_id": "step_1",
                "summary": "先撬门",
                "declared_intent": "先撬门",
                "intent_type": "skill_check",
                "params": {"expected_success": False},
                "on_previous_failure": "cancel",
            },
            {
                "step_id": "step_2",
                "summary": "再进入房间",
                "declared_intent": "再进入房间",
                "intent_type": "move",
                "params": {"expected_success": True},
                "on_previous_failure": "cancel",
            },
        ],
    })
    executor = CompositeRuleExecutor()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=FakeDispatcher(),
        rule_executor=executor,
    )

    result = await pipeline.resolve_action("act-1")

    assert result["status"] == "resolved"
    assert executor.calls == ["先撬门"]
    phases = result["result"]["metadata"]["composite_action"]["phases"]
    assert [phase["status"] for phase in phases] == ["failed", "canceled"]


@pytest.mark.asyncio
async def test_composite_action_can_continue_to_its_second_stage_after_failure():
    conn = FakeConn()
    conn.actions["act-1"]["params"] = json.dumps({
        "composite_steps": [
            {
                "step_id": "step_1",
                "summary": "先撬门",
                "declared_intent": "先撬门",
                "intent_type": "skill_check",
                "params": {"expected_success": False},
                "on_previous_failure": "cancel",
            },
            {
                "step_id": "step_2",
                "summary": "改从窗户进入",
                "declared_intent": "改从窗户进入",
                "intent_type": "move",
                "params": {"expected_success": True},
                "on_previous_failure": "continue",
            },
        ],
    })
    executor = CompositeRuleExecutor()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=FakeDispatcher(),
        rule_executor=executor,
    )

    result = await pipeline.resolve_action("act-1")

    assert result["status"] == "resolved"
    assert executor.calls == ["先撬门", "改从窗户进入"]
    phases = result["result"]["metadata"]["composite_action"]["phases"]
    assert [phase["status"] for phase in phases] == ["failed", "completed"]


@pytest.mark.asyncio
async def test_conditional_follow_up_executes_only_after_a_failed_first_step():
    conn = FakeConn()
    conn.actions["act-1"]["params"] = json.dumps({
        "composite_steps": [
            {
                "step_id": "step_1",
                "summary": "先试着撬门",
                "declared_intent": "先试着撬门",
                "intent_type": "skill_check",
                "params": {"expected_success": False},
                "on_previous_failure": "cancel",
            },
            {
                "step_id": "step_2",
                "summary": "如果撬不开就改从窗户进入",
                "declared_intent": "改从窗户进入",
                "intent_type": "move",
                "params": {"expected_success": True},
                "execution_condition": "previous_step_failure",
                "on_previous_failure": "cancel",
            },
        ],
    })
    executor = CompositeRuleExecutor()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=FakeDispatcher(),
        rule_executor=executor,
    )

    result = await pipeline.resolve_action("act-1")

    assert result["status"] == "resolved"
    assert executor.calls == ["先试着撬门", "改从窗户进入"]
    phases = result["result"]["metadata"]["composite_action"]["phases"]
    assert [phase["status"] for phase in phases] == ["failed", "completed"]


def test_composite_steps_downgrade_legacy_choice_policy_to_cancel():
    steps = ResolutionPipeline._composite_steps({
        "composite_steps": [
            {
                "step_id": "step_1",
                "summary": "先撬门",
                "declared_intent": "先撬门",
                "intent_type": "skill_check",
                "params": {},
                "on_previous_failure": "cancel",
            },
            {
                "step_id": "step_2",
                "summary": "再进入房间",
                "declared_intent": "再进入房间",
                "intent_type": "move",
                "params": {},
                "on_previous_failure": "ask",
            },
        ],
    })

    assert steps[1]["on_previous_failure"] == "cancel"


@pytest.mark.asyncio
async def test_pipeline_skips_action_already_being_resolved():
    conn = FakeConn()
    conn.actions["act-1"]["status"] = "resolving"
    dispatcher = FakeDispatcher()
    pipeline = ResolutionPipeline(
        conn=conn,
        compiler=MechanicCompiler(api_key=""),
        dispatcher=dispatcher,
    )

    result = await pipeline.resolve_action("act-1")

    assert result == {"status": "resolving", "action_id": "act-1"}
    assert dispatcher.events == []


def test_render_fallback_narrative_handles_identity_question():
    pipeline = ResolutionPipeline(conn=FakeConn(), compiler=MechanicCompiler(api_key=""))

    text = pipeline._render_fallback_narrative(
        PlayerIntent(action_id="act-id", intent_type="dialogue", declared_intent="我是谁？"),
        MechanicCompileResult(triggeredMechanic="dialogue"),
        ResolutionResult(
            actionId="act-id",
            roomId="room-1",
            characterId="char-1",
            mechanic="dialogue",
            isSuccess=True,
        ),
        {
            "player_name": "Alice",
            "xlsx_data": {"name": "菲利普·格雷", "occupation": "教授"},
        },
    )

    assert "菲利普·格雷" in text
    assert "教授" in text


def test_render_fallback_narrative_is_action_specific_without_generic_no_change_line():
    pipeline = ResolutionPipeline(conn=FakeConn(), compiler=MechanicCompiler(api_key=""))

    text = pipeline._render_fallback_narrative(
        PlayerIntent(
            action_id="act-look",
            intent_type="dialogue",
            declared_intent="我仔细阅读桌上的旧报纸",
        ),
        MechanicCompileResult(triggeredMechanic="dialogue"),
        ResolutionResult(
            actionId="act-look",
            roomId="room-1",
            characterId="char-1",
            mechanic="dialogue",
            isSuccess=True,
        ),
        {"player_name": "Alice", "xlsx_data": {"name": "菲利普·格雷"}},
    )

    assert "旧报纸" in text
    assert "注意力" in text
    assert "周围暂时没有新的变化" not in text
    assert "没有明显效果" not in text


@pytest.mark.asyncio
async def test_enrich_dialogue_narrative_accepts_narrative_payload():
    pipeline = ResolutionPipeline(
        conn=FakeConn(),
        compiler=MechanicCompiler(api_key=""),
        gateway=GatewayReturningNarrativePayload(),
    )

    text = await pipeline._enrich_dialogue_narrative(
        {"room_id": "room-1", "character_id": "char-1", "declared_intent": "我轻声询问屋里是否有人"},
        {
            "player_name": "Alice",
            "xlsx_data": {"name": "菲利普·格雷", "occupation": "教授"},
        },
        {"room_id": "room-1"},
        None,
    )

    assert text == "窗外的风掠过木板缝隙，带来一阵短促的呜咽。"


@pytest.mark.asyncio
async def test_enrich_dialogue_narrative_accepts_kp_response():
    pipeline = ResolutionPipeline(
        conn=FakeConn(),
        compiler=MechanicCompiler(api_key=""),
        gateway=GatewayReturningKpResponse(),
    )

    text = await pipeline._enrich_dialogue_narrative(
        {"room_id": "room-1", "character_id": "char-1", "declared_intent": "我试着和同伴确认刚才的脚步声"},
        {
            "player_name": "Alice",
            "xlsx_data": {"name": "菲利普·格雷", "occupation": "教授"},
        },
        {"room_id": "room-1"},
        None,
    )

    assert text == "你的话音刚落，屋里忽然安静得能听见墙后细碎的摩擦声。"
