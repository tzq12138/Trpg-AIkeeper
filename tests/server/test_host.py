import json
import pytest
from src.server.models import EngineEvent, HostHUD, PlayerPublicStatus, RevealTransaction, TransactionStep
from src.server.host.host_store import HostStore, HOST_VISIBLE_EVENTS, PRIVATE_EVENTS
from src.server.host.public_stage import build_public_stage_projection


class TestHostStoreRouting:
    def test_host_ack_releases_only_events_allowed_by_release_gate(self):
        from src.server.host.router_host import _events_released_by_host_ack

        store = HostStore("room-1")
        store.start_transaction(RevealTransaction(
            transaction_id="tx-1",
            steps=[TransactionStep(step_id="step-1", kind="narrative_text")],
        ))
        store.advance_step()
        ready = {"event_type": "s2c_private_notice", "execute_after_step": 1}
        pending = {"event_type": "s2c_action_completed", "execute_after_step": 3}
        store.add_delayed_event(ready)
        store.add_delayed_event(pending)

        assert _events_released_by_host_ack(store, "wrong-transaction", 999, "step-1") == []
        assert _events_released_by_host_ack(store, "tx-1", 999, "wrong-step") == []
        assert _events_released_by_host_ack(store, "tx-1", 999, "step-1") == [ready]
        assert store.delayed_events == [pending]

    def test_route_valid_host_event(self):
        store = HostStore("room-1")
        event = EngineEvent(
            room_id="room-1", type="s2c_engine_state",
            audience="host", payload={"state": "thinking"},
            room_sequence=1,
        )
        assert store.route_event(event) is True
        assert store.last_host_sequence == 1

    def test_route_drops_private_event(self):
        store = HostStore("room-1")
        event = EngineEvent(
            room_id="room-1", type="s2c_private_notice",
            audience="player", room_sequence=1,
        )
        assert store.route_event(event) is False

    def test_route_drops_unknown_event(self):
        store = HostStore("room-1")
        event = EngineEvent(
            room_id="room-1", type="s2c_action_queued",
            audience="system", room_sequence=1,
        )
        assert store.route_event(event) is False

    def test_route_drops_duplicate_sequence(self):
        store = HostStore("room-1")
        event1 = EngineEvent(
            room_id="room-1", type="s2c_engine_state",
            audience="host", room_sequence=5,
        )
        event2 = EngineEvent(
            room_id="room-1", type="s2c_engine_state",
            audience="host", room_sequence=5,
        )
        store.route_event(event1)
        assert store.route_event(event2) is False

    def test_route_allows_sequence_zero(self):
        store = HostStore("room-1")
        event = EngineEvent(
            room_id="room-1", type="s2c_engine_state",
            audience="host", room_sequence=0,
        )
        assert store.route_event(event) is True


class TestPublicStageProjection:
    def test_projection_limits_public_stage_to_six_players(self):
        hud = HostHUD(
            room_id="room-1",
            players=[
                PlayerPublicStatus(
                    character_id=f"char-{index}",
                    player_name=f"Player {index}",
                    investigator_name=f"Investigator {index}",
                    hp=10,
                    hp_max=10,
                    san=50,
                    san_max=50,
                )
                for index in range(1, 8)
            ],
        )

        projection = build_public_stage_projection(hud, [])

        assert [player["characterId"] for player in projection["players"]] == [
            "char-1",
            "char-2",
            "char-3",
            "char-4",
            "char-5",
            "char-6",
        ]

    def test_projection_includes_only_public_team_context(self):
        hud = HostHUD(
            room_id="room-1",
            team_objectives=["保护安娜并离开走廊"],
            scene_time="1924-10-14 23:40",
        )

        projection = build_public_stage_projection(hud, [])

        assert projection["teamObjectives"] == ["保护安娜并离开走廊"]
        assert projection["sceneTime"] == "1924-10-14 23:40"
        assert "personalObjectives" not in projection
        assert "sceneVariables" not in projection

    def test_projection_redacts_exact_resources_and_host_queue(self):
        hud = HostHUD(
            room_id="room-1",
            scene_image_url="/assets/warehouse.png",
            engine_state="thinking",
            queue_status={"normal": 2, "urgent": 1},
            players=[
                PlayerPublicStatus(
                    character_id="char-1",
                    player_name="Alice",
                    investigator_name="Ada",
                    hp=2,
                    hp_max=10,
                    san=18,
                    san_max=50,
                    mp=7,
                    mp_max=10,
                    luck=40,
                    status_tags=["bleeding"],
                ),
            ],
        )

        projection = build_public_stage_projection(
            hud,
            [{"text": "仓库门外传来急促脚步。", "issued_at": "2026-07-19T12:00:00Z"}],
        )

        assert projection["statusText"] == "KP 正在理解行动"
        assert projection["players"] == [{
            "characterId": "char-1",
            "playerName": "Alice",
            "investigatorName": "Ada",
            "condition": "濒危",
            "conditionTone": "danger",
        }]
        assert projection["recentEvents"] == [{
            "text": "仓库门外传来急促脚步。",
            "issuedAt": "2026-07-19T12:00:00Z",
        }]
        assert "queueStatus" not in projection
        assert {"hp", "hpMax", "san", "sanMax", "mp", "mpMax", "luck", "statusTags"}.isdisjoint(
            projection["players"][0],
        )


