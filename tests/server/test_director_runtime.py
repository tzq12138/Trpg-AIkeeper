import asyncio
import json

import pytest
from pydantic import ValidationError

from src.server.ai.director import (
    _validate_semantic_progression,
    apply_director_plan,
    resolve_conditional_solo_target,
)
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.models import ActionDraftDTO, DirectorPlanDTO, MechanicCompileResult, ResolutionResult
from tests.server.conftest import create_room, setup_auth_test_data
from tests.server.test_solo_adventure_runtime import _setup_solo_room


class _RecordingDirectorGateway:
    def __init__(self, plan: dict | None = None):
        self.plan = plan or {
            "interpreted_intent": "look around the platform",
            "intent_type": "dialogue",
            "confidence": 0.91,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
        }
        self.contexts: list[dict] = []

    async def analyze_director_action(self, context: dict, room_id: str | None = None):
        self.contexts.append(context)
        return self.plan


class _FailingDirectorGateway:
    async def analyze_director_action(self, context: dict, room_id: str | None = None):
        raise RuntimeError("provider failed with prompt: SECRET_KEEPER_PROMPT")


class _SlowDirectorGateway:
    def __init__(self):
        self.cancelled = False

    async def analyze_director_action(self, context: dict, room_id: str | None = None):
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return {
            "interpreted_intent": "look around the station",
            "intent_type": "dialogue",
            "confidence": 0.9,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
        }


class _AutoSuccessCompiler:
    async def compile(self, *_args, **_kwargs):
        return MechanicCompileResult(triggeredMechanic="auto_success")


class _NoMutationRuleExecutor:
    async def execute(self, intent, *_args, **_kwargs):
        return ResolutionResult(
            actionId=intent.action_id,
            roomId="",
            characterId="",
            isSuccess=True,
            narrative="ok",
            mutations=[],
            metadata={},
        )


class _HpMutationRuleExecutor:
    async def execute(self, intent, *_args, **_kwargs):
        return ResolutionResult(
            actionId=intent.action_id,
            roomId="",
            characterId="",
            isSuccess=True,
            narrative="ok",
            mutations=[{
                "op": "replace",
                "path": "/character/hp",
                "value": 9,
            }],
            metadata={},
        )


class _RecordingDispatcher:
    def __init__(self):
        self.events = []

    async def emit(self, room_id, event_type, audience, payload, **kwargs):
        self.events.append((room_id, event_type, audience, payload, kwargs))


class _InvalidNarratorGateway:
    async def narrate_action(self, *_args, **_kwargs):
        return {"unexpected": "provider response"}


def _bind_ai_only_runtime(test_db, room_id: str, package_id: str) -> dict:
    room = test_db.execute(
        "SELECT scenario_version_id, state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    test_db.execute(
        """
        INSERT INTO runtime_package_versions (
            runtime_package_version_id, scenario_version_id,
            package_version_number, gate_status, input_checksum,
            runtime_package, created_by
        ) VALUES (%s, %s, 99, 'ready', %s, %s, 'test')
        """,
        (
            package_id,
            room["scenario_version_id"],
            package_id,
            json.dumps({"runtime_policy": {"session_mode": "ai_only"}}),
        ),
    )
    test_db.execute(
        "UPDATE rooms SET runtime_package_version_id = %s WHERE room_id = %s",
        (package_id, room_id),
    )
    return dict(room)


def _setup_player(client, test_db, *, display_name: str = "Investigator Ada"):
    setup_auth_test_data(test_db)
    room_id = create_room(client)["room_id"]
    joined = client.post(f"/api/player/rooms/{room_id}/join").json()
    test_db.execute(
        "UPDATE characters SET player_name = %s, xlsx_data = %s WHERE character_id = %s",
        (display_name, json.dumps({"hp": 10, "skills": {}}), joined["character_id"]),
    )
    test_db.commit()
    return room_id, joined["character_id"], joined["player_token"]


def test_director_plan_dto_carries_non_authoritative_state_patch():
    plan = DirectorPlanDTO(
        action_id="action-1",
        context_version=7,
        actor_display_name="Investigator Ada",
        declared_intent="I open the sealed door",
        interpreted_intent="open the sealed door carefully",
        intent_type="move",
        preconditions=[{"kind": "position", "expected": "door"}],
        mechanic_plan={"mechanic": "skill_check", "skillName": "Locksmith"},
        state_patch=[{"op": "replace", "path": "/hp", "value": 1}],
        event_plan=[{"type": "s2c_ai_stage_changed"}],
        semantic_progression={"targetNodeId": "2"},
        npc_reactions=[{"npc": "guard", "reaction": "watches"}],
        time_impact={"seconds": 30},
        visibility="party",
        basis_refs=[{"source": "scene", "citation": {"page_number": 1}}],
        citations=[{"page_number": 1}],
        confidence=0.8,
        requires_player_clarification=False,
        clarification_options=[],
        requires_host_exception=False,
        exception_reason=None,
        narration_mode="summarize",
    )

    assert plan.state_patch[0].path == "/hp"
    assert plan.context_version == 7


def test_director_plan_dto_rejects_loose_state_patch_and_citations():
    with pytest.raises(ValidationError):
        DirectorPlanDTO(
            action_id="action-1",
            context_version=7,
            actor_display_name="Ada",
            declared_intent="I open the door",
            interpreted_intent="open the door",
            intent_type="move",
            state_patch=[{"path": "/hp", "value": 1}],
            citations=[{"raw_text": "full source paragraph must not be accepted"}],
            confidence=0.8,
            requires_player_clarification=False,
            requires_host_exception=False,
            narration_mode="summarize",
        )


def test_director_plan_dto_rejects_sensitive_nested_provider_output():
    with pytest.raises(ValidationError):
        DirectorPlanDTO(
            interpreted_intent="inspect the visible station",
            intent_type="dialogue",
            npc_reactions=[{
                "summary": "ordinary reaction",
                "storage_path": "C:/private/provider-output.txt",
            }],
        )


def test_director_rule_version_only_uses_live_binding_for_explicit_v1(test_db):
    from src.server.ai.director import _rule_version

    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, player_experience_version) "
        "VALUES ('director-missing-binding-room', 'token', 'v2')"
    )
    test_db.execute(
        "INSERT INTO rule_sets "
        "(rule_set_id, name, slug, system, description, is_base, "
        "license_type, status, created_by) "
        "VALUES ('director-live-rules', 'Live', 'director-live-rules', "
        "'coc7', '', FALSE, 'open', 'published', 'tester')"
    )
    test_db.execute(
        "INSERT INTO rule_set_versions "
        "(rule_set_version_id, rule_set_id, version_number, label, status, "
        "runtime_eligible, metadata, created_by) VALUES ('director-live-v1', "
        "'director-live-rules', 1, 'v1', 'published', TRUE, '{}', 'tester')"
    )
    test_db.execute(
        "INSERT INTO rule_version_publication_gates (rule_set_version_id, status) "
        "VALUES ('director-live-v1', 'ready')"
    )
    test_db.execute(
        "INSERT INTO room_rule_bindings "
        "(room_id, rule_set_version_id, priority) "
        "VALUES ('director-missing-binding-room', 'director-live-v1', 100)"
    )

    assert _rule_version(
        test_db,
        "director-missing-binding-room",
    ) == "unversioned"

    test_db.execute(
        "UPDATE rooms SET player_experience_version = 'v1' "
        "WHERE room_id = 'director-missing-binding-room'"
    )

    assert _rule_version(
        test_db,
        "director-missing-binding-room",
    ) == "director-live-v1"

    test_db.execute(
        "UPDATE rule_set_versions SET runtime_eligible = FALSE "
        "WHERE rule_set_version_id = 'director-live-v1'"
    )

    assert _rule_version(
        test_db,
        "director-missing-binding-room",
    ) == "unversioned"


def test_director_plan_exposes_sanitized_composite_steps_to_confirmation(
    client,
    test_db,
):
    _, character_id, _ = _setup_player(client, test_db)
    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone())
    draft = ActionDraftDTO(
        intent_type="skill_check",
        declared_intent="我先撬锁，成功后进入房间。",
        understanding_summary="先撬锁，再进入房间",
        risk="medium",
        confidence=0.8,
        analysis_source="local_fallback",
    )
    plan = DirectorPlanDTO(
        interpreted_intent="先撬锁，再进入房间",
        intent_type="skill_check",
        confidence=0.9,
        requires_player_clarification=False,
        requires_host_exception=False,
        narration_mode="observe",
        action_steps=[
            {
                "step_id": "pick-lock",
                "summary": "尝试撬开房门",
                "declared_intent": "我先尝试撬开房门。",
                "intent_type": "skill_check",
                "params": {"skillName": "Locksmith"},
            },
            {
                "step_id": "enter-room",
                "summary": "门开后进入房间",
                "declared_intent": "如果门打开，我就进入房间。",
                "intent_type": "move",
                "params": {"target": "room"},
                "execution_condition": "previous_step_success",
                "on_previous_failure": "cancel",
            },
        ],
    )

    applied = apply_director_plan(test_db, character, draft, plan, {})

    assert [step.step_id for step in applied.composite_steps] == [
        "pick-lock",
        "enter-room",
    ]
    assert applied.composite_steps[0].intent_type == "skill_check"
    assert applied.composite_steps[1].execution_condition == "previous_step_success"
    assert applied.requires_confirmation is True
    assert applied.confirmation_requirements == ["stateful_action"]


