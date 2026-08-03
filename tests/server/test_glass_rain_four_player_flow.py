import asyncio

import pytest

from src.server.ai.gateway import AiGateway
from src.server.ai.providers import BaseAiProvider
from src.server.engine.resolution_pipeline import ResolutionPipeline
from src.server.engine.state_service import StateService
from src.server.models import MechanicCompileResult
from tests.server.test_glass_rain_golden_flow import (
    _FailingNarratorGateway,
    _GoldenFlowCompiler,
    _RecordingDispatcher,
    _create_started_room,
    _install_glass_rain,
    _runtime_package,
)


class _PersuadeCompiler:
    async def compile(self, _intent, _scenario, _character):
        return MechanicCompileResult(
            triggeredMechanic="skill_check",
            skillName="说服",
            difficulty="regular",
        )


class _DeterministicDirectorGateway:
    authoritative_audit_required = False

    async def analyze_director_action(self, context, room_id=None):
        del room_id
        return {
            "context_version": context["context_version"],
            "interpreted_intent": context["declared_intent"],
            "intent_type": context["intent_type"],
            "confidence": 0.99,
            "requires_player_clarification": False,
            "requires_host_exception": False,
            "narration_mode": "local_verified",
            "analysis_source": "local_fallback",
        }

    async def narrate_action(self, *_args, **_kwargs):
        raise RuntimeError("simulated narrator outage")


class _SwitchableConfiguredProvider(BaseAiProvider):
    def __init__(self, provider_config_id):
        super().__init__(f"configured:{provider_config_id}")
        self.model = "golden-model"
        self.provider_config_id = provider_config_id
        self.fail = True
        self.healthy = False

    async def call(self, _task_type, _context):
        if self.fail:
            raise TimeoutError("private configured provider timeout")
        return {"narrative": {"public": "provider recovered"}}

    async def health_check(self) -> bool:
        return self.healthy


