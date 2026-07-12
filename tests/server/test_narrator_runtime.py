import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.player.router_player import _settle_turn_background
from src.server.models import MechanicCompileResult, NarrationResultDTO, ResolutionResult
from tests.server.conftest import create_room, setup_auth_test_data


class _NarratorGateway:
    def __init__(self, response: dict | None = None, *, fail: bool = False):
        self.response = response or _valid_narration()
        self.fail = fail
        self.contexts: list[dict] = []

    async def narrate_action(self, context: dict, room_id: str | None = None, **_kwargs):
        self.contexts.append(context)
        if self.fail:
            raise RuntimeError("narrator provider failed")
        payload = dict(self.response)
        payload.setdefault("action_id", "narrator-action")
        return payload


class _StaticCompiler:
    def __init__(self, mechanic: str):
        self.mechanic = mechanic

    async def compile(self, *_args, **_kwargs):
        return MechanicCompileResult(triggeredMechanic=self.mechanic)


class _StaticRuleExecutor:
    async def execute(self, intent, *_args, **_kwargs):
        return ResolutionResult(
            actionId=intent.action_id,
            roomId="narrator-room",
            characterId="narrator-character",
            mechanic=intent.intent_type,
            isSuccess=True,
            narrative="deterministic fallback",
            mutations=[],
            metadata={
                "rule_summary": "The visible desk can be inspected safely.",
                "visible_state_changes": ["The desk drawer is now ajar."],
            },
        )


class _TurnPipeline:
    async def resolve_action(self, action_id: str):
        return {
            "status": "completed",
            "action_id": action_id,
            "result": {
                "narrative": f"verified narrator text for {action_id}",
                "metadata": {
                    "narration": {
                        "narrative_text": f"verified narrator text for {action_id}",
                    }
                },
            },
        }


class _FailingTurnPipeline:
    def __init__(self, conn):
        self.conn = conn

    async def resolve_action(self, action_id: str):
        self.conn.execute(
            "UPDATE actions SET status = 'resolving' WHERE action_id = %s",
            (action_id,),
        )
        self.conn.commit()
        raise ValueError("invalid provider intent")


class _ForbiddenNarrativeProvider:
    def __init__(self):
        self.calls = 0

    async def generate(self, _context):
        self.calls += 1
        return "SECONDARY UNVERIFIED NARRATIVE"


class _RecordingDispatcher:
    def __init__(self):
        self.events: list[tuple[str, str, str, dict]] = []

    async def emit(self, room_id, event_type, audience, payload, character_id=None):
        self.events.append((room_id, event_type, audience, payload))


def _valid_narration(**overrides):
    payload = {
        "context_version": 4,
        "director_plan_digest": "look-desk:4",
        "narrative_text": "Ada leans over the visible oak desk; dust shifts around the brass key.",
        "environment_changes": ["The desk drawer is now ajar."],
        "interactable_objects": ["oak desk", "brass key"],
        "open_question": "How do you examine the brass key?",
        "fact_refs": {
            "narrative_text": ["fact:ada", "fact:oak-desk", "fact:brass-key", "fact:dust"],
            "environment_changes": ["fact:desk-drawer"],
            "interactable_objects": ["fact:oak-desk", "fact:brass-key"],
            "open_question": ["fact:brass-key"],
        },
        "redacted_citations": [{"source": "scene", "page_number": 1}],
        "style_pack_version": "noir-v1",
        "provider_source": "fallback_provider",
        "status": "completed",
    }
    payload.update(overrides)
    return payload