def test_director_analysis_returns_composite_steps_from_the_primary_gateway(
    client,
    test_db,
):
    _, _, player_token = _setup_player(client, test_db)
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "先制服守卫，再取走钥匙",
            "intent_type": "combat_action",
            "confidence": 0.9,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
            "action_steps": [
                {
                    "step_id": "subdue-guard",
                    "summary": "制服守卫",
                    "declared_intent": "我先制服守卫。",
                    "intent_type": "combat_action",
                    "params": {},
                },
                {
                    "step_id": "take-key",
                    "summary": "取得守卫身上的钥匙",
                    "declared_intent": "守卫失去反抗能力后，我取走钥匙。",
                    "intent_type": "use_item",
                    "params": {},
                    "execution_condition": "previous_step_success",
                    "on_previous_failure": "cancel",
                },
            ],
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我先制服守卫，再取走他身上的钥匙。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    assert gateway.contexts
    draft = response.json()
    assert [step["step_id"] for step in draft["composite_steps"]] == [
        "subdue-guard",
        "take-key",
    ]
    assert draft["requires_confirmation"] is True


def test_action_analyze_sends_full_director_context_with_display_name(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    gateway = _RecordingDirectorGateway()
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "I listen at the station door", "ephemeral": True},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    assert gateway.contexts, "Director gateway was not called"
    context = gateway.contexts[0]
    assert context["room"]["room_id"] == room_id
    assert context["actor"]["character_id"] == character_id
    assert context["actor"]["display_name"] == "Investigator Ada"
    assert context["actor_display_name"] == "Investigator Ada"
    assert context["declared_intent"] == "I listen at the station door"
    assert "current_scene" in context
    assert "runtime_package" in context
    assert "recent_events" in context
    assert "inventory" in context
    assert set(context) > {"declared_intent"}


def test_director_empty_clarification_options_keeps_draft_confirmable(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "inspect the visible label",
            "intent_type": "dialogue",
            "confidence": 0.68,
            "requires_player_clarification": True,
            "clarification_options": [],
            "requires_host_exception": False,
            "narration_mode": "observe",
            "analysis_source": "fallback_provider",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "I inspect the visible label."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["status"] == "awaiting_confirmation"
    assert draft["adjudication_stage"] == "director_plan_validated"
    assert draft["confirmation_requirements"] == ["stateful_action"]


def test_local_fallback_accepts_chinese_inventory_search_after_provider_timeout(
    client,
    test_db,
):
    _, _, player_token = _setup_player(client, test_db)
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = _FailingDirectorGateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我翻查未登记行李，寻找地下通道钥匙。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["status"] == "awaiting_confirmation"
    assert draft["risk"] == "low"
    assert draft["resolution_route"] == "local"
    assert draft["analysis_source"] == "local_fallback"


def test_low_risk_chinese_inspection_ignores_invalid_ai_scene_target(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "inspect the visible return-route clue",
            "intent_type": "skill_check",
            "confidence": 0.9,
            "semantic_progression": {
                "targetNodeId": "return-route",
                "citation": {"source_part_id": "part-clue"},
            },
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
            "analysis_source": "fallback_provider",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我检查并记录午夜退件路线。"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["risk"] == "low"
    assert draft["intent_type"] == "dialogue"
    assert draft["resolution_route"] == "local"
    assert draft["params"].get("targetNodeId") is None


def test_director_analysis_cancels_a_slow_provider_at_the_action_deadline(
    client,
    test_db,
    monkeypatch,
):
    from src.server.player import router_actions_v2

    _, _, player_token = _setup_player(client, test_db)
    gateway = _SlowDirectorGateway()
    previous_gateway = getattr(client.app.state, "gateway", None)
    monkeypatch.setattr(
        router_actions_v2,
        "_DIRECTOR_ANALYSIS_TIMEOUT_SECONDS",
        0.001,
        raising=False,
    )
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "I try something impossible."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    assert gateway.cancelled is True
    assert response.json()["adjudication_stage"] == "host_exception_required"


def test_director_analysis_redacts_backstage_entry_references_from_player_summary(
    client,
    test_db,
):
    _, _, player_token = _setup_player(client, test_db)
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": (
                "玩家想登上长途车。这对应场景文本中“转到263”的指令，"
                "并从当前场景（条目1）移动到条目263。"
            ),
            "intent_type": "move",
            "confidence": 0.92,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "summarize",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我登上刚到的长途车", "ephemeral": True},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    summary = response.json()["understanding_summary"]
    assert "条目" not in summary
    assert "节点" not in summary
    assert "263" not in summary
    assert "转到" not in summary


def test_director_context_limits_runtime_package_to_current_solo_branch(test_db):
    from src.server.ai.director import build_director_context

    room_id, scenario_version_id = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('compact-director-character', %s, 'Ada', 'compact-token', %s)",
        (room_id, json.dumps({"name": "Ada", "skills": {"侦查": 60}})),
    )
    nodes = [
        {
            "node_id": str(index),
            "title": f"Entry {index}",
            "text": "x" * 5000,
            "target_node_ids": [str(index + 1)] if index < 20 else [],
            "citation": {"page_number": index},
        }
        for index in range(1, 21)
    ]
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, input_checksum, runtime_package, created_by) "
        "VALUES ('compact-director-package', %s, 1, 'ready', 'sha', %s, 'test')",
        (
            scenario_version_id,
            json.dumps({
                "world_book": {
                    "synopsis": "A compact mystery.",
                    "truth": "UNRELATED WORLD TRUTH MUST NOT LEAVE THE ENGINE",
                },
                "semantic_scenes": [{
                    "logical_key": "remote-vault",
                    "title": "UNRELATED REMOTE SCENE SECRET",
                }],
                "npc_states": [{
                    "scene_id": "remote-vault",
                    "truth": "UNRELATED NPC SECRET",
                }],
                "clue_dependencies": [{
                    "scene_id": "remote-vault",
                    "description": "UNRELATED CLUE SECRET",
                }],
                "semantic_progression_rules": {
                    "solo_adventure": {"root_node_id": "1", "nodes": nodes}
                },
                "story_evidence_nodes": [
                    {"logical_key": str(index), "title": f"Entry {index}"}
                    for index in range(1, 21)
                ],
            }),
        ),
    )
    test_db.commit()
    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = 'compact-director-character'"
    ).fetchone())
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="I look around",
        understanding_summary="look around",
        risk="low",
        confidence=0.8,
        analysis_source="local_fallback",
    )

    context = build_director_context(test_db, character, draft)

    compact_nodes = context["runtime_package"]["semantic_progression_rules"]["solo_adventure"]["nodes"]
    assert [node["node_id"] for node in compact_nodes] == ["1", "2"]
    assert all(len(node["text"]) <= 1200 for node in compact_nodes)
    assert len(json.dumps(context, ensure_ascii=False)) < 20_000
    rendered = json.dumps(context, ensure_ascii=False)
    for secret in (
        "UNRELATED WORLD TRUTH MUST NOT LEAVE THE ENGINE",
        "UNRELATED REMOTE SCENE SECRET",
        "UNRELATED NPC SECRET",
        "UNRELATED CLUE SECRET",
    ):
        assert secret not in rendered


def test_director_context_never_projects_current_scene_raw_clue_dependency(
    client,
    test_db,
):
    from src.server.ai.director import build_director_context

    room_id, character_id, _ = _setup_player(client, test_db)
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, input_checksum, runtime_package, created_by) "
        "VALUES ('current-clue-director-package', %s, 1, 'ready', 'sha', %s, 'test')",
        (
            scenario_version_id,
            json.dumps({
                "semantic_scenes": [{
                    "scene_id": "current-vault",
                    "name": "Current public vault",
                }],
                "clue_dependencies": [{
                    "clue_id": "current-secret-clue",
                    "name": "CURRENT CLUE NAME SECRET",
                    "scene_id": "current-vault",
                    "description": "CURRENT CLUE DESCRIPTION SECRET",
                    "public_version": "CURRENT CLUE PUBLIC VERSION SECRET",
                    "private_version": "CURRENT CLUE PRIVATE VERSION SECRET",
                    "prerequisite_fact_refs": ["CURRENT CLUE PREREQUISITE SECRET"],
                    "reveal_conditions": [{"kind": "inspect", "scene_id": "current-vault"}],
                }],
            }),
        ),
    )
    test_db.execute(
        "UPDATE rooms SET runtime_package_version_id = 'current-clue-director-package' "
        "WHERE room_id = %s",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, version) "
        "VALUES (%s, 'current-vault', '[\"current-vault\"]', 1) "
        "ON CONFLICT (room_id) DO UPDATE SET current_scene = EXCLUDED.current_scene",
        (room_id,),
    )
    test_db.commit()
    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s",
        (character_id,),
    ).fetchone())
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="I inspect the room.",
        understanding_summary="inspect the room",
        risk="low",
        confidence=0.8,
        analysis_source="local_fallback",
    )

    context = build_director_context(test_db, character, draft)
    rendered = json.dumps(context, ensure_ascii=False)

    assert context["runtime_package"]["clue_dependencies"] == []
    for secret in (
        "CURRENT CLUE NAME SECRET",
        "CURRENT CLUE DESCRIPTION SECRET",
        "CURRENT CLUE PUBLIC VERSION SECRET",
        "CURRENT CLUE PRIVATE VERSION SECRET",
        "CURRENT CLUE PREREQUISITE SECRET",
    ):
        assert secret not in rendered


