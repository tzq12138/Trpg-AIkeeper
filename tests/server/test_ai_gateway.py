import json

import pytest

from src.server.ai.contracts import CombatRoundSuggestion, KpResponse, NarrativePayload
from src.server.ai.gateway import AiGateway, ProviderFailure
from src.server.ai.providers import BaseAiProvider
from src.server.scenario.content_package import ContentPackage, ContentPart


class FakeProvider:
    def __init__(self, response):
        self.name = "fake"
        self.response = response

    async def call(self, task_type: str, context: dict):
        return self.response

    async def health_check(self) -> bool:
        return True


class EchoUserMessageProvider:
    name = "fake"

    async def call(self, task_type: str, context: dict):
        return {"narrative": {"public": context["user_message"]}}

    async def health_check(self) -> bool:
        return True


class RecordingProvider(BaseAiProvider):
    def __init__(self, name: str, response, capabilities: set[str] | None = None):
        super().__init__(name, capabilities=capabilities)
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def call(self, task_type: str, context: dict):
        self.calls.append((task_type, context))
        return self.response

    async def health_check(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_all_provider_failures_return_structured_failure_without_empty_dto():
    gateway = AiGateway()
    remote = RecordingProvider("remote", None)
    local = RecordingProvider("local", None)
    gateway._providers = {"remote": remote, "local": local}
    gateway._provider_order = ["remote", "local"]

    failure = await gateway._call_providers(
        "generate_narrative",
        {"declared_intent": "inspect"},
    )

    assert isinstance(failure, ProviderFailure)
    assert failure.task_type == "generate_narrative"
    assert failure.attempts == [
        "remote:null_response",
        "local:null_response",
        "local_fallback:null_response",
    ]
    assert failure.last_error_code == "provider_unavailable"
    assert failure.fallback_available is False
    assert failure.retryable is False  # null-response chains are not retryable
    assert gateway.last_provider_failure is failure

    # The public narration API must fail closed rather than manufacture an empty payload.
    assert await gateway.generate_narrative({"declared_intent": "inspect"}) is None


@pytest.mark.asyncio
async def test_combat_round_planning_requires_a_dedicated_suggestion_contract():
    gateway = AiGateway()
    remote = RecordingProvider(
        "configured",
        {
            "clusters": [
                {"actionIds": ["public-action"], "publicTitle": "Doorway exchange"}
            ],
            "dependencies": [
                {"actionId": "public-action", "dependsOnActionIds": []}
            ],
        },
    )
    gateway._providers = {"configured": remote}
    gateway._provider_order = ["configured"]

    result = await gateway.resolve_combat_round(
        {"public_actions": [{"action_id": "public-action"}]},
        room_id="combat-room",
    )

    assert isinstance(result, CombatRoundSuggestion)
    assert result.clusters[0].public_title == "Doorway exchange"
    assert remote.calls[0][0] == "resolve_combat_round"


@pytest.mark.asyncio
async def test_combat_round_planning_rejects_generic_narrative_without_local_fallback():
    gateway = AiGateway()
    remote = RecordingProvider("configured", {"narrative": {"public": "Attack now"}})
    local = RecordingProvider("local", {"clusters": [], "dependencies": []})
    gateway._providers = {"configured": remote, "local": local}
    gateway._provider_order = ["configured", "local"]

    result = await gateway.resolve_combat_round(
        {"public_actions": [{"action_id": "public-action"}]},
        room_id="combat-room",
    )

    assert result is None
    assert local.calls == []


@pytest.mark.asyncio
async def test_hypothesis_disproof_suggestion_only_returns_supplied_confirmed_fact_ids():
    gateway = AiGateway()
    remote = RecordingProvider("configured", {
        "suggestedStatus": "possible_disproved",
        "reason": "The confirmed fact conflicts.",
        "factIds": ["fact-1", "invented-fact"],
        "confidence": "medium",
    })
    gateway._providers = {"configured": remote}
    gateway._provider_order = ["configured"]

    result = await gateway.suggest_hypothesis_disproof(
        {
            "hypothesis": {"evidence_card_id": "hypothesis-1", "title": "A hypothesis"},
            "confirmed_facts": [{"evidence_card_id": "fact-1", "title": "A confirmed fact"}],
        },
        room_id="room-hypothesis",
    )

    assert result == {
        "suggestedStatus": "possible_disproved",
        "reason": "The confirmed fact conflicts.",
        "factIds": ["fact-1"],
        "confidence": "medium",
    }
    assert remote.calls[0][0] == "suggest_hypothesis_disproof"


@pytest.mark.asyncio
async def test_scene_image_suggestion_uses_text_provider_and_requires_source_citations():
    gateway = AiGateway()
    provider = RecordingProvider("configured", {
        "summary": "地下室需要一张场景图。",
        "suggestions": [{"scene_id": "cellar"}],
    })
    gateway._providers = {"configured": provider}
    gateway._provider_order = ["configured"]

    result = await gateway.suggest_scene_images({
        "scenes": [{"scene_id": "cellar", "description": "潮湿的地下室"}],
        "source_parts": [{"source_part_id": "part-1", "text_content": "地下室石阶潮湿。"}],
    })

    assert result["suggestions"][0]["scene_id"] == "cellar"
    context = provider.calls[0][1]
    assert context["user_message"]
    assert "citation" in context["system_prompt"]


@pytest.mark.asyncio
async def test_scenario_image_suggestion_restricts_provider_to_given_targets():
    gateway = AiGateway()
    provider = RecordingProvider("configured", {
        "summary": "图书管理员可补一张肖像。",
        "suggestions": [{"target_type": "npc", "target_key": "librarian"}],
    })
    gateway._providers = {"configured": provider}
    gateway._provider_order = ["configured"]

    result = await gateway.suggest_scenario_images({
        "targets": [{"target_type": "npc", "target_key": "librarian"}],
        "source_parts": [{"source_part_id": "part-1", "text_content": "图书管理员神色疲惫。"}],
    })

    assert result["suggestions"][0]["target_key"] == "librarian"
    context = provider.calls[0][1]
    assert "target_type" in context["system_prompt"]
    assert "librarian" in context["user_message"]


@pytest.mark.asyncio
async def test_structure_scenario_requests_extended_import_timeout():
    gateway = AiGateway()
    remote = RecordingProvider("remote", {"scenes": [{"name": "港口"}]})
    gateway._providers = {"remote": remote}
    gateway._provider_order = ["remote"]

    await gateway.structure_scenario("场景：港口。")

    assert remote.calls[0][1]["timeout_seconds"] == 180


@pytest.mark.asyncio
async def test_runtime_contract_repair_disables_local_fallback():
    gateway = AiGateway()
    remote = RecordingProvider("remote", {"branches": [], "endings": []})
    local = RecordingProvider("local", {"branches": [{"branch_id": "invented"}]})
    gateway._providers = {"remote": remote, "local": local}
    gateway._provider_order = ["remote", "local"]

    result = await gateway.repair_runtime_contract(
        {"canonical_text": "场景：港口。", "parts": []},
        {"scenes": [{"scene_id": "harbor", "name": "港口"}]},
    )

    assert result == {"branches": [], "endings": []}
    assert local.calls == []
    context = remote.calls[0][1]
    assert context["timeout_seconds"] == 180
    assert "不得新增场景" in context["system_prompt"]


@pytest.mark.asyncio
async def test_structure_scenario_skips_empty_worldbook_before_fallback():
    gateway = AiGateway()
    empty = RecordingProvider("configured", {"scenes": [], "endings": []})
    backup = RecordingProvider("mcp", {"scenes": [{"name": "港口"}]})
    gateway._providers = {"configured": empty, "mcp": backup}
    gateway._provider_order = ["configured", "mcp"]

    result = await gateway.structure_scenario("场景：港口。")

    assert result == {"scenes": [{"name": "港口"}]}
    assert len(empty.calls) == 1
    assert len(backup.calls) == 1


@pytest.mark.asyncio
async def test_generate_map_requires_json_structured_provider_output_without_local_fallback():
    gateway = AiGateway()
    remote = RecordingProvider("remote", None)
    local = RecordingProvider("local", {"narrative": {"public": "不是地图"}})
    gateway._providers = {"remote": remote, "local": local}
    gateway._provider_order = ["remote", "local"]

    result = await gateway.generate_map([{"name": "大厅"}])

    assert result is None
    assert local.calls == []
    assert "JSON" in remote.calls[0][1]["system_prompt"]


@pytest.mark.asyncio
async def test_generate_narrative_unwraps_kp_response_shape():
    gateway = AiGateway()
    gateway._providers = {
        "fake": FakeProvider({
            "narrative": {"public": "烛火忽然晃动，墙上的影子拉长了一瞬。"},
            "keeperNotes": "internal",
        })
    }
    gateway._provider_order = ["fake"]

    result = await gateway.generate_narrative({"player_words": "我环顾四周"})

    assert isinstance(result, NarrativePayload)
    assert result.public == "烛火忽然晃动，墙上的影子拉长了一瞬。"


@pytest.mark.asyncio
async def test_ephemeral_action_analysis_does_not_create_ai_call_log(test_db):
    gateway = AiGateway(db_conn=test_db)
    gateway._providers = {
        "fake": FakeProvider(
            {
                "understanding_summary": "临时分析",
                "risk": "low",
                "intent_type": "dialogue",
                "confirmation_requirements": [],
                "confidence": 0.9,
            }
        )
    }
    gateway._provider_order = ["fake"]
    before = test_db.execute("SELECT COUNT(*) AS count FROM ai_call_logs").fetchone()["count"]

    await gateway.analyze_action_draft(
        {
            "declared_intent": "我看看桌面",
            "intent_type": "dialogue",
            "base_state_version": 0,
            "suppress_response_log": True,
        },
        room_id="room-ephemeral",
    )

    after = test_db.execute("SELECT COUNT(*) AS count FROM ai_call_logs").fetchone()["count"]
    assert after == before


@pytest.mark.asyncio
async def test_analyze_director_action_requires_structured_json_without_local_fallback():
    gateway = AiGateway()
    remote = RecordingProvider("remote", {"text": "not a director plan"})
    local = RecordingProvider("local", {"interpreted_intent": "local story"})
    gateway._providers = {"remote": remote, "local": local}
    gateway._provider_order = ["remote", "local"]

    result = await gateway.analyze_director_action(
        {
            "declared_intent": "I open the door",
            "actor_display_name": "Ada",
            "room": {"state_version": 3},
        },
        room_id="room-director",
    )

    assert result is None
    assert local.calls == []
    assert remote.calls[0][0] == "analyze_director_action"
    assert "JSON" in remote.calls[0][1]["system_prompt"]


@pytest.mark.asyncio
async def test_analyze_director_action_rejects_incomplete_json_schema():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "interpreted_intent": "open the door",
            "confidence": 0.8,
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.analyze_director_action(
        {
            "declared_intent": "I open the door",
            "actor_display_name": "Ada",
            "room": {"state_version": 3},
        },
        room_id="room-director",
    )

    assert result is None


@pytest.mark.asyncio
async def test_analyze_director_action_accepts_core_provider_fields_with_safe_defaults():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "actor_display_name": "Ada",
            "interpreted_intent": "inspect the visible station",
            "intent_type": "dialogue",
            "confidence": 0.88,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.analyze_director_action(
        {
            "context_version": 3,
            "declared_intent": "I look around",
            "actor_display_name": "Ada",
            "local_analysis": {"draft_id": "draft-1", "visibility": "public"},
        },
        room_id="room-director",
    )

    assert result is not None
    assert result["action_id"] == "draft-1"
    assert result["context_version"] == 3
    assert result["state_patch"] == []
    assert result["event_plan"] == []
    assert result["semantic_progression"] == {
        "targetNodeId": None,
        "fromNodeId": None,
        "citation": None,
        "rationale": None,
    }
    assert result["analysis_source"] == "fallback_provider"


@pytest.mark.asyncio
async def test_director_provider_payload_removes_account_tokens_and_raw_safety_text():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "actor_display_name": "Ada",
            "interpreted_intent": "inspect the visible station",
            "intent_type": "dialogue",
            "confidence": 0.88,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.analyze_director_action(
        {
            "context_version": 3,
            "declared_intent": "I look around",
            "actor_display_name": "Ada",
            "account_id": "account-secret",
            "owner_token": "owner-secret",
            "player_token": "player-secret",
            "raw_safety_text": "private-boundary-text",
            "safety_reason": "private-safety-reason",
            "private_note": "private-player-note",
            "room": {
                "room_id": "room-internal-id",
                "state_version": 3,
            },
            "actor": {
                "character_id": "character-internal-id",
                "display_name": "Ada",
                "sheet": {
                    "occupation": "记者",
                    "player_token": "nested-player-secret",
                    "backstory": "irrelevant-private-backstory",
                },
            },
            "local_analysis": {"draft_id": "draft-minimal"},
            "current_scene": {
                "node_id": "station",
                "text": "站台当前可见。",
                "room_id": "nested-room-internal-id",
                "citation": {
                    "page_number": 7,
                    "storage_path": "current-scene-storage-secret",
                    "full_text": "current-scene-full-text-secret",
                },
                "scene_variables": {
                    "solo_skill_bonus_dice": -1,
                    "solo_adventure_version": "scene-variable-version-secret",
                    "requestId": "scene-variable-action-secret",
                },
            },
            "runtime_package": {
                "scenario_version_id": "scenario-version-internal-id",
                "world_book": {"truth": "irrelevant-world-secret"},
                "semantic_scenes": [{"id": "remote-scene-internal-id"}],
                "story_evidence_nodes": [
                    {
                        "logical_key": "station",
                        "title": "站台管理员知道末班车时间",
                        "citation": {
                            "page_number": 8,
                            "absolute_path": "evidence-absolute-path-secret",
                        },
                    }
                ],
                "semantic_progression_rules": {
                    "edges": [{
                        "from_scene_id": "station",
                        "to_scene_id": "platform",
                        "relation_type": "transitions_to",
                        "conditions": [{
                            "kind": "scene",
                            "id": "station",
                            "full_text": "condition-full-text-secret",
                        }],
                        "citation": {
                            "page_number": 9,
                            "storage_path": "edge-storage-secret",
                        },
                    }],
                    "solo_adventure": {"nodes": []},
                },
            },
            "recent_events": [
                {
                    "event_id": "event-internal-id",
                    "event_type": "s2c_public_observation",
                    "audience": "party",
                    "payload": {
                        "text": "站台仍然开放。",
                        "requestId": "event-request-action-secret",
                        "nested": {"account": "event-nested-secret"},
                    },
                }
            ],
            "inventory": [
                {
                    "id": "inventory-internal-id",
                    "character_id": "character-internal-id",
                    "name": "记者证",
                    "quantity": 1,
                    "source": "scenario_purchase:inventory-source-node-secret",
                }
            ],
        },
        room_id="room-director",
    )

    assert result is not None
    payload = remote.calls[0][1]
    rendered = json.dumps(payload, ensure_ascii=False)
    assert "I look around" in rendered
    assert "Ada" in rendered
    assert "记者" in rendered
    assert "站台管理员知道末班车时间" in rendered
    assert "记者证" in rendered
    for forbidden in (
        "account-secret",
        "owner-secret",
        "player-secret",
        "nested-player-secret",
        "private-boundary-text",
        "private-safety-reason",
        "private-player-note",
        "room-internal-id",
        "character-internal-id",
        "nested-room-internal-id",
        "scenario-version-internal-id",
        "remote-scene-internal-id",
        "irrelevant-world-secret",
        "irrelevant-private-backstory",
        "draft-minimal",
        "event-internal-id",
        "inventory-internal-id",
        "scene-variable-version-secret",
        "scene-variable-action-secret",
        "event-request-action-secret",
        "event-nested-secret",
        "inventory-source-node-secret",
        "current-scene-storage-secret",
        "current-scene-full-text-secret",
        "evidence-absolute-path-secret",
        "condition-full-text-secret",
        "edge-storage-secret",
    ):
        assert forbidden not in rendered
    assert payload["current_scene"]["scene_variables"] == {
        "solo_skill_bonus_dice": -1,
    }
    assert payload["current_scene"]["citation"] == {"page_number": 7}


@pytest.mark.asyncio
async def test_room_runtime_binding_prevents_silent_remote_provider_switch(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) VALUES ('pinned-ai-room', 'owner')"
    )
    test_db.execute(
        "INSERT INTO host_states (room_id, state) VALUES ('pinned-ai-room', %s)",
        (
            json.dumps({
                "ai_config": {
                    "provider_order": "other,pinned,local",
                    "runtime_binding": {
                        "locked": True,
                        "primary_provider": "pinned",
                        "primary_model": "model-a",
                        "prompt_template_version": "m0-runtime-v1",
                        "rule_compiler_version": "rules-v1",
                    },
                },
            }),
        ),
    )
    test_db.commit()
    gateway = AiGateway(db_conn=test_db)
    pinned = RecordingProvider(
        "pinned",
        {"narrative": {"public": "pinned result"}},
    )
    pinned.model = "model-a"
    other = RecordingProvider(
        "other",
        {"narrative": {"public": "silently switched result"}},
    )
    other.model = "model-b"
    local = RecordingProvider(
        "local",
        {"narrative": {"public": "deterministic fallback"}},
    )
    gateway._providers = {
        "pinned": pinned,
        "other": other,
        "local": local,
    }
    gateway._provider_order = ["other", "pinned", "local"]

    result = await gateway.resolve_turn(
        {"declared_intent": "I inspect the station."},
        room_id="pinned-ai-room",
    )

    assert result.narrative.public == "pinned result"
    assert len(pinned.calls) == 1
    assert other.calls == []
    assert local.calls == []