class TestHostStoreSnapshot:
    def test_owner_can_advance_presentation_without_mutating_world_state(self, client, test_db):
        from tests.server.conftest import create_room, setup_auth_test_data
        from src.server.host.router_host import get_host_store

        setup_auth_test_data(test_db)
        room = create_room(client)
        store = get_host_store(room["room_id"], test_db)
        store.start_transaction(RevealTransaction(
            transaction_id="presentation-transaction",
            steps=[TransactionStep(step_id="presentation-step", kind="narrative_text")],
        ))
        store.save_state(test_db)
        before = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()["state_version"]

        response = client.post(
            f"/api/host/{room['room_id']}/presentation/next",
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "transactionId": "presentation-transaction",
            "currentStepIndex": 1,
            "totalSteps": 1,
            "paused": False,
            "completed": True,
            "queuedTransactions": 0,
            "canSkipVisual": False,
        }
        after = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()["state_version"]
        assert after == before

    def test_owner_can_start_the_next_persisted_presentation(self, client, test_db):
        from tests.server.conftest import create_room, setup_auth_test_data
        from src.server.host.router_host import get_host_store

        setup_auth_test_data(test_db)
        room = create_room(client)
        store = get_host_store(room["room_id"], test_db)
        store.enqueue_transaction(RevealTransaction(
            transaction_id="queued-presentation",
            steps=[TransactionStep(step_id="queued-step", kind="narrative_text")],
        ))
        store.save_state(test_db)

        response = client.post(
            f"/api/host/{room['room_id']}/presentation/play",
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "transactionId": "queued-presentation",
            "currentStepIndex": 0,
            "totalSteps": 1,
            "paused": False,
            "completed": False,
            "queuedTransactions": 0,
            "canSkipVisual": False,
        }

    def test_presentation_status_reports_queued_transactions_before_playback(self, client, test_db):
        from tests.server.conftest import create_room, setup_auth_test_data
        from src.server.host.router_host import get_host_store

        setup_auth_test_data(test_db)
        room = create_room(client)
        store = get_host_store(room["room_id"], test_db)
        store.enqueue_transaction(RevealTransaction(transaction_id="waiting-presentation"))
        store.save_state(test_db)

        response = client.get(
            f"/api/host/{room['room_id']}/presentation",
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert response.status_code == 200
        assert response.json()["transactionId"] is None
        assert response.json()["queuedTransactions"] == 1

    def test_presentation_step_releases_only_the_matching_saved_player_projection(self, client, test_db, monkeypatch):
        from tests.server.conftest import create_room, setup_auth_test_data
        from src.server.host.router_host import get_host_store
        from src.server.host.ws_manager import manager

        setup_auth_test_data(test_db)
        room = create_room(client)
        store = get_host_store(room["room_id"], test_db)
        store.start_transaction(RevealTransaction(
            transaction_id="release-presentation",
            steps=[TransactionStep(step_id="release-step", kind="narrative_text")],
        ))
        store.add_delayed_event({
            "room_id": room["room_id"],
            "character_id": "release-character",
            "event_type": "s2c_action_completed",
            "audience": "player",
            "payload": {"actionId": "saved-action", "status": "completed"},
            "execute_after_step": 1,
        })
        store.save_state(test_db)
        delivered = []

        async def capture_delivery(room_id, connection_id, event):
            delivered.append((room_id, connection_id, event.model_dump(by_alias=True)))

        monkeypatch.setattr(manager, "send_event", capture_delivery)

        response = client.post(
            f"/api/host/{room['room_id']}/presentation/next",
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert response.status_code == 200
        assert len(delivered) == 1
        delivered_room, connection_id, event = delivered[0]
        assert delivered_room == room["room_id"]
        assert connection_id == "player:release-character"
        assert event["roomId"] == room["room_id"]
        assert event["type"] == "s2c_action_completed"
        assert event["audience"] == "player"
        assert event["payload"] == {"actionId": "saved-action", "status": "completed"}
        assert store.delayed_events == []

    def test_owner_can_skip_only_consecutive_visual_presentation_steps(self, client, test_db):
        from tests.server.conftest import create_room, setup_auth_test_data
        from src.server.host.router_host import get_host_store

        setup_auth_test_data(test_db)
        room = create_room(client)
        store = get_host_store(room["room_id"], test_db)
        store.start_transaction(RevealTransaction(
            transaction_id="visual-skip-transaction",
            steps=[
                TransactionStep(step_id="visual-1", kind="scene_transition", payload={"secretScene": "幕后楼梯"}),
                TransactionStep(step_id="visual-2", kind="scene_transition", payload={"secretScene": "隐藏地下室"}),
                TransactionStep(step_id="narrative-1", kind="narrative_text", payload={"text": "不应被跳过"}),
            ],
        ))
        store.add_delayed_event({
            "room_id": room["room_id"],
            "character_id": "visual-character",
            "event_type": "s2c_action_completed",
            "audience": "player",
            "payload": {"status": "after-first-visual"},
            "execute_after_step": 1,
        })
        store.add_delayed_event({
            "room_id": room["room_id"],
            "character_id": "visual-character",
            "event_type": "s2c_action_completed",
            "audience": "player",
            "payload": {"status": "after-second-visual"},
            "execute_after_step": 2,
        })
        store.save_state(test_db)
        before = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s", (room["room_id"],)
        ).fetchone()["state_version"]

        response = client.post(
            f"/api/host/{room['room_id']}/presentation/skip-visual",
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert response.status_code == 200
        assert response.json()["skippedVisualSteps"] == 2
        assert response.json()["currentStepIndex"] == 2
        assert response.json()["canSkipVisual"] is False
        assert store.current_step_index == 2
        assert store.delayed_events == []
        assert test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s", (room["room_id"],)
        ).fetchone()["state_version"] == before
        assert "secretScene" not in response.text

        no_visual = client.post(
            f"/api/host/{room['room_id']}/presentation/skip-visual",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert no_visual.status_code == 409

    def test_public_presentation_reveals_only_released_stage_narration_after_narrative_step(self, client, test_db):
        from tests.server.conftest import create_room, setup_auth_test_data
        from src.server.host.router_host import get_host_store

        setup_auth_test_data(test_db)
        room = create_room(client)
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES ('stage-presentation-character', %s, 'Player', 'stage-presentation-token', 'ready')",
            (room["room_id"],),
        )
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
            "VALUES ('stage-presentation-action', %s, 'stage-presentation-character', 'action', '私密行动原话', 'completed')",
            (room["room_id"],),
        )
        test_db.execute(
            "INSERT INTO resolution_bundles "
            "(action_id, room_id, character_id, canonical_result, rule_explanation, actor_projection, stage_projection, host_console, release_status) "
            "VALUES ('stage-presentation-action', %s, 'stage-presentation-character', '{}', '{}', '{}', %s, %s, 'released')",
            (
                room["room_id"],
                json.dumps({"narrativeText": "雨声压过了远处的汽笛。"}),
                json.dumps({"hiddenReason": "Host 原始内幕不得投到舞台"}),
            ),
        )
        test_db.commit()
        store = get_host_store(room["room_id"], test_db)
        store.start_transaction(RevealTransaction(
            transaction_id="stage-presentation-transaction",
            action_id="stage-presentation-action",
            steps=[
                TransactionStep(kind="roll", payload={"secretRoll": 7}),
                TransactionStep(kind="narrative_text", payload={"text": "Host 原始内幕不得投到舞台"}),
            ],
        ))
        store.save_state(test_db)
        headers = {"X-Owner-Token": room["owner_token"]}

        initial = client.get(f"/api/host/{room['room_id']}/stage-presentation", headers=headers)
        assert initial.status_code == 200
        assert initial.json() == {
            "available": False,
            "version": 0,
            "kind": None,
            "narrativeText": None,
        }

        client.post(f"/api/host/{room['room_id']}/presentation/next", headers=headers)
        before_narration = client.get(f"/api/host/{room['room_id']}/stage-presentation", headers=headers)
        assert before_narration.status_code == 200
        assert before_narration.json()["available"] is False

        client.post(f"/api/host/{room['room_id']}/presentation/next", headers=headers)
        public_projection = client.get(f"/api/host/{room['room_id']}/stage-presentation", headers=headers)

        assert public_projection.status_code == 200
        assert public_projection.json() == {
            "available": True,
            "version": 2,
            "kind": "narrative_text",
            "narrativeText": "雨声压过了远处的汽笛。",
        }
        assert "Host 原始内幕" not in public_projection.text
        assert "secretRoll" not in public_projection.text
        assert "stage-presentation-action" not in public_projection.text

    def test_public_presentation_excludes_unreleased_bundle_and_replay_does_not_mutate_world(self, client, test_db):
        from tests.server.conftest import create_room, setup_auth_test_data
        from src.server.host.router_host import get_host_store

        setup_auth_test_data(test_db)
        room = create_room(client)
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES ('unreleased-stage-character', %s, 'Player', 'unreleased-stage-token', 'ready')",
            (room["room_id"],),
        )
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
            "VALUES ('unreleased-stage-action', %s, 'unreleased-stage-character', 'action', '私密行动原话', 'completed')",
            (room["room_id"],),
        )
        test_db.execute(
            "INSERT INTO resolution_bundles "
            "(action_id, room_id, character_id, canonical_result, rule_explanation, actor_projection, stage_projection, host_console, release_status) "
            "VALUES ('unreleased-stage-action', %s, 'unreleased-stage-character', '{}', '{}', '{}', %s, '{}', 'ready')",
            (room["room_id"], json.dumps({"narrativeText": "尚未发布的叙事"})),
        )
        test_db.commit()
        store = get_host_store(room["room_id"], test_db)
        store.start_transaction(RevealTransaction(
            action_id="unreleased-stage-action",
            steps=[TransactionStep(kind="narrative_text", payload={"text": "Host 不能直出"})],
        ))
        store.save_state(test_db)
        headers = {"X-Owner-Token": room["owner_token"]}
        before = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s", (room["room_id"],)
        ).fetchone()["state_version"]

        client.post(f"/api/host/{room['room_id']}/presentation/next", headers=headers)
        replay = client.post(f"/api/host/{room['room_id']}/presentation/replay", headers=headers)
        projection = client.get(f"/api/host/{room['room_id']}/stage-presentation", headers=headers)

        assert replay.status_code == 200
        assert replay.json()["version"] == 2
        assert projection.status_code == 200
        assert projection.json() == {
            "available": False,
            "version": 2,
            "kind": None,
            "narrativeText": None,
        }
        after = test_db.execute(
            "SELECT state_version FROM rooms WHERE room_id = %s", (room["room_id"],)
        ).fetchone()["state_version"]
        assert after == before

    def test_restore_preserves_active_transaction_step_and_delayed_events(self, test_db):
        test_db.execute(
            "INSERT INTO rooms (room_id, owner_token) VALUES ('room-restore', 'owner-token')"
        )
        test_db.commit()
        store = HostStore("room-restore")
        transaction = RevealTransaction(
            transaction_id="tx-restore",
            steps=[
                TransactionStep(kind="roll", payload={"dice": "1d100"}),
                TransactionStep(kind="narrative_text", payload={"text": "恢复后的叙事"}),
            ],
        )
        store.start_transaction(transaction)
        store.advance_step()
        store.add_delayed_event({"event_type": "s2c_private_notice", "execute_after_step": 2})
        store.save_state(test_db)

        restored = HostStore("room-restore")
        restored.restore_from_db(test_db)

        assert restored.active_transaction_id == "tx-restore"
        assert restored.current_step_index == 1
        assert restored.active_transaction is not None
        assert restored.active_transaction.steps[1].payload["text"] == "恢复后的叙事"
        assert restored.delayed_events == [{"event_type": "s2c_private_notice", "execute_after_step": 2}]

    def test_apply_snapshot(self):
        store = HostStore("room-1")
        store.apply_snapshot({
            "players": [
                {"character_id": "c1", "player_name": "Alice", "hp": 10, "hp_max": 12, "san": 50, "san_max": 60},
                {"character_id": "c2", "player_name": "Bob", "hp": 8, "hp_max": 10},
            ],
            "scene_image_url": "http://example.com/scene.jpg",
            "host_sequence": 42,
        })
        assert len(store.players) == 2
        assert store.players[0].player_name == "Alice"
        assert store.players[0].hp == 10
        assert store.current_scene_image_url == "http://example.com/scene.jpg"
        assert store.last_host_sequence == 42

    def test_apply_status_delta(self):
        store = HostStore("room-1")
        store.apply_snapshot({"players": [{"character_id": "c1", "player_name": "Alice", "hp": 10, "hp_max": 12}]})
        store.apply_public_status_delta({"character_id": "c1", "hp": 8})
        assert store.players[0].hp == 8
        assert store.players[0].hp_max == 12

    def test_apply_status_delta_unknown_char(self):
        store = HostStore("room-1")
        store.apply_snapshot({"players": []})
        store.apply_public_status_delta({"character_id": "unknown", "hp": 5})
        assert len(store.players) == 0

    def test_chat_messages_capped_at_200(self):
        store = HostStore("room-1")
        for i in range(220):
            store.append_chat_message({"text": f"msg-{i}"})
        assert len(store.chat_messages) == 200
        assert store.chat_messages[0]["text"] == "msg-20"