def test_director_context_limits_generic_edges_to_current_scene(client, test_db):
    from src.server.ai.director import build_director_context

    room_id, character_id, _ = _setup_player(client, test_db)
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()["scenario_version_id"]
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, input_checksum, runtime_package, created_by) "
        "VALUES ('generic-edges-package', %s, 1, 'ready', 'sha', %s, 'test')",
        (
            scenario_version_id,
            json.dumps({
                "semantic_scenes": [
                    {
                        "scene_id": "study",
                        "name": "书房",
                        "truth": "CURRENT SCENE EMBEDDED TRUTH",
                        "payload": {
                            "scene_id": "study",
                            "name": "书房",
                            "hidden_clue": "CURRENT SCENE EMBEDDED CLUE",
                        },
                    },
                    {
                        "scene_id": "harbor",
                        "name": "港口",
                        "truth": "TARGET SCENE EMBEDDED TRUTH",
                        "payload": {
                            "scene_id": "harbor",
                            "name": "港口",
                            "hidden_clue": "TARGET SCENE EMBEDDED CLUE",
                        },
                    },
                    {
                        "scene_id": "warehouse",
                        "name": "仓库",
                        "truth": "REMOTE SCENE EMBEDDED TRUTH",
                    },
                ],
                "semantic_progression_rules": {
                    "edges": [
                        {
                            "from_scene_id": "study",
                            "to_scene_id": "harbor",
                            "relation_type": "transitions_to",
                            "conditions": [],
                            "citation": {"page_number": 8},
                        },
                        {
                            "from_scene_id": "harbor",
                            "to_scene_id": "warehouse",
                            "relation_type": "transitions_to",
                            "conditions": [],
                            "citation": {"page_number": 9},
                        },
                    ],
                    "solo_adventure": {},
                },
            }),
        ),
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, version) "
        "VALUES (%s, 'study', '[\"study\"]', 1)",
        (room_id,),
    )
    test_db.commit()
    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone())
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="I examine the study.",
        understanding_summary="examine the study",
        risk="low",
        confidence=0.8,
        analysis_source="local_fallback",
    )

    context = build_director_context(test_db, character, draft)

    assert context["runtime_package"]["semantic_progression_rules"]["edges"] == [{
        "from_scene_id": "study",
        "to_scene_id": "harbor",
        "relation_type": "transitions_to",
        "conditions": [],
        "citation": {"page_number": 8},
    }]
    rendered = json.dumps(context["runtime_package"], ensure_ascii=False)
    assert "港口" in rendered
    assert "仓库" not in rendered
    for secret in (
        "CURRENT SCENE EMBEDDED TRUTH",
        "CURRENT SCENE EMBEDDED CLUE",
        "TARGET SCENE EMBEDDED TRUTH",
        "TARGET SCENE EMBEDDED CLUE",
        "REMOTE SCENE EMBEDDED TRUTH",
    ):
        assert secret not in rendered


def test_director_context_uses_the_room_runtime_package_snapshot(client, test_db):
    from src.server.ai.director import build_director_context

    room_id, character_id, _ = _setup_player(client, test_db)
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    for package_id, version_number, synopsis in [
        ("director-snapshot-v1", 1, "已固定的开团版本"),
        ("director-snapshot-v2", 2, "后来重新编译的版本"),
    ]:
        test_db.execute(
            "INSERT INTO runtime_package_versions "
            "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, "
            "input_checksum, runtime_package, created_by) "
            "VALUES (%s, %s, %s, 'ready', 'sha', %s, 'test')",
            (package_id, scenario_version_id, version_number, json.dumps({"world_book": {"synopsis": synopsis}})),
        )
    test_db.execute(
        "UPDATE rooms SET runtime_package_version_id = 'director-snapshot-v1' WHERE room_id = %s",
        (room_id,),
    )
    test_db.commit()

    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s",
        (character_id,),
    ).fetchone())
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="我观察周围。",
        understanding_summary="观察周围",
        risk="low",
        confidence=0.8,
        analysis_source="local_fallback",
    )

    context = build_director_context(test_db, character, draft)

    assert context["runtime_package"]["world_book"]["synopsis"] == "已固定的开团版本"


def test_director_context_excludes_room_tokens_and_other_player_private_events(client, test_db):
    from src.server.ai.director import build_director_context

    room_id, character_id, _ = _setup_player(client, test_db)
    other = client.post(f"/api/player/rooms/{room_id}/join").json()
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s)",
        (room_id, "s2c_team_message", "party", json.dumps({"text": "队伍都看见了走廊尽头的火光。"})),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s)",
        (room_id, "s2c_private_notice", "player", json.dumps({
            "characterId": character_id,
            "text": "只有你看见了袖口的血迹。",
        })),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s)",
        (room_id, "s2c_private_notice", "player", json.dumps({
            "characterId": other["character_id"],
            "text": "另一名玩家的私密线索。",
        })),
    )
    test_db.execute(
        "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, %s, %s)",
        (room_id, "s2c_action_exception_requested", "host", json.dumps({
            "text": "仅 Host 可见的异常原因。",
        })),
    )
    test_db.commit()
    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s", (character_id,),
    ).fetchone())
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="我观察走廊。",
        understanding_summary="观察走廊",
        risk="low",
        confidence=0.8,
        analysis_source="local_fallback",
    )

    context = build_director_context(test_db, character, draft)
    rendered = json.dumps(context, ensure_ascii=False)

    assert "队伍都看见了走廊尽头的火光。" in rendered
    assert "只有你看见了袖口的血迹。" in rendered
    assert "另一名玩家的私密线索。" not in rendered
    assert "仅 Host 可见的异常原因。" not in rendered
    assert "owner_token" not in context["room"]
    assert "player_token" not in rendered


def test_director_context_only_includes_hidden_facts_relevant_to_current_scene(
    client,
    test_db,
):
    from src.server.ai.director import build_director_context

    room_id, character_id, _ = _setup_player(client, test_db)
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    test_db.execute(
        "INSERT INTO room_scene_state "
        "(room_id, current_scene, visited_scenes, version) "
        "VALUES (%s, 'station', '[\"station\"]', 1)",
        (room_id,),
    )
    for content_item_id, logical_key, title in [
        ("hidden-current", "station", "站台管理员隐瞒了末班车时间"),
        ("hidden-remote", "sealed-vault", "遥远保险库中的幕后真相"),
    ]:
        test_db.execute(
            "INSERT INTO content_items "
            "(content_item_id, scenario_version_id, item_type, logical_key, "
            "title, visibility, checksum) "
            "VALUES (%s, %s, 'fact', %s, %s, 'hidden', %s)",
            (
                content_item_id,
                scenario_version_id,
                logical_key,
                title,
                f"sha-{content_item_id}",
            ),
        )
    test_db.commit()
    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s",
        (character_id,),
    ).fetchone())
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="我询问站台管理员末班车时间。",
        understanding_summary="询问末班车时间",
        risk="low",
        confidence=0.8,
        analysis_source="local_fallback",
    )

    context = build_director_context(test_db, character, draft)

    assert [fact["logical_key"] for fact in context["hidden_facts"]] == ["station"]
    assert [fact["fact_id"] for fact in context["hidden_facts"]] == [
        "hidden-current"
    ]
    assert "遥远保险库中的幕后真相" not in json.dumps(
        context,
        ensure_ascii=False,
    )


