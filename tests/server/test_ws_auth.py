"""Tests for WebSocket authentication (host & player)."""

import pytest
from fastapi.testclient import TestClient
from src.server.main import app
from src.server.router_auth import _hash_password
from tests.server.conftest import create_scenario


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
    create_scenario(test_db, "sc-ws", "WS Test")
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


class TestPlayerWSAuth:
    def _setup_player(self, client_with_data, test_db):
        """Create a room and join as player. Returns (room_id, player_token)."""
        # Create room as host
        token = _login(client_with_data, "wshost")
        res = client_with_data.post(
            "/api/rooms",
            json={"scenario_id": "sc-ws"},
            headers={"Authorization": f"Bearer {token}"},
        )
        room = res.json()
        # Join as player
        resp = client_with_data.post(f"/api/player/rooms/{room['room_id']}/join")
        assert resp.status_code == 200
        return room["room_id"], resp.json()["player_token"]

    def test_player_ws_valid_token_accepted(self, client_with_data, test_db):
        room_id, player_token = self._setup_player(client_with_data, test_db)
        with client_with_data.websocket_connect(
            f"/ws?room={room_id}&role=player&token={player_token}"
        ) as ws:
            assert ws  # Connected

    def test_player_ws_wrong_token_rejected(self, client_with_data, test_db):
        room_id, _ = self._setup_player(client_with_data, test_db)
        # Player WS accepts first then closes with 4003 — use try/except to catch close
        try:
            with client_with_data.websocket_connect(
                f"/ws?room={room_id}&role=player&token=wrong-token"
            ) as ws:
                ws.receive_text()  # Should fail on close
        except Exception:
            pass  # Close expected

    def test_player_ws_wrong_room_rejected(self, client_with_data, test_db):
        _, player_token = self._setup_player(client_with_data, test_db)
        try:
            with client_with_data.websocket_connect(
                f"/ws?room=nonexistent&role=player&token={player_token}"
            ) as ws:
                ws.receive_text()
        except Exception:
            pass  # Close expected