def _setup_narrator_room(client, test_db):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    character_id = joined["character_id"]
    test_db.execute(
        "UPDATE rooms SET state_version = 4 WHERE room_id = %s",
        (room_id,),
    )
    room = test_db.execute(
        "SELECT scenario_id, scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    scenario_version_id = room["scenario_version_id"]
    test_db.execute(
        "UPDATE characters SET player_name = 'Player', xlsx_data = %s WHERE character_id = %s",
        (
            json.dumps(
                {
                    "name": "Ada",
                    "skills": {"Spot Hidden": 60},
                    "abilities": ["listen carefully"],
                    "background": "private raw original text",
                },
                ensure_ascii=False,
            ),
            character_id,
        ),
    )
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (
            json.dumps(
                {
                    "truth": {"culprit": "Hidden Count"},
                    "endings": [{"name": "Bad Ending"}],
                },
                ensure_ascii=False,
            ),
            scenario_version_id,
        ),
    )
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, input_checksum, runtime_package, created_by) "
        "VALUES (%s, %s, 1, 'ready', 'sha', %s, 'test') "
        "ON CONFLICT (runtime_package_version_id) DO UPDATE SET runtime_package = EXCLUDED.runtime_package",
        (
            f"narrator-runtime-{room_id}",
            scenario_version_id,
            json.dumps(
                {
                    "style_pack": {
                        "version": "noir-v1",
                        "voice": "grounded noir",
                    },
                    "scene_briefs": {
                        "lobby": "A visible lobby with an oak desk and a brass key."
                    },
                    "interactable_objects": ["oak desk", "brass key"],
                    "allowed_facts": [
                        {"fact_ref": "fact:ada", "text": "Ada"},
                        {"fact_ref": "fact:visible-lobby", "text": "visible lobby"},
                        {"fact_ref": "fact:oak-desk", "text": "oak desk"},
                        {"fact_ref": "fact:brass-key", "text": "brass key"},
                        {"fact_ref": "fact:desk-drawer", "text": "desk drawer"},
                        {"fact_ref": "fact:dust", "text": "dust"},
                    ],
                    "spoiler_constraints": ["Do not reveal Hidden Count or endings."],
                    "citations": [
                        {
                            "source": "scene",
                            "page_number": 1,
                            "raw_text": "RAW SECRET",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        ),
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, scene_variables, version) "
        "VALUES (%s, 'lobby', '[]', %s, 1) "
        "ON CONFLICT (room_id) DO UPDATE SET current_scene = EXCLUDED.current_scene, scene_variables = EXCLUDED.scene_variables",
        (
            room_id,
            json.dumps({"truth": "Hidden Count", "visible": "oak desk"}, ensure_ascii=False),
        ),
    )
    test_db.commit()
    return room_id, character_id, joined["player_token"]


def _insert_action(test_db, room_id: str, character_id: str, *, intent_type: str = "use_item"):
    params = {
        "director_plan": {
            "action_id": "narrator-action",
            "context_version": 4,
            "actor_display_name": "Ada",
            "declared_intent": "I inspect the brass key",
            "interpreted_intent": "inspect visible brass key",
            "intent_type": intent_type,
            "preconditions": [],
            "permissions": [],
            "mechanic_plan": {"mechanic": "auto_success"},
            "state_patch": [{"op": "replace", "path": "/hp", "value": 1}],
            "event_plan": [],
            "semantic_progression": {},
            "npc_reactions": [],
            "time_impact": {},
            "visibility": "public",
            "basis_refs": [{"source": "scene", "citation": {"page_number": 1}}],
            "citations": [{"source": "scene", "page_number": 1, "raw_text": "RAW SECRET"}],
            "confidence": 0.9,
            "requires_player_clarification": False,
            "clarification_options": [],
            "requires_host_exception": False,
            "exception_reason": None,
            "narration_mode": "summarize",
            "analysis_source": "fallback_provider",
            "state_patch_authority": "advisory_only",
        }
    }
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, idempotency_key,
            intent_type, declared_intent, params, status
        ) VALUES (
            'narrator-action', %s, %s, 'narrator-draft', 'narrator-key',
            %s, 'I inspect the brass key', %s, 'queued'
        )
        """,
        (room_id, character_id, intent_type, json.dumps(params, ensure_ascii=False)),
    )
    test_db.commit()


def test_narration_result_dto_is_strong_and_non_mutating():
    result = NarrationResultDTO(**_valid_narration(action_id="narrator-action"))
    assert result.action_id == "narrator-action"
    with pytest.raises(ValidationError):
        NarrationResultDTO(**_valid_narration(state_patch=[]))
    with pytest.raises(ValidationError):
        NarrationResultDTO(**_valid_narration(mutations=[]))


def test_narration_result_requires_human_loop_fields():
    with pytest.raises(ValidationError):
        NarrationResultDTO(**_valid_narration(environment_changes=[]))
    with pytest.raises(ValidationError):
        NarrationResultDTO(**_valid_narration(interactable_objects=[]))
    with pytest.raises(ValidationError):
        NarrationResultDTO(**_valid_narration(open_question=""))
    with pytest.raises(ValidationError):
        NarrationResultDTO(**_valid_narration(action_id="narrator-action", fact_refs={}))


def _assert_no_denied_internal_payload(value):
    denied_keys = {
        "action_id",
        "actionId",
        "local_action_id",
        "localActionId",
        "room_id",
        "roomId",
        "character_id",
        "characterId",
        "truth",
        "ending",
        "endings",
        "raw_text",
        "rawText",
        "original_text",
        "originalText",
        "source_text",
        "full_text",
    }
    denied_values = {
        "narrator-action",
        "room-v2",
        "char-v2",
        "Hidden Count",
        "Bad Ending",
        "RAW SECRET",
        "private raw original text",
        "黑祭司",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in denied_keys
            _assert_no_denied_internal_payload(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_denied_internal_payload(item)
    elif isinstance(value, str):
        for denied in denied_values:
            assert denied not in value


@pytest.mark.asyncio
async def test_non_dialogue_action_calls_narrator_with_redacted_context(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    _insert_action(test_db, room_id, character_id, intent_type="use_item")
    gateway = _NarratorGateway()

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_success"),
        rule_executor=_StaticRuleExecutor(),
        gateway=gateway,
    ).resolve_action("narrator-action")

    assert result["status"] == "completed"
    assert gateway.contexts
    context = gateway.contexts[0]
    serialized = json.dumps(context, ensure_ascii=False)
    assert context["investigator_name"] == "Ada"
    assert context["declared_intent"] == "I inspect the brass key"
    assert context["deterministic_rule_outcome"]["is_success"] is True
    assert context["runtime_package_style_pack"]["version"] == "noir-v1"
    assert all(isinstance(item, dict) for item in context["allowed_facts"])
    assert {item["fact_ref"] for item in context["allowed_facts"]} >= {
        "fact:oak-desk",
        "fact:brass-key",
    }
    _assert_no_denied_internal_payload(context)


@pytest.mark.asyncio
async def test_narrator_result_rejects_facts_outside_allowed_projection(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    _insert_action(test_db, room_id, character_id)
    gateway = _NarratorGateway(
        _valid_narration(
            narrative_text="Ada看见黑祭司藏在oak desk后面。",
            interactable_objects=["oak desk"],
            fact_refs={
                "narrative_text": ["fact:ada", "fact:unknown-cultist"],
                "environment_changes": ["fact:desk-drawer"],
                "interactable_objects": ["fact:oak-desk"],
                "open_question": ["fact:oak-desk"],
            },
        )
    )

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_success"),
        rule_executor=_StaticRuleExecutor(),
        gateway=gateway,
    ).resolve_action("narrator-action")

    assert result["status"] == "awaiting_host_exception"
    assert result["reason"] == "narrator_fact_violation"
    events = test_db.execute(
        "SELECT event_type, payload FROM events WHERE room_id = %s ORDER BY sequence",
        (room_id,),
    ).fetchall()
    assert "s2c_ai_recovery_required" in [event["event_type"] for event in events]
    assert "周围暂时没有新的变化" not in json.dumps([event["payload"] for event in events], ensure_ascii=False)


@pytest.mark.asyncio
async def test_narrator_result_requires_fact_refs_for_all_player_visible_fields(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    _insert_action(test_db, room_id, character_id)
    gateway = _NarratorGateway(_valid_narration(fact_refs={"narrative_text": ["fact:ada"]}))

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_success"),
        rule_executor=_StaticRuleExecutor(),
        gateway=gateway,
    ).resolve_action("narrator-action")

    assert result["status"] == "awaiting_host_exception"
    assert result["reason"] == "narrator_invalid_response"


@pytest.mark.asyncio
async def test_v2_action_without_verified_director_plan_fails_closed(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, idempotency_key,
            intent_type, declared_intent, params, status
        ) VALUES (
            'no-director-action', %s, %s, 'no-director-draft', 'no-director-key',
            'dialogue', 'I look around', '{}', 'queued'
        )
        """,
        (room_id, character_id),
    )
    test_db.commit()

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("dialogue"),
        rule_executor=_StaticRuleExecutor(),
    ).resolve_action("no-director-action")

    assert result["status"] == "awaiting_host_exception"
    assert result["reason"] == "director_plan_required"


