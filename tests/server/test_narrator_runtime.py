import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.server.engine import resolution_pipeline
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.state_service import StateService
from src.server.player.router_player import _settle_turn_background
from src.server.models import MechanicCompileResult, NarrationResultDTO, ResolutionResult
from src.server.ai import narrator as narrator_module
from src.server.ai.contracts import CombatRoundSuggestion
from src.server.ai.narrator import (
    _visible_state_changes,
    build_narrator_context,
    validate_narration_result,
)
from tests.server.conftest import create_room, setup_auth_test_data


class _NarratorGateway:
    def __init__(self, response: dict | None = None, *, fail: bool = False):
        self.response = response or _valid_narration()
        self.fail = fail
        self.contexts: list[dict] = []
        self.call_kwargs: list[dict] = []

    async def narrate_action(self, context: dict, room_id: str | None = None, **_kwargs):
        self.contexts.append(context)
        self.call_kwargs.append(dict(_kwargs))
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


class _FailureRuleExecutor:
    async def execute(self, intent, *_args, **_kwargs):
        return ResolutionResult(
            actionId=intent.action_id,
            roomId="narrator-room",
            characterId="narrator-character",
            mechanic=intent.intent_type,
            isSuccess=False,
            narrative="deterministic failed investigation",
            mutations=[],
            metadata={},
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


class _OrderedTurnPipeline:
    def __init__(self):
        self.action_ids = []

    async def resolve_action(self, action_id: str):
        self.action_ids.append(action_id)
        return {
            "status": "completed",
            "action_id": action_id,
            "result": {"narrative": f"公开结果 {action_id}"},
        }


class _CombatRoundGateway:
    def __init__(self):
        self.contexts: list[dict] = []

    async def resolve_combat_round(self, context: dict, room_id: str | None = None):
        self.contexts.append({"context": context, "room_id": room_id})
        if len(self.contexts) > 1:
            return CombatRoundSuggestion(
                clusters=[
                    {"actionIds": ["combat-slow"], "publicTitle": "North exit retreat"}
                ],
                dependencies=[],
            )
        return CombatRoundSuggestion(
            clusters=[
                {"actionIds": ["combat-fast"], "publicTitle": "Doorway exchange"}
            ],
            dependencies=[
                {"actionId": "combat-fast", "dependsOnActionIds": []}
            ],
        )


def test_solo_transition_exposes_a_safe_visible_change_without_node_number():
    result = ResolutionResult(
        actionId="solo-action",
        roomId="solo-room",
        characterId="solo-character",
        mechanic="move",
        metadata={
            "solo_adventure_transition": {
                "from_node_id": "1",
                "target_node_id": "263",
                "is_ending": False,
            }
        },
    )

    assert _visible_state_changes(result) == ["你已抵达新的可见场景。"]


def test_generic_scene_transition_exposes_a_safe_visible_change():
    result = ResolutionResult(
        actionId="generic-action",
        roomId="generic-room",
        characterId="generic-character",
        mechanic="move",
        metadata={
            "generic_scene_transition": {
                "from_scene_id": "study",
                "target_scene_id": "harbor",
            }
        },
    )

    assert _visible_state_changes(result) == ["你已抵达新的可见场景。"]


def test_narrator_context_uses_visible_solo_scene_when_runtime_brief_is_missing(client, test_db):
    from src.server.scenario.content_projection import ContentProjectionService

    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    version = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    graph = {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "条目 1",
                    "text": "司机发动长途车，车窗外的街道慢慢远去。请转到 263。",
                    "target_node_ids": ["263"],
                    "citation": {"page_number": 4},
                },
                {
                    "node_id": "263",
                    "title": "条目 263",
                    "text": "未到达的后续内容。",
                    "target_node_ids": [],
                    "citation": {"page_number": 58},
                },
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph, ensure_ascii=False), version),
    )
    ContentProjectionService(test_db).rebuild(version, graph, requested_by="test")
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'solo:1' WHERE room_id = %s",
        (room_id,),
    )
    _insert_action(test_db, room_id, character_id)
    action = test_db.execute("SELECT * FROM actions WHERE action_id = 'narrator-action'").fetchone()
    character = test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    room = test_db.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()

    context = build_narrator_context(
        test_db,
        action,
        character,
        room,
        ResolutionResult(
            actionId="narrator-action",
            roomId=room_id,
            characterId=character_id,
        ),
    )

    assert "长途车" in context["scene_brief"]
    assert "263" not in context["scene_brief"]
    assert "转到" not in context["scene_brief"]
    assert {
        "fact_ref": "fact:scene-brief",
        "text": context["scene_brief"],
    } in context["allowed_facts"]
    assert context["rule_version"] != "unversioned"