def test_director_context_uses_authorized_ledger_facts_and_labels_player_beliefs(
    client,
    test_db,
):
    from src.server.ai.director import build_director_context
    from src.server.engine.reveal_ledger import RevealLedger

    room_id, character_id, _ = _setup_player(client, test_db)
    other = client.post(f"/api/player/rooms/{room_id}/join").json()
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    test_db.execute(
        "INSERT INTO room_scene_state "
        "(room_id, current_scene, visited_scenes, public_facts, version) "
        "VALUES (%s, 'station', '[\"station\"]', "
        "'[\"站台入口已经打开\"]', 1)",
        (room_id,),
    )
    for item_id, title in (
        ("director-party-fact", "末班车时刻表被人改过"),
        ("director-private-fact", "只有当前角色看见袖口血迹"),
        ("director-other-private-fact", "另一角色独自听见低语"),
        ("director-unrevealed-public", "尚未由 Engine 授权的静态内容"),
    ):
        test_db.execute(
            "INSERT INTO content_items "
            "(content_item_id, scenario_version_id, item_type, logical_key, title, "
            "visibility, payload, citation, checksum) "
            "VALUES (%s, %s, 'fact', %s, %s, 'host_only', %s, %s, %s)",
            (
                item_id,
                scenario_version_id,
                item_id,
                title,
                json.dumps({
                    "fact_text": title,
                    "reveal_conditions": {"scene_ids": ["station"]},
                }),
                json.dumps({"page_number": 11}),
                f"sha-{item_id}",
            ),
        )
    test_db.execute(
        "INSERT INTO evidence_cards "
        "(evidence_card_id, room_id, created_by_character_id, title, body, "
        "card_type, fact_status, visibility, source) "
        "VALUES ('belief-card', %s, %s, '站长是凶手', "
        "'这只是玩家推测', 'question', 'hypothesis', 'party', 'player')",
        (room_id, character_id),
    )
    test_db.commit()
    ledger = RevealLedger(test_db)
    ledger.commit_proposals(
        room_id=room_id,
        source_action_id="director-party-action",
        actor_character_id=character_id,
        proposals=[{"content_item_id": "director-party-fact", "audience": "party"}],
        state_version=0,
    )
    ledger.commit_proposals(
        room_id=room_id,
        source_action_id="director-private-action",
        actor_character_id=character_id,
        proposals=[{"content_item_id": "director-private-fact", "audience": "player"}],
        state_version=0,
    )
    ledger.commit_proposals(
        room_id=room_id,
        source_action_id="director-other-action",
        actor_character_id=other["character_id"],
        proposals=[{
            "content_item_id": "director-other-private-fact",
            "audience": "player",
        }],
        state_version=0,
    )
    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = %s",
        (character_id,),
    ).fetchone())
    draft = ActionDraftDTO(
        intent_type="dialogue",
        declared_intent="我说站长肯定是凶手。",
        understanding_summary="提出对站长的怀疑",
        risk="low",
        confidence=0.8,
        analysis_source="local_fallback",
    )

    context = build_director_context(test_db, character, draft)
    rendered = json.dumps(context, ensure_ascii=False)

    assert {fact["fact_id"] for fact in context["public_facts"] if fact.get("fact_id")} == {
        "director-party-fact",
        "scene-public:1",
    }
    assert {fact["fact_id"] for fact in context["private_facts"]} == {
        "director-private-fact",
    }
    assert "站台入口已经打开" in rendered
    assert "另一角色独自听见低语" not in rendered
    assert "尚未由 Engine 授权的静态内容" not in rendered
    assert context["player_hypotheses"] == [{
        "evidence_card_id": "belief-card",
        "title": "站长是凶手",
        "body": "这只是玩家推测",
        "epistemic_status": "player_hypothesis_not_world_truth",
    }]

    affirmative_plan = DirectorPlanDTO(
        interpreted_intent="你说得对，站长就是凶手。",
        intent_type="dialogue",
        confidence=0.99,
        requires_player_clarification=False,
        requires_host_exception=False,
        narration_mode="observe",
    )
    apply_director_plan(test_db, character, draft, affirmative_plan, context)
    assert test_db.execute(
        "SELECT fact_status, source FROM evidence_cards "
        "WHERE evidence_card_id = 'belief-card'"
    ).fetchone() == {"fact_status": "hypothesis", "source": "player"}


def test_low_confidence_director_returns_clarification_options_and_cannot_confirm(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "unclear",
            "intent_type": "dialogue",
            "confidence": 0.42,
            "requires_player_clarification": True,
            "clarification_options": [
                {"label": "listen", "interpreted_intent": "listen at the door"},
                {"label": "open", "interpreted_intent": "open the door"},
                {"label": "leave", "interpreted_intent": "leave quietly"},
            ],
            "requires_host_exception": False,
            "narration_mode": "clarify",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "I deal with it somehow"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["adjudication_stage"] == "player_clarification_required"
    assert draft["status"] == "analyzing"
    assert len(draft["candidate_interpretations"]) == 3
    assert draft["requires_confirmation"] is False

    confirm = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={"X-Room-Token": player_token, "Idempotency-Key": "clarify-blocked"},
        json={"confirmations": []},
    )
    assert confirm.status_code == 409
    assert confirm.json()["detail"]["code"] == "draft_not_confirmable"


def test_single_visible_solo_target_recovers_after_clarifying_provider(
    client,
    test_db,
):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('director-local-target-character', %s, 'Ada', 'director-local-target-token', %s)",
        (room_id, json.dumps({})),
    )
    test_db.commit()
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "Please clarify your next move.",
            "intent_type": "dialogue",
            "confidence": 0.7,
            "requires_player_clarification": True,
            "requires_host_exception": False,
            "narration_mode": "clarify",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "director-local-target-token"},
            json={"declared_intent": "I search the road for the missing bus."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert len(gateway.contexts) == 1
    assert draft["status"] == "awaiting_confirmation"
    assert draft["adjudication_stage"] == "director_plan_validated"
    assert draft["params"]["fromNodeId"] == "1"
    assert draft["params"]["targetNodeId"] == "2"


def test_host_exception_director_plan_emits_recovery_event_on_confirm(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "force open locked Keeper-only evidence",
            "intent_type": "use_item",
            "confidence": 0.86,
            "requires_player_clarification": False,
            "requires_host_exception": True,
            "exception_reason": "permission_boundary",
            "narration_mode": "defer_to_host",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        draft = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "I read the Keeper-only note"},
        ).json()
    finally:
        client.app.state.gateway = previous_gateway

    assert draft["adjudication_stage"] == "host_exception_required"
    confirm = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={"X-Room-Token": player_token, "Idempotency-Key": "host-exception"},
        json={"confirmations": draft["confirmation_requirements"]},
    )

    assert confirm.status_code == 200
    assert confirm.json()["status"] == "awaiting_host_exception"
    events = test_db.execute(
        "SELECT event_type, payload FROM events WHERE room_id = %s ORDER BY sequence",
        (room_id,),
    ).fetchall()
    assert "s2c_ai_recovery_required" in [event["event_type"] for event in events]


def test_director_host_exception_without_reason_does_not_block_low_risk_action(
    client,
    test_db,
):
    _, _, player_token = _setup_player(client, test_db)
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "把行李放好并坐稳",
            "intent_type": "action",
            "confidence": 0.95,
            "requires_player_clarification": False,
            "requires_host_exception": True,
            "exception_reason": None,
            "narration_mode": "descriptive",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我把行李放好后坐稳", "ephemeral": True},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["adjudication_stage"] == "director_plan_validated"
    assert draft["resolution_route"] == "ai"


def test_director_gateway_exception_records_recovery_without_prompt_leak(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = _FailingDirectorGateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "I do something impossible"},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["adjudication_stage"] == "host_exception_required"
    assert draft["analysis_source"] == "local_fallback"
    assert "SECRET_KEEPER_PROMPT" not in response.text
    events = test_db.execute(
        "SELECT event_type, payload FROM events WHERE room_id = %s ORDER BY sequence",
        (room_id,),
    ).fetchall()
    assert "s2c_ai_recovery_required" in [event["event_type"] for event in events]
    assert "SECRET_KEEPER_PROMPT" not in json.dumps([event["payload"] for event in events])


def test_safe_local_action_uses_local_director_plan_when_provider_fails(client, test_db):
    _, _, player_token = _setup_player(client, test_db)
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = _FailingDirectorGateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我看看桌上的旧报纸", "ephemeral": True},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["analysis_source"] == "local_fallback"
    assert draft["adjudication_stage"] == "director_plan_validated"
    assert draft["resolution_route"] == "local"
    assert draft["params"]["director_plan"]["state_patch_authority"] == "advisory_only"


@pytest.mark.asyncio
async def test_ai_state_patch_is_stored_as_plan_but_not_applied_by_pipeline(client, test_db):
    _, character_id, player_token = _setup_player(client, test_db)
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "look around",
            "intent_type": "dialogue",
            "confidence": 0.9,
            "state_patch": [{"op": "replace", "path": "/hp", "value": 1}],
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        draft = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "I look around"},
        ).json()
    finally:
        client.app.state.gateway = previous_gateway
    receipt = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={"X-Room-Token": player_token, "Idempotency-Key": "patch-is-plan"},
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    action = test_db.execute(
        "SELECT params FROM actions WHERE action_id = %s", (receipt["action_id"],)
    ).fetchone()
    assert action["params"]["director_plan"]["state_patch"][0]["value"] == 1

    result = await ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    ).resolve_action(receipt["action_id"])

    assert result["status"] == "completed"
    character = test_db.execute(
        "SELECT xlsx_data FROM characters WHERE character_id = %s", (character_id,)
    ).fetchone()
    assert character["xlsx_data"]["hp"] == 10