@pytest.mark.asyncio
async def test_locked_room_does_not_silently_use_a_different_prompt_template(
    test_db,
):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) "
        "VALUES ('missing-prompt-room', 'owner')"
    )
    test_db.execute(
        "INSERT INTO host_states (room_id, state) VALUES ('missing-prompt-room', %s)",
        (
            json.dumps({
                "ai_config": {
                    "runtime_binding": {
                        "locked": True,
                        "primary_provider": "pinned",
                        "primary_model": "model-a",
                        "prompt_template_version": "removed-prompt-version",
                    },
                },
            }),
        ),
    )
    test_db.commit()
    gateway = AiGateway(db_conn=test_db)
    pinned = RecordingProvider(
        "pinned",
        {
            "actor_display_name": "Ada",
            "interpreted_intent": "inspect",
            "intent_type": "dialogue",
            "confidence": 0.8,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
        },
    )
    pinned.model = "model-a"
    gateway._providers = {"pinned": pinned}
    gateway._provider_order = ["pinned"]

    result = await gateway.analyze_director_action(
        {
            "context_version": 1,
            "declared_intent": "I inspect.",
            "actor_display_name": "Ada",
        },
        room_id="missing-prompt-room",
    )

    assert result is None
    assert pinned.calls == []


@pytest.mark.asyncio
async def test_locked_room_rejects_prompt_content_signature_mismatch(test_db):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) "
        "VALUES ('changed-prompt-room', 'owner')"
    )
    test_db.execute(
        "INSERT INTO host_states (room_id, state) VALUES ('changed-prompt-room', %s)",
        (
            json.dumps({
                "ai_config": {
                    "runtime_binding": {
                        "locked": True,
                        "primary_provider": "pinned",
                        "primary_model": "model-a",
                        "prompt_template_version": "m0-runtime-v1",
                        "prompt_template_signature": "stale-content-signature",
                    },
                },
            }),
        ),
    )
    test_db.commit()
    gateway = AiGateway(db_conn=test_db)
    pinned = RecordingProvider(
        "pinned",
        {
            "actor_display_name": "Ada",
            "interpreted_intent": "inspect",
            "intent_type": "dialogue",
            "confidence": 0.8,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
        },
    )
    pinned.model = "model-a"
    gateway._providers = {"pinned": pinned}

    result = await gateway.analyze_director_action(
        {
            "context_version": 1,
            "declared_intent": "I inspect.",
            "actor_display_name": "Ada",
        },
        room_id="changed-prompt-room",
    )

    assert result is None
    assert pinned.calls == []