def test_narrator_context_uses_compiled_generic_scene_description(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    runtime_row = test_db.execute(
        "SELECT runtime_package FROM runtime_package_versions WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (room_id,),
    ).fetchone()
    runtime_package = dict(runtime_row["runtime_package"])
    runtime_package["semantic_scenes"] = [{
        "scene_id": "harbor",
        "name": "雾港",
        "description": "潮湿的栈桥消失在浓雾里，远处传来断续的船铃。",
    }]
    test_db.execute(
        "UPDATE runtime_package_versions SET runtime_package = %s WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (json.dumps(runtime_package, ensure_ascii=False), room_id),
    )
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'harbor' WHERE room_id = %s",
        (room_id,),
    )
    _insert_action(test_db, room_id, character_id)
    action = test_db.execute("SELECT * FROM actions WHERE action_id = 'narrator-action'").fetchone()
    character = test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    room = test_db.execute("SELECT * FROM rooms WHERE room_id = %s", (room_id,)).fetchone()

    context = build_narrator_context(
        test_db,
        action,
        character,
        room,
        ResolutionResult(
            actionId="narrator-action",
            roomId=room_id,
            characterId=character_id,
        ),
    )

    assert "雾港" in context["scene_brief"]
    assert "潮湿的栈桥" in context["scene_brief"]
    assert context["scene_brief"] != "harbor"


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


def test_narrator_normalizes_safe_supplier_shape_variants_before_validation():
    from src.server.ai.gateway import _normalize_narrator_provider_result

    context = {
        "allowed_facts": [{
            "fact_ref": "fact:scene-brief",
            "text": "修表摊旁的灯还亮着，眼前只有可见的柜台。",
        }],
        "visible_state_changes": [],
        "interactable_objects": [],
        "context_version": 4,
        "director_plan_digest": "inspect-stall:4",
    }
    raw = _valid_narration(
        environment_changes="修表摊旁的灯还亮着。",
        interactable_objects=[{"name": "不应直接展示的对象结构"}],
        fact_refs={
            "narrative_text": ["fact:scene-brief"],
            "environment_changes": ["fact:scene-brief"],
            "interactable_objects": ["fact:scene-brief"],
            "open_question": ["fact:scene-brief"],
        },
    )

    normalized = _normalize_narrator_provider_result(raw, context)

    assert normalized["environment_changes"] == ["修表摊旁的灯还亮着。"]
    assert normalized["interactable_objects"] == ["当前环境"]
    assert normalized["fact_refs"]["interactable_objects"] == ["fact:scene-brief"]
    NarrationResultDTO(**{
        **normalized,
        "action_id": "narrator-action",
        "provider_source": "configured_provider",
    })


def test_narrator_normalizes_empty_environment_to_a_safe_visible_fallback():
    from src.server.ai.gateway import _normalize_narrator_provider_result

    context = {
        "allowed_facts": [{
            "fact_ref": "fact:scene-brief",
            "text": "夜市修表摊仍在眼前。",
        }],
        "visible_state_changes": [],
        "interactable_objects": ["当前环境"],
        "context_version": 4,
        "director_plan_digest": "talk-watchmaker:4",
    }
    raw = _valid_narration(
        environment_changes=[],
        interactable_objects=["当前环境"],
        fact_refs={
            "narrative_text": ["fact:scene-brief"],
            "environment_changes": ["fact:scene-brief"],
            "interactable_objects": ["fact:scene-brief"],
            "open_question": ["fact:scene-brief"],
        },
    )

    normalized = _normalize_narrator_provider_result(raw, context)

    assert normalized["environment_changes"] == ["当前场景仍可互动。"]
    assert normalized["fact_refs"]["environment_changes"] == ["fact:scene-brief"]
    NarrationResultDTO(**{
        **normalized,
        "action_id": "narrator-action",
        "provider_source": "configured_provider",
    })


def test_narrator_rejects_vehicle_conflict_against_visible_scene():
    narration = NarrationResultDTO(
        **_valid_narration(
            action_id="narrator-action",
            narrative_text="阿达登上马车，沿着道路继续前行。",
            fact_refs={
                "narrative_text": ["fact:scene-brief"],
                "environment_changes": ["fact:scene-brief"],
                "interactable_objects": ["fact:scene-brief"],
                "open_question": ["fact:scene-brief"],
            },
        )
    )

    violation = validate_narration_result(
        narration,
        {
            "allowed_facts": [
                {"fact_ref": "fact:scene-brief", "text": "司机发动长途车，车窗外的街道慢慢远去。"}
            ]
        },
    )

    assert violation == "narrator_scene_fact_conflict"


def test_narrator_cannot_launder_player_hypothesis_as_world_truth():
    narration = NarrationResultDTO(
        **_valid_narration(
            action_id="narrator-action",
            narrative_text="站长是凶手，已经没有任何疑问。",
            fact_refs={
                "narrative_text": ["fact:scene-brief"],
                "environment_changes": ["fact:scene-brief"],
                "interactable_objects": ["fact:scene-brief"],
                "open_question": ["fact:scene-brief"],
            },
        )
    )

    violation = validate_narration_result(
        narration,
        {
            "allowed_facts": [{
                "fact_ref": "fact:scene-brief",
                "text": "候车室里只看得见一张旧桌子。",
            }],
            "player_hypotheses": [{
                "text": "我怀疑站长可能就是凶手。",
                "epistemic_status": "player_hypothesis_not_world_truth",
            }],
        },
    )

    assert violation == "narrator_hypothesis_violation"


