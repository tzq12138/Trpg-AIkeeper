import json

import pytest
from pydantic import ValidationError

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
                "world_book": {"synopsis": "A compact mystery."},
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


def test_director_progression_citation_must_match_the_rule_edge(client, test_db):
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
    assert draft["adjudication_stage"] == "host_exception_required"
    assert draft["params"].get("targetNodeId") is None
    assert draft["semantic_progression"]["rejected"] is True


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