@pytest.mark.asyncio
async def test_locked_room_action_draft_rejects_prompt_signature_mismatch(
    test_db,
):
    test_db.execute(
        "INSERT INTO rooms (room_id, owner_token) "
        "VALUES ('changed-draft-prompt-room', 'owner')"
    )
    test_db.execute(
        "INSERT INTO host_states "
        "(room_id, state) VALUES ('changed-draft-prompt-room', %s)",
        (
            json.dumps({
                "ai_config": {
                    "runtime_binding": {
                        "locked": True,
                        "primary_provider": "pinned",
                        "primary_model": "model-a",
                        "prompt_template_version": "m0-runtime-v1",
                        "prompt_template_signature": "stale-content-signature",
                    },
                },
            }),
        ),
    )
    test_db.commit()
    gateway = AiGateway(db_conn=test_db)
    pinned = RecordingProvider(
        "pinned",
        {
            "understanding_summary": "inspect",
            "risk": "low",
            "intent_type": "dialogue",
            "confidence": 0.8,
        },
    )
    pinned.model = "model-a"
    gateway._providers = {"pinned": pinned}

    result = await gateway.analyze_action_draft(
        {
            "declared_intent": "I inspect.",
            "intent_type": "dialogue",
            "base_state_version": 1,
        },
        room_id="changed-draft-prompt-room",
    )

    assert result is None
    assert pinned.calls == []


