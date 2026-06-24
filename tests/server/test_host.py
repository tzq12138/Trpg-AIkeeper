import json
import pytest
from src.server.models import EngineEvent, RevealTransaction, TransactionStep
from src.server.host_store import HostStore, HOST_VISIBLE_EVENTS, PRIVATE_EVENTS


class TestHostStoreRouting:
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


class TestHostStoreSnapshot:
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
        assert len(loaded["chat_messages"]) == 50
        assert loaded["chat_messages"][0]["text"] == "msg-50"


class TestHostRESTEndpoints:
    def test_get_hud_endpoint(self, client):
        resp = client.post("/api/rooms", json={})
        room_id = resp.json()["room_id"]
        resp = client.get(f"/api/host/{room_id}/hud")
        assert resp.status_code == 200
        data = resp.json()
        assert data["roomId"] == room_id
        assert isinstance(data["players"], list)

    def test_get_hud_not_found(self, client):
        resp = client.get("/api/host/nonexistent/hud")
        assert resp.status_code == 404

    def test_emergency_reset(self, client):
        resp = client.post("/api/rooms", json={})
        room_id = resp.json()["room_id"]
        owner_token = resp.json()["owner_token"]
        resp = client.post(
            f"/api/host/{room_id}/reset",
            headers={"X-Owner-Token": owner_token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset"

    def test_emergency_reset_not_found(self, client):
        resp = client.post("/api/host/nonexistent/reset", headers={"X-Owner-Token": "x"})
        assert resp.status_code == 403

    def test_emergency_reset_wrong_owner(self, client):
        resp = client.post("/api/rooms", json={})
        room_id = resp.json()["room_id"]
        resp = client.post(
            f"/api/host/{room_id}/reset",
            headers={"X-Owner-Token": "wrong-token"},
        )
        assert resp.status_code == 403

    def test_pause_toggle(self, client):
        resp = client.post("/api/rooms", json={})
        room_id = resp.json()["room_id"]
        owner_token = resp.json()["owner_token"]
        resp = client.post(
            f"/api/host/{room_id}/pause",
            headers={"X-Owner-Token": owner_token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"
        resp = client.post(
            f"/api/host/{room_id}/pause",
            headers={"X-Owner-Token": owner_token},
        )
        assert resp.json()["status"] == "resumed"

    def test_pause_not_found(self, client):
        resp = client.post("/api/host/nonexistent/pause", headers={"X-Owner-Token": "x"})
        assert resp.status_code == 403

    def test_retry_turn_no_active(self, client):
        resp = client.post("/api/rooms", json={})
        room_id = resp.json()["room_id"]
        owner_token = resp.json()["owner_token"]
        resp = client.post(
            f"/api/host/{room_id}/retry-turn",
            headers={"X-Owner-Token": owner_token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_active_transaction"

    def test_retry_turn_not_found(self, client):
        resp = client.post("/api/host/nonexistent/retry-turn", headers={"X-Owner-Token": "x"})
        assert resp.status_code == 403