def test_verified_solo_transition_narration_uses_visible_scene_fact_only():
    narration = narrator_module.build_verified_narration(
        {
            "allowed_facts": [
                {
                    "fact_ref": "fact:scene-brief",
                    "text": "长途车突突地响着，在乡间缓慢挪动。车里的气氛令人窒息。",
                },
                {"fact_ref": "fact:visible-change:1", "text": "你已抵达新的可见场景。"},
            ],
            "visible_state_changes": ["你已抵达新的可见场景。"],
            "interactable_objects": [],
            "context_version": 5,
            "director_plan_digest": "solo:134",
            "redacted_citations": [],
            "runtime_package_style_pack": {"version": "default"},
        },
        action_id="solo-action",
    )

    assert narration.narrative_text == "长途车突突地响着，在乡间缓慢挪动。车里的气氛令人窒息。"
    assert "马车" not in narration.narrative_text
    assert narration.provider_source == "local_fallback"
    assert narration.fact_refs["narrative_text"] == ["fact:scene-brief"]


@pytest.mark.asyncio
async def test_solo_transition_uses_verified_provider_narration_before_local_fallback(
    test_db,
    monkeypatch,
):
    context = {
        "allowed_facts": [
            {"fact_ref": "fact:scene-brief", "text": "长途车沿着山路驶向村庄。"},
            {"fact_ref": "fact:visible-change:1", "text": "你已抵达新的可见场景。"},
            {"fact_ref": "fact:bus", "text": "长途车"},
        ],
        "visible_state_changes": ["你已抵达新的可见场景。"],
        "interactable_objects": ["长途车"],
        "context_version": 4,
        "director_plan_digest": "solo:1",
        "redacted_citations": [],
        "runtime_package_style_pack": {"version": "default"},
    }
    gateway = _NarratorGateway(
        _valid_narration(
            narrative_text="长途车沿着山路颠簸前行，窗外的村庄渐渐靠近。",
            environment_changes=["你已抵达新的可见场景。"],
            interactable_objects=["长途车"],
            open_question="你想先观察车厢里的什么？",
            fact_refs={
                "narrative_text": ["fact:scene-brief"],
                "environment_changes": ["fact:visible-change:1"],
                "interactable_objects": ["fact:bus"],
                "open_question": ["fact:bus"],
            },
        )
    )
    monkeypatch.setattr(
        resolution_pipeline,
        "build_narrator_context",
        lambda *_args, **_kwargs: context,
    )
    resolution = ResolutionResult(
        actionId="narrator-action",
        roomId="solo-room",
        characterId="solo-character",
        mechanic="move",
        metadata={
            "solo_adventure_transition": {
                "from_node_id": "1",
                "target_node_id": "263",
                "is_ending": False,
            }
        },
    )

    error = await ResolutionPipeline(test_db, gateway=gateway)._apply_narrator(
        {"action_id": "narrator-action", "room_id": "solo-room"},
        {"character_id": "solo-character"},
        {"room_id": "solo-room"},
        resolution,
    )

    assert error is None
    assert len(gateway.contexts) == 1
    assert gateway.call_kwargs == [{
        "action_id": "narrator-action",
        "timeout_seconds": 55,
    }]
    assert resolution.narrative == "长途车沿着山路颠簸前行，窗外的村庄渐渐靠近。"
    assert resolution.metadata["narration"]["provider_source"] == "fallback_provider"


@pytest.mark.asyncio
async def test_solo_transition_falls_back_when_provider_raises(test_db, monkeypatch):
    context = {
        "allowed_facts": [
            {"fact_ref": "fact:scene-brief", "text": "长途车沿着山路驶向村庄。"},
            {"fact_ref": "fact:visible-change:1", "text": "你已抵达新的可见场景。"},
        ],
        "visible_state_changes": ["你已抵达新的可见场景。"],
        "interactable_objects": [],
        "context_version": 4,
        "director_plan_digest": "solo:1",
        "redacted_citations": [],
        "runtime_package_style_pack": {"version": "default"},
    }
    monkeypatch.setattr(
        resolution_pipeline,
        "build_narrator_context",
        lambda *_args, **_kwargs: context,
    )
    resolution = ResolutionResult(
        actionId="narrator-action",
        roomId="solo-room",
        characterId="solo-character",
        mechanic="move",
        metadata={
            "solo_adventure_transition": {
                "from_node_id": "1",
                "target_node_id": "263",
                "is_ending": False,
            }
        },
    )

    error = await ResolutionPipeline(
        test_db,
        gateway=_NarratorGateway(fail=True),
    )._apply_narrator(
        {"action_id": "narrator-action", "room_id": "solo-room"},
        {"character_id": "solo-character"},
        {"room_id": "solo-room"},
        resolution,
    )

    assert error is None
    assert resolution.metadata["narration"]["provider_source"] == "local_fallback"
    assert resolution.metadata["narration"]["rejected_provider_reason"] == "narrator_provider_failed"