@pytest.mark.asyncio
async def test_analyze_director_action_accepts_at_most_two_composite_steps():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "actor_display_name": "Ada",
            "interpreted_intent": "先撬锁，再进入房间",
            "intent_type": "skill_check",
            "confidence": 0.88,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
            "intent_contract": {
                "target": "房门",
                "method": "开锁",
                "object": "门锁",
                "constraints": ["保持安静"],
                "resources": ["开锁工具"],
                "conditions": ["门锁完好"],
                "visibility": "public",
                "ambiguities": [],
            },
            "action_steps": [
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
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.analyze_director_action(
        {
            "context_version": 3,
            "declared_intent": "我先撬锁，成功后进入房间。",
            "actor_display_name": "Ada",
            "local_analysis": {"draft_id": "draft-1", "visibility": "public"},
        },
        room_id="room-director",
    )

    assert result is not None
    assert [step["step_id"] for step in result["action_steps"]] == [
        "pick-lock",
        "enter-room",
    ]
    assert result["action_steps"][1]["execution_condition"] == "previous_step_success"
    assert result["intent_contract"]["target"] == "房门"
    assert result["intent_contract"]["conditions"] == ["门锁完好"]


@pytest.mark.asyncio
async def test_analyze_director_action_requests_a_primary_step_when_provider_returns_three():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "actor_display_name": "Ada",
            "interpreted_intent": "射击人影、掩护同伴并检查门锁",
            "intent_type": "combat_action",
            "confidence": 0.91,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
            "action_steps": [
                {
                    "step_id": "shoot",
                    "summary": "朝人影射击",
                    "declared_intent": "我朝人影射击。",
                    "intent_type": "combat_action",
                },
                {
                    "step_id": "cover",
                    "summary": "掩护同伴撤退",
                    "declared_intent": "我掩护同伴撤退。",
                    "intent_type": "combat_action",
                },
                {
                    "step_id": "inspect-lock",
                    "summary": "检查门锁",
                    "declared_intent": "我检查门锁。",
                    "intent_type": "skill_check",
                },
            ],
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.analyze_director_action(
        {
            "context_version": 3,
            "declared_intent": "我射击人影、掩护同伴，再检查门锁。",
            "actor_display_name": "Ada",
            "local_analysis": {"draft_id": "draft-1", "visibility": "public"},
        },
        room_id="room-director",
    )

    assert result is not None
    assert result["action_steps"] == []
    assert result["requires_player_clarification"] is True
    assert len(result["clarification_options"]) == 3
    assert "主要" in result["clarification_options"][0]["label"]


@pytest.mark.asyncio
async def test_analyze_director_action_normalizes_observation_and_unsafe_state_patch():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "actor_display_name": "Ada",
            "interpreted_intent": "inspect the visible station",
            "intent_type": "observation",
            "state_patch": {"hp": 0},
            "narration_identity": "Ada",
            "confidence": 0.91,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "observe",
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.analyze_director_action(
        {
            "context_version": 3,
            "declared_intent": "I look around",
            "actor_display_name": "Ada",
            "local_analysis": {"draft_id": "draft-1", "visibility": "public"},
        },
        room_id="room-director",
    )

    assert result is not None
    assert result["intent_type"] == "dialogue"
    assert result["state_patch"] == []
    assert "narration_identity" not in result


@pytest.mark.asyncio
async def test_analyze_director_action_falls_back_from_unknown_intent_and_empty_host_exception():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "interpreted_intent": "put the suitcase away",
            "intent_type": "action",
            "confidence": 0.95,
            "requires_player_clarification": False,
            "requires_host_exception": True,
            "exception_reason": None,
            "narration_mode": "descriptive",
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.analyze_director_action(
        {
            "declared_intent": "I put my suitcase away and sit down",
            "actor_display_name": "Ada",
            "local_analysis": {"intent_type": "dialogue", "visibility": "public"},
        },
        room_id="room-director",
    )

    assert result is not None
    assert result["intent_type"] == "dialogue"
    assert result["requires_host_exception"] is False


@pytest.mark.asyncio
async def test_analyze_director_action_normalizes_redacted_provider_citations():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "interpreted_intent": "board the bus",
            "intent_type": "move",
            "confidence": 0.9,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "scene",
            "citations": [
                {
                    "label": "redacted-label",
                    "page": 51,
                    "verified": True,
                    "source_part_id": "part-51",
                }
            ],
            "semantic_progression": {
                "targetNodeId": "8",
                "citation_label": "redacted-label",
                "citation": {
                    "label": "redacted-label",
                    "page": 51,
                    "verified": True,
                    "source_part_id": "part-51",
                },
            },
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.analyze_director_action(
        {
            "declared_intent": "I board the bus",
            "actor_display_name": "Ada",
            "local_analysis": {"intent_type": "move", "visibility": "public"},
        },
        room_id="room-director",
    )

    assert result is not None
    citation = {
        "source": None,
        "source_part_id": "part-51",
        "content_item_id": None,
        "page_number": 51,
        "location": None,
    }
    assert result["citations"] == [citation]
    assert result["semantic_progression"] == {
        "targetNodeId": "8",
        "fromNodeId": None,
        "citation": citation,
        "rationale": None,
    }


@pytest.mark.asyncio
async def test_analyze_director_action_marks_actual_provider_source():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "action_id": "action-1",
            "context_version": 3,
            "actor_display_name": "Ada",
            "declared_intent": "I open the door",
            "interpreted_intent": "open the door",
            "intent_type": "move",
            "preconditions": [],
            "mechanic_plan": {"mechanic": "auto_success"},
            "state_patch": [],
            "event_plan": [],
            "semantic_progression": {},
            "npc_reactions": [],
            "time_impact": {},
            "visibility": "public",
            "basis_refs": [],
            "citations": [],
            "confidence": 0.8,
            "requires_player_clarification": False,
            "clarification_options": [],
            "requires_host_exception": False,
            "exception_reason": None,
            "narration_mode": "summarize",
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.analyze_director_action(
        {
            "declared_intent": "I open the door",
            "actor_display_name": "Ada",
            "room": {"state_version": 3},
        },
        room_id="room-director",
    )

    assert result is not None
    assert result["analysis_source"] == "fallback_provider"


@pytest.mark.asyncio
async def test_narrate_action_scrubs_internal_ids_and_overwrites_provider_source():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "context_version": 4,
            "director_plan_digest": "digest",
            "narrative_text": "Ada checks the brass key on the oak desk.",
            "environment_changes": ["The desk drawer is open."],
            "interactable_objects": ["oak desk", "brass key"],
            "open_question": "How do you inspect the brass key?",
            "fact_refs": {
                "narrative_text": ["fact:ada", "fact:brass-key", "fact:oak-desk"],
                "environment_changes": ["fact:desk-drawer"],
                "interactable_objects": ["fact:oak-desk", "fact:brass-key"],
                "open_question": ["fact:brass-key"],
            },
            "redacted_citations": [{"source": "scene", "page_number": 1}],
            "style_pack_version": "noir-v1",
            "provider_source": "configured_provider",
            "status": "completed",
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]

    result = await gateway.narrate_action(
        {
            "local_action_id": "action-secret",
            "room_id": "room-secret",
            "character_id": "char-secret",
            "investigator_name": "Ada",
            "allowed_facts": [{"fact_ref": "fact:ada", "text": "Ada"}],
        },
        room_id="room-secret",
    )

    provider_context = remote.calls[0][1]
    serialized = json.dumps(provider_context, ensure_ascii=False)
    assert "action-secret" not in serialized
    assert "room-secret" not in serialized
    assert "char-secret" not in serialized
    assert result["action_id"] == "action-secret"
    assert result["provider_source"] == "fallback_provider"