class TestTransactionPlayer:
    def test_enqueue_and_pop_normal(self):
        store = HostStore("room-1")
        tx = RevealTransaction(
            transaction_id="tx-1",
            priority="normal",
            steps=[TransactionStep(kind="narrative_text", payload={"text": "hello"})],
        )
        store.enqueue_transaction(tx)
        assert len(store.normal_queue) == 1
        popped = store.pop_next_transaction()
        assert popped.transaction_id == "tx-1"

    def test_urgent_pops_before_normal(self):
        store = HostStore("room-1")
        normal_tx = RevealTransaction(transaction_id="tx-n", priority="normal")
        urgent_tx = RevealTransaction(transaction_id="tx-u", priority="urgent")
        store.enqueue_transaction(normal_tx)
        store.enqueue_transaction(urgent_tx)
        popped = store.pop_next_transaction()
        assert popped.transaction_id == "tx-u"

    def test_start_and_advance_steps(self):
        store = HostStore("room-1")
        tx = RevealTransaction(
            transaction_id="tx-1",
            steps=[
                TransactionStep(kind="roll", payload={"dice": "1d20"}),
                TransactionStep(kind="status_delta", payload={"character_id": "c1", "hp": 5}),
                TransactionStep(kind="narrative_text", payload={"text": "The end"}),
            ],
        )
        store.start_transaction(tx)
        assert store.active_transaction_id == "tx-1"
        assert store.current_step_index == 0

        step1 = store.advance_step()
        assert step1.kind == "roll"
        assert store.current_step_index == 1

        step2 = store.advance_step()
        assert step2.kind == "status_delta"
        assert store.current_step_index == 2

        step3 = store.advance_step()
        assert step3.kind == "narrative_text"
        assert store.current_step_index == 3

        step4 = store.advance_step()
        assert step4 is None

    def test_complete_transaction_clears_state(self):
        store = HostStore("room-1")
        tx = RevealTransaction(transaction_id="tx-1", steps=[])
        store.start_transaction(tx)
        store.complete_transaction()
        assert store.active_transaction_id is None
        assert store.active_transaction is None
        assert store.current_step_index == 0

    def test_urgent_preemption_saves_interrupted(self):
        store = HostStore("room-1")
        normal_tx = RevealTransaction(
            transaction_id="tx-normal",
            steps=[
                TransactionStep(kind="roll"),
                TransactionStep(kind="narrative_text"),
            ],
        )
        store.start_transaction(normal_tx)
        store.advance_step()

        urgent_tx = RevealTransaction(transaction_id="tx-urgent", priority="urgent")
        store.preempt_for_urgent(urgent_tx)

        assert store.active_transaction_id == "tx-urgent"
        assert store.interrupted_transaction.transaction_id == "tx-normal"
        assert store.interrupted_step_index == 1

    def test_resume_interrupted(self):
        store = HostStore("room-1")
        normal_tx = RevealTransaction(
            transaction_id="tx-normal",
            steps=[TransactionStep(kind="roll"), TransactionStep(kind="narrative_text")],
        )
        store.start_transaction(normal_tx)
        store.advance_step()

        urgent_tx = RevealTransaction(transaction_id="tx-urgent")
        store.preempt_for_urgent(urgent_tx)
        store.complete_transaction()

        resumed = store.resume_interrupted()
        assert resumed.transaction_id == "tx-normal"
        assert store.current_step_index == 1

    def test_cancel_interrupted(self):
        store = HostStore("room-1")
        normal_tx = RevealTransaction(transaction_id="tx-normal")
        store.start_transaction(normal_tx)

        urgent_tx = RevealTransaction(transaction_id="tx-urgent")
        store.preempt_for_urgent(urgent_tx)
        store.cancel_interrupted()

        assert store.interrupted_transaction is None
        assert store.interrupted_step_index == 0