@pytest.mark.asyncio
async def test_pipeline_commits_validated_reveal_before_projection(client, test_db):
    from src.server.engine.state_service import StateService

    room_id, character_id, player_token = _setup_player(client, test_db)
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    test_db.execute(
        "INSERT INTO room_scene_state "
        "(room_id, current_scene, visited_scenes, version) "
        "VALUES (%s, 'study', '[\"study\"]', 1)",
        (room_id,),
    )
    test_db.execute(
        "INSERT INTO content_items "
        "(content_item_id, scenario_version_id, item_type, logical_key, title, "
        "visibility, payload, citation, checksum) "
        "VALUES ('pipeline-reveal-fact', %s, 'fact', 'study', "
        "'书桌夹层里有一封未寄出的信', 'host_only', %s, %s, 'sha-reveal')",
        (
            scenario_version_id,
            json.dumps({"fact_text": "书桌夹层里有一封未寄出的信"}),
            json.dumps({"page_number": 12}),
        ),
    )
    test_db.commit()
    gateway = _RecordingDirectorGateway({
        "interpreted_intent": "检查书桌夹层",
        "intent_type": "dialogue",
        "confidence": 0.9,
        "reveal_proposals": [{
            "content_item_id": "pipeline-reveal-fact",
            "audience": "party",
        }],
        "requires_player_clarification": False,
        "requires_host_exception": False,
        "narration_mode": "observe",
    })
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        draft = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={"declared_intent": "我检查书桌夹层。"},
        ).json()
    finally:
        client.app.state.gateway = previous_gateway
    receipt = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={
            "X-Room-Token": player_token,
            "Idempotency-Key": "pipeline-reveal",
        },
        json={"confirmations": draft["confirmation_requirements"]},
    ).json()
    dispatcher = _RecordingDispatcher()

    result = await ResolutionPipeline(
        test_db,
        dispatcher=dispatcher,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_HpMutationRuleExecutor(),
        state_service=StateService(test_db),
    ).resolve_action(receipt["action_id"])

    assert result["status"] == "completed"
    reveal = test_db.execute(
        "SELECT source_action_id, state_version, event_sequence FROM fact_reveals "
        "WHERE fact_id = 'pipeline-reveal-fact'"
    ).fetchone()
    assert reveal["source_action_id"] == receipt["action_id"]
    assert reveal["state_version"] == test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["state_version"]
    assert reveal["state_version"] == 1
    event = test_db.execute(
        "SELECT event_type, action_id, state_version FROM events "
        "WHERE sequence = %s",
        (reveal["event_sequence"],),
    ).fetchone()
    assert dict(event) == {
        "event_type": "s2c_fact_revealed",
        "action_id": receipt["action_id"],
        "state_version": reveal["state_version"],
    }
    assert any(item[1] == "s2c_public_observation" for item in dispatcher.events)


@pytest.mark.asyncio
async def test_pipeline_rejects_unmet_reveal_without_secret_in_response_or_event(
    client,
    test_db,
):
    room_id, character_id, _ = _setup_player(client, test_db)
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    test_db.execute(
        "INSERT INTO room_scene_state "
        "(room_id, current_scene, visited_scenes, version) "
        "VALUES (%s, 'study', '[\"study\"]', 1)",
        (room_id,),
    )
    secret = "地下密室中的幕后真凶是站长"
    test_db.execute(
        "INSERT INTO content_items "
        "(content_item_id, scenario_version_id, item_type, logical_key, title, "
        "visibility, payload, citation, checksum) "
        "VALUES ('pipeline-blocked-fact', %s, 'fact', 'vault', %s, "
        "'host_only', %s, %s, 'sha-blocked')",
        (
            scenario_version_id,
            secret,
            json.dumps({
                "fact_text": secret,
                "reveal_conditions": {"scene_ids": ["vault"]},
            }),
            json.dumps({"page_number": 20}),
        ),
    )
    room = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()
    test_db.execute(
        "INSERT INTO actions "
        "(action_id, room_id, character_id, intent_type, declared_intent, "
        "params, status, draft_id, idempotency_key) "
        "VALUES ('pipeline-blocked-action', %s, %s, 'dialogue', "
        "'我看看书桌。', %s, 'queued', 'pipeline-blocked-draft', 'blocked-reveal')",
        (
            room_id,
            character_id,
            json.dumps({
                "director_plan": {
                    "context_version": room["state_version"],
                    "preconditions": [],
                    "permissions": [],
                    "state_patch": [],
                    "reveal_proposals": [{
                        "content_item_id": "pipeline-blocked-fact",
                        "audience": "party",
                    }],
                    "state_patch_authority": "advisory_only",
                }
            }),
        ),
    )
    test_db.commit()

    result = await ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    ).resolve_action("pipeline-blocked-action")

    assert result == {
        "status": "rejected",
        "action_id": "pipeline-blocked-action",
        "reason": "reveal_condition_unmet",
    }
    rendered = json.dumps(result, ensure_ascii=False) + json.dumps(
        [
            row["payload"]
            for row in test_db.execute(
                "SELECT payload FROM events WHERE room_id = %s",
                (room_id,),
            ).fetchall()
        ],
        ensure_ascii=False,
    )
    assert secret not in rendered
    assert test_db.execute(
        "SELECT COUNT(*) AS count FROM fact_reveals "
        "WHERE source_action_id = 'pipeline-blocked-action'"
    ).fetchone()["count"] == 0


@pytest.mark.asyncio
async def test_director_unknown_precondition_and_denied_permission_fail_closed(client, test_db):
    room_id, character_id, player_token = _setup_player(client, test_db)
    room = test_db.execute(
        "SELECT state_version FROM rooms WHERE room_id = %s", (room_id,)
    ).fetchone()
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, intent_type, declared_intent,
            params, status, draft_id, idempotency_key
        ) VALUES (%s, %s, %s, 'dialogue', 'I inspect hidden keeper notes', %s, 'queued', 'director-precondition-draft', 'director-precondition-key')
        """,
        (
            "director-precondition-action",
            room_id,
            character_id,
            json.dumps(
                {
                    "director_plan": {
                        "context_version": room["state_version"],
                        "preconditions": [{"kind": "unknown_external_fact"}],
                        "permissions": [{"scope": "keeper_notes", "allowed": False}],
                        "state_patch": [{"op": "replace", "path": "/hp", "value": 1}],
                        "state_patch_authority": "advisory_only",
                    }
                }
            ),
        ),
    )
    test_db.commit()

    result = await ResolutionPipeline(
        test_db,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
    ).resolve_action("director-precondition-action")

    assert result["status"] == "awaiting_host_exception"
    assert result["reason"] in {
        "director_precondition_unsupported",
        "director_permission_denied",
    }


@pytest.mark.asyncio
async def test_ai_only_invalid_director_plan_rejects_without_human_review(client, test_db):
    room_id, character_id, _ = _setup_player(client, test_db)
    room = _bind_ai_only_runtime(test_db, room_id, "ai-only-director-package")
    params = {
        "analysis": {"risk": "medium", "visibility": "public"},
        "director_plan": {
            "context_version": room["state_version"],
            "preconditions": [],
            "permissions": [],
            "state_patch": [],
            "state_patch_authority": "authoritative",
        },
    }
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, intent_type, declared_intent,
            params, status, draft_id, idempotency_key
        ) VALUES (%s, %s, %s, 'dialogue', 'I inspect the room', %s,
                  'queued', 'ai-only-director-draft', 'ai-only-director-key')
        """,
        ("ai-only-director-action", room_id, character_id, json.dumps(params)),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('ai-only-director-action', 'queued', '{}')"
    )
    test_db.commit()
    dispatcher = _RecordingDispatcher()

    result = await ResolutionPipeline(
        test_db,
        dispatcher=dispatcher,
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
        host_connection_checker=lambda _room_id: False,
    ).resolve_action("ai-only-director-action")

    assert result == {
        "status": "rejected",
        "action_id": "ai-only-director-action",
        "reason": "director_plan_unverified",
    }
    assert not any(
        event[1] == "s2c_action_exception_requested" for event in dispatcher.events
    )


@pytest.mark.asyncio
async def test_ai_only_invalid_narrator_response_uses_verified_template(client, test_db):
    room_id, character_id, _ = _setup_player(client, test_db)
    room = _bind_ai_only_runtime(test_db, room_id, "ai-only-narrator-package")
    params = {
        "analysis": {"risk": "low", "visibility": "public"},
        "director_plan": {
            "context_version": room["state_version"],
            "preconditions": [],
            "permissions": [],
            "state_patch": [],
            "state_patch_authority": "advisory_only",
        },
    }
    test_db.execute(
        """
        INSERT INTO actions (
            action_id, room_id, character_id, intent_type, declared_intent,
            params, status, draft_id, idempotency_key
        ) VALUES (%s, %s, %s, 'dialogue', 'I inspect the room', %s,
                  'queued', 'ai-only-narrator-draft', 'ai-only-narrator-key')
        """,
        ("ai-only-narrator-action", room_id, character_id, json.dumps(params)),
    )
    test_db.execute(
        "INSERT INTO action_status_events (action_id, status, metadata) "
        "VALUES ('ai-only-narrator-action', 'queued', '{}')"
    )
    test_db.commit()
    dispatcher = _RecordingDispatcher()

    result = await ResolutionPipeline(
        test_db,
        dispatcher=dispatcher,
        gateway=_InvalidNarratorGateway(),
        compiler=_AutoSuccessCompiler(),
        rule_executor=_NoMutationRuleExecutor(),
        host_connection_checker=lambda _room_id: False,
    ).resolve_action("ai-only-narrator-action")

    assert result["status"] == "completed"
    narration = result["result"]["metadata"]["narration"]
    assert narration["rejected_provider_reason"] == "narrator_invalid_response"
    assert result["result"]["narrative"]
    assert not any(
        event[1] == "s2c_action_exception_requested" for event in dispatcher.events
    )