@pytest.mark.asyncio
async def test_narrate_action_repairs_only_empty_system_change_from_verified_context():
    gateway = AiGateway()
    remote = RecordingProvider(
        "mcp",
        {
            "context_version": 0,
            "director_plan_digest": "untrusted-digest",
            "narrative_text": "Ada steps into the coach and takes the window seat.",
            "environment_changes": [],
            "interactable_objects": ["coach window"],
            "open_question": "What do you inspect from your seat?",
            "fact_refs": {
                "narrative_text": ["fact:scene"],
                "environment_changes": [],
                "interactable_objects": ["fact:scene"],
                "open_question": ["fact:scene"],
            },
            "redacted_citations": [],
            "style_pack_version": "noir-v1",
            "state_patch": [{"field": "hp", "value": 0}],
            "status": "completed",
        },
    )
    gateway._providers = {"mcp": remote}
    gateway._provider_order = ["mcp"]
    context = {
        "local_action_id": "action-safe",
        "context_version": 4,
        "director_plan_digest": "verified-digest",
        "visible_state_changes": ["你已抵达新的可见场景。"],
        "allowed_facts": [
            {"fact_ref": "fact:visible-change:arrival", "text": "你已抵达新的可见场景。"},
            {"fact_ref": "fact:scene", "text": "长途车车厢"},
        ],
    }

    result = await gateway.narrate_action(context, action_id="action-safe")

    assert result is not None
    assert result["context_version"] == 4
    assert result["director_plan_digest"] == "verified-digest"
    assert result["environment_changes"] == ["你已抵达新的可见场景。"]
    assert result["fact_refs"]["environment_changes"] == ["fact:visible-change:arrival"]
    assert "state_patch" not in result