def _analyze(client, player, declared_intent, *, intent_type=None, params=None):
    payload = {"declared_intent": declared_intent}
    if intent_type:
        payload["intent_type"] = intent_type
    if params:
        payload["params"] = params
    response = client.post(
        "/api/player/action-drafts/analyze",
        headers={"X-Room-Token": player["player_token"]},
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client, player, draft, key, *, selected_skill=None):
    payload = {"confirmations": draft["confirmation_requirements"]}
    if selected_skill:
        payload["selected_skill"] = selected_skill
    response = client.post(
        f"/api/player/action-drafts/{draft['draft_id']}/confirm",
        headers={
            "X-Room-Token": player["player_token"],
            "Idempotency-Key": key,
        },
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _analyze_confirm_resolve(
    client,
    pipeline,
    player,
    declared_intent,
    *,
    key,
    intent_type=None,
    params=None,
):
    draft = _analyze(
        client,
        player,
        declared_intent,
        intent_type=intent_type,
        params=params,
    )
    receipt = _confirm(client, player, draft, key)
    return receipt, await pipeline.resolve_action(receipt["action_id"])


@pytest.mark.asyncio
async def test_glass_rain_four_players_complete_authoritative_runtime(
    client,
    test_db,
    monkeypatch,
):
    monkeypatch.setenv("JWT_SECRET", "glass-rain-four-player-secret")
    installed, tokens, templates = _install_glass_rain(client, test_db)
    room, players, state_service = _create_started_room(
        client,
        test_db,
        installed,
        tokens,
        templates,
    )
    assert len(players) == 4
    assert len({player["character_id"] for player in players}) == 4
    assert len({player["character"]["source"]["template_id"] for player in players}) == 4

    frozen = test_db.execute(
        "SELECT risk_contract_version, risk_contract_hash FROM rooms WHERE room_id = %s",
        (room["room_id"],),
    ).fetchone()
    confirmations = test_db.execute(
        "SELECT character_id, contract_version, contract_hash "
        "FROM session_zero_confirmations WHERE room_id = %s AND step = 'safety'",
        (room["room_id"],),
    ).fetchall()
    assert len(confirmations) == 4
    assert {
        (row["contract_version"], row["contract_hash"])
        for row in confirmations
    } == {(frozen["risk_contract_version"], frozen["risk_contract_hash"])}

    previous_gateway = client.app.state.gateway
    client.app.state.gateway = _DeterministicDirectorGateway()
    dispatcher = _RecordingDispatcher()
    try:
        clarification = _analyze(
            client,
            players[3],
            "我已经拿到那把维护钥匙",
        )
        assert clarification["adjudication_stage"] == "player_clarification_required"
        assert 2 <= len(clarification["candidate_interpretations"]) <= 3

        first = _confirm(
            client,
            players[0],
            _analyze(client, players[0], "我检查公开的告示牌"),
            "glass-concurrent-a",
        )
        second = _confirm(
            client,
            players[1],
            _analyze(client, players[1], "我看看桌上的旧报纸"),
            "glass-concurrent-b",
        )
        concurrent = await asyncio.gather(
            ResolutionPipeline(
                conn=test_db,
                compiler=_GoldenFlowCompiler(),
                gateway=_FailingNarratorGateway(),
                dispatcher=dispatcher,
                state_service=state_service,
                host_connection_checker=lambda _room_id: False,
            ).resolve_action(first["action_id"]),
            ResolutionPipeline(
                conn=test_db,
                compiler=_GoldenFlowCompiler(),
                gateway=_FailingNarratorGateway(),
                dispatcher=dispatcher,
                state_service=state_service,
                host_connection_checker=lambda _room_id: False,
            ).resolve_action(second["action_id"]),
        )
        assert [item["status"] for item in concurrent] == ["completed", "completed"]
        assert test_db.execute(
            "SELECT status FROM action_drafts WHERE draft_id = %s",
            (clarification["draft_id"],),
        ).fetchone()["status"] == "analyzing"

        pvp = _confirm(
            client,
            players[2],
            _analyze(
                client,
                players[2],
                "我限制另一名调查员继续行动",
                intent_type="combat_action",
                params={
                    "targetId": players[3]["character_id"],
                    "pvpEffect": "restrict_action",
                },
            ),
            "glass-pvp-reject",
        )
        assert pvp["status"] == "awaiting_player_consent"
        consent = client.get(
            "/api/player/action-consents",
            headers={"X-Room-Token": players[3]["player_token"]},
        ).json()["items"][0]
        rejected = client.post(
            f"/api/player/action-consents/{consent['consentId']}",
            headers={"X-Room-Token": players[3]["player_token"]},
            json={"accepted": False},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["actionStatus"] == "rejected"
        assert test_db.execute(
            "SELECT result FROM actions WHERE action_id = %s",
            (pvp["action_id"],),
        ).fetchone()["result"]["outcome"] == "no_effect"

        with monkeypatch.context() as luck_patch:
            values = iter([6, 5])
            luck_patch.setattr(
                "src.server.engine.skill_check.random.randint",
                lambda _low, _high: next(values),
            )
            skill_draft = _analyze(
                client,
                players[0],
                "我进行一次说服检定争取保安配合",
                intent_type="skill_check",
                params={"skillName": "说服"},
            )
            skill_receipt = _confirm(
                client,
                players[0],
                skill_draft,
                "glass-locksmith-failure",
            )
            skill_pipeline = ResolutionPipeline(
                conn=test_db,
                compiler=_PersuadeCompiler(),
                gateway=_FailingNarratorGateway(),
                dispatcher=dispatcher,
                state_service=state_service,
                host_connection_checker=lambda _room_id: False,
            )
            failed = await skill_pipeline.resolve_action(skill_receipt["action_id"])
            assert failed["status"] == "awaiting_player_choice", failed
            follow_up = failed["result"]["metadata"]["follow_up"]
            assert follow_up["luck"]["required"] == 5
            assert follow_up["push"]["warning"]
            luck_before = state_service.get_runtime_state(
                players[0]["character_id"], room["room_id"]
            )["luck"]
            submitted = client.post(
                f"/api/player/actions/{skill_receipt['action_id']}/follow-up",
                headers={
                    "X-Room-Token": players[0]["player_token"],
                    "Idempotency-Key": "glass-spend-five-luck",
                },
                json={"decision": "spend_luck"},
            )
            assert submitted.status_code == 200, submitted.text
            completed_follow_up = await skill_pipeline.resolve_action(
                skill_receipt["action_id"]
            )
            assert completed_follow_up["status"] == "completed"
            assert state_service.get_runtime_state(
                players[0]["character_id"], room["room_id"]
            )["luck"] == luck_before - 5

        from src.server.ai.provider_config import AiProviderConfigStore

        provider_store = AiProviderConfigStore(test_db)
        provider_config = provider_store.create(
            {
                "name": "Golden Provider",
                "api_base_url": "https://example.test/v1",
                "protocol": "responses",
                "model": "golden-model",
                "api_key": "golden-test-key",
                "supports_image": False,
            },
            actor_id="acc-admin",
        )
        provider_config_id = provider_config["provider_config_id"]
        provider_store.record_test(
            provider_config_id,
            passed=True,
            latency_ms=1,
            actor_id="acc-admin",
        )
        test_db.commit()
        switched = client.post(
            f"/api/rooms/{room['room_id']}/ai-provider/switch",
            headers={"X-Owner-Token": room["owner_token"]},
            json={
                "provider_config_id": provider_config_id,
                "confirm": True,
                "reason": "四人黄金流程故障恢复验证",
            },
        )
        assert switched.status_code == 200, switched.text
        fake_provider = _SwitchableConfiguredProvider(provider_config_id)
        monkeypatch.setattr(
            "src.server.ai.gateway.ConfiguredOpenAIProvider",
            lambda *_args, **_kwargs: fake_provider,
        )
        health_gateway = AiGateway(db_conn=test_db)
        client.app.state.gateway = health_gateway
        for _ in range(3):
            await health_gateway.generate_narrative({}, room_id=room["room_id"])
        assert test_db.execute(
            "SELECT integrity_status FROM rooms WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()["integrity_status"] == "paused_provider"
        blocked = client.post(
            "/api/player/action-drafts/analyze",
            headers={"X-Room-Token": players[0]["player_token"]},
            json={"declared_intent": "我继续机械行动"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "room_provider_paused"
        fake_provider.healthy = True
        recovered = client.post(
            f"/api/rooms/{room['room_id']}/ai-provider/recover",
            headers={"X-Owner-Token": room["owner_token"]},
            json={"confirm": True, "reason": "黄金流程健康检查恢复"},
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["status"] == "healthy"
        switched_local = client.post(
            f"/api/rooms/{room['room_id']}/ai-provider/switch",
            headers={"X-Owner-Token": room["owner_token"]},
            json={
                "provider_config_id": "builtin:local",
                "confirm": True,
                "reason": "黄金流程切换到内置确定性运行时",
            },
        )
        assert switched_local.status_code == 200, switched_local.text
        client.app.state.gateway = AiGateway(db_conn=test_db)

        pipeline = ResolutionPipeline(
            conn=test_db,
            compiler=_GoldenFlowCompiler(),
            gateway=_FailingNarratorGateway(),
            dispatcher=dispatcher,
            state_service=state_service,
            host_connection_checker=lambda _room_id: False,
        )
        _, orchid = await _analyze_confirm_resolve(
            client,
            pipeline,
            players[0],
            "前往兰花展厅",
            key="glass-move-orchid",
            intent_type="move",
        )
        assert orchid["status"] == "completed"
        cistern_draft = _analyze(
            client,
            players[0],
            "前往地下蓄水池",
            intent_type="move",
        )
        cistern_progression = cistern_draft["semantic_progression"]
        assert cistern_progression["targetNodeId"] == "cistern"
        assert cistern_progression["fromNodeId"] == "orchid-hall"
        assert cistern_progression["validated"] is True
        assert cistern_progression["citation"]["source_part_id"].startswith(
            "golden-golden-team-glass-rain-source-part-"
        )
        cistern_receipt = _confirm(
            client,
            players[0],
            cistern_draft,
            "glass-move-cistern",
        )
        cistern = await pipeline.resolve_action(cistern_receipt["action_id"])
        assert cistern["status"] == "completed", cistern

        package = _runtime_package(test_db, room["room_id"])
        from src.server.ai.director import select_progression_recovery

        recovery = select_progression_recovery(
            test_db,
            room["room_id"],
            "cistern",
            package,
        )
        assert recovery["status"] == "recovery"
        assert recovery["recoveryNodeId"] == "glass-radio-recovery"
        _, recovery_result = await _analyze_confirm_resolve(
            client,
            pipeline,
            players[0],
            "使用维护无线电的恢复路线返回灌溉控制室",
            key="glass-recovery-control-room",
            intent_type="move",
        )
        assert recovery_result["status"] == "completed"
        recovery_state = test_db.execute(
            "SELECT scene_variables FROM room_scene_state WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()["scene_variables"]
        assert recovery_state["progression_recovery_costs"][-1] == {
            "recovery_node_id": "glass-radio-recovery",
            "kind": "time",
            "amount": 10,
        }
        _, returned = await _analyze_confirm_resolve(
            client,
            pipeline,
            players[0],
            "前往地下蓄水池",
            key="glass-return-cistern",
            intent_type="move",
        )
        assert returned["status"] == "completed"

        pending = _confirm(
            client,
            players[2],
            _analyze(client, players[2], "我继续查看墙上的公开说明"),
            "glass-pending-at-ending",
        )
        final_receipt, ending = await _analyze_confirm_resolve(
            client,
            pipeline,
            players[0],
            "收听维护无线电并确认先关阀门再断电",
            key="glass-final-maintenance-radio",
        )
        assert final_receipt["action_id"]
        assert ending["status"] == "completed"
        assert ending["result"]["metadata"]["verified_ending"]["ending_type"] == "victory"

        archive = test_db.execute(
            "SELECT ending_type, character_arcs FROM campaign_archives WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()
        assert archive["ending_type"] == "victory"
        assert len(archive["character_arcs"]) == 4
        assert test_db.execute(
            "SELECT status FROM actions WHERE action_id = %s",
            (pending["action_id"],),
        ).fetchone()["status"] == "canceled"
        assert test_db.execute(
            "SELECT COUNT(*) AS count FROM action_status_events AS events "
            "JOIN actions ON actions.action_id = events.action_id "
            "WHERE actions.room_id = %s AND events.status = 'awaiting_host_exception'",
            (room["room_id"],),
        ).fetchone()["count"] == 0
        persisted_clues = test_db.execute(
            "SELECT clue_id, text, source FROM clues WHERE room_id = %s",
            (room["room_id"],),
        ).fetchall()
        assert persisted_clues
        assert {row["source"] for row in persisted_clues} <= {
            "runtime:silver-pollen",
            "runtime:repeating-number",
            "runtime:g17-test-sheet",
            "runtime:restart-log",
            "runtime:maintenance-radio",
        }
        assert "runtime:maintenance-radio" in {
            row["source"] for row in persisted_clues
        }

        fresh_room_response = client.post(
            "/api/rooms",
            headers={"Authorization": f"Bearer {tokens['admin']}"},
            json={"scenario_id": installed["scenarioId"]},
        )
        assert fresh_room_response.status_code == 200, fresh_room_response.text
        fresh_room = fresh_room_response.json()
        fresh_player_response = client.post(
            f"/api/player/rooms/{fresh_room['room_id']}/join-with-character",
            headers={"Authorization": f"Bearer {tokens['player_4']}"},
            data={
                "player_name": "Fresh Player",
                "template_id": templates[0],
            },
        )
        assert fresh_player_response.status_code == 200, fresh_player_response.text
        fresh_player = fresh_player_response.json()
        old_luck = state_service.get_runtime_state(
            players[0]["character_id"], room["room_id"]
        )["luck"]
        fresh_luck = StateService(test_db).get_runtime_state(
            fresh_player["character_id"], fresh_room["room_id"]
        )["luck"]
        assert fresh_luck == old_luck + 5
        assert test_db.execute(
            "SELECT COUNT(*) AS count FROM clues WHERE room_id = %s",
            (fresh_room["room_id"],),
        ).fetchone()["count"] == 0
    finally:
        client.app.state.gateway = previous_gateway