class TestHostStoreReset:
    def test_reset_clears_all(self):
        store = HostStore("room-1")
        store.apply_snapshot({"players": [{"character_id": "c1", "player_name": "A", "hp": 5}]})
        store.current_scene_image_url = "http://img"
        store.append_chat_message({"text": "hello"})
        store.enqueue_transaction(RevealTransaction(transaction_id="tx-1"))
        store.atmosphere["bgm"] = {"trackId": "x"}
        store.reset()

        assert store.players == []
        assert store.current_scene_image_url is None
        assert store.chat_messages == []
        assert store.normal_queue == []
        assert store.urgent_queue == []
        assert store.active_transaction_id is None
        assert store.atmosphere == {"bgm": None, "sfx_queue": [], "visual": None}
        assert store.is_paused is False

    def test_reset_clears_interrupted(self):
        store = HostStore("room-1")
        tx = RevealTransaction(transaction_id="tx-1")
        store.start_transaction(tx)
        store.preempt_for_urgent(RevealTransaction(transaction_id="tx-2"))
        store.reset()
        assert store.interrupted_transaction is None


class TestAtmosphere:
    def test_apply_atmosphere_bgm(self):
        store = HostStore("room-1")
        store.apply_atmosphere({"bgm": {"trackId": "horror", "volume": 0.8}})
        assert store.atmosphere["bgm"]["trackId"] == "horror"

    def test_apply_atmosphere_sfx(self):
        store = HostStore("room-1")
        store.apply_atmosphere({"sfx": [{"clipId": "door_creak"}]})
        store.apply_atmosphere({"sfx": [{"clipId": "thunder"}]})
        assert len(store.atmosphere["sfx_queue"]) == 2

    def test_apply_atmosphere_visual(self):
        store = HostStore("room-1")
        store.apply_atmosphere({"visual": {"filter": "cold_blue", "vignette": True}})
        assert store.atmosphere["visual"]["filter"] == "cold_blue"