@pytest.mark.asyncio
async def test_narrate_action_normalizes_mimo_success_and_verified_fact_ref_list():
    gateway = AiGateway()
    remote = RecordingProvider(
        "configured:mimo",
        {
            "context_version": 0,
            "director_plan_digest": "untrusted-digest",
            "narrative_text": "Ada boards the coach and takes the window seat.",
            "environment_changes": ["Ada reaches the visible coach interior."],
            "interactable_objects": ["coach window"],
            "open_question": "What do you inspect from your seat?",
            "fact_refs": ["fact:scene", "fact:visible-change:arrival"],
            "redacted_citations": [],
            "style_pack_version": "noir-v1",
            "status": "success",
        },
    )
    gateway._providers = {"configured:mimo": remote}
    gateway._provider_order = ["configured:mimo"]
    context = {
        "local_action_id": "action-mimo",
        "context_version": 4,
        "director_plan_digest": "verified-digest",
        "allowed_facts": [
            {"fact_ref": "fact:scene", "text": "长途车车厢"},
            {
                "fact_ref": "fact:visible-change:arrival",
                "text": "Ada reaches the visible coach interior.",
            },
        ],
    }

    result = await gateway.narrate_action(context, action_id="action-mimo")

    assert result is not None
    assert result["status"] == "completed"
    assert result["context_version"] == 4
    assert result["director_plan_digest"] == "verified-digest"
    assert set(result["fact_refs"]) == {
        "narrative_text",
        "environment_changes",
        "interactable_objects",
        "open_question",
    }
    assert all(
        refs == ["fact:scene", "fact:visible-change:arrival"]
        for refs in result["fact_refs"].values()
    )


@pytest.mark.asyncio
async def test_narrate_action_repairs_empty_mimo_interactables_and_question_from_context():
    gateway = AiGateway()
    remote = RecordingProvider(
        "configured:mimo",
        {
            "narrative_text": "Ada enters the coach.",
            "environment_changes": ["Ada reaches the visible coach interior."],
            "interactable_objects": [],
            "open_question": "",
            "fact_refs": {
                "narrative_text": ["fact:scene"],
                "environment_changes": ["fact:visible-change:arrival"],
                "interactable_objects": [],
                "open_question": [],
            },
            "redacted_citations": [],
            "style_pack_version": "noir-v1",
            "status": "completed",
        },
    )
    gateway._providers = {"configured:mimo": remote}
    gateway._provider_order = ["configured:mimo"]
    context = {
        "local_action_id": "action-mimo-empty",
        "context_version": 4,
        "director_plan_digest": "verified-digest",
        "interactable_objects": ["coach window"],
        "allowed_facts": [
            {"fact_ref": "fact:scene", "text": "长途车车厢"},
            {
                "fact_ref": "fact:visible-change:arrival",
                "text": "Ada reaches the visible coach interior.",
            },
            {"fact_ref": "fact:interactable:1", "text": "coach window"},
        ],
    }

    result = await gateway.narrate_action(context, action_id="action-mimo-empty")

    assert result is not None
    assert result["interactable_objects"] == ["coach window"]
    assert result["open_question"] == "你想如何继续观察coach window？"
    assert result["fact_refs"]["interactable_objects"] == ["fact:interactable:1"]
    assert result["fact_refs"]["open_question"] == ["fact:interactable:1"]


@pytest.mark.asyncio
async def test_narrate_action_uses_visible_scene_when_mimo_has_no_interactables():
    gateway = AiGateway()
    remote = RecordingProvider(
        "configured:mimo",
        {
            "narrative_text": "Ada enters the coach.",
            "environment_changes": ["Ada reaches the visible coach interior."],
            "interactable_objects": [],
            "open_question": "",
            "fact_refs": {
                "narrative_text": ["fact:scene"],
                "environment_changes": ["fact:visible-change:arrival"],
                "interactable_objects": [],
                "open_question": [],
            },
            "redacted_citations": [],
            "style_pack_version": "noir-v1",
            "status": "completed",
        },
    )
    gateway._providers = {"configured:mimo": remote}
    gateway._provider_order = ["configured:mimo"]
    context = {
        "local_action_id": "action-mimo-scene",
        "context_version": 4,
        "director_plan_digest": "verified-digest",
        "allowed_facts": [
            {"fact_ref": "fact:scene", "text": "长途车车厢"},
            {
                "fact_ref": "fact:visible-change:arrival",
                "text": "Ada reaches the visible coach interior.",
            },
        ],
    }

    result = await gateway.narrate_action(context, action_id="action-mimo-scene")

    assert result is not None
    assert result["interactable_objects"] == ["当前环境"]
    assert result["open_question"] == "你想如何继续观察当前环境？"
    assert result["fact_refs"]["interactable_objects"] == ["fact:scene"]
    assert result["fact_refs"]["open_question"] == ["fact:scene"]