@pytest.mark.asyncio
async def test_valid_narrator_output_replaces_numbered_solo_template_and_emits_event(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    _insert_action(test_db, room_id, character_id, intent_type="use_item")
    gateway = _NarratorGateway()

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_success"),
        rule_executor=_StaticRuleExecutor(),
        gateway=gateway,
    ).resolve_action("narrator-action")

    narrative = result["result"]["narrative"]
    assert "条目" not in narrative
    assert "转到条目" not in narrative
    assert "brass key" in narrative
    events = test_db.execute(
        "SELECT event_type, payload FROM events WHERE room_id = %s ORDER BY sequence",
        (room_id,),
    ).fetchall()
    event_types = [event["event_type"] for event in events]
    assert "s2c_narration_completed" in event_types
    assert "s2c_action_completed" in event_types


@pytest.mark.asyncio
async def test_narrator_provider_failure_enters_recovery_without_fake_narrative(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    _insert_action(test_db, room_id, character_id)

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_success"),
        rule_executor=_StaticRuleExecutor(),
        gateway=_NarratorGateway(fail=True),
    ).resolve_action("narrator-action")

    assert result["status"] == "awaiting_host_exception"
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'narrator-action'"
    ).fetchone()
    assert action["status"] == "awaiting_host_exception"
    assert "周围暂时没有新的变化" not in json.dumps(action["result"], ensure_ascii=False)
    events = test_db.execute(
        "SELECT event_type, payload FROM events WHERE room_id = %s ORDER BY sequence",
        (room_id,),
    ).fetchall()
    assert "s2c_ai_recovery_required" in [event["event_type"] for event in events]