def test_verified_solo_ending_narration_marks_adventure_complete():
    narration = narrator_module.build_verified_narration(
        {
            "allowed_facts": [
                {
                    "fact_ref": "fact:scene-brief",
                    "text": "你骑下山路，向文明与黎明而行。",
                },
                {"fact_ref": "fact:visible-change:1", "text": "本次冒险已结束。"},
            ],
            "visible_state_changes": ["本次冒险已结束。"],
            "interactable_objects": ["本次冒险记录"],
            "adventure_ended": True,
            "context_version": 6,
            "director_plan_digest": "solo:185",
            "redacted_citations": [],
            "runtime_package_style_pack": {"version": "default"},
        },
        action_id="solo-ending",
    )

    assert narration.environment_changes == ["本次冒险已结束。"]
    assert narration.interactable_objects == ["本次冒险记录"]
    assert narration.open_question == "本次冒险已经结束。你可以在历史记录中回顾这次旅程。"
    assert narration.narrative_text.endswith("本次冒险已经结束。")


def test_verified_solo_transition_narration_hides_import_source_marker():
    narration = narrator_module.build_verified_narration(
        {
            "allowed_facts": [
                {
                    "fact_ref": "fact:scene-brief",
                    "text": "七宫涟个人汉 你的行程重新开始了。司机转弯时变得更加小心。",
                }
            ],
            "visible_state_changes": [],
            "interactable_objects": [],
            "context_version": 5,
            "director_plan_digest": "solo:71",
            "redacted_citations": [],
            "runtime_package_style_pack": {"version": "default"},
        },
        action_id="solo-action",
    )

    assert "宫涟个人汉化" not in narration.narrative_text
    assert "七宫" not in narration.narrative_text
    assert "个人汉" not in narration.narrative_text
    assert "你的行程重新开始了。" in narration.narrative_text


def test_verified_solo_transition_narration_hides_inline_short_import_marker():
    narration = narrator_module.build_verified_narration(
        {
            "allowed_facts": [
                {"fact_ref": "fact:scene-brief", "text": "七宫 这些野兽逼近了。"}
            ],
            "visible_state_changes": [],
            "interactable_objects": [],
            "context_version": 5,
            "director_plan_digest": "solo:5",
            "redacted_citations": [],
            "runtime_package_style_pack": {"version": "default"},
        },
        action_id="solo-inline-marker",
    )

    assert "七宫" not in narration.narrative_text
    assert "这些野兽逼近了。" in narration.narrative_text


def test_verified_solo_transition_narration_uses_visible_scene_question():
    narration = narrator_module.build_verified_narration(
        {
            "allowed_facts": [
                {
                    "fact_ref": "fact:scene-brief",
                    "text": "西拉斯看着你问道：你干哪行？",
                }
            ],
            "visible_state_changes": [],
            "interactable_objects": [],
            "context_version": 5,
            "director_plan_digest": "solo:71",
            "redacted_citations": [],
            "runtime_package_style_pack": {"version": "default"},
        },
        action_id="solo-action",
    )

    assert narration.open_question == "眼下的对话还没有结束。你想如何回应：“你干哪行？”"
    assert narration.fact_refs["open_question"] == ["fact:scene-brief"]