@pytest.mark.asyncio
async def test_narrate_action_repairs_missing_mimo_field_citations_from_verified_context():
    gateway = AiGateway()
    remote = RecordingProvider(
        "configured:mimo",
        {
            "narrative_text": "Ada continues the journey.",
            "environment_changes": [],
            "interactable_objects": [],
            "open_question": "旅程的下一站是什么？",
            "fact_refs": {},
            "redacted_citations": [],
            "style_pack_version": "noir-v1",
            "status": "completed",
        },
    )
    gateway._providers = {"configured:mimo": remote}
    gateway._provider_order = ["configured:mimo"]
    context = {
        "local_action_id": "action-mimo-missing-citations",
        "context_version": 4,
        "director_plan_digest": "verified-digest",
        "visible_state_changes": ["你已抵达新的可见场景。"],
        "allowed_facts": [
            {"fact_ref": "fact:scene", "text": "长途车车厢"},
            {
                "fact_ref": "fact:visible-change:arrival",
                "text": "你已抵达新的可见场景。",
            },
        ],
    }

    result = await gateway.narrate_action(
        context,
        action_id="action-mimo-missing-citations",
    )

    assert result is not None
    assert result["narrative_text"] == "你已抵达新的可见场景。"
    assert result["environment_changes"] == ["你已抵达新的可见场景。"]
    assert result["interactable_objects"] == ["当前环境"]
    assert result["open_question"] == "你想如何继续观察当前环境？"
    assert result["fact_refs"] == {
        "narrative_text": ["fact:visible-change:arrival"],
        "environment_changes": ["fact:visible-change:arrival"],
        "interactable_objects": ["fact:scene"],
        "open_question": ["fact:scene"],
    }


@pytest.mark.asyncio
async def test_narrate_action_falls_back_when_mcp_result_cannot_be_validated():
    gateway = AiGateway()
    invalid_mcp = RecordingProvider("mcp", {"unexpected": "shape"})
    fallback = RecordingProvider(
        "deepseek",
        {
            "narrative_text": "雨水沿着候车亭的玻璃缓缓滑落。",
            "environment_changes": ["候车区仍然安静。"],
            "interactable_objects": ["候车亭"],
            "open_question": "你想先观察候车亭的哪个角落？",
            "fact_refs": {
                "narrative_text": ["fact:scene"],
                "environment_changes": ["fact:scene"],
                "interactable_objects": ["fact:scene"],
                "open_question": ["fact:scene"],
            },
            "redacted_citations": [],
            "style_pack_version": "noir-v1",
            "status": "completed",
        },
    )
    gateway._providers = {"mcp": invalid_mcp, "deepseek": fallback}
    gateway._provider_order = ["mcp", "deepseek"]

    result = await gateway.narrate_action(
        {
            "local_action_id": "action-narrator-fallback",
            "context_version": 4,
            "director_plan_digest": "观察候车亭。",
            "allowed_facts": [{"fact_ref": "fact:scene", "text": "雨夜的候车亭"}],
        },
        action_id="action-narrator-fallback",
    )

    assert result is not None
    assert result["narrative_text"] == "雨水沿着候车亭的玻璃缓缓滑落。"
    assert len(invalid_mcp.calls) == 1
    assert len(fallback.calls) == 1


@pytest.mark.asyncio
async def test_generate_narrative_accepts_full_kp_response_model():
    gateway = AiGateway()
    gateway._providers = {
        "fake": FakeProvider(
            KpResponse(
                narrative=NarrativePayload(public="空气里有股焦味，像有什么东西刚刚熄灭。")
            ).model_dump(by_alias=True)
        )
    }
    gateway._provider_order = ["fake"]

    result = await gateway.generate_narrative({"player_words": "我闻一闻空气"})

    assert isinstance(result, NarrativePayload)
    assert result.public == "空气里有股焦味，像有什么东西刚刚熄灭。"


@pytest.mark.asyncio
async def test_generate_narrative_builds_user_message_when_missing():
    gateway = AiGateway()
    gateway._providers = {"fake": EchoUserMessageProvider()}
    gateway._provider_order = ["fake"]

    result = await gateway.generate_narrative({
        "scenario_title": "向火独行",
        "investigator_name": "查尔斯·钱伯斯",
        "occupation": "记者",
        "background": "追踪异常新闻的调查记者",
        "player_words": "我压低声音问老板，今晚灯塔那边到底发生过什么。",
    })

    assert "查尔斯·钱伯斯" in result.public
    assert "记者" in result.public
    assert "今晚灯塔那边到底发生过什么" in result.public


@pytest.mark.asyncio
async def test_generate_narrative_preserves_retry_context_when_player_words_missing():
    gateway = AiGateway()
    gateway._providers = {"fake": EchoUserMessageProvider()}
    gateway._provider_order = ["fake"]

    result = await gateway.generate_narrative({
        "room_id": "room-1",
        "character_id": "char-1",
        "declared_intent": "我贴近门边偷听屋里的动静",
        "intent_type": "dialogue",
        "previous_narrative": "你刚刚的脚步声在走廊尽头荡开。",
        "spoiler_constraint": "不要提前说出凶手身份",
    })

    assert "我贴近门边偷听屋里的动静" in result.public
    assert "不要提前说出凶手身份" in result.public
    assert "上一版叙事" in result.public


@pytest.mark.asyncio
async def test_structure_content_package_text_uses_existing_chain():
    gateway = AiGateway()
    mcp = RecordingProvider("mcp", None, capabilities={"text", "image"})
    deepseek = RecordingProvider("deepseek", {"scenes": [{"name": "A"}]})
    local = RecordingProvider("local", {"scenes": [{"name": "local"}]})
    gateway._providers = {"mcp": mcp, "deepseek": deepseek, "local": local}
    gateway._provider_order = ["mcp", "deepseek", "local"]

    package = ContentPackage(
        source_filename="scenario.txt",
        source_sha256="sha",
        mime_type="text/plain",
        parts=[ContentPart(ordinal=1, kind="text", text="第一幕：调查开始")],
        canonical_text="第一幕：调查开始",
        requires_multimodal=False,
    )

    result = await gateway.structure_content_package(package)

    assert result == {"scenes": [{"name": "A"}]}
    assert [provider.calls[0][0] for provider in (mcp, deepseek)] == [
        "structure_scenario",
        "structure_scenario",
    ]
    assert "rawText" in mcp.calls[0][1]
    assert mcp.calls[0][1]["rawText"] == "第一幕：调查开始"
    assert local.calls == []