def test_director_semantic_progression_maps_target_with_valid_citation(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('director-solo-character', %s, 'Ada', 'director-solo-token', %s)",
        (room_id, json.dumps({})),
    )
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, input_checksum, runtime_package, created_by) "
        "VALUES ('director-runtime-package', 'solo-runtime-version', 1, 'ready', 'sha', %s, 'test-admin')",
        (
            json.dumps(
                {
                    "semantic_progression_rules": {
                        "solo_adventure": {
                            "root_node_id": "1",
                            "nodes": [
                                {
                                    "node_id": "1",
                                    "target_node_ids": ["2"],
                                    "citation": {"page_number": 1},
                                }
                            ],
                        }
                    }
                }
            ),
        ),
    )
    test_db.commit()
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "board the train",
            "intent_type": "move",
            "confidence": 0.92,
            "semantic_progression": {
                "targetNodeId": "2",
                "citation": {"page_number": 1},
            },
            "citations": [{"page_number": 1}],
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "summarize",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "director-solo-token"},
            json={"declared_intent": "The train arrives; I board it."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["params"]["fromNodeId"] == "1"
    assert draft["params"]["targetNodeId"] == "2"
    assert draft["semantic_progression"]["targetNodeId"] == "2"
    assert draft["citations"] == [{
        "label": "已校验依据",
        "page": 1,
        "scene": None,
        "verified": True,
    }]
    assert "entry 2" not in json.dumps(draft).lower()


def test_director_semantic_progression_without_evidence_is_rejected(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('director-uncited-character', %s, 'Ada', 'director-uncited-token', %s)",
        (room_id, json.dumps({})),
    )
    test_db.commit()
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "skip ahead",
            "intent_type": "move",
            "confidence": 0.95,
            "semantic_progression": {"targetNodeId": "2"},
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "summarize",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "director-uncited-token"},
            json={"declared_intent": "I board it."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["adjudication_stage"] == "host_exception_required"
    assert draft["params"].get("targetNodeId") is None
    assert draft["semantic_progression"]["rejected"] is True


def test_director_validates_current_generic_scene_edge_with_matching_citation(test_db):
    plan = DirectorPlanDTO(
        interpreted_intent="I take the marked path to the harbor.",
        intent_type="move",
        confidence=0.9,
        semantic_progression={
            "targetNodeId": "harbor",
            "citation": {"source_part_id": "part-harbor", "page_number": 8},
        },
    )
    context = {
        "current_scene": {"current_scene": "study"},
        "runtime_package": {
            "semantic_progression_rules": {
                "edges": [{
                    "from_scene_id": "study",
                    "to_scene_id": "harbor",
                    "relation_type": "transitions_to",
                    "conditions": [],
                    "citation": {"source_part_id": "part-harbor", "page_number": 8},
                }],
            },
        },
    }

    result = _validate_semantic_progression(test_db, {"xlsx_data": "{}"}, plan, context)

    assert result == {
        "targetNodeId": "harbor",
        "fromNodeId": "study",
        "citation": {"source_part_id": "part-harbor", "page_number": 8},
        "ruleCitation": {"source_part_id": "part-harbor", "page_number": 8},
        "validated": True,
    }


def test_local_fallback_resolves_a_named_generic_scene_target(client, test_db):
    room_id, _, player_token = _setup_player(client, test_db)
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    citation = {
        "source_part_id": "part-cistern",
        "label": "地下蓄水池",
        "source_ref": "module.json#/knowledge_graph/scenes/3",
        "citation_id": "cit-cistern",
    }
    test_db.execute(
        """
        INSERT INTO runtime_package_versions
        (runtime_package_version_id, scenario_version_id, package_version_number,
         gate_status, input_checksum, runtime_package, created_by)
        VALUES (%s, %s, 99, 'ready', 'generic-fallback', %s, 'test')
        """,
        (
            f"generic-fallback-{room_id}",
            scenario_version_id,
            json.dumps({
                "semantic_scenes": [
                    {"scene_id": "orchid-hall", "name": "兰花展厅"},
                    {"scene_id": "cistern", "name": "地下蓄水池"},
                ],
                "semantic_progression_rules": {
                    "edges": [{
                        "from_scene_id": "orchid-hall",
                        "to_scene_id": "cistern",
                        "relation_type": "transitions_to",
                        "conditions": [],
                        "citation": citation,
                    }],
                },
            }, ensure_ascii=False),
        ),
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, version) "
        "VALUES (%s, 'orchid-hall', '[\"orchid-hall\"]', 1)",
        (room_id,),
    )
    test_db.commit()
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = _FailingDirectorGateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={
                "declared_intent": "我走向地下蓄水池，查看阀门平台。",
                "intent_type": "dialogue",
                "ephemeral": True,
            },
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["intent_type"] == "move"
    assert draft["params"]["fromNodeId"] == "orchid-hall"
    assert draft["params"]["targetNodeId"] == "cistern"
    assert draft["semantic_progression"]["validated"] is True
    assert draft["resolution_route"] == "local"


def test_failing_director_recovers_high_risk_compiled_scene_transition_in_ai_only_room(
    client,
    test_db,
    monkeypatch,
):
    room_id, _, player_token = _setup_player(client, test_db)
    scenario_version_id = test_db.execute(
        "SELECT scenario_version_id FROM rooms WHERE room_id = %s",
        (room_id,),
    ).fetchone()["scenario_version_id"]
    package_id = f"high-risk-generic-fallback-{room_id}"
    citation = {"source_part_id": "part-cistern", "source_ref": "module.json#/scenes/2"}
    test_db.execute(
        """
        INSERT INTO runtime_package_versions
        (runtime_package_version_id, scenario_version_id, package_version_number,
         gate_status, input_checksum, runtime_package, created_by)
        VALUES (%s, %s, 99, 'ready', 'high-risk-generic-fallback', %s, 'test')
        """,
        (
            package_id,
            scenario_version_id,
            json.dumps({
                "runtime_policy": {"session_mode": "ai_only"},
                "semantic_scenes": [
                    {"scene_id": "orchid-hall", "name": "兰花展厅"},
                    {"scene_id": "cistern", "name": "地下蓄水池"},
                ],
                "semantic_progression_rules": {
                    "edges": [{
                        "from_scene_id": "orchid-hall",
                        "to_scene_id": "cistern",
                        "relation_type": "transitions_to",
                        "conditions": [],
                        "citation": citation,
                    }],
                },
            }, ensure_ascii=False),
        ),
    )
    test_db.execute(
        "UPDATE rooms SET runtime_package_version_id = %s WHERE room_id = %s",
        (package_id, room_id),
    )
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, version) "
        "VALUES (%s, 'orchid-hall', '[\"orchid-hall\"]', 1)",
        (room_id,),
    )
    test_db.commit()
    from src.server.player import router_actions_v2

    def high_risk_move(body):
        return ActionDraftDTO(
            intent_type="move",
            declared_intent=body.declared_intent,
            understanding_summary="你将前往地下蓄水池。",
            risk="high",
            confirmation_requirements=["movement", "state_change"],
            requires_confirmation=True,
            confidence=0.9,
            analysis_source="local_fallback",
            resolution_route="local",
            ephemeral=body.ephemeral,
        )

    monkeypatch.setattr(router_actions_v2, "analyze_action_draft", high_risk_move)

    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = _FailingDirectorGateway()
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": player_token},
            json={
                "declared_intent": "我走向地下蓄水池。",
                "ephemeral": True,
            },
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["risk"] == "high"
    assert draft["resolution_route"] == "local"
    assert draft["adjudication_stage"] == "director_plan_validated"
    assert draft["params"]["fromNodeId"] == "orchid-hall"
    assert draft["params"]["targetNodeId"] == "cistern"
    assert draft["semantic_progression"]["validated"] is True