@pytest.mark.asyncio
async def test_narrator_vehicle_conflict_requires_host_exception(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    runtime_row = test_db.execute(
        "SELECT runtime_package FROM runtime_package_versions WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (room_id,),
    ).fetchone()
    runtime_package = dict(runtime_row["runtime_package"])
    runtime_package["scene_briefs"]["lobby"] = "司机发动长途车，车窗外的街道慢慢远去。"
    test_db.execute(
        "UPDATE runtime_package_versions SET runtime_package = %s WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (json.dumps(runtime_package, ensure_ascii=False), room_id),
    )
    _insert_action(test_db, room_id, character_id)
    gateway = _NarratorGateway(
        _valid_narration(
            action_id="narrator-action",
            narrative_text="阿达登上马车，沿着道路继续前行。",
            fact_refs={
                "narrative_text": ["fact:scene-brief"],
                "environment_changes": ["fact:scene-brief"],
                "interactable_objects": ["fact:scene-brief"],
                "open_question": ["fact:scene-brief"],
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
    assert result["reason"] == "narrator_scene_fact_conflict"


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
    assert "declared_intent" not in context
    assert context["deterministic_rule_outcome"]["is_success"] is True
    assert context["runtime_package_style_pack"]["version"] == "noir-v1"
    assert all(isinstance(item, dict) for item in context["allowed_facts"])
    assert {item["text"] for item in context["allowed_facts"]} >= {
        "oak desk",
        "brass key",
    }
    assert {item["fact_ref"] for item in context["allowed_facts"]}.isdisjoint({
        "fact:oak-desk",
        "fact:brass-key",
    })
    _assert_no_denied_internal_payload(context)


@pytest.mark.asyncio
async def test_validated_generic_scene_progression_updates_authoritative_state_without_map(
    client,
    test_db,
):
    from src.server.engine.state_service import StateService

    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    runtime_row = test_db.execute(
        "SELECT runtime_package FROM runtime_package_versions WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (room_id,),
    ).fetchone()
    runtime_package = dict(runtime_row["runtime_package"])
    citation = {"source_part_id": "part-harbor", "page_number": 8}
    runtime_package["semantic_progression_rules"] = {
        "edges": [{
            "from_scene_id": "study",
            "to_scene_id": "harbor",
            "relation_type": "transitions_to",
            "conditions": [],
            "citation": citation,
        }],
        "solo_adventure": {},
    }
    test_db.execute(
        "UPDATE runtime_package_versions SET runtime_package = %s WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (json.dumps(runtime_package, ensure_ascii=False), room_id),
    )
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'study', visited_scenes = '[\"study\"]' "
        "WHERE room_id = %s",
        (room_id,),
    )
    _insert_action(test_db, room_id, character_id, intent_type="move")
    action = test_db.execute(
        "SELECT params FROM actions WHERE action_id = 'narrator-action'"
    ).fetchone()
    params = dict(action["params"])
    params["fromNodeId"] = "study"
    params["targetNodeId"] = "harbor"
    params["analysis"] = {
        "semantic_progression": {
            "fromNodeId": "study",
            "targetNodeId": "harbor",
            "ruleCitation": citation,
            "validated": True,
        },
    }
    test_db.execute(
        "UPDATE actions SET params = %s WHERE action_id = 'narrator-action'",
        (json.dumps(params, ensure_ascii=False),),
    )
    test_db.commit()

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("move"),
        state_service=StateService(test_db),
    ).resolve_action("narrator-action")

    assert result["status"] == "completed"
    scene = test_db.execute(
        "SELECT current_scene, visited_scenes FROM room_scene_state WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert scene["current_scene"] == "harbor"
    assert scene["visited_scenes"] == ["study", "harbor"]
    event_types = [
        row["event_type"]
        for row in test_db.execute(
            "SELECT event_type FROM events WHERE room_id = %s", (room_id,)
        ).fetchall()
    ]
    assert "s2c_scene_sync" in event_types
    assert "s2c_player_moved" not in event_types
    assert "s2c_map_updated" not in event_types


@pytest.mark.asyncio
async def test_client_cannot_supply_generic_scene_progression_marker(client, test_db):
    from src.server.models import PlayerIntent

    room_id, _, _ = _setup_narrator_room(client, test_db)
    intent = PlayerIntent(
        intent_type="move",
        declared_intent="I walk to the harbor.",
        params={
            "fromNodeId": "study",
            "targetNodeId": "harbor",
            "generic_scene_progression": {
                "from_scene_id": "study",
                "target_scene_id": "harbor",
            },
        },
    )

    error = await ResolutionPipeline(test_db)._validate_move(
        {"room_id": room_id},
        intent,
    )

    assert error == "no_map"
    assert "generic_scene_progression" not in intent.params


@pytest.mark.asyncio
async def test_runtime_condition_clue_is_persisted_and_can_complete_an_ending(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    runtime_row = test_db.execute(
        "SELECT runtime_package FROM runtime_package_versions WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (room_id,),
    ).fetchone()
    runtime_package = dict(runtime_row["runtime_package"])
    runtime_package.update({
        "semantic_scenes": [{
            "scene_id": "orchid-hall",
            "name": "兰花展厅",
        }],
        "clue_dependencies": [{
            "clue_id": "g17-test-sheet",
            "name": "G-17 test sheet",
            "public_version": "A water-damaged experiment record.",
            "location": "兰花展厅",
            "importance": "core",
            "reveal_conditions": [{
                "kind": "inspect",
                "scene_id": "orchid-hall",
            }],
            "prerequisite_fact_refs": [],
            "failure_outcome": {"preserve_core": True},
            "citation": {"source_part_id": "part-g17"},
        }],
        "ending_conditions": [{
            "ending_id": "g17-exit",
            "type": "victory",
            "citation": {"source_part_id": "part-g17"},
            "completion_conditions": {"all_clues": ["g17-test-sheet"]},
        }],
    })
    test_db.execute(
        "UPDATE runtime_package_versions SET runtime_package = %s WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (json.dumps(runtime_package, ensure_ascii=False), room_id),
    )
    test_db.execute(
        "UPDATE room_scene_state SET current_scene = 'orchid-hall' WHERE room_id = %s",
        (room_id,),
    )
    _insert_action(test_db, room_id, character_id)
    test_db.execute(
        "UPDATE actions SET declared_intent = %s WHERE action_id = 'narrator-action'",
        ("I inspect the G-17 test sheet.",),
    )
    test_db.commit()

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_success"),
        rule_executor=_StaticRuleExecutor(),
    ).resolve_action("narrator-action")

    assert result["status"] == "completed"
    clue = test_db.execute(
        "SELECT clue_id, source FROM clues WHERE room_id = %s AND character_id = %s",
        (room_id, character_id),
    ).fetchone()
    assert clue["source"] == "runtime:g17-test-sheet"
    assert clue["clue_id"] != "g17-test-sheet"
    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()["status"] == "completed"
    projected_event_types = {
        row["event_type"]
        for row in test_db.execute(
            "SELECT event_type FROM events WHERE room_id = %s",
            (room_id,),
        ).fetchall()
    }
    assert {
        "s2c_campaign_ended",
        "s2c_public_observation",
        "s2c_action_completed",
    } <= projected_event_types


@pytest.mark.asyncio
async def test_preserved_runtime_clue_is_committed_after_rule_failure(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    runtime_row = test_db.execute(
        "SELECT runtime_package FROM runtime_package_versions WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (room_id,),
    ).fetchone()
    runtime_package = dict(runtime_row["runtime_package"])
    runtime_package.update({
        "semantic_scenes": [{
            "scene_id": "lobby",
            "name": "Lobby",
        }],
        "clue_dependencies": [{
            "clue_id": "failed-inspection-clue",
            "name": "Failed inspection clue",
            "public_version": "The brass key has a visible maker mark.",
            "location": "Lobby",
            "importance": "core",
            "reveal_conditions": [{"kind": "inspect", "scene_id": "lobby"}],
            "prerequisite_fact_refs": [],
            "failure_outcome": {"preserve_core": True},
        }],
    })
    test_db.execute(
        "UPDATE runtime_package_versions SET runtime_package = %s WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (json.dumps(runtime_package, ensure_ascii=False), room_id),
    )
    _insert_action(test_db, room_id, character_id)

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_failure"),
        rule_executor=_FailureRuleExecutor(),
    ).resolve_action("narrator-action")

    clue = test_db.execute(
        "SELECT source FROM clues WHERE room_id = %s AND character_id = %s",
        (room_id, character_id),
    ).fetchone()

    assert result["status"] == "completed"
    assert clue["source"] == "runtime:failed-inspection-clue"


@pytest.mark.asyncio
async def test_verified_generic_ending_completes_room_only_after_condition_match(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    state_service = StateService(test_db)
    state_service.initialize_character_state(character_id, room_id)
    test_db.execute(
        "UPDATE character_runtime_state SET san = 42, status_tags = %s, temp_modifiers = %s "
        "WHERE character_id = %s AND room_id = %s",
        (
            json.dumps(["temporary_insanity"]),
            json.dumps(
                {
                    "coc7_sanity": {
                        "insanity_type": "temporary",
                        "phase": "underlying",
                        "control": "player",
                    }
                }
            ),
            character_id,
            room_id,
        ),
    )
    runtime_row = test_db.execute(
        "SELECT runtime_package FROM runtime_package_versions WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (room_id,),
    ).fetchone()
    runtime_package = dict(runtime_row["runtime_package"])
    runtime_package["ending_conditions"] = [{
        "ending_id": "leave-lobby",
        "type": "victory",
        "citation": {"source_ref": "page:1", "page_number": 1},
        "completion_conditions": {
            "entered_scenes": ["lobby"],
            "room_status": "active",
        },
    }]
    test_db.execute(
        "UPDATE runtime_package_versions SET runtime_package = %s WHERE scenario_version_id = "
        "(SELECT scenario_version_id FROM rooms WHERE room_id = %s)",
        (json.dumps(runtime_package, ensure_ascii=False), room_id),
    )
    test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room_id,))
    _insert_action(test_db, room_id, character_id)

    gateway = _NarratorGateway()
    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_success"),
        rule_executor=_StaticRuleExecutor(),
        gateway=gateway,
        state_service=state_service,
    ).resolve_action("narrator-action")

    assert result["status"] == "completed"
    assert gateway.contexts[0]["adventure_ended"] is True
    assert test_db.execute(
        "SELECT status FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()["status"] == "completed"
    event = test_db.execute(
        "SELECT payload FROM events WHERE room_id = %s AND event_type = 's2c_campaign_ended'",
        (room_id,),
    ).fetchone()
    assert event["payload"]["completion_source"] == "verified_runtime_ending"
    archive = test_db.execute(
        "SELECT ending_type, summary, character_arcs FROM campaign_archives WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    assert archive["ending_type"] == "victory"
    assert archive["summary"]
    assert archive["character_arcs"] == [
        {
            "character_id": character_id,
            "player_name": "Player",
            "total_actions": 1,
            "final_san": 42,
            "sanity_outcome": {
                "insanity_type": "temporary",
                "phase": "underlying",
                "control": "player",
                "archive_required": False,
            },
        }
    ]


@pytest.mark.asyncio
async def test_narrator_fact_violation_uses_verified_local_narration(client, test_db):
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

    assert result["status"] == "completed"
    narration = result["result"]["metadata"]["narration"]
    assert narration["provider_source"] == "local_fallback"
    assert narration["rejected_provider_reason"] == "narrator_fact_violation"
    events = test_db.execute(
        "SELECT event_type, payload FROM events WHERE room_id = %s ORDER BY sequence",
        (room_id,),
    ).fetchall()
    assert "s2c_ai_recovery_required" not in [event["event_type"] for event in events]
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
async def test_non_solo_timeout_uses_verified_local_narration(client, test_db, monkeypatch):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    _insert_action(test_db, room_id, character_id)

    async def timeout(awaitable, timeout):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(resolution_pipeline.asyncio, "wait_for", timeout)
    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_success"),
        rule_executor=_StaticRuleExecutor(),
        gateway=_NarratorGateway(fail=True),
    ).resolve_action("narrator-action")

    assert result["status"] == "completed"
    narration = result["result"]["metadata"]["narration"]
    assert narration["provider_source"] == "local_fallback"
    assert narration["rejected_provider_reason"] == "narrator_timeout"
    events = test_db.execute(
        "SELECT event_type FROM events WHERE room_id = %s ORDER BY sequence",
        (room_id,),
    ).fetchall()
    assert "s2c_ai_recovery_required" not in [event["event_type"] for event in events]


def test_verified_narration_fallback_allows_post_resolution_state_version(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    _insert_action(test_db, room_id, character_id)
    test_db.execute(
        "UPDATE rooms SET state_version = state_version + 1 WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()
    action = test_db.execute(
        "SELECT * FROM actions WHERE action_id = 'narrator-action'"
    ).fetchone()
    room = test_db.execute(
        "SELECT * FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()

    assert ResolutionPipeline(test_db)._can_use_verified_narration_fallback(
        dict(action),
        dict(room),
    ) is True


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
async def test_non_solo_provider_failure_uses_verified_local_narration(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    _insert_action(test_db, room_id, character_id)

    result = await ResolutionPipeline(
        test_db,
        compiler=_StaticCompiler("auto_success"),
        rule_executor=_StaticRuleExecutor(),
        gateway=_NarratorGateway(fail=True),
    ).resolve_action("narrator-action")

    assert result["status"] == "completed"
    action = test_db.execute(
        "SELECT status, result FROM actions WHERE action_id = 'narrator-action'"
    ).fetchone()
    assert action["status"] == "completed"
    narration = action["result"]["metadata"]["narration"]
    assert narration["provider_source"] == "local_fallback"
    assert narration["rejected_provider_reason"] == "narrator_provider_failed"
    events = test_db.execute(
        "SELECT event_type, payload FROM events WHERE room_id = %s ORDER BY sequence",
        (room_id,),
    ).fetchall()
    assert "s2c_ai_recovery_required" not in [event["event_type"] for event in events]


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
    # B1 migration (04 §6): s2c_turn_resolved carries the safe summary only
    # (build_turn_resolved_projection). Each action's verified narration is
    # NOT broadcast a second time — it persists exactly once on the action
    # row, and no broadcast payload carries narrative body text.
    turn_event = next(event for event in dispatcher.events if event[1] == "s2c_turn_resolved")
    turn_payload = json.dumps(turn_event[3], ensure_ascii=False)
    assert '"actionCount": 2' in turn_payload
    all_payloads = json.dumps([event[3] for event in dispatcher.events], ensure_ascii=False)
    assert "SECONDARY UNVERIFIED NARRATIVE" not in all_payloads
    # No second public narrative: the verified text is never broadcast again
    # (per-action narration persistence is the real pipeline's bundle path,
    # exercised by the bundle suites, not by this turn-settlement fake).
    assert "verified narrator text for batch-action-0" not in all_payloads
    assert all_payloads.count("verified narrator text") == 0


@pytest.mark.asyncio
async def test_combat_turn_settlement_uses_locked_plan_and_safe_round_summary(client, test_db):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    second_character_id = f"{character_id}-second"
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, status, xlsx_data) "
        "VALUES (%s, %s, 'Second', 'second-token', 'ready', %s)",
        (second_character_id, room_id, json.dumps({"name": "Ben"}, ensure_ascii=False)),
    )
    test_db.execute("UPDATE characters SET status = 'ready' WHERE character_id = %s", (character_id,))
    test_db.execute(
        "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
        "VALUES ('combat-settlement-encounter', %s, 'combat', 'active', 4)",
        (room_id,),
    )
    for participant_id, dex in ((character_id, 35), (second_character_id, 80)):
        test_db.execute(
            "INSERT INTO encounter_participants (encounter_id, character_id, dex) VALUES "
            "('combat-settlement-encounter', %s, %s)",
            (participant_id, dex),
        )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id) "
        "VALUES ('combat-settlement-turn', %s, 1, 'collecting', 'combat', 'combat-settlement-encounter')",
        (room_id,),
    )
    for action_id, participant_id, intent, params in (
        ('combat-slow', character_id, '我掩护安娜后退', {'depends_on_action_ids': ['combat-fast']}),
        ('combat-fast', second_character_id, '我朝走廊中的人影开枪', {}),
    ):
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, turn_id, intent_type, declared_intent, params, status) "
            "VALUES (%s, %s, %s, 'combat-settlement-turn', 'combat_action', %s, %s, 'queued')",
            (action_id, room_id, participant_id, intent, json.dumps(params)),
        )
        test_db.execute(
            "INSERT INTO resolution_bundles "
            "(action_id, room_id, character_id, canonical_result, rule_explanation, "
            "actor_projection, stage_projection, host_console, release_status) "
            "VALUES (%s, %s, %s, '{}', '{}', '{}', %s, '{}', 'released')",
            (
                action_id,
                room_id,
                participant_id,
                json.dumps({"narrativeText": f"公开结果 {action_id}"}, ensure_ascii=False),
            ),
        )
    test_db.commit()
    pipeline = _OrderedTurnPipeline()
    dispatcher = _RecordingDispatcher()
    gateway = _CombatRoundGateway()
    app = SimpleNamespace(
        state=SimpleNamespace(
            db=test_db,
            pg_db=None,
            pipeline=pipeline,
            dispatcher=dispatcher,
            gateway=gateway,
        )
    )

    await _settle_turn_background(app, room_id, 'combat-settlement-turn')

    assert pipeline.action_ids == ['combat-fast', 'combat-slow']
    locked = next(event for event in dispatcher.events if event[1] == 's2c_combat_round_locked')
    assert locked[3]['round_number'] == 4
    assert [cluster['public_title'] for cluster in locked[3]['public_clusters']] == [
        'Doorway exchange',
        '当前冲突',
    ]
    assert '我朝走廊中的人影开枪' not in json.dumps(locked[3], ensure_ascii=False)
    assert [item['action_id'] for item in gateway.contexts[0]['context']['public_actions']] == [
        'combat-fast',
        'combat-slow',
    ]
    assert len(gateway.contexts) == 2
    assert gateway.contexts[1]['context']['replan_after_resolution'] is True
    assert gateway.contexts[1]['context']['public_actions'] == [
        {
            'action_id': 'combat-slow',
            'global_order': 2,
            'rule_binding': 'combat_action',
            'declared_intent': '我掩护安娜后退',
        }
    ]
    assert gateway.contexts[1]['context']['completed_public_facts'] == [
        {'action_id': 'combat-fast', 'text': '公开结果 combat-fast'},
    ]
    stored_plan = test_db.execute(
        "SELECT combat_plan FROM room_turns WHERE turn_id = 'combat-settlement-turn'"
    ).fetchone()['combat_plan']
    stored_plan = json.loads(stored_plan) if isinstance(stored_plan, str) else stored_plan
    assert [step['action_id'] for step in stored_plan['steps']] == ['combat-fast', 'combat-slow']
    assert stored_plan['resolved_public_facts'] == [
        {'action_id': 'combat-fast', 'text': '公开结果 combat-fast'},
        {'action_id': 'combat-slow', 'text': '公开结果 combat-slow'},
    ]
    turn_event = next(event for event in dispatcher.events if event[1] == 's2c_turn_resolved')
    assert 'actions' not in turn_event[3]
    assert turn_event[3]['combat_summary']['title'] == '第 4 轮结束'
    encounter = test_db.execute(
        "SELECT current_round FROM encounters WHERE encounter_id = 'combat-settlement-encounter'"
    ).fetchone()
    next_turn = test_db.execute(
        "SELECT mode, encounter_id FROM room_turns WHERE room_id = %s AND turn_index = 2",
        (room_id,),
    ).fetchone()
    assert encounter['current_round'] == 5
    assert next_turn == {'mode': 'combat', 'encounter_id': 'combat-settlement-encounter'}


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


