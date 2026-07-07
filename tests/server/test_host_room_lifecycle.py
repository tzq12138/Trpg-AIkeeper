"""Tests for host room lifecycle: create → configure → start."""

import pytest
from fastapi.testclient import TestClient
from src.server.main import app
from src.server.router_auth import _hash_password


@pytest.fixture
def client_with_data(test_db):
    from src.server.engine.engine import Engine
    c = TestClient(app)
    app.state.db = test_db
    app.state.engine = Engine(test_db)

    for aid, uname, role in [
        ("acc-admin", "admin", "admin"),
        ("acc-host", "hostlife", "host"),
        ("acc-player", "player", "player"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (username) DO UPDATE "
            "SET role = %s, account_id = EXCLUDED.account_id",
            (aid, uname, _hash_password("test123"), uname, role, role),
        )
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status) "
        "VALUES ('sc-life', 'Lifecycle Scenario', 'content', 'structured')"
    )
    test_db.commit()
    return c


def _login(client, username: str, password: str = "test123") -> str:
    res = client.post("/api/auth/login", json={
        "username": username, "password": password,
    })
    assert res.status_code == 200, res.text
    return res.json()["token"]


def _create_room(client, token):
    res = client.post(
        "/api/rooms",
        json={"scenario_id": "sc-life"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    return res.json()


class TestHostCreateRoom:
    def test_create_room_no_auth_returns_401(self, client_with_data):
        res = client_with_data.post("/api/rooms", json={"scenario_id": "sc-life"})
        assert res.status_code == 401

    def test_create_room_player_returns_403(self, client_with_data):
        token = _login(client_with_data, "player")
        res = client_with_data.post(
            "/api/rooms", json={"scenario_id": "sc-life"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403

    def test_create_room_host_requires_scenario(self, client_with_data):
        token = _login(client_with_data, "hostlife")
        res = client_with_data.post(
            "/api/rooms", json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code in (400, 422)

    def test_create_room_host_success(self, client_with_data):
        token = _login(client_with_data, "hostlife")
        data = _create_room(client_with_data, token)
        assert data["status"] == "lobby"
        assert data["room_id"]
        assert data["owner_token"]
        assert data["owner_account_id"] == "acc-host"
        assert data["scenario_id"] == "sc-life"


class TestStartRoom:
    def _setup_room_with_player(self, client_with_data, test_db, ready=True):
        host_token = _login(client_with_data, "hostlife")
        room = _create_room(client_with_data, host_token)
        room_id = room["room_id"]
        owner_token = room["owner_token"]

        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES (%s, %s, %s, %s, %s, 'joined')",
            ("ch-start", room_id, "Alice", "pt-start", ready),
        )
        test_db.commit()
        return room_id, owner_token

    def test_start_room_no_auth_returns_403(self, client_with_data, test_db):
        room_id, _ = self._setup_room_with_player(client_with_data, test_db)
        res = client_with_data.post(f"/api/rooms/{room_id}/start")
        assert res.status_code == 403

    def test_start_room_with_owner_token_succeeds(self, client_with_data, test_db):
        room_id, owner_token = self._setup_room_with_player(client_with_data, test_db)
        res = client_with_data.post(
            f"/api/rooms/{room_id}/start",
            headers={"X-Owner-Token": owner_token},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "active"

    def test_start_room_empty_returns_409(self, client_with_data):
        """Empty room (no players) should not start."""
        host_token = _login(client_with_data, "hostlife")
        room = _create_room(client_with_data, host_token)
        res = client_with_data.post(
            f"/api/rooms/{room['room_id']}/start",
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert res.status_code == 409
        assert "至少需要一名玩家" in res.json()["detail"]

    def test_start_room_not_ready_returns_409(self, client_with_data, test_db):
        """Room with a not-ready player should not start."""
        room_id, owner_token = self._setup_room_with_player(client_with_data, test_db, ready=False)
        res = client_with_data.post(
            f"/api/rooms/{room_id}/start",
            headers={"X-Owner-Token": owner_token},
        )
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert detail["status"] == "not_ready"

    def test_start_room_force_start_empty_succeeds(self, client_with_data):
        """Owner can force-start an empty room with reason + confirm."""
        host_token = _login(client_with_data, "hostlife")
        room = _create_room(client_with_data, host_token)
        res = client_with_data.post(
            f"/api/rooms/{room['room_id']}/start",
            json={"force_start": True, "reason": "demo test", "confirm": True},
            headers={"X-Owner-Token": room["owner_token"]},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "active"

    def test_start_room_no_scenario_fails(self, client_with_data, test_db):
        test_db.execute(
            "INSERT INTO rooms (room_id, owner_token, status) VALUES ('r-nosc', 'tok-nosc', 'lobby')"
        )
        test_db.commit()
        res = client_with_data.post(
            "/api/rooms/r-nosc/start",
            headers={"X-Owner-Token": "tok-nosc"},
        )
        assert res.status_code in (400, 404)

    def test_force_start_by_non_owner_rejected(self, client_with_data, test_db):
        room_id, _ = self._setup_room_with_player(client_with_data, test_db, ready=False)
        res = client_with_data.post(
            f"/api/rooms/{room_id}/start",
            json={"force_start": True},
            headers={"X-Owner-Token": "wrong-token"},
        )
        assert res.status_code == 403

    def test_force_start_with_not_ready_succeeds(self, client_with_data, test_db):
        room_id, owner_token = self._setup_room_with_player(client_with_data, test_db, ready=False)
        res = client_with_data.post(
            f"/api/rooms/{room_id}/start",
            json={"force_start": True, "reason": "跳过未准备", "confirm": True},
            headers={"X-Owner-Token": owner_token},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "active"

    def test_force_start_missing_reason_returns_400(self, client_with_data, test_db):
        room_id, owner_token = self._setup_room_with_player(client_with_data, test_db, ready=False)
        res = client_with_data.post(
            f"/api/rooms/{room_id}/start",
            json={"force_start": True, "confirm": True},
            headers={"X-Owner-Token": owner_token},
        )
        assert res.status_code == 400

    def test_force_start_missing_confirm_returns_400(self, client_with_data, test_db):
        room_id, owner_token = self._setup_room_with_player(client_with_data, test_db, ready=False)
        res = client_with_data.post(
            f"/api/rooms/{room_id}/start",
            json={"force_start": True, "reason": "test"},
            headers={"X-Owner-Token": owner_token},
        )
        assert res.status_code == 400

    def test_force_start_writes_audit_event(self, client_with_data, test_db):
        room_id, owner_token = self._setup_room_with_player(client_with_data, test_db, ready=False)
        res = client_with_data.post(
            f"/api/rooms/{room_id}/start",
            json={"force_start": True, "reason": "audit test", "confirm": True},
            headers={"X-Owner-Token": owner_token},
        )
        assert res.status_code == 200
        events = test_db.execute(
            "SELECT * FROM events WHERE room_id = %s AND event_type = 's2c_force_start_audit'",
            (room_id,),
        ).fetchall()
        assert len(events) >= 1


class TestApproveReject:
    def _setup_active_room_with_pending(self, client_with_data, test_db):
        """Create an active room with one joined and one pending player."""
        host_token = _login(client_with_data, "hostlife")
        room = _create_room(client_with_data, host_token)
        room_id = room["room_id"]
        owner_token = room["owner_token"]

        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES ('ch-host', %s, 'HostPlayer', 'pt-host', true, 'joined')",
            (room_id,),
        )
        test_db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES ('ch-pend', %s, 'Pending', 'pt-pend', false, 'pending_approval')",
            (room_id,),
        )
        test_db.commit()
        client_with_data.post(
            f"/api/rooms/{room_id}/start",
            headers={"X-Owner-Token": owner_token},
        )
        return room_id, owner_token

    def test_approve_pending_character(self, client_with_data, test_db):
        room_id, owner_token = self._setup_active_room_with_pending(client_with_data, test_db)
        resp = client_with_data.post(
            f"/api/host/{room_id}/approve/ch-pend",
            headers={"X-Owner-Token": owner_token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        char = test_db.execute(
            "SELECT status FROM characters WHERE character_id = 'ch-pend'"
        ).fetchone()
        assert char["status"] == "joined"

    def test_reject_pending_character(self, client_with_data, test_db):
        room_id, owner_token = self._setup_active_room_with_pending(client_with_data, test_db)
        resp = client_with_data.post(
            f"/api/host/{room_id}/reject/ch-pend",
            headers={"X-Owner-Token": owner_token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        char = test_db.execute(
            "SELECT status FROM characters WHERE character_id = 'ch-pend'"
        ).fetchone()
        assert char["status"] == "left"

    def test_non_owner_cannot_approve(self, client_with_data, test_db):
        room_id, _ = self._setup_active_room_with_pending(client_with_data, test_db)
        resp = client_with_data.post(
            f"/api/host/{room_id}/approve/ch-pend",
            headers={"X-Owner-Token": "wrong-token"},
        )
        assert resp.status_code == 403