def test_director_uses_runtime_evidence_for_an_uncited_generic_scene_target(test_db):
    plan = DirectorPlanDTO(
        interpreted_intent="I take the marked path to the harbor.",
        intent_type="move",
        confidence=0.9,
        semantic_progression={"targetNodeId": "harbor"},
    )
    context = {
        "current_scene": {"current_scene": "study"},
        "runtime_package": {
            "semantic_progression_rules": {
                "edges": [{
                    "from_scene_id": "study",
                    "to_scene_id": "harbor",
                    "relation_type": "transitions_to",
                    "conditions": [],
                    "citation": {"source_part_id": "part-harbor", "page_number": 8},
                }],
            },
        },
    }

    result = _validate_semantic_progression(test_db, {"xlsx_data": "{}"}, plan, context)

    assert result == {
        "targetNodeId": "harbor",
        "fromNodeId": "study",
        "citation": {"source_part_id": "part-harbor", "page_number": 8},
        "ruleCitation": {"source_part_id": "part-harbor", "page_number": 8},
        "providerCitationMissing": True,
        "validated": True,
    }


def test_director_rejects_generic_scene_edge_when_required_clue_is_missing(test_db):
    plan = DirectorPlanDTO(
        interpreted_intent="I take the marked path to the harbor.",
        intent_type="move",
        confidence=0.9,
        semantic_progression={
            "targetNodeId": "harbor",
            "citation": {"source_part_id": "part-harbor", "page_number": 8},
        },
    )
    context = {
        "current_scene": {"current_scene": "study"},
        "runtime_package": {
            "semantic_progression_rules": {
                "edges": [{
                    "from_scene_id": "study",
                    "to_scene_id": "harbor",
                    "relation_type": "transitions_to",
                    "conditions": [{"kind": "clue", "id": "ticket"}],
                    "citation": {"source_part_id": "part-harbor", "page_number": 8},
                }],
            },
        },
    }

    result = _validate_semantic_progression(
        test_db,
        {"room_id": "generic-condition-room", "xlsx_data": "{}"},
        plan,
        context,
    )

    assert result["validated"] is False
    assert result["rejected"] is True


def test_director_validates_generic_scene_edge_with_runtime_canonical_clue(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token, status) VALUES "
        "('generic-runtime-clue-room', 'generic-runtime-clue-owner', 'active')"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token) VALUES "
        "('generic-runtime-clue-character', 'generic-runtime-clue-room', 'Player', 'token')"
    )
    test_db.execute(
        "INSERT INTO clues (clue_id, room_id, character_id, text, source) VALUES "
        "('runtime-opaque-ticket', 'generic-runtime-clue-room', "
        "'generic-runtime-clue-character', 'Ticket', 'runtime:ticket')"
    )
    test_db.commit()
    plan = DirectorPlanDTO(
        interpreted_intent="I take the marked path to the harbor.",
        intent_type="move",
        confidence=0.9,
        semantic_progression={
            "targetNodeId": "harbor",
            "citation": {"source_part_id": "part-harbor", "page_number": 8},
        },
    )
    context = {
        "current_scene": {"current_scene": "study"},
        "runtime_package": {
            "semantic_progression_rules": {
                "edges": [{
                    "from_scene_id": "study",
                    "to_scene_id": "harbor",
                    "relation_type": "transitions_to",
                    "conditions": [{"kind": "clue", "id": "ticket"}],
                    "citation": {"source_part_id": "part-harbor", "page_number": 8},
                }],
            },
        },
    }

    result = _validate_semantic_progression(
        test_db,
        {"room_id": "generic-runtime-clue-room", "xlsx_data": "{}"},
        plan,
        context,
    )

    assert result["validated"] is True
    assert result["targetNodeId"] == "harbor"


def test_director_validates_generic_scene_edge_when_required_scene_was_visited(client, test_db):
    room_id, _, _ = _setup_player(client, test_db)
    test_db.execute(
        "INSERT INTO room_scene_state (room_id, current_scene, visited_scenes, version) "
        "VALUES (%s, 'study', '[\"archive\", \"study\"]', 1)",
        (room_id,),
    )
    test_db.commit()
    plan = DirectorPlanDTO(
        interpreted_intent="I follow the archive notes to the harbor.",
        intent_type="move",
        confidence=0.9,
        semantic_progression={
            "targetNodeId": "harbor",
            "citation": {"source_part_id": "part-harbor", "page_number": 8},
        },
    )
    context = {
        "current_scene": {"current_scene": "study"},
        "runtime_package": {
            "semantic_progression_rules": {
                "edges": [{
                    "from_scene_id": "study",
                    "to_scene_id": "harbor",
                    "relation_type": "transitions_to",
                    "conditions": [{"kind": "scene", "id": "archive"}],
                    "citation": {"source_part_id": "part-harbor", "page_number": 8},
                }],
            },
        },
    }

    result = _validate_semantic_progression(
        test_db,
        {"room_id": room_id, "xlsx_data": "{}"},
        plan,
        context,
    )

    assert result["validated"] is True


def test_director_single_target_progression_replaces_mismatched_provider_citation(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('director-wrong-rule-citation-character', %s, 'Ada', 'director-wrong-rule-token', %s)",
        (room_id, json.dumps({})),
    )
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, input_checksum, runtime_package, created_by) "
        "VALUES ('director-wrong-rule-runtime', 'solo-runtime-version', 1, 'ready', 'sha', %s, 'test-admin')",
        (
            json.dumps(
                {
                    "semantic_progression_rules": {
                        "solo_adventure": {
                            "root_node_id": "1",
                            "nodes": [
                                {
                                    "node_id": "1",
                                    "target_node_ids": ["2"],
                                    "citation": {"page_number": 2},
                                }
                            ],
                        }
                    },
                    "citations": [{"page_number": 1}],
                }
            ),
        ),
    )
    test_db.commit()
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "board the train",
            "intent_type": "move",
            "confidence": 0.92,
            "semantic_progression": {
                "targetNodeId": "2",
                "citation": {"page_number": 1},
            },
            "citations": [{"page_number": 1}],
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "summarize",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "director-wrong-rule-token"},
            json={"declared_intent": "The train arrives; I board it."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["adjudication_stage"] == "director_plan_validated"
    assert draft["params"]["fromNodeId"] == "1"
    assert draft["params"]["targetNodeId"] == "2"
    assert draft["semantic_progression"]["citation"] == {"page_number": 2}
    assert draft["semantic_progression"]["providerCitationReplaced"] is True


def test_director_uses_character_stat_to_validate_conditional_solo_branch(client, test_db):
    plan = DirectorPlanDTO(
        semantic_progression={
            "targetNodeId": "2",
            "citation": {"source_part_id": "wrong-part", "page_number": 9},
        }
    )
    context = {
        "current_scene": {"node_id": "1"},
        "runtime_package": {
            "semantic_progression_rules": {
                "solo_adventure": {
                    "nodes": [
                        {
                            "node_id": "1",
                            "text": "如果你的“体型”是40，转到2。如果你的“体型”高于40，转到3。",
                            "target_node_ids": ["2", "3"],
                            "citation": {
                                "source_part_id": "part-size",
                                "page_number": 5,
                            },
                        }
                    ]
                }
            }
        },
    }

    result = _validate_semantic_progression(
        test_db,
        {"xlsx_data": json.dumps({"attributes": {"siz": 40}})},
        plan,
        context,
    )

    assert result["validated"] is True
    assert result["targetNodeId"] == "2"
    assert result["citation"] == {
        "source_part_id": "part-size",
        "page_number": 5,
    }
    assert result["conditionValidated"] is True


def test_director_resolves_comparative_attribute_branch_without_roll():
    target = resolve_conditional_solo_target(
        {"xlsx_data": json.dumps({"attributes": {"dex": 60, "siz": 40}})},
        {
            "text": (
                "比较你的“体型”和“敏捷”。"
                "如果你的“敏捷”较高，转到42。"
                "如果你的“体型”较高，进行一次“敏捷”检定。"
            ),
            "target_node_ids": ["42", "36"],
        },
    )

    assert target == "42"


def test_director_resolves_wrapped_comparative_attribute_branch_without_roll():
    target = resolve_conditional_solo_target(
        {"xlsx_data": json.dumps({"attributes": {"dex": 60, "siz": 40}})},
        {
            "text": (
                "比较你的“体型”和“敏\n捷”。如果你的“敏\n捷”较高，转到42。"
                "如果你的“体型”较高，进行一次“敏捷”检定。"
            ),
            "target_node_ids": ["42", "36"],
        },
    )

    assert target == "42"


def test_visible_solo_transition_resolves_character_condition_before_ai(test_db):
    from src.server.player.router_actions_v2 import _apply_visible_solo_transition
    from src.server.scenario.content_projection import ContentProjectionService

    room_id, scenario_version_id = _setup_solo_room(test_db)
    graph = {
        "solo_adventure": {
            "root_node_id": "1",
            "integrity": {"is_valid": True},
            "nodes": [
                {
                    "node_id": "1",
                    "title": "车顶行李架",
                    "text": "如果你的“体型”是40，转到2。如果你的“体型”高于40，转到3。",
                    "target_node_ids": ["2", "3"],
                    "citation": {"page_number": 5},
                },
                {
                    "node_id": "2",
                    "title": "司机搭手",
                    "text": "司机帮你放好行李。",
                    "target_node_ids": [],
                    "citation": {"page_number": 6},
                },
                {
                    "node_id": "3",
                    "title": "独自搬运",
                    "text": "你独自把行李抬上去。",
                    "target_node_ids": [],
                    "citation": {"page_number": 7},
                },
            ],
        }
    }
    test_db.execute(
        "UPDATE scenario_versions SET knowledge_graph = %s WHERE scenario_version_id = %s",
        (json.dumps(graph), scenario_version_id),
    )
    ContentProjectionService(test_db).rebuild(
        scenario_version_id, graph, requested_by="test-admin"
    )
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('conditional-solo-character', %s, 'Ada', 'conditional-token', %s)",
        (room_id, json.dumps({"attributes": {"siz": 40}})),
    )
    test_db.commit()
    character = dict(test_db.execute(
        "SELECT * FROM characters WHERE character_id = 'conditional-solo-character'"
    ).fetchone())
    draft = ActionDraftDTO(
        intent_type="move",
        declared_intent="我把行李固定好，准备登车。",
        understanding_summary="继续旅程",
        risk="medium",
        confidence=0.9,
        analysis_source="local_fallback",
    )

    resolved = _apply_visible_solo_transition(test_db, character, draft)

    assert resolved.params["fromNodeId"] == "1"
    assert resolved.params["targetNodeId"] == "2"
    assert resolved.resolution_route == "local"