@pytest.mark.asyncio
async def test_structure_content_package_requests_cited_scene_branches():
    gateway = AiGateway()
    provider = RecordingProvider(
        "configured",
        {"scenes": [{"name": "A"}]},
        capabilities={"text"},
    )
    gateway._providers = {"configured": provider}
    gateway._provider_order = ["configured"]
    package = ContentPackage(
        source_filename="scenario.txt",
        source_sha256="sha",
        mime_type="text/plain",
        parts=[ContentPart(ordinal=1, kind="text", text="第一幕：调查开始")],
        canonical_text="第一幕：调查开始",
        requires_multimodal=False,
    )

    await gateway.structure_content_package(package)

    prompt = provider.calls[0][1]["system_prompt"]
    assert "branches" in prompt
    assert "scene_id" in prompt
    assert "from_scene_id" in prompt
    assert "citation" in prompt


@pytest.mark.asyncio
async def test_structure_content_package_requires_image_provider():
    gateway = AiGateway()
    deepseek = RecordingProvider("deepseek", {"scenes": [{"name": "text"}]})
    local = RecordingProvider("local", {"scenes": [{"name": "local"}]})
    gateway._providers = {"deepseek": deepseek, "local": local}
    gateway._provider_order = ["deepseek", "local"]

    package = ContentPackage(
        source_filename="scan.pdf",
        source_sha256="sha",
        mime_type="application/pdf",
        parts=[ContentPart(ordinal=1, kind="image", mime_type="image/png", data_url="data:image/png;base64,AA==")],
        canonical_text="",
        requires_multimodal=True,
    )

    with pytest.raises(RuntimeError, match="multimodal_provider_unavailable"):
        await gateway.structure_content_package(package)

    assert deepseek.calls == []
    assert local.calls == []


@pytest.mark.asyncio
async def test_structure_content_package_rejects_narrative_shaped_image_result():
    gateway = AiGateway()
    mcp = RecordingProvider(
        "mcp",
        {"narrative": {"public": "provider error fallback"}},
        capabilities={"text", "image"},
    )
    gateway._providers = {"mcp": mcp}
    gateway._provider_order = ["mcp"]
    package = ContentPackage(
        source_filename="scan.pdf",
        source_sha256="sha",
        mime_type="application/pdf",
        parts=[ContentPart(
            ordinal=1,
            kind="image",
            mime_type="image/png",
            data_url="data:image/png;base64,AA==",
        )],
        canonical_text="",
        requires_multimodal=True,
    )

    with pytest.raises(RuntimeError, match="multimodal_provider_unavailable"):
        await gateway.structure_content_package(package)


@pytest.mark.asyncio
async def test_structure_content_package_falls_back_to_text_chain_when_canonical_text_is_long_enough():
    gateway = AiGateway()
    mcp = RecordingProvider("mcp", None, capabilities={"text", "image"})
    deepseek = RecordingProvider("deepseek", {"scenes": [{"name": "fallback"}]})
    local = RecordingProvider("local", {"scenes": [{"name": "local"}]})
    gateway._providers = {"mcp": mcp, "deepseek": deepseek, "local": local}
    gateway._provider_order = ["mcp", "deepseek", "local"]

    canonical_text = "这是一个足够长的纯文本摘要，用于在图像解析失败后回退到文本结构化链路。"
    canonical_text = canonical_text + "补充内容" * 10
    package = ContentPackage(
        source_filename="mixed.pdf",
        source_sha256="sha",
        mime_type="application/pdf",
        parts=[ContentPart(ordinal=1, kind="image", mime_type="image/png", data_url="data:image/png;base64,AA==")],
        canonical_text=canonical_text,
        requires_multimodal=True,
    )

    result = await gateway.structure_content_package(package)

    assert result == {"scenes": [{"name": "fallback"}]}
    assert len(mcp.calls) == 2
    assert mcp.calls[0][1]["contentPackage"]["requires_multimodal"] is True
    assert mcp.calls[1][1]["rawText"] == canonical_text
    assert deepseek.calls[0][1]["rawText"] == canonical_text
    assert local.calls == []


# ── R4 slice B: review_action_intent gateway task contract ──


@pytest.mark.asyncio
async def test_review_action_intent_returns_validated_candidate(test_db):
    gateway = AiGateway(db_conn=test_db)
    gateway._providers = {
        "fake": FakeProvider(
            {
                "candidateExplanation": "冻结文本本意是检查地板。",
                "reason": "只基于冻结原文的重释。",
                "conviction": "medium",
            }
        )
    }
    gateway._provider_order = ["fake"]
    result = await gateway.review_action_intent(
        {"frozen_intent": "我检查了门框", "objection": "结算对象理解错了"},
        room_id="room-review-gw",
    )
    assert result is not None
    assert result["candidateExplanation"] == "冻结文本本意是检查地板。"
    assert result["reason"]
    assert result["conviction"] == "medium"
    # The candidate never carries mutations.
    assert "mutations" not in result


@pytest.mark.asyncio
async def test_review_action_intent_rejects_missing_explanation_or_bad_shape(test_db):
    for raw in (
        {"reason": "没有候选解释", "conviction": "low"},
        {"candidateExplanation": "", "reason": "空", "conviction": "high"},
        {"candidateExplanation": 123, "reason": "类型错", "conviction": "low"},
        "not a dict",
    ):
        gateway = AiGateway(db_conn=test_db)
        gateway._providers = {"fake": FakeProvider(raw)}
        gateway._provider_order = ["fake"]
        result = await gateway.review_action_intent(
            {"frozen_intent": "原文", "objection": "异议"},
            room_id="room-review-gw",
        )
        assert result is None


@pytest.mark.asyncio
async def test_review_action_intent_provider_failure_returns_none(test_db):
    class _RaisingProvider(FakeProvider):
        async def call(self, task_type, context):
            del task_type, context
            raise TimeoutError("provider down")

    gateway = AiGateway(db_conn=test_db)
    gateway._providers = {"fake": _RaisingProvider({})}
    gateway._provider_order = ["fake"]
    result = await gateway.review_action_intent(
        {"frozen_intent": "原文", "objection": "异议"},
        room_id="room-review-gw",
    )
    assert result is None