@pytest.mark.asyncio
async def test_ai_only_turn_settlement_pauses_on_resolution_exception_without_host_queue(
    client,
    test_db,
):
    room_id, character_id, _ = _setup_narrator_room(client, test_db)
    package_id = f"narrator-runtime-{room_id}"
    package = test_db.execute(
        "SELECT runtime_package FROM runtime_package_versions "
        "WHERE runtime_package_version_id = %s",
        (package_id,),
    ).fetchone()["runtime_package"]
    package = dict(package)
    package["runtime_policy"] = {"session_mode": "ai_only"}
    test_db.execute(
        "UPDATE runtime_package_versions SET runtime_package = %s "
        "WHERE runtime_package_version_id = %s",
        (json.dumps(package, ensure_ascii=False), package_id),
    )
    test_db.execute(
        "UPDATE rooms SET status = 'active', runtime_package_version_id = %s "
        "WHERE room_id = %s",
        (package_id, room_id),
    )
    test_db.execute(
        "INSERT INTO room_turns (turn_id, room_id, turn_index, status) "
        "VALUES ('turn-ai-only-failure', %s, 1, 'collecting')",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, draft_id, idempotency_key, "
        "turn_id, intent_type, declared_intent, params, status) VALUES "
        "('ai-only-failed-action', %s, %s, 'ai-only-failed-draft', "
        "'ai-only-failed-key', 'turn-ai-only-failure', 'dialogue', "
        "'I look around', '{}', 'queued')",
        (room_id, character_id),
    )
    test_db.commit()
    dispatcher = _RecordingDispatcher()
    app = SimpleNamespace(
        state=SimpleNamespace(
            db=test_db,
            pg_db=None,
            pipeline=_FailingTurnPipeline(test_db),
            dispatcher=dispatcher,
        )
    )

    await _settle_turn_background(app, room_id, "turn-ai-only-failure")

    action = test_db.execute(
        "SELECT status, result FROM actions "
        "WHERE action_id = 'ai-only-failed-action'"
    ).fetchone()
    room = test_db.execute(
        "SELECT status, integrity_reason FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    # R1/R7A migration (04 §6): an ai_only integrity pause PRESERVES the
    # in-flight action for verified recovery — it is never terminated with a
    # rejected result — and the pause notice is a durable party row written
    # by the pause helper, not a pipeline dispatcher event.
    assert action["status"] == "resolving"
    assert (action["result"] or {}) == {}
    assert room == {
        "status": "paused",
        "integrity_reason": "resolution_pipeline_error",
    }
    pause_rows = test_db.execute(
        "SELECT event_type, audience FROM events "
        "WHERE room_id = %s AND event_type = 's2c_room_paused'",
        (room_id,),
    ).fetchall()
    assert len(pause_rows) == 1 and pause_rows[0]["audience"] == "party"
    assert "s2c_action_exception_requested" not in [event[1] for event in dispatcher.events]