def test_director_uses_current_node_citation_for_confident_multichoice_without_citation(test_db):
    plan = DirectorPlanDTO(
        interpreted_intent="I leave through the road on the left.",
        intent_type="move",
        confidence=0.9,
        semantic_progression={"targetNodeId": "2"},
    )
    context = {
        "current_scene": {"node_id": "1"},
        "runtime_package": {
            "semantic_progression_rules": {
                "solo_adventure": {
                    "nodes": [
                        {
                            "node_id": "1",
                            "text": "向左走，转到2。向右走，转到3。",
                            "target_node_ids": ["2", "3"],
                            "citation": {"source_part_id": "part-road", "page_number": 7},
                        }
                    ]
                }
            }
        },
    }

    result = _validate_semantic_progression(test_db, {"xlsx_data": "{}"}, plan, context)

    assert result["validated"] is True
    assert result["targetNodeId"] == "2"
    assert result["citation"] == {"source_part_id": "part-road", "page_number": 7}
    assert result["providerCitationMissing"] is True


def test_director_uses_current_node_citation_for_medium_confidence_multichoice_without_citation(test_db):
    plan = DirectorPlanDTO(
        interpreted_intent="I have investigated enough and wait for the afternoon.",
        intent_type="move",
        confidence=0.75,
        semantic_progression={"targetNodeId": "3"},
    )
    context = {
        "current_scene": {"node_id": "1"},
        "runtime_package": {
            "semantic_progression_rules": {
                "solo_adventure": {
                    "nodes": [
                        {
                            "node_id": "1",
                            "text": "继续调查，或推进时间，转到3。",
                            "target_node_ids": ["2", "3"],
                            "citation": {"source_part_id": "part-wait", "page_number": 9},
                        }
                    ]
                }
            }
        },
    }

    result = _validate_semantic_progression(test_db, {"xlsx_data": "{}"}, plan, context)

    assert result["validated"] is True
    assert result["targetNodeId"] == "3"
    assert result["citation"] == {"source_part_id": "part-wait", "page_number": 9}
    assert result["providerCitationMissing"] is True


def test_director_uses_current_node_citation_for_single_target_without_citation(test_db):
    plan = DirectorPlanDTO(
        interpreted_intent="I answer the driver's question and continue the journey.",
        intent_type="dialogue",
        confidence=0.68,
        semantic_progression={"targetNodeId": "2"},
    )
    context = {
        "current_scene": {"node_id": "1"},
        "runtime_package": {
            "semantic_progression_rules": {
                "solo_adventure": {
                    "nodes": [
                        {
                            "node_id": "1",
                            "text": "司机等你回答。转到2。",
                            "target_node_ids": ["2"],
                            "citation": {"source_part_id": "part-driver", "page_number": 8},
                        }
                    ]
                }
            }
        },
    }

    result = _validate_semantic_progression(test_db, {"xlsx_data": "{}"}, plan, context)

    assert result["validated"] is True
    assert result["targetNodeId"] == "2"
    assert result["citation"] == {"source_part_id": "part-driver", "page_number": 8}
    assert result["providerCitationMissing"] is True


def test_director_defers_provider_target_after_forced_single_transition(test_db):
    plan = DirectorPlanDTO(
        interpreted_intent="I go to the grocery store to ask about a carriage.",
        intent_type="move",
        confidence=0.95,
        semantic_progression={
            "targetNodeId": "3",
            "citation": {"source_part_id": "part-grocery", "page_number": 5},
        },
    )
    context = {
        "current_scene": {"node_id": "1"},
        "runtime_package": {
            "semantic_progression_rules": {
                "solo_adventure": {
                    "nodes": [
                        {
                            "node_id": "1",
                            "text": "You return to the village. Turn to 2.",
                            "target_node_ids": ["2"],
                            "citation": {"source_part_id": "part-return", "page_number": 4},
                        },
                        {
                            "node_id": "2",
                            "text": "You may visit the grocery store. Turn to 3.",
                            "target_node_ids": ["3"],
                            "citation": {"source_part_id": "part-grocery", "page_number": 5},
                        },
                    ]
                }
            }
        },
    }

    result = _validate_semantic_progression(test_db, {"xlsx_data": "{}"}, plan, context)

    assert result["validated"] is True
    assert result["targetNodeId"] == "2"
    assert result["citation"] == {"source_part_id": "part-return", "page_number": 4}
    assert result["providerTargetDeferred"] is True


def test_director_accepts_selected_target_citation_for_multichoice_progression(test_db):
    plan = DirectorPlanDTO(
        interpreted_intent="I ask the driver where he will spend the night.",
        intent_type="dialogue",
        confidence=0.9,
        semantic_progression={
            "targetNodeId": "2",
            "citation": {"source_part_id": "part-destination-approximate", "page_number": 8},
        },
    )
    context = {
        "current_scene": {"node_id": "1"},
        "runtime_package": {
            "semantic_progression_rules": {
                "solo_adventure": {
                    "nodes": [
                        {
                            "node_id": "1",
                            "target_node_ids": ["2", "3"],
                            "citation": {"source_part_id": "part-choice", "page_number": 7},
                        },
                        {
                            "node_id": "2",
                            "target_node_ids": [],
                            "citation": {"source_part_id": "part-destination", "page_number": 8},
                        },
                    ]
                }
            }
        },
    }

    result = _validate_semantic_progression(test_db, {"xlsx_data": "{}"}, plan, context)

    assert result["validated"] is True
    assert result["citation"] == {"source_part_id": "part-choice", "page_number": 7}
    assert result["providerCitationTargetPageMatched"] is True


def test_director_progression_rejects_citation_with_only_empty_values(client, test_db):
    room_id, _ = _setup_solo_room(test_db)
    test_db.execute(
        "INSERT INTO characters (character_id, room_id, player_name, player_token, xlsx_data) "
        "VALUES ('director-empty-citation-character', %s, 'Ada', 'director-empty-citation-token', %s)",
        (room_id, json.dumps({})),
    )
    test_db.execute(
        "INSERT INTO runtime_package_versions "
        "(runtime_package_version_id, scenario_version_id, package_version_number, gate_status, input_checksum, runtime_package, created_by) "
        "VALUES ('director-empty-citation-runtime', 'solo-runtime-version', 1, 'ready', 'sha', %s, 'test-admin')",
        (
            json.dumps(
                {
                    "semantic_progression_rules": {
                        "solo_adventure": {
                            "root_node_id": "1",
                            "nodes": [
                                {
                                    "node_id": "1",
                                    "target_node_ids": ["2"],
                                    "citation": {
                                        "source_part_id": "part-1",
                                        "page_number": 1,
                                    },
                                }
                            ],
                        }
                    }
                }
            ),
        ),
    )
    test_db.commit()
    gateway = _RecordingDirectorGateway(
        {
            "interpreted_intent": "board the train",
            "intent_type": "move",
            "confidence": 0.92,
            "semantic_progression": {
                "targetNodeId": "2",
                "citation": {
                    "source_part_id": None,
                    "content_item_id": None,
                    "page_number": None,
                },
            },
            "citations": [],
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "summarize",
        }
    )
    previous_gateway = getattr(client.app.state, "gateway", None)
    client.app.state.gateway = gateway
    try:
        response = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": "director-empty-citation-token"},
            json={"declared_intent": "The train arrives; I board it."},
        )
    finally:
        client.app.state.gateway = previous_gateway

    assert response.status_code == 200
    draft = response.json()
    assert draft["adjudication_stage"] == "host_exception_required"
    assert draft["params"].get("targetNodeId") is None
    assert draft["semantic_progression"]["rejected"] is True
