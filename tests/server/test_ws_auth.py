"""Tests for WebSocket authentication (host & player)."""

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
        ("acc-host", "wshost", "host"),
        ("acc-player", "wsplayer", "player"),
    ]:
        test_db.execute(
            "INSERT INTO accounts (account_id, username, password_hash, display_name, role) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (username) DO UPDATE "
            "SET role = %s, account_id = EXCLUDED.account_id",
            (aid, uname, _hash_password("test123"), uname, role, role),
        )
    test_db.execute(
        "INSERT INTO scenarios (scenario_id, title, raw_text, import_status) "
        "VALUES ('sc-ws', 'WS Test', 'text', 'structured')"
    )
    test_db.commit()
    return c


def _login(client, username: str) -> str:
    res = client.post("/api/auth/login", json={
        "username": username, "password": "test123",
    })
    return res.json()["token"]


class TestHostWSAuth:
    def _create_room(self, client):
        token = _login(client, "wshost")
        res = client.post(
            "/api/rooms",
            json={"scenario_id": "sc-ws"},
            headers={"Authorization": f"Bearer {token}"},
        )
        return res.json()

    def test_host_ws_no_token_rejected(self, client_with_data):
        """No owner token → connection closed with code 1008."""
        room = self._create_room(client_with_data)
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client_with_data.websocket_connect(
                f"/ws?room={room['room_id']}&role=host"
            ):
                pass

    def test_host_ws_wrong_token_rejected(self, client_with_data):
        """Wrong owner token → connection closed."""
        room = self._create_room(client_with_data)
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client_with_data.websocket_connect(
                f"/ws?room={room['room_id']}&role=host&ownerToken=wrong"
            ):
                pass

    def test_host_ws_valid_token_accepted(self, client_with_data):
        room = self._create_room(client_with_data)
        with client_with_data.websocket_connect(
            f"/ws?room={room['room_id']}&role=host&ownerToken={room['owner_token']}"
        ) as ws:
            # Should succeed
            assert ws  # Connected