def test_manual_action_hints_use_visible_context_only(client, test_db):
    room_id, _, player_token = _setup_narrator_room(client, test_db)

    response = client.post(
        "/api/player/action-hints",
        headers={"X-Room-Token": player_token},
        json={},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "examples" not in payload
    assert 3 <= len(payload["hints"]) <= 5
    joined = json.dumps(payload, ensure_ascii=False)
    assert "最佳" not in joined
    assert "1." not in joined
    assert "Hidden Count" not in joined
    assert "Bad Ending" not in joined
    assert "oak desk" in joined or "brass key" in joined


@pytest.mark.asyncio
async def test_turn_settlement_uses_verified_narrator_results_without_second_public_narrative(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    second_character_id = f"{character_id}-2"
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES (%s, %s, 'Second', 'second-token', %s)",
        (second_character_id, room_id, json.dumps({"name": "Ben"}, ensure_ascii=False)),
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status) VALUES ('turn-narrator', %s, 1, 'collecting')",
        (room_id,),
    )
    for index in range(2):
        test_db.execute(
            """
            INSERT INTO actions (
                action_id, room_id, character_id, draft_id, idempotency_key,
                turn_id, intent_type, declared_intent, params, status
            ) VALUES (
                %s, %s, %s, %s, %s,
                'turn-narrator', 'dialogue', 'I look around', '{}', 'queued'
            )
            """,
            (
                f"batch-action-{index}",
                room_id,
                character_id if index == 0 else second_character_id,
                f"batch-draft-{index}",
                f"batch-key-{index}",
            ),
        )
    test_db.commit()
    provider = _ForbiddenNarrativeProvider()
    dispatcher = _RecordingDispatcher()
    app = SimpleNamespace(
        state=SimpleNamespace(
            db=test_db,
            pg_db=None,
            pipeline=_TurnPipeline(),
            narrative_provider=provider,
            dispatcher=dispatcher,
        )
    )

    await _settle_turn_background(app, room_id, "turn-narrator")

    assert provider.calls == 0
    event_types = [event[1] for event in dispatcher.events]
    assert "s2c_turn_resolved" in event_types
    assert "s2c_public_observation" not in event_types
    turn_event = next(event for event in dispatcher.events if event[1] == "s2c_turn_resolved")
    assert "SECONDARY UNVERIFIED NARRATIVE" not in json.dumps(turn_event[3], ensure_ascii=False)
    assert "verified narrator text for batch-action-0" in json.dumps(turn_event[3], ensure_ascii=False)


@pytest.mark.asyncio
async def test_turn_settlement_routes_resolution_exception_to_host_queue(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status) VALUES ('turn-failure', %s, 1, 'collecting')",
        (room_id,),
    )
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, draft_id, idempotency_key,
            turn_id, intent_type, declared_intent, params, status
        ) VALUES (
            'failed-action', %s, %s, 'failed-draft', 'failed-key',
            'turn-failure', 'dialogue', 'I look around', '{}', 'queued'
        )
        """,
        (room_id, character_id),
    )
    test_db.commit()
    app = SimpleNamespace(
        state=SimpleNamespace(
            db=test_db,
            pg_db=None,
            pipeline=_FailingTurnPipeline(test_db),
            dispatcher=_RecordingDispatcher(),
        )
    )

    await _settle_turn_background(app, room_id, "turn-failure")

    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'failed-action'"
    ).fetchone()
    assert action["status"] == "awaiting_host_exception"
    assert "resolution_pipeline_error" in json.dumps(action["result"])
    event_types = [event[1] for event in app.state.dispatcher.events]
    assert "s2c_action_exception_requested" in event_types
    assert "s2c_ai_recovery_required" in event_types