class TestHostHUD:
    def test_get_hud(self):
        store = HostStore("room-1")
        store.apply_snapshot({"players": [{"character_id": "c1", "player_name": "Alice", "hp": 10}]})
        store.set_engine_state("thinking")
        hud = store.get_hud()
        assert hud.room_id == "room-1"
        assert len(hud.players) == 1
        assert hud.engine_state == "thinking"
        assert hud.queue_status == {"normal": 0, "urgent": 0}

    def test_hud_queue_counts(self):
        store = HostStore("room-1")
        store.enqueue_transaction(RevealTransaction(priority="normal"))
        store.enqueue_transaction(RevealTransaction(priority="normal"))
        store.enqueue_transaction(RevealTransaction(priority="urgent"))
        hud = store.get_hud()
        assert hud.queue_status["normal"] == 2
        assert hud.queue_status["urgent"] == 1


class TestHostSceneAndChat:
    def test_set_scene_image(self):
        store = HostStore("room-1")
        store.set_scene_image("http://example.com/img.png")
        assert store.current_scene_image_url == "http://example.com/img.png"
        store.set_scene_image(None)
        assert store.current_scene_image_url is None

    def test_append_chat(self):
        store = HostStore("room-1")
        store.append_chat_message({"text": "Hello", "speaker": "keeper"})
        assert len(store.chat_messages) == 1
        assert store.chat_messages[0]["speaker"] == "keeper"

    def test_set_engine_state(self):
        store = HostStore("room-1")
        store.set_engine_state("busy")
        assert store.engine_state == "busy"


class TestHostStorePersistence:
    def _make_room(self, db_conn, room_id="persist-room-1"):
        db_conn.execute(
            "INSERT INTO rooms (room_id, owner_token, status) VALUES (?, 'tok', 'active')",
            (room_id,),
        )

    def test_save_and_load_state(self, test_db):
        self._make_room(test_db)
        store = HostStore("persist-room-1")
        store.apply_snapshot({
            "players": [{"character_id": "c1", "player_name": "Alice", "hp": 10, "hp_max": 12, "san": 50, "san_max": 60}],
            "scene_image_url": "http://example.com/scene.jpg",
            "host_sequence": 7,
        })
        store.set_engine_state("thinking")
        store.apply_atmosphere({"bgm": {"trackId": "horror"}})
        store.append_chat_message({"text": "hello"})
        store.is_paused = True

        store.save_state(test_db)

        loaded = HostStore.load_state("persist-room-1", test_db)
        assert loaded is not None
        assert loaded["current_scene_image_url"] == "http://example.com/scene.jpg"
        assert loaded["engine_state"] == "thinking"
        assert loaded["is_paused"] is True
        assert loaded["last_host_sequence"] == 7
        assert len(loaded["players"]) == 1
        assert loaded["players"][0]["player_name"] == "Alice"
        assert loaded["atmosphere"]["bgm"]["trackId"] == "horror"
        assert len(loaded["chat_messages"]) == 1

    def test_load_state_nonexistent(self, test_db):
        assert HostStore.load_state("no-such-room", test_db) is None

    def test_save_state_upsert(self, test_db):
        self._make_room(test_db, "upsert-room")
        store = HostStore("upsert-room")
        store.set_engine_state("idle")
        store.save_state(test_db)

        store.set_engine_state("busy")
        store.save_state(test_db)

        loaded = HostStore.load_state("upsert-room", test_db)
        assert loaded["engine_state"] == "busy"

    def test_restore_from_db(self, test_db):
        self._make_room(test_db, "restore-room")
        store = HostStore("restore-room")
        store.apply_snapshot({
            "players": [{"character_id": "c1", "player_name": "Bob", "hp": 8, "hp_max": 10}],
        })
        store.set_engine_state("thinking")
        store.set_scene_image("http://example.com/img.png")
        store.save_state(test_db)

        new_store = HostStore("restore-room")
        new_store.restore_from_db(test_db)

        assert new_store.engine_state == "thinking"
        assert new_store.current_scene_image_url == "http://example.com/img.png"
        assert len(new_store.players) == 1
        assert new_store.players[0].player_name == "Bob"
        assert new_store.players[0].hp == 8

    def test_restore_from_db_no_data(self, test_db):
        store = HostStore("no-data-room")
        store.set_engine_state("busy")
        store.restore_from_db(test_db)
        assert store.engine_state == "busy"

    def test_save_chat_messages_capped_at_50(self, test_db):
        self._make_room(test_db, "chat-cap-room")
        store = HostStore("chat-cap-room")
        for i in range(100):
            store.append_chat_message({"text": f"msg-{i}"})
        store.save_state(test_db)

        loaded = HostStore.load_state("chat-cap-room", test_db)
        # save_state now persists all in-memory messages (append_chat_message caps at MAX=200)
        assert len(loaded["chat_messages"]) == 100
        assert loaded["chat_messages"][0]["text"] == "msg-0"


