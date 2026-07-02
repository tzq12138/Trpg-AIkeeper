"""Room lifecycle tests — authenticated game flow (plan21 v2)."""

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
        ("acc-host", "testhost", "host"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (username) DO UPDATE "
            "SET role = %s, account_id = EXCLUDED.account_id",
            (aid, uname, _hash_password("test123"), uname, role, role),
        )
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status) "
        "VALUES ('sc-test', 'Test Scenario', 'text', 'structured')"
    )
    test_db.commit()
    return c


def _login(client, username="testhost"):
    res = client.post("/api/auth/login", json={"username": username, "password": "test123"})
    assert res.status_code == 200, res.text
    return res.json()["token"]


def _create_room(client, token=None):
    if token is None:
        token = _login(client)
    res = client.post(
        "/api/rooms",
        json={"scenario_id": "sc-test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    return res.json()


class TestCreateRoom:
    def test_create_room_requires_auth(self, client_with_data):
        res = client_with_data.post("/api/rooms", json={"scenario_id": "sc-test"})
        assert res.status_code == 401

    def test_create_room_host_succeeds(self, client_with_data):
        token = _login(client_with_data)
        data = _create_room(client_with_data, token)
        assert data["status"] == "lobby"
        assert data["room_id"]
        assert data["owner_token"]
        assert data["scenario_id"] == "sc-test"

    def test_create_room_admin_succeeds(self, client_with_data):
        token = _login(client_with_data, "admin")
        data = _create_room(client_with_data, token)
        assert data["status"] == "lobby"
        assert data["owner_account_id"] == "acc-admin"


class TestGetRoom:
    def test_get_room_public(self, client_with_data):
        data = _create_room(client_with_data)
        res = client_with_data.get(f"/api/rooms/{data['room_id']}")
        assert res.status_code == 200
        result = res.json()
        assert result["room_id"] == data["room_id"]
        assert "owner_token" not in result

    def test_get_room_not_found(self, client_with_data):
        res = client_with_data.get("/api/rooms/nonexistent")
        assert res.status_code == 404


class TestStartRoom:
    def test_start_room_with_owner_token(self, client_with_data):
        data = _create_room(client_with_data)
        # Add a ready player — empty room start is now rejected
        client_with_data.app.state.db.execute(
            "INSERT INTO characters (character_id, room_id, player_name, player_token, is_ready, status) "
            "VALUES ('ch-start', %s, 'Alice', 'ptok', true, 'joined')",
            (data['room_id'],),
        )
        client_with_data.app.state.db.commit()
        res = client_with_data.post(
            f"/api/rooms/{data['room_id']}/start",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "active"

    def test_start_room_empty_returns_409(self, client_with_data):
        data = _create_room(client_with_data)
        res = client_with_data.post(
            f"/api/rooms/{data['room_id']}/start",
            headers={"X-Owner-Token": data["owner_token"]},
        )
        assert res.status_code == 409
        assert "至少需要一名玩家" in res.json()["detail"]

    def test_start_room_wrong_owner(self, client_with_data):
        data = _create_room(client_with_data)
        res = client_with_data.post(
            f"/api/rooms/{data['room_id']}/start",
            headers={"X-Owner-Token": "wrong-token"},
        )
        assert res.status_code == 403