class TestHostRESTEndpoints:
    def test_owner_can_update_public_scene_time_without_overwriting_scene_state(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room

        setup_auth_test_data(test_db)
        room = create_room(client)
        test_db.execute(
            "INSERT INTO room_scene_state (room_id, current_scene, scene_variables, version) "
            "VALUES (%s, 'harbor', %s, 4)",
            (room["room_id"], json.dumps({"hidden_truth": "不要公开", "weather": "rain"}, ensure_ascii=False)),
        )
        test_db.commit()

        denied = client.put(
            f"/api/host/{room['room_id']}/public-scene-time",
            json={"sceneTime": "1924-10-14 23:40"},
        )
        response = client.put(
            f"/api/host/{room['room_id']}/public-scene-time",
            json={"sceneTime": "1924-10-14 23:40"},
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert denied.status_code == 403
        assert response.status_code == 200
        assert response.json() == {"sceneTime": "1924-10-14 23:40", "version": 5}
        scene = test_db.execute(
            "SELECT scene_variables, version FROM room_scene_state WHERE room_id = %s",
            (room["room_id"],),
        ).fetchone()
        assert scene["scene_variables"] == {
            "hidden_truth": "不要公开",
            "weather": "rain",
            "public_time": "1924-10-14 23:40",
        }
        assert scene["version"] == 5
        stage = client.get(
            f"/api/host/{room['room_id']}/stage-projection",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert stage.status_code == 200
        assert stage.json()["sceneTime"] == "1924-10-14 23:40"

    def test_get_hud_endpoint(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room
        setup_auth_test_data(test_db)
        room = create_room(client)
        resp = client.get(f"/api/host/{room['room_id']}/hud",
                          headers={"X-Owner-Token": room["owner_token"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("roomId") or data.get("room_id")
        assert isinstance(data["players"], list)

    def test_stage_projection_requires_owner_and_excludes_host_state(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room
        setup_auth_test_data(test_db)
        room = create_room(client)

        denied = client.get(f"/api/host/{room['room_id']}/stage-projection")
        allowed = client.get(
            f"/api/host/{room['room_id']}/stage-projection",
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert denied.status_code == 403
        assert allowed.status_code == 200
        payload = allowed.json()
        assert set(payload) == {
            "roomId", "sceneImageUrl", "statusText", "teamObjectives", "sceneTime", "players", "recentEvents"
        }
        assert "queueStatus" not in payload

    def test_stage_projection_includes_only_public_combat_round_summary(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room
        setup_auth_test_data(test_db)
        room = create_room(client)
        test_db.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'party', %s)",
            (
                room['room_id'],
                's2c_turn_resolved',
                json.dumps({
                    'combat_summary': {
                        'title': '第 4 轮结束',
                        'public_facts': ['北侧铁门已经打开'],
                        'current_situation': '北侧铁门已经打开',
                        'hidden_enemy_hp': 1,
                    },
                }, ensure_ascii=False),
            ),
        )
        test_db.commit()

        response = client.get(
            f"/api/host/{room['room_id']}/stage-projection",
            headers={"X-Owner-Token": room["owner_token"]},
        )

        assert response.status_code == 200
        events = response.json()['recentEvents']
        assert any('第 4 轮结束' in event['text'] for event in events)
        rendered = json.dumps(events, ensure_ascii=False)
        assert '北侧铁门已经打开' in rendered
        assert events[-1]['text'].count('北侧铁门已经打开') == 1
        assert 'hidden_enemy_hp' not in rendered

    def test_stage_projection_exposes_only_safe_live_combat_progress(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room

        setup_auth_test_data(test_db)
        room = create_room(client)
        player = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
        test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room['room_id'],))
        test_db.execute(
            "UPDATE characters SET status = 'ready' WHERE character_id = %s",
            (player['character_id'],),
        )
        test_db.execute(
            "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
            "VALUES ('stage-live-combat', %s, 'combat', 'active', 4)",
            (room['room_id'],),
        )
        test_db.execute(
            "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id, combat_plan) "
            "VALUES ('stage-live-turn', %s, 1, 'resolving', 'combat', 'stage-live-combat', %s)",
            (
                room['room_id'],
                json.dumps({
                    'presentation_clusters': [
                        {
                            'public_title': '走廊入口的争夺',
                            'action_ids': ['internal-public-action'],
                            'completed_public_facts': [],
                        },
                        {
                            'public_title': '暗中的物品递交',
                            'action_ids': ['private-action'],
                            'visibility': 'private',
                        },
                    ],
                    'steps': [{'global_order': 1, 'action_id': 'internal-public-action'}],
                }, ensure_ascii=False),
            ),
        )
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, turn_id, intent_type, declared_intent, status) "
            "VALUES ('internal-public-action', %s, %s, 'stage-live-turn', 'combat_action', '我准备行动', 'queued')",
            (room['room_id'], player['character_id']),
        )
        test_db.commit()

        response = client.get(
            f"/api/host/{room['room_id']}/stage-projection",
            headers={'X-Owner-Token': room['owner_token']},
        )

        assert response.status_code == 200
        assert response.json()['combatRound'] == {
            'roundNumber': 4,
            'phase': 'resolution',
            'submittedCount': 1,
            'totalPlayers': 1,
            'currentConflict': '走廊入口的争夺',
        }
        rendered = json.dumps(response.json(), ensure_ascii=False)
        assert 'internal-public-action' not in rendered
        assert 'private-action' not in rendered
        assert '暗中的物品递交' not in rendered

    def test_public_combat_units_require_explicit_observation_and_redact_exact_values(self):
        from src.server.host.public_stage import (
            build_public_combat_unit_projection,
            build_public_encounter_event_projection,
        )

        units = build_public_combat_unit_projection([
            {
                "character_id": "investigator-ada",
                "side": "player",
                "display_name": "艾达",
                "hp": 7,
                "hp_max": 10,
                "distance_band": "near",
                "dex": 80,
            },
            {
                "character_id": "npc-shadow",
                "side": "enemy",
                "public_visibility": "visible",
                "public_label": "走廊中的人影",
                "hp": 3,
                "hp_max": 9,
                "distance_band": "near",
                "weapon_name": "未公开的手枪",
            },
            {
                "character_id": "npc-gunner",
                "side": "enemy",
                "public_visibility": "lost",
                "public_label": "黑暗中的枪手",
                "last_observed_position": "走廊北侧",
                "hp": 1,
                "hp_max": 12,
                "distance_band": "engaged",
            },
            {
                "character_id": "npc-secret",
                "side": "enemy",
                "public_visibility": "hidden",
                "public_label": "地下室里的怪物",
                "hp": 99,
                "hp_max": 99,
            },
        ])

        assert units == [
            {
                "label": "艾达",
                "kind": "investigator",
                "healthSegments": 6,
                "condition": "受伤",
                "distanceBand": "near",
            },
            {
                "label": "走廊中的人影",
                "kind": "observed_enemy",
                "healthSegments": 3,
                "condition": "重伤",
                "distanceBand": "near",
            },
            {
                "label": "黑暗中的枪手",
                "kind": "observed_enemy",
                "condition": "失去踪迹",
                "lastObservedAt": "走廊北侧",
            },
        ]
        rendered = json.dumps(units, ensure_ascii=False)
        for unsafe in ("character_id", "hp", "hp_max", "dex", "weapon_name", "地下室里的怪物"):
            assert unsafe not in rendered

        event = build_public_encounter_event_projection(
            {"encounter_id": "enc-1", "type": "combat", "status": "active", "current_round": 4, "summary": "幕后计划"},
            units,
        )
        assert event == {
            "encounterId": "enc-1",
            "encounter": {"type": "combat", "status": "active", "currentRound": 4},
            "publicUnits": units,
        }
        assert "幕后计划" not in json.dumps(event, ensure_ascii=False)

    def test_stage_and_player_combat_projection_share_only_observed_units(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room

        setup_auth_test_data(test_db)
        room = create_room(client)
        player = client.post(f"/api/player/rooms/{room['room_id']}/join").json()
        test_db.execute("UPDATE rooms SET status = 'active' WHERE room_id = %s", (room["room_id"],))
        test_db.execute(
            "UPDATE characters SET status = 'ready' WHERE character_id = %s",
            (player["character_id"],),
        )
        test_db.execute(
            "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
            "VALUES ('stage-observed-combat', %s, 'combat', 'active', 2)",
            (room["room_id"],),
        )
        test_db.execute(
            "INSERT INTO room_turns (turn_id, room_id, turn_index, status, mode, encounter_id) "
            "VALUES ('stage-observed-turn', %s, 1, 'collecting', 'combat', 'stage-observed-combat')",
            (room["room_id"],),
        )
        test_db.execute(
            "INSERT INTO encounter_participants "
            "(encounter_id, character_id, side, hp, hp_max, distance_band, display_name) "
            "VALUES ('stage-observed-combat', %s, 'player', 9, 10, 'near', '艾达')",
            (player["character_id"],),
        )
        test_db.execute(
            "INSERT INTO encounter_participants "
            "(encounter_id, character_id, side, hp, hp_max, distance_band, public_visibility, public_label) "
            "VALUES ('stage-observed-combat', 'npc:visible', 'enemy', 2, 8, 'short', 'visible', '走廊中的人影')",
        )
        test_db.execute(
            "INSERT INTO encounter_participants "
            "(encounter_id, character_id, side, hp, hp_max, public_visibility, public_label) "
            "VALUES ('stage-observed-combat', 'npc:hidden', 'enemy', 8, 8, 'hidden', '不该显示的身份')",
        )
        test_db.commit()

        stage = client.get(
            f"/api/host/{room['room_id']}/stage-projection",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        player_round = client.get(
            "/api/player/combat-round",
            headers={"X-Room-Token": player["player_token"]},
        )

        assert stage.status_code == 200
        assert player_round.status_code == 200
        expected_units = [
            {
                "label": "艾达",
                "kind": "investigator",
                "healthSegments": 7,
                "condition": "情况稳定",
                "distanceBand": "near",
            },
            {
                "label": "走廊中的人影",
                "kind": "observed_enemy",
                "healthSegments": 2,
                "condition": "濒危",
                "distanceBand": "short",
            },
        ]
        assert stage.json()["combatRound"]["publicUnits"] == expected_units
        assert player_round.json()["publicUnits"] == expected_units
        rendered = json.dumps({"stage": stage.json(), "player": player_round.json()}, ensure_ascii=False)
        assert "不该显示的身份" not in rendered
        assert "npc:hidden" not in rendered
        assert "hp_max" not in rendered

    def test_host_manual_combat_advance_requires_reason_and_writes_audit(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room

        setup_auth_test_data(test_db)
        room = create_room(client)
        test_db.execute(
            "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
            "VALUES ('manual-combat-audit', %s, 'combat', 'active', 1)",
            (room["room_id"],),
        )
        test_db.commit()

        missing_reason = client.post(
            f"/api/host/{room['room_id']}/encounter/next-round",
            headers={"X-Owner-Token": room["owner_token"]},
            json={},
        )
        approved = client.post(
            f"/api/host/{room['room_id']}/encounter/next-round",
            headers={"X-Owner-Token": room["owner_token"]},
            json={"reason": "自动结算进程中断，需要人工恢复。"},
        )

        assert missing_reason.status_code == 400
        assert approved.status_code == 200
        audit = test_db.execute(
            "SELECT audience, payload FROM events "
            "WHERE room_id = %s AND event_type = 'host_encounter_intervention' "
            "ORDER BY sequence DESC LIMIT 1",
            (room["room_id"],),
        ).fetchone()
        assert audit["audience"] == "system"
        payload = audit["payload"] if isinstance(audit["payload"], dict) else json.loads(audit["payload"])
        assert payload["operation"] == "advance_round"
        assert payload["reason"] == "自动结算进程中断，需要人工恢复。"

    def test_other_manual_encounter_operations_require_reason_and_write_audit(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room

        setup_auth_test_data(test_db)
        room = create_room(client)
        test_db.execute(
            "INSERT INTO encounters (encounter_id, room_id, type, status, current_round) "
            "VALUES ('manual-combat-other-audit', %s, 'combat', 'active', 1)",
            (room["room_id"],),
        )
        test_db.commit()
        headers = {"X-Owner-Token": room["owner_token"]}

        assert client.post(
            f"/api/host/{room['room_id']}/encounter/npc",
            headers=headers,
            json={"encounterId": "manual-combat-other-audit", "name": "临时敌人"},
        ).status_code == 400
        created = client.post(
            f"/api/host/{room['room_id']}/encounter/npc",
            headers=headers,
            json={
                "encounterId": "manual-combat-other-audit",
                "name": "临时敌人",
                "reason": "剧本勘误后需要补入已公开敌人。",
            },
        )
        assert created.status_code == 200
        assert client.post(
            f"/api/host/{room['room_id']}/encounter/resolve",
            headers=headers,
            json={},
        ).status_code == 400
        resolved = client.post(
            f"/api/host/{room['room_id']}/encounter/resolve",
            headers=headers,
            json={"reason": "规则异常已确认，结束重复遭遇。"},
        )
        assert resolved.status_code == 200

        rows = test_db.execute(
            "SELECT payload FROM events WHERE room_id = %s "
            "AND event_type = 'host_encounter_intervention' ORDER BY sequence",
            (room["room_id"],),
        ).fetchall()
        operations = []
        for row in rows:
            payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
            operations.append(payload["operation"])
        assert operations == ["create_encounter_participant", "resolve_encounter"]

    def test_get_hud_not_found(self, client):
        resp = client.get("/api/host/nonexistent/hud",
                          headers={"X-Owner-Token": "x"})
        assert resp.status_code in (403, 404)

    def test_emergency_reset(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room
        setup_auth_test_data(test_db)
        room = create_room(client)
        resp = client.post(
            f"/api/host/{room['room_id']}/reset",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset"

    def test_emergency_reset_not_found(self, client):
        resp = client.post("/api/host/nonexistent/reset", headers={"X-Owner-Token": "x"})
        assert resp.status_code in (403, 404)

    def test_emergency_reset_wrong_owner(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room
        setup_auth_test_data(test_db)
        room = create_room(client)
        resp = client.post(
            f"/api/host/{room['room_id']}/reset",
            headers={"X-Owner-Token": "wrong-token"},
        )
        assert resp.status_code == 403

    def test_pause_toggle(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room
        setup_auth_test_data(test_db)
        room = create_room(client)
        resp = client.post(
            f"/api/host/{room['room_id']}/pause",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"
        resp = client.post(
            f"/api/host/{room['room_id']}/pause",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert resp.json()["status"] == "resumed"

    def test_pause_not_found(self, client):
        resp = client.post("/api/host/nonexistent/pause", headers={"X-Owner-Token": "x"})
        assert resp.status_code in (403, 404)

    def test_retry_turn_no_active(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room
        setup_auth_test_data(test_db)
        room = create_room(client)
        resp = client.post(
            f"/api/host/{room['room_id']}/retry-turn",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_active_transaction"

    def test_retry_turn_not_found(self, client):
        resp = client.post("/api/host/nonexistent/retry-turn", headers={"X-Owner-Token": "x"})
        assert resp.status_code in (403, 404)

    def test_owner_can_replay_a_pending_projection_without_passing_new_content(self, client, test_db, monkeypatch):
        from tests.server.conftest import setup_auth_test_data, create_room
        setup_auth_test_data(test_db)
        room = create_room(client)
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES ('projection-owner-character', %s, 'Player', 'projection-token', 'ready')",
            (room['room_id'],),
        )
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
            "VALUES ('projection-pending-action', %s, 'projection-owner-character', 'action', '检查门锁', 'completed')",
            (room['room_id'],),
        )
        test_db.commit()

        class ReplayOnlyPipeline:
            async def replay_projection(self, action_id):
                assert action_id == 'projection-pending-action'
                return {'status': 'replayed', 'action_id': action_id}

        monkeypatch.setattr(client.app.state, "pipeline", ReplayOnlyPipeline(), raising=False)
        response = client.post(
            f"/api/host/{room['room_id']}/actions/projection-pending-action/replay-projection",
            headers={'X-Owner-Token': room['owner_token']},
        )

        assert response.status_code == 200
        assert response.json() == {'status': 'replayed', 'action_id': 'projection-pending-action'}

    def test_owner_lists_projection_recoveries_without_private_action_text(self, client, test_db):
        from tests.server.conftest import setup_auth_test_data, create_room
        setup_auth_test_data(test_db)
        room = create_room(client)
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, status) "
            "VALUES ('projection-list-character', %s, 'Player', 'projection-list-token', 'ready')",
            (room['room_id'],),
        )
        test_db.execute(
            "INSERT INTO actions (action_id, room_id, character_id, intent_type, declared_intent, status) "
            "VALUES ('projection-list-action', %s, 'projection-list-character', 'action', '不应显示的私密原话', 'completed')",
            (room['room_id'],),
        )
        test_db.execute(
            "INSERT INTO resolution_bundles "
            "(action_id, room_id, character_id, canonical_result, rule_explanation, actor_projection, stage_projection, host_console, release_status) "
            "VALUES ('projection-list-action', %s, 'projection-list-character', '{}', '{}', '{}', '{}', '{}', 'projection_pending')",
            (room['room_id'],),
        )
        test_db.commit()

        response = client.get(
            f"/api/host/{room['room_id']}/projection-replays",
            headers={'X-Owner-Token': room['owner_token']},
        )

        assert response.status_code == 200
        assert response.json()['items'] == [{
            'action_id': 'projection-list-action',
            'character_id': 'projection-list-character',
        }]
        assert '不应显示的私密原话' not in response.text
